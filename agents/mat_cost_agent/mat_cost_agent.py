"""mat-cost-agent — 材料科学成本估算员(per dev plan §七 W14)

Stage 1 / Phase 1:纯查表 + 加合
Stage 2(WAU v1.0.0 GA 后):接 wau-cost 统一成本 SDK

业务流程(per act() 实现):
1. 解析 user_intent → workflow + n_candidates + budget
2. 调 cost_engine.estimate_workflow_cost
3. 比 budget 给 over_budget 警告 + 降本建议
4. 返回 CostEstimate

用法:
    from agents.mat_cost_agent.mat_cost_agent import MatCostAgent
    from matwau.core.agent_base import AgentRequest

    agent = MatCostAgent()
    req = AgentRequest(
        run_id="cost-001",
        message="experiment_planning workflow 跑 10 候选,预算 ¥200",
        context={"workflow": "experiment_planning", "n_candidates": 10, "budget": 200},
    )
    response = agent.run(req)
    print(response.artifacts["estimate"].total)  # 总成本
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许直接 python3 -m 运行本文件
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

from .cost_engine import (  # noqa: E402
    AGENT_UNIT_COST,
    CostEstimate,
    WORKFLOW_AGENTS,
    estimate_from_artifacts,
    estimate_workflow_cost,
)


# ============================================================================
# 配置 + 辅助
# ============================================================================


@dataclass
class CostConfig:
    """用户配置(per AgentRequest.context)"""

    workflow: str = "experiment_planning"
    n_candidates: int = 10
    budget: Optional[float] = None
    per_node_costs: Optional[Dict[str, float]] = None
    include_reduction_suggestions: bool = True

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "CostConfig":
        if not d:
            return cls()
        return cls(
            workflow=d.get("workflow", "experiment_planning"),
            n_candidates=d.get("n_candidates", 10),
            budget=d.get("budget"),
            per_node_costs=d.get("per_node_costs"),
            include_reduction_suggestions=d.get("include_reduction_suggestions", True),
        )


def _estimate_to_response(estimate: CostEstimate, config: CostConfig) -> AgentResponse:
    """CostEstimate → AgentResponse"""
    lines = [
        f"💰 mat-cost 估算: {estimate.workflow} workflow",
        f"   候选数: {estimate.n_candidates} | 总成本: ¥{estimate.total:.2f}",
    ]

    if estimate.budget is not None:
        budget_str = f"¥{estimate.budget:.2f}"
        if estimate.over_budget:
            lines.append(f"   ⚠️ 超预算!预算 {budget_str} / 超出 ¥{estimate.overage:.2f}")
        else:
            lines.append(f"   ✓ 在预算内(预算 {budget_str},剩余 ¥{estimate.budget - estimate.total:.2f})")

    lines.append(f"\n📊 成本分解:")
    sorted_breakdown = sorted(estimate.breakdown.items(), key=lambda x: -x[1])
    for agent, cost in sorted_breakdown:
        pct = cost / estimate.total * 100 if estimate.total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        lines.append(f"   {bar} {agent:30s} ¥{cost:>8.2f} ({pct:5.1f}%)")

    if estimate.suggestions:
        lines.append(f"\n💡 建议:")
        for s in estimate.suggestions[:5]:
            lines.append(f"   - {s}")

    return AgentResponse(
        reply="\n".join(lines),
        artifacts={
            "estimate": estimate,
            "estimate_dict": estimate.to_dict(),
            "workflow": estimate.workflow,
            "n_candidates": estimate.n_candidates,
            "breakdown": estimate.breakdown,
            "total": estimate.total,
            "budget": estimate.budget,
            "over_budget": estimate.over_budget,
            "overage": estimate.overage,
            "suggestions": estimate.suggestions,
        },
        confidence=0.9 if not estimate.over_budget else 0.6,
        cost=0.001,  # mat-cost 自身成本
    )


# ============================================================================
# MatCostAgent 主体
# ============================================================================


class MatCostAgent(MatWAUAgentBase):
    """mat-cost-agent — 材料科学成本估算员

    业务流程:
    1. 解析 user_intent / context → CostConfig(workflow + n_candidates + budget)
    2. 调 cost_engine.estimate_workflow_cost
    3. 返回 CostEstimate + 警告 + 降本建议
    """

    name = "mat-cost-agent"

    def __init__(
        self,
        *,
        default_n_candidates: int = 10,
        cost_per_call: float = 0.001,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.default_n_candidates = default_n_candidates
        self.cost_per_call = cost_per_call

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学成本估算员 agent(mat-cost-agent),用预定义成本表估算 workflow 成本。

能力:
1. 接收 CostConfig(workflow + n_candidates + budget)
2. 调 cost_engine.estimate_workflow_cost 算每 agent 成本
3. 比 budget 给 over_budget 警告 + 降本建议
4. 返回 CostEstimate(breakdown + total + over_budget + suggestions)

5 个 workflow + agent 单价(per cost_engine.py):
- mat-gen-agent:¥0.06/候选(MatterGen + LLM)
- mat-sim-agent:¥0.5/候选(CHGNet MLIP)
- mat-hpc-agent:¥100/job(VASP)
- mat-exp-agent:¥10/配方
- mat-critic / mat-bayesian / mat-lit / mat-intent:小成本(¥0.01-0.1/次)

Stage 1 纯查表,Stage 2 接 wau-cost 统一成本 SDK。

约束:
- 0 行 UI 代码
- 1 次调用 = 1 次 Goldens 跑分(mat-cost.yaml,pass-rate > 50% Stage 1)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ""
        config: CostConfig = ctx.get("_input_config") or CostConfig()

        # W15: 域路由(从 ctx["domain"] 取)
        ctx_domain = ctx.get("domain")

        # 1. 跑估算(W15: 透传 domain)
        try:
            estimate = estimate_workflow_cost(
                workflow=config.workflow,
                n_candidates=config.n_candidates,
                budget=config.budget,
                per_node_costs=config.per_node_costs,
                domain=ctx_domain,
            )
        except Exception as e:
            return self._error_response(f"mat-cost 估算失败: {e}")

        # 2. 转 response
        response = _estimate_to_response(estimate, config)

        # 3. SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = CostConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-cost: {reason}",
            artifacts={"estimate": None, "total": 0.0},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-cost 错误: {error}",
            artifacts={"estimate": None, "total": 0.0},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatCostAgent:
    return MatCostAgent(
        default_n_candidates=10,
        cost_per_call=0.001,
    )


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatCostAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    # Demo 1: experiment_planning 10 候选预算 200
    print("\n💰 Demo 1: experiment_planning 10 候选预算 ¥200")
    req1 = AgentRequest(
        run_id="cost-demo-1",
        message="experiment_planning 10 候选预算 200",
        context={"workflow": "experiment_planning", "n_candidates": 10, "budget": 200},
    )
    r1 = agent.run(req1)
    print(r1.reply)

    # Demo 2: design_new_material 不设预算
    print("\n\n💰 Demo 2: design_new_material 不设预算")
    req2 = AgentRequest(
        run_id="cost-demo-2",
        message="design_new_material 5 候选",
        context={"workflow": "design_new_material", "n_candidates": 5},
    )
    r2 = agent.run(req2)
    print(r2.reply)

    # Demo 3: 预算很低
    print("\n\n💰 Demo 3: 预算很低 ¥50")
    req3 = AgentRequest(
        run_id="cost-demo-3",
        message="experiment_planning 10 候选预算 50",
        context={"workflow": "experiment_planning", "n_candidates": 10, "budget": 50},
    )
    r3 = agent.run(req3)
    print(r3.reply)


__all__ = [
    "MatCostAgent",
    "CostConfig",
    "create_default_agent",
]