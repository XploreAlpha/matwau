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
from pathlib import Path
from typing import Any, Dict, Optional

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
    ) -> None:
        """构造

        不传任何 agent → 用默认(Stage 1 mock)
        critic_agent 不传 → 自动懒加载 MatCriticAgent(W12 新增,替换原 StubAgent)
        lit_agent 不传 → 自动懒加载 MatLitAgent(W14 新增,替换原 StubAgent)
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

        return self.executor.execute(workflow, initial_inputs=initial_inputs)


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