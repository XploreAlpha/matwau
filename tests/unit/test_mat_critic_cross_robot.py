"""test_mat_critic_cross_robot.py — W30 mat-critic 跨机器人一致性单元测试

覆盖(W30 拍板 40 测试):
- TestPhaseLibrary       6 — phase_library 元素映射 + 模糊匹配
- TestExtractors         6 — 4 extractors × dict/dataclass 形式
- TestRuleR1XrdPhase     4 — R1 4 case(pass / fail / 同名 / unmatched)
- TestRuleR2EdsElements  4 — R2 4 case(subset / extra / empty / dict)
- TestRuleR3DscClass     4 — R3 4 case(polymer Tg / metal Tm / ceramic / mismatch)
- TestRuleR4CostSanity   3 — R4 3 case(normal / too high / too low)
- TestRuleR5XrdPeakCount 3 — R5 3 case(crystalline / amorphous / edge)
- TestCrossRobotResult   3 — CrossRobotResult dataclass 行为
- TestEvaluateChemistReport 4 — evaluate_chemist_report 4 模式
- TestCriticVerdictExtension 3 — CriticVerdict 字段 + to_dict 兼容
- TestCrossRobotGuard    4 — CrossRobotConsistencyGuard 4 case
"""
from __future__ import annotations

import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from agents.mat_critic_agent import (
    CriticScore,
    CriticVerdict,
    CrossRobotScore,
    FailureType,
    build_robot_evidence_list,
    evaluate_cross_robot,
    evaluate_chemist_report,
    list_known_phases,
    match_phase_name,
    parse_formula_elements,
    rule_dsc_class_matches_synth,
    rule_eds_elements_subset_of_synth,
    rule_synth_cost_per_gram,
    rule_xrd_peak_count_for_crystallinity,
    rule_xrd_phase_in_synth_product,
)
from agents.mat_critic_agent.cross_robot import (
    CrossRobotConsistencyGuard,
    CrossRobotResult,
    RobotEvidence,
    _extract_dsc_tm,
    _extract_em_eds,
    _extract_synth_product,
    _extract_xrd_peaks,
)
from agents.mat_critic_agent.cross_robot_phase_library import PHASE_ELEMENT_MAP


# ============================================================================
# TestPhaseLibrary — phase_library 元素映射 + 模糊匹配 (6 tests)
# ============================================================================


class TestPhaseLibrary:
    def test_list_known_phases_returns_17(self):
        """Phase 库 ≥ 17 项"""
        phases = list_known_phases()
        assert len(phases) >= 17
        assert "Inconel 718" in phases
        assert "TiO2" in phases
        assert "PMMA" in phases

    def test_parse_formula_elements_basic(self):
        """parse_formula_elements 解析基本化学式"""
        assert parse_formula_elements("TiO2") == {"Ti", "O"}
        assert parse_formula_elements("Al2O3") == {"Al", "O"}
        assert parse_formula_elements("Si") == {"Si"}

    def test_parse_formula_elements_complex(self):
        """parse_formula_elements 解析复杂化学式"""
        # LiCoO2 → Li / Co / O
        result = parse_formula_elements("LiCoO2")
        assert "Li" in result
        assert "Co" in result
        assert "O" in result

    def test_parse_formula_elements_by_name(self):
        """parse_formula_elements 通过名称查(Inconel 718)"""
        result = parse_formula_elements("Inconel 718")
        # Inconel 718 → {Ni, Cr, Fe, Nb, Mo, Ti, Al}
        assert "Ni" in result
        assert "Cr" in result
        assert "Fe" in result

    def test_match_phase_name_exact(self):
        """match_phase_name 精确匹配"""
        assert match_phase_name("Inconel 718") == "Inconel 718"
        assert match_phase_name("TiO2") == "TiO2"
        assert match_phase_name("PMMA") == "PMMA"

    def test_match_phase_name_fuzzy(self):
        """match_phase_name 模糊匹配(大小写 / 子串)"""
        # 大小写不敏感
        assert match_phase_name("inconel 718") == "Inconel 718"
        # "Inconel" 跟 PHASE_ELEMENT_MAP["Inconel"] 完全匹配 → 精确匹配优先
        assert match_phase_name("Inconel") == "Inconel"
        # "Phase: TiO2" → 走子串匹配
        assert match_phase_name("Phase: TiO2") == "TiO2"


