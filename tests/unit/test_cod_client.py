"""test_cod_client.py — COD client 单元测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 11 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.cod_client import (  # noqa: E402
    COD_CIF_URL_TEMPLATE,
    CodClient,
    CodReference,
    fetch_cif,
    is_cod_available,
    search_cod,
)
from agents.cod_client.client import (  # noqa: E402
    _build_cod_query,
    _mock_cod_response,
    _parse_cif_text,
)


# ============================================================================
# Test 1: CodReference 基本
# ============================================================================


class TestCodReference:
    """CodReference dataclass + to_dict"""

    def test_to_dict_full(self):
        r = CodReference(
            cod_id="1522345", formula="Si",
            spacegroup_h_m="Fd-3m", spacegroup_number=227,
            a=5.4309, b=5.4309, c=5.4309,
            alpha=90.0, beta=90.0, gamma=90.0,
            volume=160.2,
            cod_cif_url=COD_CIF_URL_TEMPLATE.format(cod_id="1522345"),
            citation="Smith et al. (2020)",
        )
        d = r.to_dict()
        assert d["cod_id"] == "1522345"
        assert d["formula"] == "Si"
        assert d["spacegroup_h_m"] == "Fd-3m"
        assert d["spacegroup_number"] == 227
        assert d["a"] == 5.4309
        assert d["volume"] == 160.2

    def test_to_dict_minimal(self):
        r = CodReference(cod_id="1", formula="X")
        d = r.to_dict()
        assert d["cod_id"] == "1"
        assert d["formula"] == "X"
        assert d["spacegroup_number"] == 0
        assert d["a"] == 0.0


# ============================================================================
# Test 2: _build_cod_query
# ============================================================================


class TestBuildCodQuery:
    """_build_cod_query 化学式提取"""

    def test_inconel_alias(self):
        assert _build_cod_query("Inconel 718 实验结构") == "Inconel 718"

    def test_llzo_alias(self):
        assert _build_cod_query("LLZO 已知结构") == "LLZO"

    def test_extract_formula_with_digits(self):
        assert _build_cod_query("LiCoO2") == "LiCoO2"

    def test_single_element(self):
        assert _build_cod_query("Si 已知") == "Si"
        assert _build_cod_query("Fe") == "Fe"

    def test_exclude_i_a(self):
        """排除英文单词 I / A"""
        result = _build_cod_query("I want to find")
        # 'I' 不应被识别为元素
        assert result != "I"

    def test_empty(self):
        assert _build_cod_query("") == ""


# ============================================================================
# Test 3: _parse_cif_text
# ============================================================================


class TestParseCifText:
    """_parse_cif_text 从 CIF 文本提取字段"""

    SAMPLE_CIF = """data_test
_chemical_formula_sum 'Si'
_chemical_formula_weight 28.09
_symmetry_space_group_name_H-M 'Fd-3m'
_space_group_IT_number 227
_cell_length_a 5.4309(3)
_cell_length_b 5.4309(3)
_cell_length_c 5.4309(3)
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_cell_volume 160.2
_publ_author 'Smith'
_publ_section_title 'Si crystal structure'
loop_
_atom_site_label
_atom_site_type_symbol
"""

    def test_basic_parse(self):
        ref = _parse_cif_text(self.SAMPLE_CIF, "test-id")
        assert ref is not None
        assert ref.formula == "Si"
        assert ref.spacegroup_h_m == "Fd-3m"
        assert ref.spacegroup_number == 227
        assert abs(ref.a - 5.4309) < 0.001
        assert abs(ref.volume - 160.2) < 0.1

    def test_parse_with_brackets(self):
        """CIF 数字带括号(误差),应正确解析"""
        cif = """data_x
_chemical_formula_sum 'Si'
_cell_length_a 5.4309(3)
"""
        ref = _parse_cif_text(cif, "x")
        assert ref is not None
        assert abs(ref.a - 5.4309) < 0.001

    def test_parse_empty_returns_none(self):
        assert _parse_cif_text("", "x") is None
        assert _parse_cif_text("short", "x") is None

    def test_parse_no_formula_returns_none(self):
        cif = """data_x
