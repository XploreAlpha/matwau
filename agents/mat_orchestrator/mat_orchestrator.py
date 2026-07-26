"""mat-orchestrator — DAG 调度器(per W10)

业务流程:
1. 接 MatIntent(从 mat-intent-agent)
2. 根据 subclass 选 workflow 模板
3. 用 DAGExecutor 执行
4. 聚合 WorkflowResult

Stage 1 mock:5 workflow 模板 + DAG executor
Stage 2 接 mat-lit / mat-critic

用法:
    from agents.mat_orchestrator.mat_orchestrator import MatOrchestrator
    from agents.mat_intent_agent.mat_intent_agent import create_default_agent

    intent_agent = create_default_agent()
    orchestrator = MatOrchestrator(intent_agent=intent_agent)
    result = orchestrator.run(user_intent="出 LiCoO2 实验方案")
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许直接 python3 -m 运行
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager  # noqa: E402
from matwau.harness.safety_guard import SafetyGuard  # noqa: E402

from .dag import (  # noqa: E402
    DAG,
    DAGExecutor,
    WorkflowResult,
    get_workflow_for_subclass,
)


# ============================================================================
# Stub agent(per W12/W14 后已替换,保留给未来扩展)
# ============================================================================


class StubAgent:
    """W12/W14 后已替换所有 stub,保留给未来扩展"""

    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role

    def run(self, req: AgentRequest) -> AgentResponse:
        return AgentResponse(
            reply=f"⏳ {self.role}(stub): 当前 stub,任务 {req.message[:50]}",
            artifacts={"stub": True, "role": self.role},
            confidence=0.5,
            cost=0.01,
        )


# ============================================================================
# MatOrchestrator 主体
# ============================================================================


class MatOrchestrator:
    """mat-orchestrator — DAG 调度器(独立类,不继承 MatWAUAgentBase)

    注:MatOrchestrator 是调度器,不是 agent。它编排其他 agent。
    """

    def __init__(
        self,
        *,
        intent_agent=None,
        gen_agent=None,
        sim_agent=None,
        hpc_agent=None,
        exp_agent=None,
        critic_agent=None,
        lit_agent=None,
        lineage_store=None,            # W32 — LineageStore 实例(默认 None → 不打 lineage)
        lineage_recorder=None,         # W32 — LineageRecorder 实例(默认 None → 不打 lineage)
        enable_lineage: bool = True,   # W32 — False → 关闭 lineage(测试用)
    ) -> None:
        """构造

        不传任何 agent → 用默认(Stage 1 mock)
        critic_agent 不传 → 自动懒加载 MatCriticAgent(W12 新增,替换原 StubAgent)
        lit_agent 不传 → 自动懒加载 MatLitAgent(W14 新增,替换原 StubAgent)

        W32 新增:
        - lineage_store: 显式注入 LineageStore(None → 默认从 get_lineage_store() 拿)
        - lineage_recorder: 显式注入 LineageRecorder(优先于 lineage_store)
        - enable_lineage: False → 关闭 lineage hook(测试 / CI 友好)
        """
        # 懒加载
        if gen_agent is None or sim_agent is None or hpc_agent is None or exp_agent is None:
            from agents.mat_gen_agent.mat_gen_agent import create_default_agent as create_gen
            from agents.mat_sim_agent.mat_sim_agent import create_default_agent as create_sim
            from agents.mat_hpc_agent.mat_hpc_agent import create_default_agent as create_hpc
            from agents.mat_exp_agent.mat_exp_agent import create_default_agent as create_exp

        if gen_agent is None:
            gen_agent = create_gen()
        if sim_agent is None:
            sim_agent = create_sim()
        if hpc_agent is None:
            hpc_agent = create_hpc()
        if exp_agent is None:
            exp_agent = create_exp()

        if intent_agent is None:
            from agents.mat_intent_agent.mat_intent_agent import create_default_agent as create_intent

            intent_agent = create_intent()

        if critic_agent is None:
            from agents.mat_critic_agent.mat_critic_agent import create_default_agent as create_critic

            critic_agent = create_critic()

        if lit_agent is None:
            from agents.mat_lit_agent.mat_lit_agent import create_default_agent as create_lit

            lit_agent = create_lit()

        self.intent_agent = intent_agent
        self.gen_agent = gen_agent
        self.sim_agent = sim_agent
        self.hpc_agent = hpc_agent
        self.exp_agent = exp_agent
        self.critic_agent = critic_agent
        self.lit_agent = lit_agent

        # Agent registry
        # W12: mat-critic-agent 替换原 mat-critic-stub
        # W14: mat-lit-agent 替换原 mat-lit-stub
        self.agent_registry = {
            "mat-gen-agent": gen_agent,
            "mat-sim-agent": sim_agent,
            "mat-hpc-agent": hpc_agent,
            "mat-exp-agent": exp_agent,
            "mat-critic-agent": critic_agent,
            "mat-lit-agent": lit_agent,
        }

        # DAG executor
        self.executor = DAGExecutor(self.agent_registry)

        # W32 — Lineage 注入
        self._lineage_recorder = None
        if enable_lineage:
            if lineage_recorder is not None:
                self._lineage_recorder = lineage_recorder
            elif lineage_store is not None:
                # 包 LineageStore → LineageRecorder
                from agents.mat_data_lineage_agent import LineageRecorder
                self._lineage_recorder = LineageRecorder(store=lineage_store)
            else:
                # 默认从 get_lineage_store() 工厂拿
                from matwau.configs import get_lineage_store
                from agents.mat_data_lineage_agent import LineageRecorder
                store = get_lineage_store()
                if store is not None:
                    self._lineage_recorder = LineageRecorder(store=store)

    # ========================================================================
    # 公开 API
    # ========================================================================

    def run(
        self,
        *,
        user_intent: str,
        budget: Optional[float] = None,
        n_samples: Optional[int] = None,
        domain: Optional[str] = None,
    ) -> WorkflowResult:
        """跑编排(用户 1 句话 → mat-intent 解析 → 选 workflow → 跑 DAG)

        Args:
            user_intent: 用户 1 句话意图
            budget: 总预算(可选)
            n_samples: 生成候选数(None → 用 mat-intent 解析)
            domain: 材料域(W15;None → 自动 detect / 默认 inorganic_crystal)

        Returns:
            WorkflowResult
        """
        # W15: 域自动 detect(显式 > auto)
        from agents.material_domain_router import DEFAULT_DOMAIN, detect_domain
        run_domain = domain or detect_domain(user_intent) or DEFAULT_DOMAIN

        # Stage 0: mat-intent 解析(W15: 透传 domain)
        intent_req = AgentRequest(
            run_id="orch-intent",
            message=user_intent,
            context={"domain": run_domain},
        )
        intent_response = self.intent_agent.run(intent_req)
        mi = intent_response.artifacts["mat_intent"]

        # Stage 1: 选 workflow
        workflow = get_workflow_for_subclass(mi.subclass)
        if workflow is None:
            return WorkflowResult(
                workflow_name="unknown",
                subclass=mi.subclass,
                success=False,
                error=f"未知子类: {mi.subclass}",
            )

        # Stage 2: 拼装 initial_inputs
        # 把 user_intent + 解析的 elements / forbidden / n_samples 传下去
        initial_inputs = {
            "user_intent": user_intent,
            "subclass": mi.subclass,
            "material_system": mi.material_system,
            "target_props": mi.target_props,
            "elements": mi.elements,
            "forbidden": mi.forbidden,
            "n_samples": n_samples or mi.n_samples,
            "budget": budget,
            "mat_intent": mi,
            "domain": run_domain,  # W15: 域路由透传到下游 agent
        }

        # Stage 3: 跑 DAG
        result = self.executor.execute(workflow, initial_inputs=initial_inputs)

        # W32 — Lineage hook:workflow 终点记录
        if self._lineage_recorder is not None:
            self._lineage_recorder.record_workflow_result(
                workflow_name=result.workflow_name,
                subclass=mi.subclass,
                result=result,
            )

        return result

    def run_with_intent(
        self,
        *,
        user_intent: str,
        mat_intent,  # 已解析的 MatIntent
        budget: Optional[float] = None,
    ) -> WorkflowResult:
        """用已解析的 MatIntent 跑编排(测试用,跳过 mat-intent 阶段)"""
        workflow = get_workflow_for_subclass(mat_intent.subclass)
        if workflow is None:
            return WorkflowResult(
                workflow_name="unknown",
                subclass=mat_intent.subclass,
                success=False,
                error=f"未知子类: {mat_intent.subclass}",
            )

        initial_inputs = {
            "user_intent": user_intent,
            "subclass": mat_intent.subclass,
            "material_system": mat_intent.material_system,
            "elements": mat_intent.elements,
            "forbidden": mat_intent.forbidden,
            "n_samples": mat_intent.n_samples,
            "budget": budget,
            "mat_intent": mat_intent,
        }

        result = self.executor.execute(workflow, initial_inputs=initial_inputs)

        # W32 — Lineage hook:workflow 终点记录
        if self._lineage_recorder is not None:
            self._lineage_recorder.record_workflow_result(
                workflow_name=result.workflow_name,
                subclass=mat_intent.subclass,
                result=result,
            )

        return result

    def run_batch(
        self,
        experiments: List["ChemistTask"],
        *,
        parallel: bool = True,
        max_workers: int = 4,
        critic_agent: Optional[Any] = None,
    ) -> "BatchWorkflowResult":
        """W31 — 跑 N 个 experiment 并行,每个跑完接 critic L4 复核,聚合 BatchWorkflowResult

        Args:
            experiments: List[ChemistTask](每项含 target_sample + robot_steps + budget)
            parallel: True → ThreadPoolExecutor 并行;False → 串行
            max_workers: 并行 worker 数(默认 4)
            critic_agent: 可选 MatCriticAgent,默认 None → 内部 create_default_agent()

        Returns:
            BatchWorkflowResult(overall_verdict + experiment_results)
        """
        from uuid import uuid4
        from .dag import BatchWorkflowResult, ExperimentResult
        from .parallel_runner import ParallelBatchRunner

        if not experiments:
            return BatchWorkflowResult(
                n_total=0, n_passed=0, n_warned=0, n_failed=0, n_blocked=0,
                overall_verdict="fail", parallel=parallel, max_workers=max_workers,
            )

        # 1. 准备 critic agent
        critic = critic_agent if critic_agent is not None else self.critic_agent

        start_time = time.time()

        # 2. 构造 worker callables
        def _run_one(idx: int, task: "ChemistTask") -> ExperimentResult:
            from agents.mat_chemist_agent import MatChemistAgent

            chemist = MatChemistAgent()
            exp_id = f"exp-{idx}-{uuid4().hex[:6]}"
            t0 = time.time()
            chem_cost = 0.0
            try:
                # Step A: 跑 chemist
                chem_req = AgentRequest(
                    run_id=f"{exp_id}-chemist",
                    message=task.goal,
                    artifacts={"task": task},
                )
                chem_resp = chemist.run(chem_req)
                chem_cost = chem_resp.cost if hasattr(chem_resp, "cost") else chem_resp.artifacts.get("total_cost_cny", 0.0)

                # W31 patch 后 artifacts["report"] = ChemistReport 对象
                report = chem_resp.artifacts.get("report")
                if report is None:
                    return ExperimentResult(
                        experiment_id=exp_id,
                        target_sample=task.target_sample,
                        chemist_report=None,
                        critic_verdict=None,
                        cost_cny=0.0,
                        duration_seconds=time.time() - t0,
                        verdict="fail",
                        error="chemist returned no report",
                    )

                # W32 — Lineage hook:chemist 跑完记 1 条
                if self._lineage_recorder is not None:
                    self._lineage_recorder.record_chemist_report(
                        experiment_id=exp_id,
                        task=task,
                        report=report,
                        cost=chem_cost,
                        duration_seconds=time.time() - t0,
                    )

                # Step B: 接 critic L4
                critic_t0 = time.time()
                critic_req = AgentRequest(
                    run_id=f"{exp_id}-critic",
                    message=f"{task.target_sample} 表征复核",
                    artifacts={"report": report},
                )
                critic_resp = critic.run(critic_req)
                critic_duration = time.time() - critic_t0
                verdict_obj = critic_resp.artifacts.get("verdict")
                critic_verdict = critic_resp.artifacts.get("critic_verdict")

                # W32 — Lineage hook:critic 跑完记 1 条(parent = chemist)
                if self._lineage_recorder is not None:
                    self._lineage_recorder.record_critic_verdict(
                        experiment_id=exp_id,
                        target_sample=task.target_sample,
                        critic_verdict=critic_verdict,
                        cost=critic_resp.cost if hasattr(critic_resp, "cost") else 0.0,
                        duration_seconds=critic_duration,
                        user_intent=task.goal,
                    )

                return ExperimentResult(
                    experiment_id=exp_id,
                    target_sample=task.target_sample,
                    chemist_report=report,
                    critic_verdict=critic_verdict,
                    cost_cny=chem_cost,
                    duration_seconds=time.time() - t0,
                    verdict=verdict_obj.verdict if verdict_obj else "fail",
                )
            except Exception as e:
                return ExperimentResult(
                    experiment_id=exp_id,
                    target_sample=task.target_sample,
                    chemist_report=None,
                    critic_verdict=None,
                    cost_cny=0.0,
                    duration_seconds=time.time() - t0,
                    verdict="fail",
                    error=f"{type(e).__name__}: {e}",
                )

        callables = [_make_callable(_run_one, i, t) for i, t in enumerate(experiments)]

        # 3. fan-out via ParallelBatchRunner
        runner = ParallelBatchRunner(max_workers=max_workers if parallel else 1)
        results = runner.run_all(callables)

        # 4. fan-in 聚合
        n_total = len(results)
        n_passed = sum(1 for r in results if r.verdict == "pass")
        n_warned = sum(1 for r in results if r.verdict == "warn")
        n_failed = sum(1 for r in results if r.verdict == "fail")
        n_blocked = sum(1 for r in results if r.blocked)
        total_cost = sum(r.cost_cny for r in results)
        total_duration = time.time() - start_time

        # overall_verdict 逻辑:全 pass → pass;部分 pass/warn → warn;全 fail → fail
        if n_passed == n_total and n_total > 0:
            overall_verdict = "pass"
        elif n_passed > 0 or n_warned > 0:
            overall_verdict = "warn"
        else:
            overall_verdict = "fail"

        batch_result = BatchWorkflowResult(
            workflow_name="multi_experiment_characterization",
            n_total=n_total,
            n_passed=n_passed,
            n_warned=n_warned,
            n_failed=n_failed,
            n_blocked=n_blocked,
            experiment_results=results,
            total_cost_cny=total_cost,
            total_duration_seconds=total_duration,
            overall_verdict=overall_verdict,
            parallel=parallel,
            max_workers=max_workers,
        )

        # W32 — Lineage hook:每 experiment + batch 总览
        if self._lineage_recorder is not None:
            for r in results:
                self._lineage_recorder.record_experiment_result(r)
            self._lineage_recorder.record_batch_workflow_result(batch_result)

        return batch_result


def _make_callable(fn, idx, task):
    """构造一个 closure 捕获 idx + task,避免 lambda 默认参数陷阱"""
    def _callable():
        return fn(idx, task)
    return _callable


def create_default_orchestrator() -> MatOrchestrator:
    """便利函数:创建默认 MatOrchestrator"""
    return MatOrchestrator()


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatOrchestrator Demo")
    print("=" * 60)

    orch = create_default_orchestrator()

    test_intents = [
        "出 LiCoO2 实验方案",                              # experiment_planning
        "设计新型固态电解质",                               # design_new_material
        "优化 LiCoO2 配方",                                # optimize_existing
        "为什么 XRD 谱不对",                               # explain_failure
        "Review 一下 LLZO 最新进展",                       # literature_review
    ]

    for intent_text in test_intents:
        print(f"\n📝 {intent_text}")
        result = orch.run(user_intent=intent_text)
        print(f"   workflow: {result.workflow_name}, success={result.success}")
        print(f"   nodes: {[(nr.node_id, nr.agent_name) for nr in result.node_results]}")
        print(f"   total: {result.total_duration_seconds:.3f}s")

__all__ = ["MatOrchestrator", "create_default_orchestrator", "StubAgent"]