# ============================================================================
# TestExtractors — 4 extractors × dict/dataclass 形式 (6 tests)
# ============================================================================


class TestExtractors:
    def test_extract_xrd_peaks_dict(self):
        """_extract_xrd_peaks 从 dict 抽 peaks + matched_phase"""
        item = {
            "peaks": [{"two_theta": 43.5, "intensity": 100.0}],
            "matched_phase": "Inconel 718",
        }
        peaks, matched = _extract_xrd_peaks(item)
        assert len(peaks) == 1
        assert matched == "Inconel 718"

    def test_extract_em_eds_dict(self):
        """_extract_em_eds 从 dict 抽 EDS"""
        item = {"elements_detected": [{"element": "Ni", "wt_pct": 50.0}]}
        eds = _extract_em_eds(item)
        assert len(eds) == 1
        assert eds[0]["element"] == "Ni"

    def test_extract_dsc_tm_dict(self):
        """_extract_dsc_tm 从 dict 抽 Tg/Tm/Tc"""
        item = {
            "glass_transition_temp_c": 105.0,
            "melting_temp_c": None,
            "crystallization_temp_c": 165.0,
        }
        tg, tm, tc = _extract_dsc_tm(item)
        assert tg == 105.0
        assert tm is None
        assert tc == 165.0

    def test_extract_synth_product_dict(self):
        """_extract_synth_product 从 dict 抽 product + yield + cost"""
        item = {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 200.0}
        formula, yield_g, cost = _extract_synth_product(item)
        assert formula == "Inconel 718"
        assert yield_g == 5.0
        assert cost == 200.0

    def test_extract_xrd_peaks_dataclass(self):
        """_extract_xrd_peaks 兼容 dataclass-like 对象"""
        class FakeXrdResult:
            peaks = [{"two_theta": 30.0}]
            matched_phase = "Si"

        peaks, matched = _extract_xrd_peaks(FakeXrdResult())
        assert len(peaks) == 1
        assert matched == "Si"

    def test_extract_dsc_tm_dataclass(self):
        """_extract_dsc_tm 兼容 dataclass-like 对象"""
        class FakeDscResult:
            glass_transition_temp_c = 105.0
            melting_temp_c = 160.0
            crystallization_temp_c = None

        tg, tm, tc = _extract_dsc_tm(FakeDscResult())
        assert tg == 105.0
        assert tm == 160.0
        assert tc is None


# ============================================================================
# TestRuleR1XrdPhase — R1 XRD matched_phase vs synth product (4 tests)
# ============================================================================


class TestRuleR1XrdPhase:
    def test_r1_inconel_match(self):
        """R1: XRD 'Inconel 718' + synth 'Inconel 718' → pass"""
        passed, issue = rule_xrd_phase_in_synth_product("Inconel 718", "Inconel 718")
        assert passed is True
        assert issue == ""

    def test_r1_tio2_al2o3_mismatch(self):
        """R1: XRD 'ZnO' + synth 'Inconel 718' → fail(元素完全不重叠)"""
        passed, issue = rule_xrd_phase_in_synth_product("ZnO", "Inconel 718")
        assert passed is False
        assert "mismatch" in issue.lower() or "zn" in issue.lower()

    def test_r1_inconel_fuzzy_match(self):
        """R1: XRD 'Inconel' + synth 'Inconel 718' → pass(模糊匹配)"""
        passed, issue = rule_xrd_phase_in_synth_product("Inconel", "Inconel 718")
        assert passed is True

    def test_r1_empty_xrd_skip(self):
        """R1: xrd_phase 为空 → 跳过(pass)"""
        passed, issue = rule_xrd_phase_in_synth_product("", "TiO2")
        assert passed is True


# ============================================================================
# TestRuleR2EdsElements — R2 EDS 元素 ⊆ synth 化学式 (4 tests)
# ============================================================================


