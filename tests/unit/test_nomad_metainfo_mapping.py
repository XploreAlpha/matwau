"""test_nomad_metainfo_mapping.py — NOMAD metainfo 映射测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 13 项
"M2 验收门:覆盖 ≥ 30 种 metainfo 字段映射,0 fail"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.nomad_client.metainfo_mapping import (  # noqa: E402
    KNOWN_PROPERTY_GROUPS,
    KNOWN_SECTIONS,
    MAPPED_METAINFO_PATHS,
    UNMAPPED_PATTERNS,
    count_mapped_metainfo_paths,
    extract_nomad_record,
)


# ============================================================================
# Test 1: 覆盖数量(per dev-plan 验收门 ≥ 30)
# ============================================================================


class TestMetainfoCoverage:
    """MAPPED_METAINFO_PATHS 覆盖数量验证"""

    def test_mapped_paths_at_least_30(self):
        """M2 验收门: ≥ 30 种 metainfo 字段映射"""
        assert count_mapped_metainfo_paths() >= 30, (
            f"仅映射 {count_mapped_metainfo_paths()} 个 metainfo 路径,< 30 验收要求"
        )

    def test_mapped_paths_unique(self):
        """MAPPED_METAINFO_PATHS 中路径应唯一"""
        assert len(MAPPED_METAINFO_PATHS) == len(set(MAPPED_METAINFO_PATHS))

    def test_unmapped_patterns_is_list(self):
        """UNMAPPED_PATTERNS 应是非空 list(str)"""
        assert isinstance(UNMAPPED_PATTERNS, list)
        assert all(isinstance(p, str) for p in UNMAPPED_PATTERNS)
        assert len(UNMAPPED_PATTERNS) >= 3

    def test_known_sections_frozenset(self):
        """KNOWN_SECTIONS 应是 frozenset"""
        assert isinstance(KNOWN_SECTIONS, frozenset)
        assert "section_system" in KNOWN_SECTIONS

    def test_known_property_groups(self):
        """KNOWN_PROPERTY_GROUPS 含 electronic / thermodynamic"""
        assert "electronic" in KNOWN_PROPERTY_GROUPS
        assert "thermodynamic" in KNOWN_PROPERTY_GROUPS


# ============================================================================
# Test 2: extract_nomad_record — 完整 entry
# ============================================================================


NOMAD_FULL_ENTRY = {
    "entry_id": "nomad-test-001",
    "upload_id": "upload-001",
    "archive_id": "archive-001",
    "results": {
        "material": {
            "chemical_formula_hill": "CoLiO2",
            "chemical_formula_reduced": "LiCoO2",
            "elements": ["Li", "Co", "O"],
            "symmetry": {
                "international_short_symbol": "R-3m",
                "space_group_number": 166,
            },
            "lattice": {
                "a": 2.815, "b": 2.815, "c": 14.05,
                "alpha": 90.0, "beta": 90.0, "gamma": 120.0,
                "volume": 96.5,
            },
        },
        "properties": {
            "electronic": {
                "band_gap": 2.3,
                "band_gap_fermi_level": 2.3,
                "fermi_level": 3.5,
            },
            "thermodynamic": {
                "formation_energy": -1.78,
                "energy_above_hull": 0.02,
            },
            "mechanical": {
                "bulk_modulus": 180.0,
                "shear_modulus": 70.0,
                "young_modulus": 200.0,
            },
            "structural": {
                "crystal_system": "trigonal",
                "spacegroup": "R-3m",
                "lattice_type": "hR1",
            },
        },
        "method": {
            "simulation": {
                "program_name": "VASP",
                "xc_functional": "PBE+U",
                "code_version": "6.3.0",
                "ecutwfc": 520.0,
            },
            "ensemble": {"type": "NVT"},
        },
        "sample": {
            "elements": ["Li", "Co", "O"],
            "chemical_formula": "LiCoO2",
        },
    },
    "available_properties": ["electronic", "thermodynamic", "mechanical", "structural"],
}


class TestExtractNomadRecord:
    """完整 NOMAD entry 提取"""

    def test_extract_formula_hill_priority(self):
        """优先 chemical_formula_hill"""
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert d["formula"] == "CoLiO2"

    def test_extract_elements(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert "Li" in d["elements"]
        assert "Co" in d["elements"]
        assert "O" in d["elements"]

    def test_extract_spacegroup(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert d["spacegroup_symbol"] == "R-3m"
        assert d["spacegroup_number"] == 166

    def test_extract_lattice(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert abs(d["a"] - 2.815) < 0.001
        assert abs(d["c"] - 14.05) < 0.001
        assert abs(d["gamma"] - 120.0) < 0.001
        assert abs(d["volume"] - 96.5) < 0.001

    def test_extract_band_gap(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert abs(d["band_gap_eV"] - 2.3) < 0.001

    def test_extract_formation_energy(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert abs(d["formation_energy_per_atom_eV"] - (-1.78)) < 0.001

    def test_extract_bulk_modulus(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert abs(d["bulk_modulus_GPa"] - 180.0) < 0.001

    def test_extract_method(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert d["xc_functional"] == "PBE+U"
        assert d["program_name"] == "VASP"

    def test_extract_ids(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert d["entry_id"] == "nomad-test-001"
        assert d["upload_id"] == "upload-001"
        assert d["archive_id"] == "archive-001"

    def test_extract_available_properties(self):
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        assert "electronic" in d["available_properties"]
        assert "thermodynamic" in d["available_properties"]


# ============================================================================
# Test 3: extract_nomad_record — 鲁棒性(空 / 部分字段)
# ============================================================================


class TestExtractNomadRobustness:
    """空 / 部分字段 / 错误类型的鲁棒性"""

    def test_empty_entry(self):
        d = extract_nomad_record({})
        assert d["formula"] == ""
        assert d["entry_id"] == ""
        assert d["band_gap_eV"] == 0.0

    def test_partial_material(self):
        """只有 chemical_formula_hill,无 symmetry/lattice"""
        d = extract_nomad_record({
            "entry_id": "x",
            "results": {"material": {"chemical_formula_hill": "Si2"}},
        })
        assert d["formula"] == "Si2"
        assert d["spacegroup_symbol"] == ""
        assert d["a"] == 0.0

    def test_symm_fallback(self):
        """symmetry.international_short_symbol 缺 → 退到 space_group_symbol"""
        d = extract_nomad_record({
            "entry_id": "x",
            "results": {"material": {"symmetry": {"space_group_symbol": "Fd-3m"}}},
        })
        assert d["spacegroup_symbol"] == "Fd-3m"

    def test_numeric_as_string(self):
        """数字以 string 给 → 应能 parse"""
        d = extract_nomad_record({
            "entry_id": "x",
            "results": {"properties": {"electronic": {"band_gap": "1.11"}}},
        })
        assert abs(d["band_gap_eV"] - 1.11) < 0.001

    def test_value_in_dict(self):
        """dict 包裹 {{value: 1.5}}"""
        d = extract_nomad_record({
            "entry_id": "x",
            "results": {"properties": {"electronic": {"band_gap": {"value": 1.5}}}},
        })
        assert abs(d["band_gap_eV"] - 1.5) < 0.001

    def test_list_first_element(self):
        """list 首元素取值"""
        d = extract_nomad_record({
            "entry_id": "x",
            "results": {"properties": {"electronic": {"band_gap": [1.2, 1.3]}}},
        })
        assert abs(d["band_gap_eV"] - 1.2) < 0.001


# ============================================================================
# Test 4: NomadReference 集成
# ============================================================================


class TestNomadReferenceIntegration:
    """NomadReference.from_record-like path → 与 metainfo_mapping 一致性"""

    def test_canonical_key_from_extracted(self):
        """extracted dict → CanonicalKey"""
        from agents.data_canonical import CanonicalKey
        d = extract_nomad_record(NOMAD_FULL_ENTRY)
        k = CanonicalKey.from_formula_spacegroup(d["formula"], d["spacegroup_symbol"])
        assert k.reduced_formula == "CoLiO2"
        assert k.pearson_symbol == "hR1"
        assert k.spacegroup_number == 166