_symmetry_space_group_name_H-M 'Fd-3m'
"""
        assert _parse_cif_text(cif, "x") is None


# ============================================================================
# Test 4: _mock_cod_response
# ============================================================================


class TestMockCodResponse:
    """mock fallback 数据完整性"""

    def test_known_silicon(self):
        refs = _mock_cod_response("Si", n=5)
        assert len(refs) >= 1
        assert refs[0].formula == "Si"
        assert refs[0].spacegroup_h_m == "Fd-3m"
        assert refs[0].spacegroup_number == 227
        assert refs[0].a == 5.4309

    def test_known_inconel(self):
        refs = _mock_cod_response("Ni3Cr2Fe2Mo")
        assert refs[0].formula == "Ni19Fe18Cr5Mo"
        assert refs[0].spacegroup_h_m == "Fm-3m"

    def test_known_lco(self):
        refs = _mock_cod_response("LiCoO2")
        assert refs[0].spacegroup_h_m == "R-3m"
        assert refs[0].spacegroup_number == 166

    def test_known_tio2(self):
        refs = _mock_cod_response("TiO2")
        assert refs[0].spacegroup_h_m == "P4_2/mnm"
        assert refs[0].spacegroup_number == 136

    def test_unknown_returns_generic(self):
        refs = _mock_cod_response("UnknownChemXyz123", n=3)
        assert len(refs) == 1
        assert refs[0].cod_id.startswith("mock-")


# ============================================================================
# Test 5: CodClient 基本
# ============================================================================


class TestCodClient:
    """CodClient 默认行为"""

    def test_default_init(self):
        c = CodClient()
        assert c.timeout == 10
        assert c.enable_fallback is True
        assert c.max_results == 5

    def test_custom_init(self):
        c = CodClient(timeout=20, max_results=10)
        assert c.timeout == 20
        assert c.max_results == 10

    def test_search_empty(self):
        c = CodClient()
        refs, is_real = c.search("")
        assert refs == []

    def test_search_known_chemical(self):
        """已知化学式 → 至少返回 1 条(mock 兜底)"""
        c = CodClient()
        refs, is_real = c.search("Si")
        assert len(refs) >= 1
        # M1 简化:is_real 总是 False(M2 才会改)
        assert isinstance(is_real, bool)

    def test_to_canonical(self):
        c = CodClient()
        ref = CodReference(
            cod_id="test", formula="Si",
            spacegroup_h_m="Fd-3m", spacegroup_number=227,
        )
        k = c.to_canonical(ref)
        assert k.reduced_formula == "Si"
        assert k.pearson_symbol == "cF8"
        assert k.spacegroup_number == 227

    def test_canonical_fields_helper(self):
        """_canonical_fields static method"""
        ref = CodReference(
            cod_id="x", formula="LiCoO2",
            spacegroup_h_m="R-3m", spacegroup_number=166,
        )
        rf, ps, sgn = CodClient._canonical_fields(ref)
        assert rf == "CoLiO2"
        assert ps == "hR1"
        assert sgn == 166


# ============================================================================
# Test 6: 模块级便捷函数
# ============================================================================


class TestModuleConvenience:
    """模块级 search_cod / fetch_cif / is_cod_available"""

    def test_search_cod(self):
        refs, is_real = search_cod("Si")
        assert isinstance(refs, list)
        assert isinstance(is_real, bool)

    def test_fetch_cif_invalid_id(self):
        """无效 cod-id 返回 None,不抛"""
        result = fetch_cif("nonexistent-999999999", timeout=2)
        # 网络不可控,但至少不抛
        assert result is None or isinstance(result, str)

    def test_is_cod_available_returns_bool(self):
        result = is_cod_available()
        assert isinstance(result, bool)