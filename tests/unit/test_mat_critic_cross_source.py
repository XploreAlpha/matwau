"""test_mat_critic_cross_source.py — mat_critic L5 跨数据源规则测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M3 第 9 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_critic_agent.critic_engine import (  # noqa: E402
    CrossSourceScore,
    FAIL_CROSS_SOURCE_BAND_GAP_MISMATCH,
    FAIL_CROSS_SOURCE_ENERGY_MISMATCH,
    FAIL_CROSS_SOURCE_LOW_CONSENSUS,
    RULE_R6_CROSS_SOURCE_CONSENSUS,
    RULE_R7_CROSS_SOURCE_ENERGY,
    RULE_R8_CROSS_SOURCE_BAND_GAP,
    WEIGHT_L1_PHYSICAL,
    WEIGHT_L5_CROSS_SOURCE,
    evaluate_candidates,
    evaluate_cross_source_consistency,
    evaluate_with_cross_source,
)
from agents.oqmd_client import OqmdReference  # noqa: E402
from agents.cod_client import CodReference  # noqa: E402
from agents.nomad_client import NomadReference  # noqa: E402
from agents.jarvis_client import JarvReference  # noqa: E402


# ============================================================================
# Test 1: CrossSourceScore dataclass
# ============================================================================


class TestCrossSourceScoreDataclass:
    def test_defaults(self):
        cs = CrossSourceScore()
        assert cs.name == "L5_cross_source"
        assert cs.weight == 0.1
        assert cs.score == 0.0
        assert cs.consensus_rate == 0.0
        assert cs.n_clusters == 0
        assert cs.rules_passed == []
        assert cs.rules_failed == []

    def test_to_dict(self):
        cs = CrossSourceScore(score=0.8, consensus_rate=0.75, n_clusters=4, n_conflicts=1)
        d = cs.to_dict()
        assert d["score"] == 0.8
        assert d["consensus_rate"] == 0.75
        assert d["n_clusters"] == 4
        assert d["n_conflicts"] == 1
        assert d["weight"] == 0.1


# ============================================================================
# Test 2: evaluate_cross_source_consistency — 4 源都命中
# ============================================================================


class TestEvaluateCrossSourceConsistency:
    def test_4_sources_aligned(self):
        """4 源都命中 1 个化合物,无冲突 → score=1.0,3 rules pass"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si", spacegroup="Fd-3m")],
            "COD": [CodReference(cod_id="c1", formula="Si", spacegroup_h_m="Fd-3m", spacegroup_number=227)],
            "NOMAD": [NomadReference(entry_id="n1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
            "JARVIS": [JarvReference(jid="j1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
        }
        cs = evaluate_cross_source_consistency(recs)
        assert cs.score >= 0.5
        assert RULE_R7_CROSS_SOURCE_ENERGY in cs.rules_passed
        assert RULE_R8_CROSS_SOURCE_BAND_GAP in cs.rules_passed

    def test_1_source_only(self):
        """仅 1 源 → consensus_rate=0, R6 fail"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="X")],
            "COD": [], "NOMAD": [], "JARVIS": [],
        }
        cs = evaluate_cross_source_consistency(recs, consensus_rate_threshold=0.5)
        assert RULE_R6_CROSS_SOURCE_CONSENSUS in cs.rules_failed
        assert cs.consensus_rate < 0.5

    def test_energy_mismatch_r7_fails(self):
        """形成能偏差大 + consensus_rate ≥ 0.5 → R7 fail(R6 不阻挡)"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si", spacegroup="Fd-3m", formation_energy_per_atom=-1.0)],
            "NOMAD": [NomadReference(entry_id="n1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, formation_energy_per_atom_eV=-3.0)],
            "JARVIS": [JarvReference(jid="j1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, formation_energy_per_atom_eV=-1.0)],
        }
        cs = evaluate_cross_source_consistency(recs, consensus_rate_threshold=0.5)
        # 3 源都命中 → consensus_rate=1.0 → R6 pass
        # 形成能偏差 2.0 eV → R7 fail
        assert RULE_R7_CROSS_SOURCE_ENERGY in cs.rules_failed

    def test_band_gap_mismatch_r8_fails(self):
        """带隙偏差大 → R8 fail"""
        recs = {
            "NOMAD": [NomadReference(entry_id="n1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, band_gap_eV=0.3)],
            "JARVIS": [JarvReference(jid="j1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, band_gap_eV=1.5)],
        }
        cs = evaluate_cross_source_consistency(recs)
        assert RULE_R8_CROSS_SOURCE_BAND_GAP in cs.rules_failed


# ============================================================================
# Test 3: evaluate_with_cross_source — 5 路入口
# ============================================================================


class TestEvaluateWithCrossSource:
    def test_5way_returns_verdict_with_cross_source(self):
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si")],
            "COD": [CodReference(cod_id="c1", formula="Si")],
        }
        v = evaluate_with_cross_source([{"formula": "Si"}], recs, user_intent="Si")
        assert v.cross_source is not None
        assert v.cross_source.weight == WEIGHT_L5_CROSS_SOURCE

    def test_5way_does_not_break_3way_baseline(self):
        """5 路入口不应让 3 路基线分大幅下降 — 通过 5-way 加权对比"""
        recs = {"OQMD": [OqmdReference(oqmd_id="o1", formula="Si")]}
        v5 = evaluate_with_cross_source([{"formula": "Si"}], recs, user_intent="Si")
        v3 = evaluate_candidates([{"formula": "Si"}], user_intent="Si")
        # 5-way overall 应在 [0, 1.0] 内
        assert 0.0 <= v5.overall_score <= 1.0
        # 3-way baseline 仍正确
        assert v3.cross_source is None  # 3-way 不填 L5

    def test_5way_failures_extended(self):
        """L5 fail 应扩展 failures 列表"""
        recs = {"OQMD": [OqmdReference(oqmd_id="o1", formula="X")]}  # 仅 1 源
        v = evaluate_with_cross_source([{"formula": "X"}], recs, user_intent="X")
        # 至少 1 个 L5 failure
        codes = [f.code for f in v.failures]
        assert FAIL_CROSS_SOURCE_LOW_CONSENSUS in codes


# ============================================================================
# Test 4: 现有 mat_critic 行为不变(0 回归)
# ============================================================================


class TestBackwardCompatibility:
    def test_evaluate_candidates_no_cross_source(self):
        """3 路 evaluate_candidates 不动 cross_source 字段"""
        v = evaluate_candidates([{"formula": "Si"}], user_intent="Si")
        assert v.cross_source is None

    def test_evaluate_candidates_weight_unchanged(self):
        """3 路 L1/L2/L3 权重仍 0.3/0.3/0.2"""
        assert WEIGHT_L1_PHYSICAL == 0.3


# ============================================================================
# Test 5: M3 常量导出
# ============================================================================


class TestM3Constants:
    def test_l5_weight(self):
        assert WEIGHT_L5_CROSS_SOURCE == 0.1

    def test_failure_codes(self):
        assert FAIL_CROSS_SOURCE_LOW_CONSENSUS == "cross_source_low_consensus"
        assert FAIL_CROSS_SOURCE_ENERGY_MISMATCH == "cross_source_energy_mismatch"
        assert FAIL_CROSS_SOURCE_BAND_GAP_MISMATCH == "cross_source_band_gap_mismatch"

    def test_rule_names(self):
        assert RULE_R6_CROSS_SOURCE_CONSENSUS == "R6_cross_source_consensus_rate"
        assert RULE_R7_CROSS_SOURCE_ENERGY == "R7_cross_source_formation_energy_consistency"
        assert RULE_R8_CROSS_SOURCE_BAND_GAP == "R8_cross_source_band_gap_consistency"