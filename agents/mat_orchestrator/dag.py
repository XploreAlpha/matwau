"""dag.py — DAG 节点 + 边数据结构 + 5 workflow 模板

per MatWAU-开发计划 §七 W10
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# DAG 节点
# ============================================================================


@dataclass
class DAGNode:
    """1 个 DAG 节点(执行 1 个 mat agent)"""

    node_id: str                                    # 唯一 ID
    agent_name: str                                 # 调用的 agent
    inputs: dict[str, str] = field(default_factory=dict)  # 从其他节点的 outputs 取数据
    output_key: str = "result"                      # 节点输出 key
    description: str = ""                           # 人类可读描述

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "inputs": self.inputs,
            "output_key": self.output_key,
            "description": self.description,
        }


# ============================================================================
# DAG 执行结果
# ============================================================================


@dataclass
class NodeResult:
    """1 个节点执行结果"""

    node_id: str
    agent_name: str
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0

    def to_summary(self) -> str:
        status = "✅" if self.success else "❌"
        n_outputs = len(self.outputs)
        return (
            f"   {status} {self.node_id} ({self.agent_name}, {self.duration_seconds:.2f}s): "
            f"{n_outputs} outputs"
        )


@dataclass
class WorkflowResult:
    """1 个 workflow 执行结果"""

    workflow_name: str                              # 5 workflow 名
    subclass: str                                   # 触发 workflow 的子类
    node_results: list[NodeResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    success: bool = False
    error: str | None = None

    # 最终输出(per workflow 类型)
    final_outputs: dict[str, Any] = field(default_factory=dict)

    def to_summary(self) -> str:
        lines = []
        status = "✅" if self.success else "❌"
        lines.append(f"{status} {self.workflow_name}({self.subclass}, {self.total_duration_seconds:.2f}s)")
        for nr in self.node_results:
            lines.append(nr.to_summary())
        return "\n".join(lines)


# ============================================================================
# DAG 类
# ============================================================================


class DAG:
    """简单 DAG(顺序节点列表,Stage 1 不用并行)"""

    def __init__(self, name: str, nodes: list[DAGNode]) -> None:
        self.name = name
        self.nodes = nodes

    def add_node(self, node: DAGNode) -> None:
        self.nodes.append(node)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    def __repr__(self) -> str:
        return f"DAG(name={self.name}, nodes={[n.node_id for n in self.nodes]})"


# ============================================================================
# DAG 执行器
# ============================================================================


class DAGExecutor:
    """DAG 执行器(顺序执行节点,把 outputs 传下去)"""

    def __init__(self, agent_registry: dict[str, Any]) -> None:
        """构造

        Args:
            agent_registry: {agent_name: agent_instance}
        """
        self.agent_registry = agent_registry

    def execute(
        self,
        dag: DAG,
        *,
        initial_inputs: dict[str, Any],
    ) -> WorkflowResult:
        """执行 DAG

        Args:
            dag: DAG 实例
            initial_inputs: 初始输入(第 1 节点用)

        Returns:
            WorkflowResult
        """
        result = WorkflowResult(
            workflow_name=dag.name,
            subclass=initial_inputs.get("subclass", "unknown"),
        )

        t_total = time.time()
        outputs: dict[str, Any] = dict(initial_inputs)

        for node in dag.nodes:
            t0 = time.time()
            try:
                agent = self.agent_registry.get(node.agent_name)
                if agent is None:
                    raise RuntimeError(f"agent {node.agent_name} 未注册")

                # 拼装 agent request
                agent_inputs = {}
                for input_key, src_key in node.inputs.items():
                    # src_key 可能是 "initial.xxx" / "outputs.X" / "node_id.output_key" / 字面值
                    if src_key.startswith("initial."):
                        actual_key = src_key[len("initial."):]
                        if actual_key in initial_inputs:
                            agent_inputs[input_key] = initial_inputs[actual_key]
                        continue

                    # M3 NEW: "outputs.X" 形式 — 引用全局 outputs dict
                    if src_key.startswith("outputs."):
                        actual_key = src_key[len("outputs."):]
                        if actual_key in outputs:
                            agent_inputs[input_key] = outputs[actual_key]
                        continue

                    if "." in src_key:
                        # "node_id.output_key" 形式
                        src_node_id, src_output_key = src_key.split(".", 1)
                        for nr in result.node_results:
                            if nr.node_id == src_node_id:
                                agent_inputs[input_key] = nr.outputs.get(src_output_key)
                                break
                        continue

                    # 字面值(没有 "." 且不是 "initial" 前缀,直接当字面值)
                    # 优先 outputs(避免硬覆盖),fallback 用 src_key 当字面值
                    if src_key in outputs:
                        agent_inputs[input_key] = outputs[src_key]
                    else:
                        agent_inputs[input_key] = src_key  # 字面值

                # 构造 AgentRequest
                from matwau.core.agent_base import AgentRequest

                # 默认 message + artifacts
                message = agent_inputs.get("message", "")
                artifacts = {k: v for k, v in agent_inputs.items() if k != "message"}

                # W15: 把 domain 透传到 req.context(让下游 agent 走对应 backend)
                req_context = {
                    "domain": initial_inputs.get("domain"),
                }

                req = AgentRequest(
                    run_id=f"{dag.name}-{node.node_id}",
                    message=message,
                    artifacts=artifacts if artifacts else None,
                    budget=initial_inputs.get("budget"),
                    context=req_context,
                )

                # 跑 agent
                response = agent.run(req)
                node_output = {
                    node.output_key: response,
                    "response": response,
                    "artifacts": response.artifacts,
                    "reply": response.reply,
                    "confidence": response.confidence,
                    "cost": response.cost,
                }
                # 也存每个 artifact
                if response.artifacts:
                    for k, v in response.artifacts.items():
                        node_output[k] = v

                # M3 NEW: 聚合 cross_source_records 给 critic_l5 节点用
                # 4 个 client 的 response.artifacts.records 聚合成 dict[platform] = records
                if node.agent_name in (
                    "mat-oqmd-agent",
                    "mat-cod-agent",
                    "mat-nomad-agent",
                    "mat-jarvis-agent",
                ):
                    plat_map = {
                        "mat-oqmd-agent": "OQMD",
                        "mat-cod-agent": "COD",
                        "mat-nomad-agent": "NOMAD",
                        "mat-jarvis-agent": "JARVIS",
                    }
                    plat = plat_map[node.agent_name]
                    # 收集到目前为止所有 records
                    cross_source_records = outputs.get("cross_source_records", {})
                    # 这条 response 的 records
                    recs = response.artifacts.get("records", []) if response.artifacts else []
                    # 同时存 records + artifacts(完整给 critic)
                    existing = cross_source_records.get(plat, {})
                    existing["records"] = recs
                    existing["artifacts"] = response.artifacts
                    cross_source_records[plat] = existing
                    node_output["cross_source_records"] = cross_source_records

                node_result = NodeResult(
                    node_id=node.node_id,
                    agent_name=node.agent_name,
                    success=True,
                    outputs=node_output,
                    duration_seconds=time.time() - t0,
                )
            except Exception as e:
                node_result = NodeResult(
                    node_id=node.node_id,
                    agent_name=node.agent_name,
                    success=False,
                    error=str(e),
                    duration_seconds=time.time() - t0,
                )

            result.node_results.append(node_result)

            if not node_result.success:
                result.success = False
                result.error = f"节点 {node.node_id} 失败: {node_result.error}"
                result.total_duration_seconds = time.time() - t_total
                return result

            # 把节点输出合并到 outputs,供下游节点用
            outputs.update(node_result.outputs)

        # 全部成功
        result.success = True
        result.total_duration_seconds = time.time() - t_total
        # final_outputs = 最后节点的 outputs
        if result.node_results:
            result.final_outputs = result.node_results[-1].outputs
        return result


# ============================================================================
# 5 workflow 模板
# ============================================================================


def experiment_planning_workflow() -> DAG:
    """experiment_planning:4 段(mat-gen → sim → hpc → exp)"""
    return DAG(
        name="experiment_planning",
        nodes=[
            DAGNode(
                node_id="gen",
                agent_name="mat-gen-agent",
                inputs={"message": "initial.user_intent"},
                output_key="gen_response",
                description="生成候选结构",
            ),
            DAGNode(
                node_id="sim",
                agent_name="mat-sim-agent",
                inputs={
                    "message": "弛豫",
                    "candidates": "gen.candidates",
                },
                output_key="sim_response",
                description="CHGNet 秒级弛豫",
            ),
            DAGNode(
                node_id="hpc",
                agent_name="mat-hpc-agent",
                inputs={
                    "message": "提交 VASP",
                    "simulated": "sim.simulated",
                },
                output_key="hpc_response",
                description="提交 VASP HPC",
            ),
            DAGNode(
                node_id="exp",
                agent_name="mat-exp-agent",
                inputs={
                    "message": "出实验方案",
                    "jobs": "hpc.jobs",
                },
                output_key="exp_response",
                description="出 XRD + 烧结方案",
            ),
        ],
    )


def design_new_material_workflow() -> DAG:
    """design_new_material:2 段(mat-gen → mat-sim) + 选 top-N

    不跑 HPC(用户先选 top-N 再决定要不要 HPC)
    """
    return DAG(
        name="design_new_material",
        nodes=[
            DAGNode(
                node_id="gen",
                agent_name="mat-gen-agent",
                inputs={"message": "initial.user_intent"},
                output_key="gen_response",
                description="生成候选结构(n_samples 通常 = 10)",
            ),
            DAGNode(
                node_id="sim",
                agent_name="mat-sim-agent",
                inputs={
                    "message": "弛豫",
                    "candidates": "gen.candidates",
                },
                output_key="sim_response",
                description="CHGNet 秒级弛豫,选 top-N 稳定候选",
            ),
        ],
    )


def optimize_existing_workflow() -> DAG:
    """optimize_existing:mat-sim 迭代 + 用户反馈

    Stage 1 mock:跑 1 次 mat-sim(后续可加 loop)
    """
    return DAG(
        name="optimize_existing",
        nodes=[
            DAGNode(
                node_id="sim",
                agent_name="mat-sim-agent",
                inputs={"message": "初始.user_intent"},
                output_key="sim_response",
                description="CHGNet 弛豫现有配方",
            ),
            DAGNode(
                node_id="gen_optimized",
                agent_name="mat-gen-agent",
                inputs={
                    "message": "基于弛豫结果优化",
                    "candidates": "sim.simulated",
                },
                output_key="gen_response",
                description="基于弛豫结果生成优化候选",
            ),
        ],
    )


def explain_failure_workflow() -> DAG:
    """explain_failure:mat-critic(W12 写,接真 agent)

    Stage 1(W12 之后):跑 MatCriticAgent 3 路交叉验证
    - 接 candidates / simulated / jobs / recipes 4 种上游数据(从 initial_inputs)
    - Stage 2 接 LLM 复核

    注:candidates 是可选的。如果用户只问"为什么 XRD 不对" 而没附数据,
    MatCriticAgent 内部会用 explain_failure() 给出文本建议。
    """
    return DAG(
        name="explain_failure",
        nodes=[
            DAGNode(
                node_id="critic",
                agent_name="mat-critic-agent",
                inputs={
                    "message": "initial.user_intent",
                    "candidates": "initial.candidates",  # 可选,默认 None
                },
                output_key="critic_response",
                description="mat-critic(W12): 3 路交叉验证(物理/合成/安全)",
            ),
        ],
    )


def literature_review_workflow() -> DAG:
    """literature_review:mat-lit(W14 已写,替换原 stub)

    Stage 1: 关键词提取 + mock 文献库 + 模板综述
    Stage 2(WAU v1.0.0 GA 后):接 arXiv + Materials Project + ICSD + PubChem 真 API
    """
    return DAG(
        name="literature_review",
        nodes=[
            DAGNode(
                node_id="lit",
                agent_name="mat-lit-agent",
                inputs={"message": "initial.user_intent"},
                output_key="lit_response",
                description="mat-lit(W14): 文献综述员",
            ),
        ],
    )


# ============================================================================
# M3 NEW — cross_source_lookup + cross_source_property workflow
# ============================================================================


def cross_source_lookup_workflow() -> DAG:
    """M3 cross_source_lookup: 4 数据源并行查化合物已知结构

    顺序 DAG 形式(Stage 1 不强制并行,真实 4 个 client 内部 cache + mock fallback):
    mat-oqmd-agent → mat-cod-agent → mat-nomad-agent → mat-jarvis-agent
    → mat-critic-agent (L5 cross_source_consistency_rule)

    输出:records_by_platform dict + consensus_rate + 一致性 verdict
    """
    return DAG(
        name="cross_source_lookup",
        nodes=[
            DAGNode(
                node_id="oqmd",
                agent_name="mat-oqmd-agent",
                inputs={"message": "initial.user_intent"},
                output_key="oqmd_response",
                description="OQMD DFT 数据(M1)",
            ),
            DAGNode(
                node_id="cod",
                agent_name="mat-cod-agent",
                inputs={"message": "initial.user_intent"},
                output_key="cod_response",
                description="COD 实验晶体结构(M1)",
            ),
            DAGNode(
                node_id="nomad",
                agent_name="mat-nomad-agent",
                inputs={"message": "initial.user_intent"},
                output_key="nomad_response",
                description="NOMAD archive 综合数据(M2)",
            ),
            DAGNode(
                node_id="jarvis",
                agent_name="mat-jarvis-agent",
                inputs={"message": "initial.user_intent"},
                output_key="jarvis_response",
                description="JARVIS 综合性质(M2)",
            ),
            DAGNode(
                node_id="critic_l5",
                agent_name="mat-critic-agent",
                inputs={
                    "message": "initial.user_intent",
                    "records_by_platform": "outputs.cross_source_records",
                    "use_cross_source": "true",
                },
                output_key="critic_response",
                description="mat-critic L5 跨数据源一致率(M3)",
            ),
        ],
    )


def cross_source_property_workflow() -> DAG:
    """M3 cross_source_property: 4 数据源 + critic L5(同 lookup,但 message 不同 — 表征性质对比)

    用同一套 5 节点 DAG,但 message 模板不同(强调"对比形成焓/带隙"等属性)。
    """
    return DAG(
        name="cross_source_property",
        nodes=[
            DAGNode(
                node_id="oqmd",
                agent_name="mat-oqmd-agent",
                inputs={"message": "initial.user_intent"},
                output_key="oqmd_response",
                description="OQMD DFT 形成焓 + 凸包距离",
            ),
            DAGNode(
                node_id="cod",
                agent_name="mat-cod-agent",
                inputs={"message": "initial.user_intent"},
                output_key="cod_response",
                description="COD 实验晶格常数",
            ),
            DAGNode(
                node_id="nomad",
                agent_name="mat-nomad-agent",
                inputs={"message": "initial.user_intent"},
                output_key="nomad_response",
                description="NOMAD archive + band_gap/formation_energy",
            ),
            DAGNode(
                node_id="jarvis",
                agent_name="mat-jarvis-agent",
                inputs={"message": "initial.user_intent"},
                output_key="jarvis_response",
                description="JARVIS Eg + bulk modulus",
            ),
            DAGNode(
                node_id="critic_l5",
                agent_name="mat-critic-agent",
                inputs={
                    "message": "initial.user_intent",
                    "records_by_platform": "outputs.cross_source_records",
                    "use_cross_source": "true",
                },
                output_key="critic_response",
                description="mat-critic L5 形成能/带隙跨源一致性",
            ),
        ],
    )


# 子类 → workflow 映射
WORKFLOW_BY_SUBCLASS = {
    "experiment_planning": experiment_planning_workflow,
    "design_new_material": design_new_material_workflow,
    "optimize_existing": optimize_existing_workflow,
    "explain_failure": explain_failure_workflow,
    "literature_review": literature_review_workflow,
    # M3 NEW
    "cross_source_lookup": cross_source_lookup_workflow,
    "cross_source_property": cross_source_property_workflow,
    "external_db_query": cross_source_lookup_workflow,         # alias to lookup
    "cross_source_validation": cross_source_property_workflow, # alias to property
}


def get_workflow_for_subclass(subclass: str) -> DAG | None:
    """根据子类选 workflow"""
    factory = WORKFLOW_BY_SUBCLASS.get(subclass)
    if factory is None:
        return None
    return factory()


# ============================================================================
# W31 — 多实验并行表征(Stage 3 JARVIS 雏形)
# ============================================================================


@dataclass
class ExperimentResult:
    """1 个 experiment 的完整结果(chemist + critic)

    W31 设计:聚合 1 次 MatChemistAgent.run + 1 次 MatCriticAgent.run
    - chemist_report 含 4 robot 物理证据(per W26)
    - critic_verdict 含 L4 跨机器人一致性(per W30)
    - verdict 取 critic.verdict(pass/warn/fail)
    - error 字段记录异常(parallel_runner 异常隔离用)
    """

    experiment_id: str                                # uuid4()[:8]
    target_sample: str                                # "Inconel 718"
    chemist_report: Any                               # ChemistReport(W31 patch 后取到)
    critic_verdict: Any                               # CriticVerdict(含 L4 cross_robot)
    cost_cny: float
    duration_seconds: float
    verdict: str                                      # pass / warn / fail
    error: str | None = None
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "target_sample": self.target_sample,
            "verdict": self.verdict,
            "cost_cny": round(self.cost_cny, 2),
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
            "blocked": self.blocked,
            "has_chemist_report": self.chemist_report is not None,
            "has_critic_verdict": self.critic_verdict is not None,
        }


@dataclass
class BatchWorkflowResult:
    """N 个 experiment 的 batch 结果(Stage 3 钢铁侠终极形态)

    W31 设计:
    - experiment_results 顺序与输入 experiments 一致
    - overall_verdict:all-pass → pass;部分 pass/warn → warn;全 fail → fail
    - parallel=True 时,total_duration_seconds 接近 max(单 experiment duration)
    - failed_samples() / all_passed() 是常用查询 helper
    """

    workflow_name: str = "multi_experiment_characterization"
    n_total: int = 0
    n_passed: int = 0
    n_warned: int = 0
    n_failed: int = 0
    n_blocked: int = 0
    experiment_results: list[ExperimentResult] = field(default_factory=list)
    total_cost_cny: float = 0.0
    total_duration_seconds: float = 0.0
    overall_verdict: str = "fail"                      # 默认 fail,空批次也是 fail
    parallel: bool = True
    max_workers: int = 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "n_total": self.n_total,
            "n_passed": self.n_passed,
            "n_warned": self.n_warned,
            "n_failed": self.n_failed,
            "n_blocked": self.n_blocked,
            "overall_verdict": self.overall_verdict,
            "total_cost_cny": round(self.total_cost_cny, 2),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "parallel": self.parallel,
            "max_workers": self.max_workers,
            "experiment_results": [r.to_dict() for r in self.experiment_results],
        }

    def all_passed(self) -> bool:
        """全部 N 个实验都 pass 才返回 True(空批次返回 False)"""
        return self.n_passed == self.n_total and self.n_total > 0

    def failed_samples(self) -> list[str]:
        """返回所有 verdict=fail 的 experiment target_sample 列表"""
        return [r.target_sample for r in self.experiment_results if r.verdict == "fail"]

    def warn_samples(self) -> list[str]:
        """返回所有 verdict=warn 的 experiment target_sample 列表"""
        return [r.target_sample for r in self.experiment_results if r.verdict == "warn"]


def multi_experiment_characterization_workflow() -> DAG:
    """W31 — 多实验并行表征的 stub DAG(实际由 run_batch() 驱动)

    设计意图:
    - 保留 DAG 形态以便 goldens 路由(subclass 名=multi_experiment_characterization)
    - 实际批执行由 MatOrchestrator.run_batch() 直接用 ParallelBatchRunner,
      绕开 DAGExecutor(避免污染 W10 的 18 个老 case)
    - 这 1 个 critic 节点是占位符,实际 verdict 由 run_batch 注入
    """
    return DAG(
        name="multi_experiment_characterization",
        nodes=[
            DAGNode(
                node_id="critic_overall",
                agent_name="mat-critic-agent",
                inputs={
                    "message": "initial.user_intent",
                    "candidate": "initial.target_sample",
                },
                output_key="critic_response",
                description="mat-critic:批聚合 W31(per-experiment verdict 由 run_batch 注入)",
            ),
        ],
    )


# W31 — 第 6 个 workflow 模板注册
WORKFLOW_BY_SUBCLASS["multi_experiment_characterization"] = multi_experiment_characterization_workflow


def get_multi_experiment_default_batch() -> list[Any]:
    """默认 3 实验批(Inconel 718 + PMMA + TiO2)— 覆盖 3 domain

    Returns:
        List[ChemistTask]
    """
    from agents.mat_chemist_agent.chemist_engine import (
        ChemistTask,
        RobotStep,
        get_default_inconel_718_workflow,
        get_default_pmma_workflow,
    )

    # Inconel 718 — 4 步 metal 全跑
    task1 = get_default_inconel_718_workflow()
    # PMMA — 2 步 polymer
    task2 = get_default_pmma_workflow()
    # TiO2 — W31 NEW — 3 步 ceramic quick scan
    task3 = ChemistTask(
        target_sample="TiO2",
        domain="ceramic",
        goal="TiO2 完整表征(合成 + 晶体 + 热学)",
        robot_steps=[
            RobotStep(
                robot_type="synth",
                description="制备 TiO2 标样(球磨 + 烧结)",
                estimated_cost_cny=150.0,
            ),
            RobotStep(
                robot_type="xrd",
                description="XRD 测 TiO2 晶体相(参考 PDF #21-1272)",
                estimated_cost_cny=120.0,
            ),
            RobotStep(
                robot_type="dsc",
                description="DSC 测 TiO2 相变",
                estimated_cost_cny=80.0,
            ),
        ],
        budget_cny=5000.0,
        parallel_allowed=True,
    )
    return [task1, task2, task3]


__all__ = [
    "DAG",
    "WORKFLOW_BY_SUBCLASS",
    "BatchWorkflowResult",                          # W31 NEW
    "DAGExecutor",
    "DAGNode",
    "ExperimentResult",                             # W31 NEW
    "NodeResult",
    "WorkflowResult",
    # M3 NEW
    "cross_source_lookup_workflow",
    "cross_source_property_workflow",
    "design_new_material_workflow",
    "experiment_planning_workflow",
    "explain_failure_workflow",
    "get_multi_experiment_default_batch",           # W31 NEW
    "get_workflow_for_subclass",
    "literature_review_workflow",
    "multi_experiment_characterization_workflow",   # W31 NEW
    "optimize_existing_workflow",
]