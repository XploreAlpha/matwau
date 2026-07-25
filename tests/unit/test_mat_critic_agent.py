"""test_mat_critic_agent.py — W12 mat-critic 单元测试 + Goldens 跑分

测试覆盖:
1. critic_engine 3 路打分测试
2. FailureType 识别测试
3. MatCriticAgent act()/perceive() 测试
4. explain_failure workflow 集成
5. mat-critic.yaml Goldens 25 case 跑分

per MatWAU-开发计划 §七 W12
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_critic_agent import (  # noqa: E402
    CriticOutput,
    CriticScore,
    CriticVerdict,
    FailureType,
    MatCriticAgent,
    create_default_agent,
    evaluate_candidates,
    explain_failure,
    score_l1_physical,
    score_l2_synthesis,
    score_l3_safety,
)
from agents.mat_critic_agent.critic_engine import (  # noqa: E402
    aggregate_verdict,
    identify_failures,
)
from agents.mat_sim_agent.mat_sim_agent import SimCandidate  # noqa: E402
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-critic.yaml")


# ============================================================================
# Test helper:构造 SimCandidate
# ============================================================================


def make_cand(
    formula: str,
    relaxed_energy: float = -3.0,
    forces_max: float = 0.02,
    stability: str = "stable",
    relaxation_converged: bool = True,
    sintering_temperature_c: float = None,
) -> SimCandidate:
    """构造 1 个 SimCandidate"""
    return SimCandidate(
        formula=formula,
        cif=f"data_{formula}\n",
        relaxed_energy=relaxed_energy,
        forces_max=forces_max,
        relaxation_converged=relaxation_converged,
        stability=stability,
        confidence=0.8,
        # 烧结温度(per ExpRecipe 风格,通过 attr 扩展)
        # SimCandidate 没这字段,放 dict 形式
    )


# ============================================================================
# 测试 1: L1 物理一致性打分
# ============================================================================


class TestL1Physical:
    """L1 物理一致性测试"""

    def test_l1_stable_candidates(self):
        """稳定候选 → 高分"""
        cands = [make_cand("LiCoO2", -3.5, 0.01), make_cand("LiFePO4", -3.2, 0.02)]
        score = score_l1_physical(cands)
        assert score.score >= 0.9
        assert not score.issues

    def test_l1_metastable_candidates(self):
        """亚稳候选 → 中等"""
        cands = [make_cand("Li2SiO3", -2.2, 0.03, "metastable")]
        score = score_l1_physical(cands)
        assert 0.6 <= score.score <= 0.9

    def test_l1_unstable_candidates(self):
        """不稳定候选 → 低分"""
        cands = [make_cand("Bad", 0.8, 0.9, "unstable", relaxation_converged=False)]
        score = score_l1_physical(cands)
        assert score.score <= 0.5
        assert len(score.issues) > 0

    def test_l1_unconverged_forces(self):
        """未收敛 forces → issues 提及"""
        cands = [make_cand("X", -1.0, 0.8, "metastable", relaxation_converged=False)]
        score = score_l1_physical(cands)
        assert any("未收敛" in i or "不收敛" in i for i in score.issues)

    def test_l1_empty_candidates(self):
        """空候选 → 0.5 + issues"""
        score = score_l1_physical([])
        assert score.score == 0.5
        assert any("无候选" in i for i in score.issues)

    def test_l1_uses_formula_in_evidence(self):
        """证据含 formula"""
        cands = [make_cand("LiCoO2", 1.0, 0.9, "unstable")]
        score = score_l1_physical(cands)
        assert any("LiCoO2" in i for i in score.issues)

    def test_l1_accepts_dict_candidates(self):
        """支持 dict 形式"""
        cands = [{"formula": "Li2O", "relaxed_energy": -3.0, "forces_max": 0.01}]
        score = score_l1_physical(cands)
        assert score.score >= 0.7


# ============================================================================
# 测试 2: L2 实验可行性打分
# ============================================================================


class TestL2Synthesis:
    """L2 实验可行性测试"""

    def test_l2_common_elements(self):
        """常见元素 → 高分"""
        cands = [make_cand("Li2O"), make_cand("NaCl")]
        score = score_l2_synthesis(cands)
        assert score.score >= 0.8

    def test_l2_rare_radioactive(self):
        """含 Th → 低分"""
        cands = [make_cand("ThO2")]
        score = score_l2_synthesis(cands)
        assert score.score <= 0.6
        assert any("Th" in i for i in score.issues)

    def test_l2_pu_extreme(self):
        """含 Pu → 极低分"""
        cands = [make_cand("PuO2")]
        score = score_l2_synthesis(cands)
        assert score.score <= 0.5

    def test_l2_high_temperature(self):
        """高温 >1700℃ → issues"""
        cands = [{"formula": "X", "relaxed_energy": -3.0, "sintering": {"temperature_c": 1800}}]
        score = score_l2_synthesis(cands, req_message="高温合成")
        assert any("温度" in i or "工业" in i for i in score.issues)

    def test_l2_mixed_common_rare(self):
        """常见 + 稀有混合 → 中等"""
        cands = [make_cand("Li2O"), make_cand("ThO2")]
        score = score_l2_synthesis(cands)
        assert 0.3 <= score.score <= 0.8

    def test_l2_empty(self):
        """空候选"""
        score = score_l2_synthesis([])
        assert score.score == 0.5


# ============================================================================
# 测试 3: L3 安全规则打分
# ============================================================================


class TestL3Safety:
    """L3 安全规则测试"""

    def test_l3_no_user_forbidden(self):
        """无用户禁元素 → 高分"""
        cands = [make_cand("LiFePO4")]
        score = score_l3_safety(cands, req_message="出锂电池正极方案")
        assert score.score >= 0.9

    def test_l3_user_forbidden_co(self):
        """用户说无 Co,候选含 Co → fail 阈值"""
        cands = [make_cand("LiCoO2")]
        score = score_l3_safety(cands, req_message="出无 Co 锂电池正极")
        assert score.score <= 0.4
        assert any("Co" in i for i in score.issues)

    def test_l3_user_forbidden_no_pt(self):
        """用户说无 Pt"""
        cands = [make_cand("Pt3Ni")]
        score = score_l3_safety(cands, req_message="出无 Pt 催化剂")
        assert score.score <= 0.4

    def test_l3_radioactive(self):
        """含 Th → 立即 0.3"""
        cands = [make_cand("ThO2")]
        score = score_l3_safety(cands, req_message="设计 ThO2")
        assert score.score <= 0.3

    def test_l3_toxic_warning(self):
        """BeO 高毒但 PASS(可加 PPE)"""
        cands = [make_cand("BeO")]
        score = score_l3_safety(cands, req_message="设计 BeO 陶瓷")
        # toxic 不强制 fail,只在 issues 提醒
        assert score.score >= 0.5
        assert any("Be" in i for i in score.issues)


# ============================================================================
# 测试 4: FailureType 识别
# ============================================================================


class TestFailureIdentification:
    """失败类型识别测试"""

    def test_identify_energy_failure(self):
        """L1 低分 → energy_too_high"""
        l1 = CriticScore("L1", 0.2, 0.4, ["energy 异常"], [])
        l2 = CriticScore("L2", 0.8, 0.4, [], [])
        l3 = CriticScore("L3", 1.0, 0.2, [], [])
        failures = identify_failures(l1, l2, l3)
        assert any(f.code == "energy_too_high" for f in failures)

    def test_identify_synthesis_failure(self):
        """L2 低分 → synthesis_impossible"""
        l1 = CriticScore("L1", 0.9, 0.4, [], [])
        l2 = CriticScore("L2", 0.2, 0.4, ["温度过高"], [])
        l3 = CriticScore("L3", 1.0, 0.2, [], [])
        failures = identify_failures(l1, l2, l3)
        assert any(f.code == "synthesis_impossible" for f in failures)

    def test_identify_safety_critical(self):
        """L3 低分 → safety_violation critical"""
        l1 = CriticScore("L1", 0.9, 0.4, [], [])
        l2 = CriticScore("L2", 0.8, 0.4, [], [])
        l3 = CriticScore("L3", 0.2, 0.2, ["Co"], [])
        failures = identify_failures(l1, l2, l3)
        assert any(f.code == "safety_violation" and f.severity == "critical" for f in failures)


class TestVerdictAggregation:
    """verdict 综合判定测试"""

    def test_safety_critical_zero_tolerance(self):
        """safety critical → 即使总分高也 fail"""
        l1 = CriticScore("L1", 1.0, 0.4, [], [])
        l2 = CriticScore("L2", 1.0, 0.4, [], [])
        l3 = CriticScore("L3", 0.4, 0.2, ["Co"], [])
        failures = [FailureType(code="safety_violation", severity="critical", confidence=0.8)]
        verdict = aggregate_verdict(l1, l2, l3, failures)
        assert verdict == "fail"

    def test_pass_when_all_high(self):
        """3 路都高 → pass"""
        l1 = CriticScore("L1", 0.95, 0.4, [], [])
        l2 = CriticScore("L2", 0.85, 0.4, [], [])
        l3 = CriticScore("L3", 1.0, 0.2, [], [])
        verdict = aggregate_verdict(l1, l2, l3, [])
        assert verdict == "pass"

    def test_warn_when_middle(self):
        """中等综合分 → warn"""
        l1 = CriticScore("L1", 0.7, 0.4, [], [])
        l2 = CriticScore("L2", 0.6, 0.4, [], [])
        l3 = CriticScore("L3", 0.5, 0.2, [], [])
        verdict = aggregate_verdict(l1, l2, l3, [])
        assert verdict == "warn"


# ============================================================================
# 测试 5: evaluate_candidates 主入口
# ============================================================================


class TestEvaluateCandidates:
    """evaluate_candidates 主入口测试"""

    def test_evaluate_stable(self):
        """稳定候选 → pass"""
        cands = [make_cand("LiCoO2", -3.5), make_cand("LiFePO4", -3.2)]
        v = evaluate_candidates(cands, user_intent="评估")
        assert v.verdict == "pass"
        assert v.overall_score >= 0.7

    def test_evaluate_with_safety_violation(self):
        """用户禁元素 → fail"""
        cands = [make_cand("LiCoO2")]
        v = evaluate_candidates(cands, user_intent="出无 Co 锂电池正极")
        assert v.verdict == "fail"
        assert any(f.code == "safety_violation" for f in v.failures)

    def test_evaluate_returns_top_suggestions(self):
        """返回 top_suggestions"""
        cands = [make_cand("Bad", 1.5, 0.9)]
        v = evaluate_candidates(cands, user_intent="评估")
        assert isinstance(v.top_suggestions, list)


# ============================================================================
# 测试 6: explain_failure 专用函数
# ============================================================================


class TestExplainFailure:
    """explain_failure 解释失败"""

    def test_explain_xrd_failure(self):
        """'XRD 谱不对' → 额外 xrd_mismatch failure"""
        cands = [make_cand("X", 0.5, 0.7)]
        v = explain_failure("为什么 XRD 谱不对", candidates=cands)
        assert any(f.code == "xrd_mismatch" for f in v.failures)

    def test_explain_synthesis_failure(self):
        """'合成失败' → synthesis_failed failure"""
        cands = [make_cand("X", -2.5)]
        v = explain_failure("合成失败了", candidates=cands)
        assert any(f.code == "synthesis_failed" for f in v.failures)

    def test_explain_energy_anomaly(self):
        """'能量异常' → energy_anomaly failure"""
        cands = [make_cand("X", 2.0)]
        v = explain_failure("为什么能量异常", candidates=cands)
        assert any(f.code == "energy_anomaly" for f in v.failures)

    def test_explain_without_candidates(self):
        """无候选 → warn + 提示"""
        v = explain_failure("为什么 XRD 谱不对")
        assert v.verdict in ("warn", "pass")


# ============================================================================
# 测试 7: MatCriticAgent act()
# ============================================================================


class TestMatCriticAgent:
    """MatCriticAgent 测试"""

    def test_create_default(self):
        a = create_default_agent()
        assert isinstance(a, MatCriticAgent)
        assert a.context_manager is not None
        assert a.safety_guard is not None

    def test_run_with_stable_candidates(self):
        """稳定候选 → pass"""
        a = create_default_agent()
        cands = [make_cand("LiCoO2", -3.5), make_cand("LiFePO4", -3.2)]
        req = AgentRequest(run_id="t1", message="评估", artifacts={"candidates": cands})
        r = a.run(req)
        assert r.artifacts["verdict"].verdict == "pass"
        assert "verdict" in r.artifacts

    def test_run_with_safety_violation(self):
        """无 Co 但含 Co → fail"""
        a = create_default_agent()
        cands = [make_cand("LiCoO2")]
        req = AgentRequest(run_id="t2", message="出无 Co 锂电池正极", artifacts={"candidates": cands})
        r = a.run(req)
        assert r.artifacts["verdict"].verdict == "fail"

    def test_run_with_xrd_failure(self):
        """'XRD 谱不对' → 触发 xrd_mismatch"""
        a = create_default_agent()
        cands = [make_cand("Bad", 1.5, 0.9)]
        req = AgentRequest(run_id="t3", message="为什么 XRD 谱不对", artifacts={"candidates": cands})
        r = a.run(req)
        failures = r.artifacts.get("failures", [])
        assert any(f.code == "xrd_mismatch" for f in failures)

    def test_run_with_simulated_field(self):
        """支持 simulated 字段(mat-sim 输出)"""
        a = create_default_agent()
        cands = [make_cand("LiCoO2")]
        req = AgentRequest(run_id="t4", message="评估", artifacts={"simulated": cands})
        r = a.run(req)
        assert r.artifacts["input_count"] == 1

    def test_run_empty_candidates(self):
        """空候选 → warn"""
        a = create_default_agent()
        req = AgentRequest(run_id="t5", message="评估", artifacts={})
        r = a.run(req)
        assert r.artifacts["verdict"].verdict == "warn"

    def test_reply_contains_verdict(self):
        """reply 含 verdict 字符串"""
        a = create_default_agent()
        cands = [make_cand("LiCoO2", -3.5)]
        req = AgentRequest(run_id="t6", message="评估", artifacts={"candidates": cands})
        r = a.run(req)
        assert "verdict" in r.reply.lower() or "PASS" in r.reply or "WARN" in r.reply or "FAIL" in r.reply

    def test_run_confidence_scales(self):
        """置信度随 verdict 调整"""
        a = create_default_agent()
        # pass → 0.9
        r1 = a.run(AgentRequest(run_id="t7", message="评估", artifacts={"candidates": [make_cand("LiCoO2", -3.5)]}))
        assert r1.confidence == 0.9

    def test_run_cost_is_low(self):
        """cost 应该低(规则引擎)"""
        a = create_default_agent()
        cands = [make_cand("LiCoO2", -3.5)]
        req = AgentRequest(run_id="t8", message="评估", artifacts={"candidates": cands})
        r = a.run(req)
        assert r.cost <= 0.1


# ============================================================================
# 测试 8: CriticOutput 数据类
# ============================================================================


class TestCriticOutput:
    """CriticOutput 测试"""

    def test_to_dict(self):
        v = CriticOutput(
            verdict="pass",
            overall_score=0.85,
            l1_score=0.9,
            l2_score=0.8,
            l3_score=1.0,
            failures=[],
            top_suggestions=["建议"],
        )
        d = v.to_dict()
        assert d["verdict"] == "pass"
        assert d["overall_score"] == 0.85
        assert d["l1_score"] == 0.9


# ============================================================================
# 测试 9: mat-orchestrator explain_failure workflow 集成
# ============================================================================


class TestOrchestratorIntegration:
    """mat-orchestrator explain_failure workflow 集成测试"""

    def test_orchestrator_uses_real_critic(self):
        """orchestrator 用真 MatCriticAgent(不再用 stub)"""
        from agents.mat_orchestrator.mat_orchestrator import create_default_orchestrator as create_orch

        orch = create_orch()
        assert "mat-critic-agent" in orch.agent_registry
        assert "mat-critic-stub" not in orch.agent_registry

    def test_explain_failure_workflow(self):
        """explain_failure workflow 跑通"""
        from agents.mat_orchestrator.mat_orchestrator import create_default_orchestrator as create_orch
        from agents.mat_orchestrator.dag import (
            explain_failure_workflow,
            DAGExecutor,
        )

        orch = create_orch()
        cands = [make_cand("Bad", 0.8, 0.9)]
        wf = explain_failure_workflow()
        result = DAGExecutor(orch.agent_registry).execute(
            wf,
            initial_inputs={"user_intent": "为什么失败", "candidates": cands},
        )
        assert result.success
        assert result.node_results[0].success
        verdict = result.node_results[0].outputs["artifacts"]["verdict"]
        assert verdict.verdict in ("pass", "warn", "fail")


# ============================================================================
# 测试 10: mat-critic.yaml Goldens 25 case 跑分
# ============================================================================


def _check_goldens_case(verdict: CriticVerdict, expected: dict) -> tuple[bool, list[str]]:
    """检查 1 个 Goldens case"""
    reasons = []

    if "verdict" in expected:
        if verdict.verdict != expected["verdict"]:
            reasons.append(f"verdict={verdict.verdict} (期望 {expected['verdict']})")

    if "min_overall_score" in expected:
        if verdict.overall_score < expected["min_overall_score"]:
            reasons.append(
                f"overall_score={verdict.overall_score} < {expected['min_overall_score']}"
            )

    if "min_l1" in expected:
        if verdict.l1.score < expected["min_l1"]:
            reasons.append(f"L1={verdict.l1.score:.2f} < {expected['min_l1']}")

    if "min_l2" in expected:
        if verdict.l2.score < expected["min_l2"]:
            reasons.append(f"L2={verdict.l2.score:.2f} < {expected['min_l2']}")

    if "min_l3" in expected:
        if verdict.l3.score < expected["min_l3"]:
            reasons.append(f"L3={verdict.l3.score:.2f} < {expected['min_l3']}")

    if "failure_codes_any" in expected:
        codes = [f.code for f in verdict.failures]
        if not any(c in codes for c in expected["failure_codes_any"]):
            reasons.append(
                f"no failure code in {expected['failure_codes_any']} (got {codes})"
            )

    if "has_suggestions" in expected:
        if expected["has_suggestions"] and not verdict.top_suggestions:
            reasons.append("no top_suggestions")

    return (len(reasons) == 0, reasons)


class TestCriticGoldens:
    """mat-critic.yaml Goldens 跑分"""

    @pytest.fixture(scope="class")
    def results(self):
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            try:
                # 直接 evaluate_candidates 跑(不通过 agent)
                v = evaluate_candidates(
                    case.candidates,
                    user_intent=case.intent,
                )
                passed, reasons = _check_goldens_case(v, case.expected)
            except Exception as e:
                v = None
                passed = False
                reasons = [f"exception: {e}"]
            results.append(
                {
                    "case_id": case.id,
                    "category": case.category,
                    "passed": passed,
                    "reasons": reasons,
                    "verdict": v.verdict if v else "ERROR",
                    "overall": v.overall_score if v else 0.0,
                }
            )
        return results

    def test_goldens_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total
        print(f"\n📊 mat-critic Goldens: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_l1_physical_pass_rate(self, results):
        sub = [r for r in results if r["category"] == "l1_physical"]
        n_pass = sum(1 for r in sub if r["passed"])
        n_total = len(sub)
        rate = n_pass / n_total if n_total else 0
        print(f"\n📊 L1 物理: {n_pass}/{n_total} = {rate:.0%}")
        assert rate >= 0.5

    def test_goldens_l2_synthesis_pass_rate(self, results):
        sub = [r for r in results if r["category"] == "l2_synthesis"]
        n_pass = sum(1 for r in sub if r["passed"])
        n_total = len(sub)
        rate = n_pass / n_total if n_total else 0
        print(f"\n📊 L2 合成: {n_pass}/{n_total} = {rate:.0%}")
        assert rate >= 0.5

    def test_goldens_l3_safety_pass_rate(self, results):
        sub = [r for r in results if r["category"] == "l3_safety"]
        n_pass = sum(1 for r in sub if r["passed"])
        n_total = len(sub)
        rate = n_pass / n_total if n_total else 0
        print(f"\n📊 L3 安全: {n_pass}/{n_total} = {rate:.0%}")
        assert rate >= 0.5

    def test_goldens_e2e_pass_rate(self, results):
        sub = [r for r in results if r["category"] == "e2e"]
        n_pass = sum(1 for r in sub if r["passed"])
        n_total = len(sub)
        rate = n_pass / n_total if n_total else 0
        print(f"\n📊 e2e: {n_pass}/{n_total} = {rate:.0%}")
        assert rate >= 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])