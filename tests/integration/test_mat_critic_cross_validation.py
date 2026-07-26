"""test_mat_critic_cross_validation.py — W30 mat-critic 跨机器人一致性集成测试

覆盖(W30 拍板 18 测试):
- TestInconel718FullPipeline  3 — 4 robot 全跑 → CriticVerdict L4 pass
- TestXrdPhaseMismatch        3 — 注入 XRD mismatch → fail
- TestEdsExtraElements        3 — 注入 EDS 污染 → warn
- TestDscClassMismatch        3 — 注入 DSC Tg/Tm 不匹配 → warn
- TestEmptyReport             3 — 空 / partial ChemistReport → graceful
- TestMatCriticAgentRun       3 — MatCriticAgent.run() 端到端(4-mode auto-detect)

端到端路径:
  MatChemistAgent.run(ChemistTask) → ChemistReport
  → MatCriticAgent.run(artifacts={report: ChemistReport})
  → CriticVerdict 含 cross_robot
"""
from __future__ import annotations

import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from matwau.core.agent_base import AgentRequest

from agents.mat_chemist_agent import (
    MatChemistAgent,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
    decompose_goal_to_robots,
)
from agents.mat_critic_agent import (
    MatCriticAgent,
    evaluate_chemist_report,
    build_robot_evidence_list,
    evaluate_cross_robot,
)


# ============================================================================
# TestInconel718FullPipeline — 完整 4 robot pipeline (3 tests)
# ============================================================================


class TestInconel718FullPipeline:
    """Inconel 718 全 4 机器人跑通 → ChemistReport → CriticVerdict L4 pass"""

    def test_inconel_full_pipeline_run(self):
        """完整 Inconel 718 pipeline: 4 robot 串行 → ChemistReport → CriticVerdict L4 一致"""
        agent = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(
            run_id="integ-inconel-full-001",
            message="Inconel 718 完整表征",
            artifacts={"task": task},
        )
        response = agent.run(req)
        assert response is not None

        # 抽 ChemistReport
        report = response.artifacts.get("report")
        if report is None:
            # response 里可能没暴露 report,但 robot_results 在
            robot_results = response.artifacts.get("robot_results", [])
            assert len(robot_results) >= 3  # 至少 3 个 robot 跑过

        # Critic 喂 ChemistReport
        critic = MatCriticAgent()
        critic_req = AgentRequest(
            run_id="integ-inconel-critic-001",
            message="Inconel 718 完整表征",
            artifacts={
                "report": response.artifacts.get("report") or {
                    "robot_results": response.artifacts.get("robot_results", []),
                    "target_sample": "Inconel 718",
                },
            },
        )
        critic_resp = critic.run(critic_req)
        assert critic_resp is not None
        verdict_obj = critic_resp.artifacts.get("verdict")
        assert verdict_obj is not None

    def test_inconel_cross_robot_score_high(self):
        """Inconel 718 全跑通 → L4 score >= 0.7"""
        # 直接构造 evidence(避免 mock 整个 pipeline)
        from agents.mat_critic_agent.cross_robot import RobotEvidence

        evidence = [
            RobotEvidence(
                robot_type="synth", success=True,
                synth_product_formula="Inconel 718",
                synth_yield_grams=5.0, synth_cost_cny=500.0,
            ),
            RobotEvidence(
                robot_type="xrd", success=True,
                xrd_peaks=[{"two_theta": t} for t in [43, 50, 74, 90, 95]],
                xrd_matched_phase="Inconel 718",
            ),
            RobotEvidence(
                robot_type="em", success=True,
                em_eds_elements=[
                    {"element": "Ni"}, {"element": "Cr"}, {"element": "Fe"},
                    {"element": "Nb"}, {"element": "Mo"}, {"element": "Ti"}, {"element": "Al"},
                ],
            ),
            RobotEvidence(
                robot_type="dsc", success=True,
                dsc_Tg=None, dsc_Tm=1300.0, dsc_Tc=None,
                formula="Inconel 718",
            ),
        ]
        result = evaluate_cross_robot(evidence)
        assert result.score >= 0.7
        assert result.consistent is True
        assert len(result.rules_failed) == 0

    def test_inconel_evaluate_chemist_report_dict(self):
        """evaluate_chemist_report 吃 Inconel dict-form report"""
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0}},
                {"robot_type": "xrd", "success": True, "blocked": False,
                 "artifacts": {"peaks": [{"two_theta": t} for t in [43, 50, 74]], "matched_phase": "Inconel 718"}},
                {"robot_type": "em", "success": True, "blocked": False,
                 "artifacts": {"elements_detected": [{"element": "Ni"}, {"element": "Cr"}, {"element": "Fe"}]}},
                {"robot_type": "dsc", "success": True, "blocked": False,
                 "artifacts": {"procedure": {"sample_formula": "Inconel 718"}, "melting_temp_c": 1300.0}},
            ],
        }
        verdict = evaluate_chemist_report(report, user_intent="Inconel 718 完整表征")
        assert verdict.cross_robot.score >= 0.7
        assert verdict.cross_robot.consistent is True


