"""cost_engine.py — mat-cost 的成本估算引擎

职责:
1. 预定义每个 agent 的单次/单候选成本
2. 给定 workflow + 候选数 → cost breakdown
3. 比 budget 给 over_budget 警告 + 降本建议
4. Stage 2 准备:wau-cost SDK 接入点(成本查询 / 实际计费)

Stage 1 / Phase 1:纯查表 + 加合
Stage 2(WAU v1.0.0 GA 后):接 wau-cost 统一成本 SDK

per MatWAU-开发计划 §七 W14
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================================
# Agent 单次成本表(Stage 1 预定义)
# ============================================================================


# 每 agent 单次运行成本(¥)
# 解释:
#   - mat-gen-agent:¥0.06/候选(MatterGen ¥0.05 + LLM ¥0.01)
#   - mat-sim-agent:¥0.5/候选(CHGNet MLIP 推理)
#   - mat-hpc-agent:¥100/job(VASP HPC 真实机时)
#   - mat-exp-agent:¥10/配方(实验台时 + 试剂)
#   - mat-critic-agent:¥0.05/次(规则引擎)
#   - mat-bayesian-agent:¥0.02/次(NumPy)
#   - mat-lit-agent:¥0.1/次(mock 数据库)
#   - mat-intent-agent:¥0.01/次(简单分类)
#   - mat-cost-agent:¥0.001/次(本地计算)
#   - mat-data-lineage-agent:¥0.001/次(本地存储)

AGENT_UNIT_COST = {
    "mat-gen-agent": 0.06,            # / 候选
    "mat-sim-agent": 0.5,             # / 候选
    "mat-hpc-agent": 100.0,           # / job
    "mat-exp-agent": 10.0,            # / 配方
    "mat-critic-agent": 0.05,         # / 次
    "mat-bayesian-agent": 0.02,       # / 次
    "mat-lit-agent": 0.1,             # / 次
    "mat-intent-agent": 0.01,         # / 次
    "mat-cost-agent": 0.001,          # / 次
    "mat-data-lineage-agent": 0.001,  # / 次
}


# 每个 agent 算成本的字段(per artifact 里的字段名)
# 例如 mat-gen-agent 看 "candidates" 字段,数候选数
# 例如 mat-hpc-agent 看 "jobs" 字段,数 job 数
AGENT_COST_FIELD = {
    "mat-gen-agent": "candidates",
    "mat-sim-agent": "candidates",
    "mat-hpc-agent": "jobs",
    "mat-exp-agent": "recipes",
    "mat-critic-agent": "candidates",
    "mat-bayesian-agent": None,       # 按 1 次算
    "mat-lit-agent": None,            # 按 1 次算
    "mat-intent-agent": None,
    "mat-cost-agent": None,
    "mat-data-lineage-agent": None,
}


# 5 个 workflow 的节点顺序(per dag.py)
WORKFLOW_AGENTS = {
    "experiment_planning": ["mat-gen-agent", "mat-sim-agent", "mat-hpc-agent", "mat-exp-agent"],
    "design_new_material": ["mat-gen-agent", "mat-sim-agent"],
    "optimize_existing": ["mat-sim-agent", "mat-gen-agent"],
    "explain_failure": ["mat-critic-agent"],
    "literature_review": ["mat-lit-agent"],
}


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class CostEstimate:
    """1 个 workflow 的成本估算"""

    workflow: str
    n_candidates: int                 # 总候选数(从 user / artifacts 推断)
    breakdown: Dict[str, float]       # agent_name → ¥
    total: float                      # 总成本 ¥
    budget: Optional[float] = None
    over_budget: bool = False
    overage: float = 0.0              # 超出量 ¥
    suggestions: List[str] = field(default_factory=list)  # 降本建议

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow": self.workflow,
            "n_candidates": self.n_candidates,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "total": round(self.total, 2),
            "budget": self.budget,
            "over_budget": self.over_budget,
            "overage": round(self.overage, 2),
            "suggestions": self.suggestions,
        }


# ============================================================================
# 成本估算
# ============================================================================


def estimate_agent_cost(
    agent_name: str,
    artifacts: Optional[Dict[str, Any]] = None,
    n_override: Optional[int] = None,
    *,
    domain: Optional[str] = None,
) -> float:
    """估算 1 个 agent 的成本

    Args:
        agent_name: agent 名(mat-gen-agent 等)
        artifacts: agent 输出的 artifacts dict(数实际候选数)
        n_override: 手动覆盖候选数(用户传)
        domain: 材料域(W15;None → 默认 inorganic_crystal)

    Returns:
        成本 ¥
    """
    artifacts = artifacts or {}

    # W15: domain 单价表(优先 > 全局 AGENT_UNIT_COST)
    unit = AGENT_UNIT_COST.get(agent_name, 0.01)
    if domain is not None:
        try:
            from agents.material_domain_router import get_unit_cost_table
            unit_table = get_unit_cost_table(domain)
            unit = unit_table.get(agent_name, unit)
        except Exception:
            pass

    # 1. n_override 优先
    if n_override is not None:
        return round(unit * n_override, 2)

    # 2. 数 artifacts 里相关字段
    field_name = AGENT_COST_FIELD.get(agent_name)
    if field_name and field_name in artifacts:
        items = artifacts[field_name]
        if isinstance(items, list):
            return round(unit * len(items), 2)
        if isinstance(items, (int, float)):
            return round(unit * int(items), 2)
        return round(unit, 2)  # 1 次

    # 3. 默认 1 次
    return round(unit, 2)


def estimate_workflow_cost(
    workflow: str,
    n_candidates: int = 10,
    budget: Optional[float] = None,
    per_node_costs: Optional[Dict[str, float]] = None,
    *,
    domain: Optional[str] = None,
) -> CostEstimate:
    """估算 1 个 workflow 的总成本(W15: 支持 domain)

    Args:
        workflow: workflow 名(experiment_planning 等)
        n_candidates: 候选数(影响 gen/sim/hpc)
        budget: 预算 ¥
        per_node_costs: 手动覆盖各节点成本(Stage 2 接 wau-cost 后用)
        domain: 材料域(W15;None → 默认 inorganic_crystal)

    Returns:
        CostEstimate
    """
    if workflow not in WORKFLOW_AGENTS:
        # 未知 workflow:用所有 agent 的 1 次成本加合
        breakdown = {a: estimate_agent_cost(a, n_override=1, domain=domain) for a in AGENT_UNIT_COST}
    else:
        agents = WORKFLOW_AGENTS[workflow]
        breakdown = {}
        per_node = per_node_costs or {}
        for agent in agents:
            if agent in per_node:
                # 手动覆盖(Stage 2 用 wau-cost 实际计费)
                breakdown[agent] = per_node[agent]
            else:
                # 默认按 n_candidates 算(gen / sim)— 透传 domain
                if agent in ("mat-gen-agent", "mat-sim-agent", "mat-critic-agent"):
                    breakdown[agent] = estimate_agent_cost(agent, n_override=n_candidates, domain=domain)
                elif agent == "mat-hpc-agent":
                    # HPC 默认 n_candidates / 2(只跑稳定候选)
                    breakdown[agent] = estimate_agent_cost(agent, n_override=max(1, n_candidates // 2), domain=domain)
                elif agent == "mat-exp-agent":
                    # exp 默认 n_candidates / 4(只跑 top-N)
                    breakdown[agent] = estimate_agent_cost(agent, n_override=max(1, n_candidates // 4), domain=domain)
                else:
                    breakdown[agent] = estimate_agent_cost(agent, n_override=1, domain=domain)

    total = sum(breakdown.values())

    # 比 budget
    over_budget = False
    overage = 0.0
    suggestions = []

    if budget is not None and total > budget:
        over_budget = True
        overage = total - budget
        suggestions.append(f"总成本 ¥{total:.2f} 超过预算 ¥{budget:.2f},超出 ¥{overage:.2f}")

    # 降本建议
    if breakdown.get("mat-hpc-agent", 0) > 50:
        suggestions.append("HPC 成本 ¥" + f"{breakdown['mat-hpc-agent']:.2f} 占比高,可考虑减少 HPC job 数(只跑 top-3 稳定候选)")

    if breakdown.get("mat-sim-agent", 0) > 5:
        suggestions.append("mat-sim 成本 ¥" + f"{breakdown['mat-sim-agent']:.2f} 占比高,可考虑 Stage 1 mock(Stage 2 切真)")

    if breakdown.get("mat-exp-agent", 0) > 20:
        suggestions.append("mat-exp 成本 ¥" + f"{breakdown['mat-exp-agent']:.2f} 占比高,可先 mat-bayesian 主动学习后再实验")

    if not suggestions:
        suggestions.append("当前成本在合理范围,无降本建议")

    return CostEstimate(
        workflow=workflow,
        n_candidates=n_candidates,
        breakdown=breakdown,
        total=round(total, 2),
        budget=budget,
        over_budget=over_budget,
        overage=round(overage, 2),
        suggestions=suggestions,
    )


def estimate_from_artifacts(
    workflow: str,
    artifacts: Optional[Dict[str, Any]] = None,
    budget: Optional[float] = None,
) -> CostEstimate:
    """从实际 artifacts 数算成本(更准确)

    Args:
        workflow: workflow 名
        artifacts: 各 agent 实际输出的 artifacts dict
            格式:{agent_name: artifacts_dict}
        budget: 预算 ¥

    Returns:
        CostEstimate
    """
    artifacts = artifacts or {}
    breakdown = {}
    agents = WORKFLOW_AGENTS.get(workflow, list(AGENT_UNIT_COST.keys()))

    for agent in agents:
        agent_artifacts = artifacts.get(agent, {})
        breakdown[agent] = estimate_agent_cost(agent, artifacts=agent_artifacts)

    total = sum(breakdown.values())
    over_budget = budget is not None and total > budget
    overage = max(0, total - budget) if budget is not None else 0.0

    suggestions = []
    if over_budget:
        suggestions.append(f"实际成本 ¥{total:.2f} 超预算 ¥{budget:.2f}")
    if breakdown.get("mat-hpc-agent", 0) > 50:
        suggestions.append("HPC 成本占比高,后续考虑减少 job 数")
    if not suggestions:
        suggestions.append("当前成本合理")

    return CostEstimate(
        workflow=workflow,
        n_candidates=0,    # 从 artifacts 算不出
        breakdown=breakdown,
        total=round(total, 2),
        budget=budget,
        over_budget=over_budget,
        overage=round(overage, 2),
        suggestions=suggestions,
    )


# ============================================================================
# 降本策略
# ============================================================================


def suggest_cost_reduction(
    estimate: CostEstimate,
    target_budget: float,
) -> List[str]:
    """给降本建议(把成本压到 target_budget 内)

    Args:
        estimate: 现有 CostEstimate
        target_budget: 目标预算

    Returns:
        降本建议列表
    """
    suggestions = []
    if estimate.total <= target_budget:
        suggestions.append(f"当前 ¥{estimate.total:.2f} 已 <= 目标 ¥{target_budget:.2f},无需降本")
        return suggestions

    overage = estimate.total - target_budget
    suggestions.append(f"需降本 ¥{overage:.2f} 才能达到预算 ¥{target_budget:.2f}")

    # 按 agent 贡献占比排序
    sorted_agents = sorted(estimate.breakdown.items(), key=lambda x: -x[1])

    for agent, cost in sorted_agents:
        if cost < 1.0:
            continue
        pct = cost / estimate.total
        if agent == "mat-hpc-agent" and pct > 0.3:
            suggestions.append(
                f"HPC 占比 {pct:.0%}:VASP 是大成本,考虑:1) 跑 SLURM 多机并行;2) 只跑 top-3 稳定候选;3) 用 mat-bayesian 选最有希望的"
            )
        elif agent == "mat-exp-agent" and pct > 0.1:
            suggestions.append(
                f"exp 占比 {pct:.0%}:实验试剂 + 台时,考虑:1) XRD 共享机时;2) 烧结炉并行;3) mat-bayesian 主动学习"
            )
        elif agent == "mat-sim-agent" and pct > 0.05:
            suggestions.append(
                f"sim 占比 {pct:.0%}:CHGNet MLIP 推理,考虑:1) Stage 1 mock;2) 减少候选数;3) GPU 批量"
            )

    if not any("HPC" in s or "exp" in s or "sim" in s for s in suggestions):
        suggestions.append("降本空间有限,建议申请更多预算")

    return suggestions


__all__ = [
    "AGENT_UNIT_COST",
    "AGENT_COST_FIELD",
    "WORKFLOW_AGENTS",
    "CostEstimate",
    "estimate_agent_cost",
    "estimate_workflow_cost",
    "estimate_from_artifacts",
    "suggest_cost_reduction",
]