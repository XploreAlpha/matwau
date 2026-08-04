"""test_canonical_key.py — CanonicalKey + 化学式归一化 + Pearson 符号解析测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 14 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.data_canonical import (  # noqa: E402
    CanonicalKey,
    normalize_formula,
    parse_pearson_symbol,
    spacegroup_to_number,
)


# ============================================================================
# Test 1: normalize_formula
# ============================================================================


class TestNormalizeFormula:
    """化学式归一化(Hill system)"""

    def test_simple_binary(self):
        """LiCoO2 → CoLiO2(Hill:无 C/H,字母序)"""
        assert normalize_formula("LiCoO2") == "CoLiO2"

    def test_lithium_compound_with_lanthanum(self):
        """Li7La3Zr2O12 → La3Li7O12Zr2(Hill:无 C/H,字母序)"""
        assert normalize_formula("Li7La3Zr2O12") == "La3Li7O12Zr2"

    def test_carbon_priority(self):
        """C2H5OH → C2H6O(Hill:C 优先 → H 次之 → O)"""
        # 注意:乙醇的化学式简写;按 Hill 应为 C2H6O
        result = normalize_formula("C2H6O")
        assert result == "C2H6O"

    def test_h_after_c(self):
        """CH4 → CH4"""
        assert normalize_formula("CH4") == "CH4"

    def test_remove_whitespace(self):
        """' LiCoO2 ' → 'CoLiO2'"""
        assert normalize_formula("  LiCoO2  ") == "CoLiO2"

    def test_remove_underscore_dot(self):
        """'Li.Co.O2' → 'CoLiO2'"""
        assert normalize_formula("Li.Co.O2") == "CoLiO2"

    def test_remove_charge(self):
        """'Fe3+' → 'Fe'"""
        assert normalize_formula("Fe3+") == "Fe"

    def test_single_element(self):
        """Si → Si"""
        assert normalize_formula("Si") == "Si"

    def test_lowercase_element_preserved(self):
        """Fe2O3 → Fe2O3(正确解析小写)"""
        assert normalize_formula("Fe2O3") == "Fe2O3"

    def test_invalid_returns_empty(self):
        """非化学式返回空"""
        assert normalize_formula("hello world") == ""
        assert normalize_formula("这是一段中文文本") == ""  # 中文无化学式
        assert normalize_formula("random text with no formula") == ""

    def test_empty_returns_empty(self):
        """空字符串返回空"""
        assert normalize_formula("") == ""

    def test_aggregation(self):
        """Na2CO3 → CNa2O3(Hill:C 优先 → 其余 NaO 字母序)"""
        assert normalize_formula("Na2CO3") == "CNa2O3"


# ============================================================================
# Test 2: parse_pearson_symbol
# ============================================================================


class TestParsePearsonSymbol:
    """空间群符号 → Pearson 符号"""

    def test_fcc(self):
        """Fm-3m → cF4(FCC α-poison)"""
        assert parse_pearson_symbol("Fm-3m") == "cF4"

    def test_bcc(self):
        """Im-3m → cI2"""
        assert parse_pearson_symbol("Im-3m") == "cI2"

    def test_diamond(self):
        """Fd-3m → cF8(Si / Ge diamond)"""
        assert parse_pearson_symbol("Fd-3m") == "cF8"

    def test_garnet(self):
        """Ia-3d → cI40(LLZO garnet)"""
        assert parse_pearson_symbol("Ia-3d") == "cI40"

    def test_hcp(self):
        """P63/mmc → hP2(Mg hcp)"""
        assert parse_pearson_symbol("P63/mmc") == "hP2"

    def test_rutile(self):
        """P4_2/mnm → tP4(TiO2 rutile)"""
        assert parse_pearson_symbol("P4_2/mnm") == "tP4"

    def test_lco_layered(self):
        """R-3m → hR1(LiCoO2 layered)"""
        assert parse_pearson_symbol("R-3m") == "hR1"

    def test_wurtzite(self):
        """P63mc → hP2(ZnO wurtzite)"""
        assert parse_pearson_symbol("P63mc") == "hP2"

    def test_unknown_returns_empty(self):
        """未知空间群返回空"""
        assert parse_pearson_symbol("Unknown-Xx") == ""
        assert parse_pearson_symbol("") == ""


# ============================================================================
# Test 3: spacegroup_to_number
# ============================================================================


class TestSpacegroupNumber:
    """空间群符号 → 编号"""

    def test_fcc(self):
        assert spacegroup_to_number("Fm-3m") == 225

    def test_bcc(self):
        assert spacegroup_to_number("Im-3m") == 229

    def test_diamond(self):
        assert spacegroup_to_number("Fd-3m") == 227

    def test_garnet(self):
        assert spacegroup_to_number("Ia-3d") == 230

    def test_lco(self):
        assert spacegroup_to_number("R-3m") == 166

    def test_hcp(self):
        assert spacegroup_to_number("P63/mmc") == 194

    def test_rutile(self):
        assert spacegroup_to_number("P4_2/mnm") == 136

    def test_unknown_returns_zero(self):
        assert spacegroup_to_number("Unknown-Xx") == 0
        assert spacegroup_to_number("") == 0


# ============================================================================
# Test 4: CanonicalKey
# ============================================================================


class TestCanonicalKey:
    """CanonicalKey dataclass + matches() 行为"""

    def test_from_formula_spacegroup(self):
        """基本构造"""
        k = CanonicalKey.from_formula_spacegroup("LiCoO2", "R-3m")
        assert k.reduced_formula == "CoLiO2"
        assert k.pearson_symbol == "hR1"
        assert k.spacegroup_number == 166

    def test_from_invalid_formula(self):
        """非法化学式 → 空 canonical"""
        k = CanonicalKey.from_formula_spacegroup("hello", "Fm-3m")
        assert k.reduced_formula == ""
        assert k.pearson_symbol == ""  # 空 rf 时不算输入
        assert k.spacegroup_number == 0

    def test_from_record_oqmd(self):
        """从 OqmdRecord 构造"""
        from agents.oqmd_client import OqmdReference
        ref = OqmdReference(
            oqmd_id="oqmd-test", formula="Li7La3Zr2O12",
            spacegroup="Ia-3d",
        )
        k = CanonicalKey.from_record(ref)
        assert k.reduced_formula == "La3Li7O12Zr2"
        assert k.pearson_symbol == "cI40"
        assert k.spacegroup_number == 230

    def test_from_record_cod(self):
        """从 CodReference 构造(COD 用 spacegroup_h_m 字段)"""
        from agents.cod_client import CodReference
        ref = CodReference(
            cod_id="1000000", formula="Si",
            spacegroup_h_m="Fd-3m", spacegroup_number=227,
        )
        k = CanonicalKey.from_record(ref)
        assert k.reduced_formula == "Si"
        assert k.pearson_symbol == "cF8"
        assert k.spacegroup_number == 227

    def test_matches_fuzzy_same_formula(self):
        """fuzzy 匹配:同 formula + 至少 1 crystal field 一致"""
        k1 = CanonicalKey.from_formula_spacegroup("LiCoO2", "R-3m")
        k2 = CanonicalKey(reduced_formula="CoLiO2", pearson_symbol="", spacegroup_number=166)
        assert k1.matches(k2) is True

    def test_matches_strict_requires_all(self):
        """strict 匹配:三全一致(允许容错)"""
        k1 = CanonicalKey(reduced_formula="CoLiO2", pearson_symbol="hR1", spacegroup_number=166)
        k2 = CanonicalKey(reduced_formula="CoLiO2", pearson_symbol="hR1", spacegroup_number=166)
        assert k1.matches(k2, strict=True) is True

        # Pearson 不同 → strict 失败
        k3 = CanonicalKey(reduced_formula="CoLiO2", pearson_symbol="cF4", spacegroup_number=166)
        assert k1.matches(k3, strict=True) is False

    def test_matches_different_formula(self):
        """不同 formula → 不匹配"""
        k1 = CanonicalKey(reduced_formula="CoLiO2")
        k2 = CanonicalKey(reduced_formula="LiFePO4")
        assert k1.matches(k2) is False

    def test_matches_empty_formula(self):
        """空 formula → 不匹配"""
        k1 = CanonicalKey(reduced_formula="")
        k2 = CanonicalKey(reduced_formula="CoLiO2")
        assert k1.matches(k2) is False

    def test_to_dict(self):
        """→ dict 序列化"""
        k = CanonicalKey.from_formula_spacegroup("Si", "Fd-3m")
        d = k.to_dict()
        assert d["reduced_formula"] == "Si"
        assert d["pearson_symbol"] == "cF8"
        assert d["spacegroup_number"] == 227

    def test_str_repr(self):
        """__str__"""
        k = CanonicalKey.from_formula_spacegroup("Si", "Fd-3m")
        s = str(k)
        assert "Si" in s
        assert "cF8" in s
        assert "227" in s

    def test_immutable(self):
        """frozen dataclass 不能修改"""
        k = CanonicalKey(reduced_formula="Si")
        with pytest.raises(Exception):  # FrozenInstanceError
            k.reduced_formula = "Fe"

    def test_matches_both_empty_crystal_fields(self):
        """两边 crystal field 都空 → 默认同 formula 即视为同物相"""
        k1 = CanonicalKey(reduced_formula="X")
        k2 = CanonicalKey(reduced_formula="X")
        assert k1.matches(k2) is True


# ============================================================================
# Test 5: 跨库归一化(50 化合物 smoke test)
# ============================================================================


REAL_WORLD_COMPOUNDS = [
    # (化学式, 空间群, Pearson 期望, 空间群编号 期望)
    ("Si", "Fd-3m", "cF8", 227),
    ("Fe", "Im-3m", "cI2", 229),
    ("Cu", "Fm-3m", "cF4", 225),
    ("Al", "Fm-3m", "cF4", 225),
    ("Ni", "Fm-3m", "cF4", 225),
    ("Mg", "P63/mmc", "hP2", 194),
    ("Ti", "P63/mmc", "hP2", 194),
    ("Zn", "P63/mmc", "hP2", 194),
    ("Co", "P63/mmc", "hP2", 194),
    ("LiCoO2", "R-3m", "hR1", 166),
    ("LiFePO4", "Pnma", "oP4", 62),
    ("Li7La3Zr2O12", "Ia-3d", "cI40", 230),
    ("TiO2", "P4_2/mnm", "tP4", 136),
    ("Fe2O3", "R-3c", "hR1", 161),
    ("Al2O3", "R-3c", "hR1", 161),
    ("NaCl", "Fm-3m", "cF4", 225),
    ("CsCl", "Pm-3m", "cP1", 221),
    ("ZnO", "P63mc", "hP2", 186),
    ("GaN", "P63mc", "hP2", 186),
    ("GaAs", "F-43m", "", 0),  # 未在 map 中,期望 pearson 空
    ("Ni3Cr2Fe2Mo", "Fm-3m", "cF4", 225),
    ("CdSe", "F-43m", "", 0),
    ("CdTe", "F-43m", "", 0),
    ("MoS2", "P63/mmc", "hP2", 194),
    ("WS2", "P63/mmc", "hP2", 194),
    ("SnO2", "P4_2/mnm", "tP4", 136),
    ("CeO2", "Fm-3m", "cF4", 225),
    ("ZrO2", "P21/c", "mP4", 14),
    ("MgO", "Fm-3m", "cF4", 225),
    ("BaTiO3", "Pm-3m", "cP1", 221),
    ("SrTiO3", "Pm-3m", "cP1", 221),
    ("PbTiO3", "P4/mmm", "tP1", 123),
    ("LaB6", "Pm-3m", "cP1", 221),
    ("YBa2Cu3O7", "Pmmm", "", 0),  # 未在 map 中
    ("Bi2Te3", "R-3m", "hR1", 166),
    ("Sb2Te3", "R-3m", "hR1", 166),
    ("InAs", "F-43m", "", 0),
    ("InP", "F-43m", "", 0),
    ("InSb", "F-43m", "", 0),
    ("HgTe", "F-43m", "", 0),
    ("PbS", "Fm-3m", "cF4", 225),
    ("PbSe", "Fm-3m", "cF4", 225),
    ("PbTe", "Fm-3m", "cF4", 225),
    ("SnS", "Pnma", "oP4", 62),
    ("SnSe", "Pnma", "oP4", 62),
    ("BiFeO3", "R3c", "hR1", 161),
    ("BaFe12O19", "P63/mmc", "hP2", 194),
    ("Sr2RuO4", "I4/mmm", "tI2", 139),
    ("La2CuO4", "Bmab", "", 0),
    ("Y3Al5O12", "Ia-3d", "cI40", 230),
]


class TestRealWorldNormalization:
    """真实 50 化合物 smoke test — 归一化正确率 ≥ 95%(per requirements §6.2)"""

    @pytest.mark.parametrize("formula,sg,expected_pearson,expected_sgn", REAL_WORLD_COMPOUNDS)
    def test_canonical_key(self, formula, sg, expected_pearson, expected_sgn):
        k = CanonicalKey.from_formula_spacegroup(formula, sg)
        # reduced_formula 应该非空(化学式合法)
        assert k.reduced_formula != "", f"归一化失败:{formula}"
        # Pearson 期望值(允许部分未匹配为 "")
        assert k.pearson_symbol == expected_pearson, (
            f"{formula} {sg}: 期望 pearson={expected_pearson}, 得 {k.pearson_symbol}"
        )
        # spacegroup_number
        assert k.spacegroup_number == expected_sgn, (
            f"{formula} {sg}: 期望 sgn={expected_sgn}, 得 {k.spacegroup_number}"
        )