# ============================================================================
# TestXrdPhaseMismatch — XRD mismatch (3 tests)
# ============================================================================


class TestXrdPhaseMismatch:
    """XRD matched_phase vs synth product 不匹配 → fail"""

    def test_inconel_synth_zno_xrd(self):
        """Inconel synth + ZnO XRD → fail xrd_phase_mismatch"""
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0}},
                {"robot_type": "xrd", "success": True, "blocked": False,
                 "artifacts": {"peaks": [{"two_theta": t} for t in [32, 47, 57]], "matched_phase": "ZnO"}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        assert verdict.cross_robot.consistent is False
        assert "R1_xrd_phase_in_synth_product" in verdict.cross_robot.rules_failed
        codes = [f.code for f in verdict.failures]
        assert "xrd_phase_mismatch" in codes
        assert verdict.verdict == "fail"

    def test_tio2_synth_al2o3_xrd(self):
        """TiO2 synth + Al2O3 XRD → fail(主金属不重叠)"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
                {"robot_type": "xrd", "success": True, "blocked": False,
                 "artifacts": {"peaks": [{"two_theta": 25}, {"two_theta": 37}], "matched_phase": "Al2O3"}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        assert verdict.cross_robot.consistent is False

    def test_tio2_synth_zno_xrd(self):
        """TiO2 synth + ZnO XRD → fail(Ti vs Zn 主金属不重叠)"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
                {"robot_type": "xrd", "success": True, "blocked": False,
                 "artifacts": {"peaks": [{"two_theta": 32}, {"two_theta": 47}], "matched_phase": "ZnO"}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        assert verdict.cross_robot.consistent is False
        codes = [f.code for f in verdict.failures]
        assert "xrd_phase_mismatch" in codes


# ============================================================================
# TestEdsExtraElements — EDS 元素污染 (3 tests)
# ============================================================================


class TestEdsExtraElements:
    """EDS 检出 synth 化学式外的元素 → warn eds_extra_elements"""

    def test_inconel_with_au_contamination(self):
        """Inconel 718 + EDS Au 杂质 → warn"""
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0}},
                {"robot_type": "em", "success": True, "blocked": False,
                 "artifacts": {"elements_detected": [
                     {"element": "Ni"}, {"element": "Cr"}, {"element": "Au"},  # Au 不在
                 ]}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "eds_extra_elements" in codes

    def test_tio2_with_cu(self):
        """TiO2 + EDS Cu → warn"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
                {"robot_type": "em", "success": True, "blocked": False,
                 "artifacts": {"elements_detected": [
                     {"element": "Ti"}, {"element": "O"}, {"element": "Cu"},
                 ]}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "eds_extra_elements" in codes

    def test_clean_eds_no_failure(self):
        """EDS 元素 ⊆ synth → 无 eds_extra_elements failure"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
                {"robot_type": "em", "success": True, "blocked": False,
                 "artifacts": {"elements_detected": [{"element": "Ti"}, {"element": "O"}]}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "eds_extra_elements" not in codes


# ============================================================================
# TestDscClassMismatch — DSC Tg/Tm 类不一致 (3 tests)
# ============================================================================


class TestDscClassMismatch:
    """DSC Tg/Tm 不符合 synth 化学式类别 → warn"""

    def test_pmma_with_tm(self):
        """PMMA polymer + DSC Tm → warn dsc_class_mismatch"""
        report = {
            "target_sample": "PMMA",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "PMMA", "yield_grams": 10.0, "cost": 100.0}},
                {"robot_type": "dsc", "success": True, "blocked": False,
                 "artifacts": {"procedure": {"sample_formula": "PMMA"}, "melting_temp_c": 160.0}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "dsc_class_mismatch" in codes

    def test_inconel_with_tg(self):
        """Inconel 718 metal + DSC Tg → warn dsc_class_mismatch"""
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0}},
                {"robot_type": "dsc", "success": True, "blocked": False,
                 "artifacts": {"procedure": {"sample_formula": "Inconel 718"}, "glass_transition_temp_c": 300.0}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "dsc_class_mismatch" in codes

    def test_tio2_with_tg(self):
        """TiO2 ceramic + DSC Tg → warn dsc_class_mismatch"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
                {"robot_type": "dsc", "success": True, "blocked": False,
                 "artifacts": {"procedure": {"sample_formula": "TiO2"}, "glass_transition_temp_c": 350.0}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        codes = [f.code for f in verdict.failures]
        assert "dsc_class_mismatch" in codes


# ============================================================================
# TestEmptyReport — 空 / partial ChemistReport (3 tests)
# ============================================================================


class TestEmptyReport:
    """空 / partial ChemistReport → graceful"""

    def test_empty_dict(self):
        """空 dict report → warn 但不崩"""
        verdict = evaluate_chemist_report({"robot_results": [], "target_sample": ""})
        assert verdict.verdict in ("pass", "warn", "fail")
        # 没 robot → 默认 L4 score = 0.7
        assert verdict.cross_robot.score >= 0.5

    def test_partial_only_synth(self):
        """只有 synth 成功 → partial report → graceful"""
        report = {
            "target_sample": "TiO2",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        assert verdict.verdict in ("pass", "warn", "fail")

    def test_all_blocked(self):
        """4 robot 全 blocked → graceful(全部 success=False)"""
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": False, "blocked": True, "artifacts": {}},
                {"robot_type": "xrd", "success": False, "blocked": True, "artifacts": {}},
                {"robot_type": "em", "success": False, "blocked": True, "artifacts": {}},
                {"robot_type": "dsc", "success": False, "blocked": True, "artifacts": {}},
            ],
        }
        verdict = evaluate_chemist_report(report)
        # 全 blocked → 没证据 → L4 0.7
        assert verdict.cross_robot.score >= 0.5


# ============================================================================
# TestMatCriticAgentRun — MatCriticAgent.run() 端到端 (3 tests)
# ============================================================================


class TestMatCriticAgentRun:
    """MatCriticAgent.run() 4-mode auto-detect 端到端"""

    def test_run_with_report_key(self):
        """MatCriticAgent.run() 吃 report key"""
        critic = MatCriticAgent()
        report = {
            "target_sample": "Inconel 718",
            "robot_results": [
                {"robot_type": "synth", "success": True, "blocked": False,
                 "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0}},
                {"robot_type": "xrd", "success": True, "blocked": False,
                 "artifacts": {"peaks": [{"two_theta": t} for t in [43, 50, 74]], "matched_phase": "Inconel 718"}},
            ],
        }
        req = AgentRequest(
            run_id="integ-critic-report-001",
            message="Inconel 718",
            artifacts={"report": report},
        )
        resp = critic.run(req)
        assert resp is not None
        verdict_obj = resp.artifacts.get("verdict")
        assert verdict_obj is not None
        # l4_cross_robot_score 应 > 0
        assert verdict_obj.l4_cross_robot_score > 0.0

    def test_run_with_robot_results_key(self):
        """MatCriticAgent.run() 吃 robot_results key"""
        critic = MatCriticAgent()
        robot_results = [
            {"robot_type": "synth", "success": True, "blocked": False,
             "artifacts": {"product_formula": "TiO2", "yield_grams": 3.0, "cost": 200.0}},
            {"robot_type": "xrd", "success": True, "blocked": False,
             "artifacts": {"peaks": [{"two_theta": 25}, {"two_theta": 37}, {"two_theta": 48}], "matched_phase": "TiO2"}},
        ]
        req = AgentRequest(
            run_id="integ-critic-robot-001",
            message="TiO2 表征",
            artifacts={"robot_results": robot_results},
        )
        resp = critic.run(req)
        assert resp is not None
        assert resp.artifacts.get("verdict") is not None

    def test_run_fallback_to_candidates(self):
        """MatCriticAgent.run() 无 report/robot_results → 走原 3 路(candidates)"""
        critic = MatCriticAgent()
        candidates = [
            {"formula": "TiO2", "relaxed_energy": -3.5, "forces_max": 0.01, "stability": "stable"},
        ]
        req = AgentRequest(
            run_id="integ-critic-cand-001",
            message="评估 TiO2",
            artifacts={"candidates": candidates},
        )
        resp = critic.run(req)
        assert resp is not None
        # 原 3 路,不应有 L4
        verdict_obj = resp.artifacts.get("verdict")
        assert verdict_obj is not None