class TestRuleR2EdsElements:
    def test_r2_subset_pass(self):
        """R2: EDS {Ni, Cr} ⊆ synth 'Inconel 718' → pass"""
        eds = [{"element": "Ni", "wt_pct": 50.0}, {"element": "Cr", "wt_pct": 20.0}]
        passed, issue = rule_eds_elements_subset_of_synth(eds, "Inconel 718")
        assert passed is True

    def test_r2_extra_element_fail(self):
        """R2: EDS 含 Au(不在 synth 'Inconel 718')→ fail"""
        eds = [{"element": "Ni"}, {"element": "Au"}]
        passed, issue = rule_eds_elements_subset_of_synth(eds, "Inconel 718")
        assert passed is False
        assert "Au" in issue or "extra" in issue.lower()

    def test_r2_empty_eds_skip(self):
        """R2: EDS 空 → 跳过"""
        passed, issue = rule_eds_elements_subset_of_synth([], "TiO2")
        assert passed is True

    def test_r2_no_synth_skip(self):
        """R2: synth 为空 → 跳过"""
        eds = [{"element": "Ni"}]
        passed, issue = rule_eds_elements_subset_of_synth(eds, "")
        assert passed is True


# ============================================================================
# TestRuleR3DscClass — R3 DSC Tg/Tm 类与 synth 一致 (4 tests)
# ============================================================================


class TestRuleR3DscClass:
    def test_r3_polymer_with_tg_pass(self):
        """R3: polymer(PMMA)+ DSC Tg=105 → pass"""
        passed, issue = rule_dsc_class_matches_synth(105.0, None, "PMMA")
        assert passed is True

    def test_r3_metal_with_tm_pass(self):
        """R3: metal(Inconel)+ DSC Tm=1300 → pass"""
        passed, issue = rule_dsc_class_matches_synth(None, 1300.0, "Inconel 718")
        assert passed is True

    def test_r3_polymer_with_tm_fail(self):
        """R3: polymer(PMMA)+ DSC Tm=160 → fail"""
        passed, issue = rule_dsc_class_matches_synth(None, 160.0, "PMMA")
        assert passed is False
        assert "polymer" in issue.lower() or "tg" in issue.lower()

    def test_r3_ceramic_with_tg_fail(self):
        """R3: ceramic(TiO2)+ DSC Tg=300 → fail"""
        passed, issue = rule_dsc_class_matches_synth(300.0, None, "TiO2")
        assert passed is False


# ============================================================================
# TestRuleR4CostSanity — R4 cost-per-gram sanity (3 tests)
# ============================================================================


class TestRuleR4CostSanity:
    def test_r4_normal_pass(self):
        """R4: yield=5g, cost=¥500 → ¥100/g → pass"""
        passed, issue = rule_synth_cost_per_gram(5.0, 500.0)
        assert passed is True

    def test_r4_too_high_fail(self):
        """R4: yield=1g, cost=¥20000 → ¥20000/g → fail"""
        passed, issue = rule_synth_cost_per_gram(1.0, 20000.0)
        assert passed is False
        assert "high" in issue.lower() or "cost" in issue.lower()

    def test_r4_too_low_fail(self):
        """R4: yield=100g, cost=¥1 → ¥0.01/g → fail"""
        passed, issue = rule_synth_cost_per_gram(100.0, 1.0)
        assert passed is False
        assert "low" in issue.lower() or "cost" in issue.lower()


# ============================================================================
# TestRuleR5XrdPeakCount — R5 XRD peak count 与结晶性 (3 tests)
# ============================================================================


class TestRuleR5XrdPeakCount:
    def test_r5_crystalline_pass(self):
        """R5: TiO2 + 5 peaks → pass"""
        peaks = [{"two_theta": 25.0}, {"two_theta": 37.0}, {"two_theta": 48.0},
                 {"two_theta": 55.0}, {"two_theta": 62.0}]
        passed, issue = rule_xrd_peak_count_for_crystallinity(peaks, "TiO2")
        assert passed is True

    def test_r5_crystalline_too_few_fail(self):
        """R5: Inconel + 1 peak → fail"""
        peaks = [{"two_theta": 43.0}]
        passed, issue = rule_xrd_peak_count_for_crystallinity(peaks, "Inconel 718")
        assert passed is False
        assert "peak" in issue.lower() or "结晶" in issue

    def test_r5_polymer_skip(self):
        """R5: PMMA(polymer)→ 跳过(不强校验)"""
        peaks = [{"two_theta": 15.0}]  # 只有 1 peak
        passed, issue = rule_xrd_peak_count_for_crystallinity(peaks, "PMMA")
        assert passed is True


