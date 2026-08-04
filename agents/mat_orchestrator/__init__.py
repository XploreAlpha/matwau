"""mat-orchestrator — DAG 调度器(per W10) + W31 多实验并行

接 mat-intent 解析结果,根据子类选 workflow 模板,执行 DAG。

W31 扩展:
- 新增第 6 个 workflow 模板:multi_experiment_characterization
- 新增 BatchWorkflowResult / ExperimentResult dataclass
- 新增 ParallelBatchRunner(ThreadPoolExecutor)
- MatOrchestrator.run_batch() 跑 N 个实验并行 + critic 复核

Stage 1 mock:所有 workflow 跑现有 agent(mat-gen/sim/hpc/exp/intent)
Stage 2 接 mat-lit / mat-critic(W12/W14 写)
Stage 3 W26: mat-chemist-agent 接入
Stage 3 W30: mat-critic-agent 升级吃 ChemistReport + L4 cross_robot
Stage 3 W31: 多实验并行调度(本仓)

6 workflow 模板:
- experiment_planning:4 段(mat-gen → sim → hpc → exp)
- design_new_material:2 段(mat-gen → sim)+ top-N
- optimize_existing:mat-sim 迭代 + 用户反馈
- explain_failure:mat-critic(W12 stub)
- literature_review:mat-lit(W14 stub)
- multi_experiment_characterization:W31 — MatOrchestrator.run_batch() 跑 N 个 ChemistTask + critic 复核
"""
from .dag import (
    DAG,
    WORKFLOW_BY_SUBCLASS,
    # W31 NEW
    BatchWorkflowResult,
    DAGExecutor,
    DAGNode,
    ExperimentResult,
    NodeResult,
    WorkflowResult,
    get_multi_experiment_default_batch,
    get_workflow_for_subclass,
    multi_experiment_characterization_workflow,
)
from .mat_orchestrator import MatOrchestrator, create_default_orchestrator
from .parallel_runner import ParallelBatchRunner  # W31 NEW

__all__ = [
    "DAG",
    "WORKFLOW_BY_SUBCLASS",
    "BatchWorkflowResult",
    "DAGExecutor",
    # DAG 基础
    "DAGNode",
    # W31 NEW
    "ExperimentResult",
    # Agent
    "MatOrchestrator",
    "NodeResult",
    "ParallelBatchRunner",
    "WorkflowResult",
    "create_default_orchestrator",
    "get_multi_experiment_default_batch",
    "get_workflow_for_subclass",
    # 6 workflow 模板(5 老 + 1 W31 NEW)
    "multi_experiment_characterization_workflow",
]