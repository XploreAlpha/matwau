"""test_cross_source_resolver.py — cross_source_resolver 单元测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M3 第 8 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.data_canonical import (  # noqa: E402
    ConsensusCluster,
    ConsensusReport,
    ConsistencyConflict,
    resolve_cross_source,
)
from agents.oqmd_client import OqmdReference  # noqa: E402
from agents.cod_client import CodReference  # noqa: E402
from agents.nomad_client import NomadReference  # noqa: E402
from agents.jarvis_client import JarvReference  # noqa: E402


# ============================================================================
# Test 1: 基础聚合(4 源都命中,1 个 canonical)
# ============================================================================


class TestResolveCrossSourceBasic:
    def test_4_sources_same_canonical_consensus(self):
        """4 源都命中 1 个化合物 → 1 cluster, hit_count=4, is_consensus=True"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="LiCoO2", spacegroup="R-3m")],
            "COD": [CodReference(cod_id="c1", formula="LiCoO2", spacegroup_h_m="R-3m", spacegroup_number=166)],
            "NOMAD": [NomadReference(entry_id="n1", formula="LiCoO2", spacegroup_symbol="R-3m", spacegroup_number=166)],
            "JARVIS": [JarvReference(jid="j1", formula="LiCoO2", spacegroup_symbol="R-3m", spacegroup_number=166)],
        }
        report = resolve_cross_source(recs, user_intent="LiCoO2")
        assert report.user_intent == "LiCoO2"
        assert report.total_records == 4
        assert report.n_platforms_hit == 4
        # 至少 1 个 consensus cluster
        assert len(report.clusters) >= 1
        # 最高 hit_count 的 cluster
        best = max(report.clusters, key=lambda c: c.hit_count)
        assert best.hit_count >= 2
        assert best.is_consensus is True

    def test_single_source_only(self):
        """仅 1 源命中 → consensus_rate=0, conflict=only_one_source"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si")],
            "COD": [],
            "NOMAD": [],
            "JARVIS": [],
        }
        report = resolve_cross_source(recs, user_intent="Si")
        assert report.n_platforms_hit == 1
        assert report.consensus_rate == 0.0
        assert any(c.conflict_type == "only_one_source" for c in report.conflicts)

    def test_empty_records(self):
        """全部空 → 空 report"""
        report = resolve_cross_source({"OQMD": [], "COD": []}, user_intent="x")
        assert report.total_records == 0
        assert report.clusters == []
        assert report.conflicts == []
        assert report.consensus_rate == 0.0


# ============================================================================
# Test 2: 冲突检测
# ============================================================================


class TestConflictDetection:
    def test_formation_energy_mismatch_detected(self):
        """形成能偏差 > 0.5 eV → energy_mismatch conflict"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="LiCoO2", spacegroup="R-3m", formation_energy_per_atom=-1.78)],
            "COD": [CodReference(cod_id="c1", formula="LiCoO2", spacegroup_h_m="R-3m", spacegroup_number=166)],
            "NOMAD": [NomadReference(entry_id="n1", formula="LiCoO2", spacegroup_symbol="R-3m", spacegroup_number=166, formation_energy_per_atom_eV=-3.50)],  # 偏差 1.72
            "JARVIS": [JarvReference(jid="j1", formula="LiCoO2", spacegroup_symbol="R-3m", spacegroup_number=166, formation_energy_per_atom_eV=-1.80)],
        }
        report = resolve_cross_source(recs, energy_mismatch_threshold=0.5)
        assert any(c.conflict_type == "energy_mismatch" for c in report.conflicts)

    def test_band_gap_mismatch_detected(self):
        """带隙偏差 > 0.3 eV → band_gap_mismatch conflict"""
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si", spacegroup="Fd-3m")],
            "NOMAD": [NomadReference(entry_id="n1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, band_gap_eV=0.5)],
            "JARVIS": [JarvReference(jid="j1", formula="Si", spacegroup_symbol="Fd-3m", spacegroup_number=227, band_gap_eV=1.5)],  # 偏差 1.0
        }
        report = resolve_cross_source(recs, band_gap_mismatch_threshold=0.3)
        assert any(c.conflict_type == "band_gap_mismatch" for c in report.conflicts)


# ============================================================================
# Test 3: 平台识别
# ============================================================================


class TestPlatformDetection:
    def test_detect_oqmd(self):
        r = OqmdReference(oqmd_id="o1", formula="Si")
        from agents.data_canonical.cross_source_resolver import _detect_platform
        assert _detect_platform(r) == "OQMD"

    def test_detect_cod(self):
        r = CodReference(cod_id="c1", formula="Si")
        from agents.data_canonical.cross_source_resolver import _detect_platform
        assert _detect_platform(r) == "COD"

    def test_detect_nomad(self):
        r = NomadReference(entry_id="n1", formula="Si")
        from agents.data_canonical.cross_source_resolver import _detect_platform
        assert _detect_platform(r) == "NOMAD"

    def test_detect_jarvis(self):
        r = JarvReference(jid="j1", formula="Si")
        from agents.data_canonical.cross_source_resolver import _detect_platform
        assert _detect_platform(r) == "JARVIS"


# ============================================================================
# Test 4: ConsensusReport to_dict
# ============================================================================


class TestConsensusReportToDict:
    def test_to_dict_keys(self):
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si")],
            "COD": [CodReference(cod_id="c1", formula="Si")],
        }
        report = resolve_cross_source(recs, user_intent="Si")
        d = report.to_dict()
        for key in [
            "user_intent", "consensus_rate", "n_platforms_hit",
            "total_records", "platform_hit_counts", "clusters",
            "conflicts", "n_clusters", "n_consensus_clusters",
        ]:
            assert key in d

    def test_consensus_report_platform_hit_counts(self):
        recs = {
            "OQMD": [OqmdReference(oqmd_id="o1", formula="Si")],
            "COD": [],
            "NOMAD": [],
            "JARVIS": [],
        }
        report = resolve_cross_source(recs)
        assert report.platform_hit_counts == {"OQMD": 1}


# ============================================================================
# Test 5: _extract_energy / _extract_band_gap
# ============================================================================


class TestEnergyExtraction:
    def test_extract_oqmd_energy(self):
        r = OqmdReference(oqmd_id="o1", formula="Si", formation_energy_per_atom=-1.5)
        from agents.data_canonical.cross_source_resolver import _extract_energy
        assert abs(_extract_energy(r) - (-1.5)) < 0.001

    def test_extract_jarvis_energy(self):
        r = JarvReference(jid="j1", formula="Si", formation_energy_per_atom_eV=-0.5)
        from agents.data_canonical.cross_source_resolver import _extract_energy
        assert abs(_extract_energy(r) - (-0.5)) < 0.001

    def test_extract_band_gap_from_nomad(self):
        r = NomadReference(entry_id="n1", formula="Si", band_gap_eV=1.11)
        from agents.data_canonical.cross_source_resolver import _extract_band_gap
        assert abs(_extract_band_gap(r) - 1.11) < 0.001

    def test_extract_no_energy(self):
        r = CodReference(cod_id="c1", formula="Si")  # COD 没形成能字段
        from agents.data_canonical.cross_source_resolver import _extract_energy
        assert _extract_energy(r) == 0.0