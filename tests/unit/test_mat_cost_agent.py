"""test_mat_cost_agent.py — W14 mat-cost 单元测试 + Goldens 跑分

测试覆盖:
1. 单 agent 成本估算
2. workflow 成本估算
3. budget 超支判断
4. 降本建议
5. MatCostAgent 端到端
6. Goldens 15 case 跑分

per MatWAU-开发计划 §七 W14
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_cost_agent import (  # noqa: E402
    AGENT_UNIT_COST,
    CostConfig,
    CostEstimate,
    MatCostAgent,
    WORKFLOW_AGENTS,
    create_default_agent,
    estimate_agent_cost,
    estimate_from_artifacts,
    estimate_workflow_cost,
    suggest_cost_reduction,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-cost.yaml")


# ============================================================================
# Test 1: 单 agent 成本
# ============================================================================


class TestAgentUnitCost:
    """单 agent 单次/单候选成本"""

    def test_gen_cost(self):
        cost = estimate_agent_cost("mat-gen-agent", n_override=10)
        assert cost == 0.6  # 0.06 * 10

    def test_hpc_cost(self):
        cost = estimate_agent_cost("mat-hpc-agent", n_override=5)
        assert cost == 500.0  # 100 * 5

    def test_sim_cost(self):
        cost = estimate_agent_cost("mat-sim-agent", n_override=3)
        assert cost == 1.5  # 0.5 * 3

    def test_critic_cost(self):
        cost = estimate_agent_cost("mat-critic-agent", n_override=1)
        assert cost == 0.05

    def test_bayesian_cost(self):
        cost = estimate_agent_cost("mat-bayesian-agent", n_override=1)
        assert cost == 0.02

    def test_lit_cost(self):
        cost = estimate_agent_cost("mat-lit-agent", n_override=1)
        assert cost == 0.1

    def test_from_artifacts_list(self):
        artifacts = {"candidates": [{}, {}, {}]}  # 3 候选
        cost = estimate_agent_cost("mat-gen-agent", artifacts=artifacts)
        assert cost == 0.18  # 0.06 * 3

    def test_unknown_agent(self):
        cost = estimate_agent_cost("mat-unknown-agent", n_override=1)
        # 未知 agent 用 default 0.01
        assert cost == 0.01


# ============================================================================
# Test 2: workflow 成本
# ============================================================================


class TestWorkflowCost:
    """workflow 成本估算"""

    def test_experiment_planning(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10)
        assert est.workflow == "experiment_planning"
        # 4 节点(gen + sim + hpc + exp)
        assert "mat-gen-agent" in est.breakdown
        assert "mat-sim-agent" in est.breakdown
        assert "mat-hpc-agent" in est.breakdown
        assert "mat-exp-agent" in est.breakdown
        # HPC 占大头
        assert est.breakdown["mat-hpc-agent"] > est.breakdown["mat-gen-agent"]

    def test_design_new_material(self):
        est = estimate_workflow_cost("design_new_material", n_candidates=5)
        assert "mat-gen-agent" in est.breakdown
        assert "mat-sim-agent" in est.breakdown
        # 没有 hpc / exp
        assert "mat-hpc-agent" not in est.breakdown
        assert "mat-exp-agent" not in est.breakdown

    def test_literature_review(self):
        est = estimate_workflow_cost("literature_review", n_candidates=1)
        assert "mat-lit-agent" in est.breakdown
        # 便宜
        assert est.total < 1.0

    def test_unknown_workflow(self):
        est = estimate_workflow_cost("unknown_workflow", n_candidates=1)
        # 所有 agent 都按 1 次算
        assert len(est.breakdown) == len(AGENT_UNIT_COST)


# ============================================================================
# Test 3: Budget 检查
# ============================================================================


class TestBudget:
    """budget 超支判断"""

    def test_within_budget(self):
        est = estimate_workflow_cost("design_new_material", n_candidates=5, budget=10.0)
        assert not est.over_budget
        assert est.overage == 0.0

    def test_over_budget(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10, budget=200.0)
        assert est.over_budget
        assert est.overage > 0

    def test_budget_none(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10, budget=None)
        assert not est.over_budget

    def test_budget_exact(self):
        # 算到精确预算
        est1 = estimate_workflow_cost("design_new_material", n_candidates=5)
        est2 = estimate_workflow_cost("design_new_material", n_candidates=5, budget=est1.total)
        assert not est2.over_budget


# ============================================================================
# Test 4: 降本建议
# ============================================================================


class TestReduction:
    """降本建议"""

    def test_hpc_suggestion(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10)
        suggestions = est.suggestions
        # HPC 占比高应该有 HPC 降本建议
        assert any("HPC" in s for s in suggestions)

    def test_estimate_to_dict(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10, budget=200.0)
        d = est.to_dict()
        assert d["workflow"] == "experiment_planning"
        assert d["over_budget"] is True
        assert d["overage"] > 0
        assert "mat-hpc-agent" in d["breakdown"]

    def test_suggest_cost_reduction_within(self):
        est = estimate_workflow_cost("design_new_material", n_candidates=5, budget=10.0)
        suggestions = suggest_cost_reduction(est, target_budget=10.0)
        # 已经 <= 目标
        assert any("无需降本" in s for s in suggestions)

    def test_suggest_cost_reduction_over(self):
        est = estimate_workflow_cost("experiment_planning", n_candidates=10)
        suggestions = suggest_cost_reduction(est, target_budget=100.0)
        # 需要降本
        assert len(suggestions) > 0


# ============================================================================
# Test 5: estimate_from_artifacts
# ============================================================================


class TestFromArtifacts:
    """从实际 artifacts 算成本"""

    def test_from_artifacts(self):
        artifacts = {
            "mat-gen-agent": {"candidates": [{}, {}, {}]},     # 3 候选
            "mat-sim-agent": {"candidates": [{}, {}]},          # 2 候选
            "mat-hpc-agent": {"jobs": [{}]},                    # 1 job
            "mat-exp-agent": {"recipes": [{}]},                 # 1 配方
        }
        est = estimate_from_artifacts("experiment_planning", artifacts)
        assert est.breakdown["mat-gen-agent"] == 0.18
        assert est.breakdown["mat-sim-agent"] == 1.0
        assert est.breakdown["mat-hpc-agent"] == 100.0
        assert est.breakdown["mat-exp-agent"] == 10.0

    def test_from_artifacts_empty(self):
        est = estimate_from_artifacts("experiment_planning", {})
        # 0 候选 0 job → 总 0
        # 但各 agent 仍跑(1 次)
        assert est.breakdown["mat-hpc-agent"] >= 0


# ============================================================================
# Test 6: CostEstimate dataclass
# ============================================================================


class TestCostEstimate:
    """CostEstimate dataclass"""

    def test_to_dict(self):
        est = CostEstimate(
            workflow="test",
            n_candidates=5,
            breakdown={"a": 1.0, "b": 2.0},
            total=3.0,
            budget=10.0,
        )
        d = est.to_dict()
        assert d["workflow"] == "test"
        assert d["total"] == 3.0
        assert d["breakdown"]["a"] == 1.0


# ============================================================================
# Test 7: CostConfig
# ============================================================================


class TestCostConfig:
    """配置 dataclass"""

    def test_default(self):
        cfg = CostConfig()
        assert cfg.workflow == "experiment_planning"
        assert cfg.n_candidates == 10
        assert cfg.budget is None

    def test_from_dict(self):
        cfg = CostConfig.from_dict({"workflow": "design_new_material", "n_candidates": 5, "budget": 50.0})
        assert cfg.workflow == "design_new_material"
        assert cfg.n_candidates == 5
        assert cfg.budget == 50.0


# ============================================================================
# Test 8: MatCostAgent 端到端
# ============================================================================


class TestMatCostAgent:
    """MatCostAgent 端到端"""

    def test_create_default_agent(self):
        agent = create_default_agent()
        assert isinstance(agent, MatCostAgent)
        assert agent.name == "mat-cost-agent"

    def test_run_basic(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="cost-test-1",
            message="experiment_planning 10 候选",
            context={"workflow": "experiment_planning", "n_candidates": 10},
        )
        response = agent.run(req)
        assert response.confidence > 0
        assert "estimate" in response.artifacts

    def test_run_with_budget(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="cost-test-2",
            message="experiment_planning 10 候选预算 200",
            context={"workflow": "experiment_planning", "n_candidates": 10, "budget": 200.0},
        )
        response = agent.run(req)
        assert response.artifacts["over_budget"] is True

    def test_run_within_budget(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="cost-test-3",
            message="experiment_planning 10 候选预算 1000",
            context={"workflow": "experiment_planning", "n_candidates": 10, "budget": 1000.0},
        )
        response = agent.run(req)
        assert response.artifacts["over_budget"] is False


# ============================================================================
# Test 9: Goldens 15 case 跑分
# ============================================================================


def _run_goldens_case(case) -> Dict[str, Any]:
    """跑 1 个 Goldens case"""
    intent = case.intent
    # 解析 intent(简化):从 intent 抽 workflow + n_candidates + budget
    workflow = case.expected.get("workflow", "experiment_planning")

    # 解析 n_candidates
    import re as _re
    n_match = _re.search(r"(\d+)\s*候选", intent)
    n_candidates = int(n_match.group(1)) if n_match else 10

    # 解析 budget
    budget_match = _re.search(r"预算\s*(\d+)", intent)
    budget = float(budget_match.group(1)) if budget_match else None

    est = estimate_workflow_cost(workflow, n_candidates=n_candidates, budget=budget)
    return {
        "workflow": est.workflow,
        "total": est.total,
        "breakdown": est.breakdown,
        "over_budget": est.over_budget,
        "overage": est.overage,
        "suggestions": est.suggestions,
    }


def _check_goldens_case(case, actual) -> tuple:
    """检查 1 个 Goldens case"""
    reasons = []
    exp = case.expected

    # workflow
    if "workflow" in exp and actual["workflow"] != exp["workflow"]:
        reasons.append(f"workflow={actual['workflow']} (期望 {exp['workflow']})")

    # total 区间
    if "min_total" in exp and actual["total"] < exp["min_total"]:
        reasons.append(f"total={actual['total']:.2f} < {exp['min_total']}")
    if "max_total" in exp and actual["total"] > exp["max_total"]:
        reasons.append(f"total={actual['total']:.2f} > {exp['max_total']}")

    # breakdown 包含
    if "min_breakdown" in exp:
        for a in exp["min_breakdown"]:
            if a not in actual["breakdown"]:
                reasons.append(f"missing breakdown: {a}")

    # over_budget
    if "over_budget" in exp and actual["over_budget"] != exp["over_budget"]:
        reasons.append(f"over_budget={actual['over_budget']} (期望 {exp['over_budget']})")

    # has_hpc_suggestion
    if exp.get("has_hpc_suggestion"):
        if not any("HPC" in s for s in actual["suggestions"]):
            reasons.append("missing HPC suggestion")

    # has_exp_suggestion
    if exp.get("has_exp_suggestion"):
        if not any("exp" in s.lower() for s in actual["suggestions"]):
            reasons.append("missing exp suggestion")

    return (len(reasons) == 0, reasons)


class TestMatCostGoldens:
    """mat-cost.yaml 15 case 跑分"""

    @pytest.fixture(scope="class")
    def results(self):
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            actual = _run_goldens_case(case)
            passed, reasons = _check_goldens_case(case, actual)
            results.append({
                "case_id": case.id,
                "category": case.category,
                "passed": passed,
                "reasons": reasons,
            })
        return results

    def test_goldens_overall_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        failed = [r for r in results if not r["passed"]]
        if failed:
            print("\n❌ 失败 case:")
            for r in failed:
                print(f"   {r['case_id']} [{r['category']}]: {r['reasons']}")

        print(f"\n📊 mat-cost Goldens 总体: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_workflow_cost_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "workflow_cost"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 workflow 成本: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"workflow_cost pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_budget_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "budget"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 budget: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"budget pass-rate {pass_rate:.0%} < 50%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])