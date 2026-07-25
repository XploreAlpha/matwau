"""mat-cost-agent — 材料科学成本估算员

Stage 1: 纯查表 + 加合(AGENT_UNIT_COST 预定义单 agent 单次成本)
Stage 2: 接 wau-cost 统一成本 SDK

适用场景:
- workflow 启动前估算总成本
- 比 budget 给 over_budget 警告
- 提供降本建议(HPC job 减 / 主动学习 / Stage 1 mock)

per MatWAU-开发计划 §七 W14
"""
from .cost_engine import (
    AGENT_UNIT_COST,
    AGENT_COST_FIELD,
    WORKFLOW_AGENTS,
    CostEstimate,
    estimate_agent_cost,
    estimate_from_artifacts,
    estimate_workflow_cost,
    suggest_cost_reduction,
)
from .mat_cost_agent import (
    CostConfig,
    MatCostAgent,
    create_default_agent,
)

__all__ = [
    "MatCostAgent",
    "CostConfig",
    "CostEstimate",
    "AGENT_UNIT_COST",
    "AGENT_COST_FIELD",
    "WORKFLOW_AGENTS",
    "create_default_agent",
    "estimate_agent_cost",
    "estimate_workflow_cost",
    "estimate_from_artifacts",
    "suggest_cost_reduction",
]