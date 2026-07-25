"""mat_chemist_agent — 化学师协调 agent(W26)

W26 第 5 个物理世界 agent 角色(不是机器人,而是 JARVIS 协调员)
W26 关键:
- 接收材料研究目标 → 拆解 4 个 robot step(synth/xrd/em/dsc)
- 串行调用 4 个 robot agent
- 汇总 4 个结果成 1 个 ChemistReport
- ChemistSafetyGuard 5 类协调级拦截(预算 / 样品竞争 / 危险顺序 / 样品量过大 / 跨机器人一致性)
- 跨机器人结果 cross_validation

per MatWAU-Stage 3 钢铁侠 doc §3.5 Phase 4 + Stage 3 JARVIS 愿景
"""

from .chemist_engine import (  # noqa: F401
    ChemistReport,
    ChemistSafetyGuard,
    ChemistTask,
    RobotStep,
    RobotStepResult,
    CHEMIST_DEFAULT_BUDGET_CNY,
    ROBOT_TYPES,
    decompose_goal_to_robots,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
)
from .mat_chemist_agent import MatChemistAgent  # noqa: F401

__all__ = [
    "MatChemistAgent",
    "ChemistTask",
    "ChemistReport",
    "ChemistSafetyGuard",
    "RobotStep",
    "RobotStepResult",
    "CHEMIST_DEFAULT_BUDGET_CNY",
    "ROBOT_TYPES",
    "decompose_goal_to_robots",
    "get_default_inconel_718_workflow",
    "get_default_pmma_workflow",
]