# ============================================================================
# TestCrossRobotResult — CrossRobotResult dataclass (3 tests)
# ============================================================================


class TestCrossRobotResult:
    def test_default_values(self):
        """CrossRobotResult 默认值"""
        r = CrossRobotResult()
        assert r.score == 0.0
        assert r.consistent is True
        assert r.issues == []
        assert r.suggestions == []
        assert r.rules_passed == []
        assert r.rules_failed == []

    def test_score_calculation_all_pass(self):
        """evaluate_cross_robot: 5 rules 全 pass → score=1.0"""
        evidence_list = [
            RobotEvidence(
                robot_type="synth", success=True,
                synth_product_formula="Inconel 718",
                synth_yield_grams=5.0, synth_cost_cny=500.0,
            ),
            RobotEvidence(
                robot_type="xrd", success=True,
                xrd_peaks=[{"two_theta": 30.0}] * 5,
                xrd_matched_phase="Inconel 718",
            ),
            RobotEvidence(
                robot_type="em", success=True,
                em_eds_elements=[{"element": "Ni"}, {"element": "Cr"}],
            ),
            RobotEvidence(
                robot_type="dsc", success=True,
                dsc_Tg=None, dsc_Tm=1300.0, dsc_Tc=None,
                formula="Inconel 718",
            ),
        ]
        r = evaluate_cross_robot(evidence_list)
        # 5 rules 都应该 pass(R1 / R2 / R3 / R4 / R5)
        assert r.score >= 0.99
        assert r.consistent is True
        assert len(r.rules_failed) == 0

    def test_score_with_one_failure(self):
        """evaluate_cross_robot: 1 rule fail → score < 1.0"""
        evidence_list = [
            RobotEvidence(
                robot_type="synth", success=True,
                synth_product_formula="Inconel 718",
                synth_yield_grams=5.0, synth_cost_cny=500.0,
            ),
            RobotEvidence(
                robot_type="xrd", success=True,
                xrd_peaks=[{"two_theta": 30.0}] * 5,
                xrd_matched_phase="ZnO",  # 完全不重叠!
            ),
        ]
        r = evaluate_cross_robot(evidence_list)
        assert r.consistent is False
        assert "R1_xrd_phase_in_synth_product" in r.rules_failed


# ============================================================================
# TestEvaluateChemistReport — evaluate_chemist_report 4 模式 (4 tests)
# ============================================================================


class TestEvaluateChemistReport:
    def test_empty_dict_report(self):
        """evaluate_chemist_report: 空 dict report → graceful"""
        verdict = evaluate_chemist_report({"robot_results": [], "target_sample": ""})
        assert verdict.verdict in ("pass", "warn", "fail")
        assert verdict.cross_robot.score >= 0.0

    def test_dict_report_with_data(self):
        """evaluate_chemist_report: dict 形式含 4 robot → L4 有 score"""
        report = {
            "robot_results": [
                {
                    "robot_type": "synth", "success": True, "blocked": False,
                    "artifacts": {"product_formula": "Inconel 718", "yield_grams": 5.0, "cost": 500.0},
                },
                {
                    "robot_type": "xrd", "success": True, "blocked": False,
                    "artifacts": {
                        "peaks": [{"two_theta": 30.0}] * 5,
                        "matched_phase": "Inconel 718",
                    },
                },
            ],
            "target_sample": "Inconel 718",
        }
        verdict = evaluate_chemist_report(report)
        assert verdict.cross_robot.score > 0.5
        assert "R1_xrd_phase_in_synth_product" in verdict.cross_robot.rules_passed

    def test_dataclass_like_report(self):
        """evaluate_chemist_report: dataclass-like report"""
        class FakeChemistReport:
            robot_results = []
            target_sample = "TiO2"

        verdict = evaluate_chemist_report(FakeChemistReport())
        assert verdict.verdict in ("pass", "warn", "fail")

    def test_4_lane_weighting(self):
        """evaluate_chemist_report: 4 路权重正确(0.3/0.3/0.2/0.2)"""
        verdict = evaluate_chemist_report({"robot_results": []})
        assert verdict.l1.weight == pytest.approx(0.3, abs=1e-6)
        assert verdict.l2.weight == pytest.approx(0.3, abs=1e-6)
        assert verdict.l3.weight == pytest.approx(0.2, abs=1e-6)
        assert verdict.cross_robot.weight == pytest.approx(0.2, abs=1e-6)


# ============================================================================
# TestCriticVerdictExtension — CriticVerdict + CrossRobotScore 字段 (3 tests)
# ============================================================================


class TestCriticVerdictExtension:
    def test_cross_robot_default(self):
        """CriticVerdict.cross_robot 默认值"""
        l1 = CriticScore("L1", 0.7, 0.3, [], [])
        l2 = CriticScore("L2", 0.7, 0.3, [], [])
        l3 = CriticScore("L3", 0.7, 0.2, [], [])
        v = CriticVerdict(overall_score=0.7, verdict="pass", l1=l1, l2=l2, l3=l3)
        assert v.cross_robot is not None
        assert v.cross_robot.weight == pytest.approx(0.2, abs=1e-6)
        assert v.cross_robot.score == 0.0

    def test_to_dict_includes_l4(self):
        """CriticVerdict.to_dict() 含 l4_cross_robot"""
        l1 = CriticScore("L1", 0.8, 0.3, [], [])
        l2 = CriticScore("L2", 0.7, 0.3, [], [])
        l3 = CriticScore("L3", 0.9, 0.2, [], [])
        v = CriticVerdict(
            overall_score=0.78,
            verdict="pass",
            l1=l1, l2=l2, l3=l3,
            cross_robot=CrossRobotScore(score=0.8, consistent=True,
                                        rules_passed=["R1"], rules_failed=[]),
        )
        d = v.to_dict()
        assert "l4_cross_robot" in d
        assert d["l4_cross_robot"]["score"] == 0.8
        assert d["l4_cross_robot"]["consistent"] is True
        assert d["l4_cross_robot"]["rules_passed"] == ["R1"]

    def test_dataclass_field_order(self):
        """CrossRobotScore 可独立构造"""
        s = CrossRobotScore(score=0.9, weight=0.2, consistent=True,
                            rules_passed=["R1", "R2"], rules_failed=[])
        assert s.name == "L4_cross_robot"
        assert s.score == 0.9
        assert s.weight == 0.2


# ============================================================================
# TestCrossRobotGuard — CrossRobotConsistencyGuard (4 tests)
# ============================================================================


class TestCrossRobotGuard:
    def test_guard_default_pass(self):
        """Guard 默认 block_on_inconsistency=False → 一致失败时也 pass"""
        guard = CrossRobotConsistencyGuard()
        # 构造 mock response
        class MockCrossRobot:
            consistent = False
        class MockVerdict:
            cross_robot = MockCrossRobot()
        class MockResponse:
            artifacts = {"critic_verdict": MockVerdict()}

        assert guard.check(MockResponse()) is True

    def test_guard_block_mode(self):
        """Guard block_on_inconsistency=True + 不一致 → 阻断"""
        guard = CrossRobotConsistencyGuard(block_on_inconsistency=True)

        class MockCrossRobot:
            consistent = False
        class MockVerdict:
            cross_robot = MockCrossRobot()
        class MockResponse:
            artifacts = {"critic_verdict": MockVerdict()}

        assert guard.check(MockResponse()) is False
        assert guard.blocks_count == 1

    def test_guard_consistent_pass(self):
        """Guard consistent=True → 不阻断"""
        guard = CrossRobotConsistencyGuard(block_on_inconsistency=True)

        class MockCrossRobot:
            consistent = True
        class MockVerdict:
            cross_robot = MockCrossRobot()
        class MockResponse:
            artifacts = {"critic_verdict": MockVerdict()}

        assert guard.check(MockResponse()) is True

    def test_guard_no_verdict_skip(self):
        """Guard 没 verdict → skip(pass)"""
        guard = CrossRobotConsistencyGuard(block_on_inconsistency=True)

        class MockResponse:
            artifacts = {}

        assert guard.check(MockResponse()) is True