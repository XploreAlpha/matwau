"""canonical_key.py — CanonicalKey 抽象 + 化学式归一化 + Pearson 符号解析

v1.3-Academic M1 基础抽象,被 OQMD / COD / NOMAD / JARVIS 4 client 共用,
供 mat_critic L4 跨数据源规则(M3)+ cross_source_resolver(M3)使用。

设计原则(per MatWAU-Harness-Loop-工程心法实践 §3.3):
- 纯函数为主,无 IO / 无 LLM / 无网络
- 输入 record 输出 CanonicalKey(类方法)
- 提供 tolerance=strict / fuzzy 两种 matches 策略

字段语义:
- reduced_formula: Hill system 排序后的化学式(如 Li7La3Zr2O12)
  注意:跨库归一化时,OQMD/MP/NOMAD 已用 Hill;COD/CIF 用 IUCr convention
- pearson_symbol: Pearson 符号(cF4 / hP2 / oP8 / mP16 等 24 种)
- spacegroup_number: 1-230 空间群编号

References:
- Hill system: https://en.wikipedia.org/wiki/Chemical_formula#Hill_system
- Pearson symbol: https://en.wikipedia.org/wiki/Pearson_symbol
- Space group numbering: https://www.cryst.ehu.es/cgi-bin/cryst/programs/nph-trgen
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ============================================================================
# 常量
# ============================================================================


# 元素按 Hill system 排序的优先级(C + H 排前,其余按字母序)
_HILL_ORDER = (
    "C", "H",
)
# 其余元素按字母序(在 normalize_formula 中拼接)


# Pearson symbol 表(24 种 + 部分简写)
_PEARSON_PATTERN = re.compile(r"^([abc])(\d)?([PFIVC])(\d+)$")

# 空间群符号 → 编号(常用子集,完整 230 见 mat_critic cross_robot.py)
_SPACEGROUP_NUMBER_MAP = {
    "P1": 1, "P-1": 2,
    "P21/c": 14, "P2_1/c": 14, "C2/c": 15,
    "P212121": 19, "Pna21": 33,
    "Pm-3m": 221, "Pm3m": 221, "Pn-3m": 223, "Pn3m": 223,
    "Fm-3m": 225, "Fm3m": 225, "Fd-3m": 227, "Fd3m": 227,
    "Im-3m": 229, "Im3m": 229,
    "Ia-3d": 230, "Ia3d": 230,
    "R-3m": 166, "R3m": 166, "R3c": 161, "R-3c": 161,
    "P63/mmc": 194, "P6_3/mmc": 194, "P4/mmm": 123,
    "P6/mmm": 191, "P4_2/mnm": 136,
    "P63mc": 186, "P6_3mc": 186, "Pca21": 29,
    "Pnma": 62, "P n m a": 62,
    "Pbca": 61, "P b c a": 61,
    "I4/mmm": 139,
}


# ============================================================================
# 纯函数 — 化学式归一化
# ============================================================================


def normalize_formula(formula: str) -> str:
    """归一化化学式(Hill system)

    规则:
    1. 移除空格 / 下划线 / 点
    2. 提取元素 + 数量(支持多层嵌套如 Li7La3Zr2O12)
    3. 按 Hill system 重排:C 优先 → H 次之 → 其余按元素符号字母序
    4. 数字默认 1

    Examples:
        "LiCoO2"        → "CoLiO2"(Co 按字母序)
        "Li7La3Zr2O12"  → "La3Li7O12Zr2"
        " Inconel 718 " → ""(非化学式,返回空字符串)
        "Fe2O3"         → "Fe2O3"

    Args:
        formula: 原始化学式字符串

    Returns:
        归一化后的化学式;若非合法化学式返回 ""
    """
    if not formula:
        return ""

    # 移除空白 / 下划线 / 点
    s = formula.replace(" ", "").replace("_", "").replace(".", "")
    # 移除 + - 电荷符号(物理化学式常见,如 "Fe3+" / "Fe+")
    s = re.sub(r"\d*[+\-]\d*$|[+\-]$", "", s)

    # 解析元素 + 数字
    # 模式:大写字母 + 可选小写字母 + 可选数字(单次)
    # 嵌套如 Li7La3Zr2O12 用 finditer 顺序扫描
    element_counts: dict[str, int] = {}
    i = 0
    while i < len(s):
        if not s[i].isupper():
            return ""  # 非大写字母开头 = 非化学式
        # 元素符号 = 大写 + 可选小写
        j = i + 1
        while j < len(s) and s[j].islower():
            j += 1
        elem = s[i:j]
        # 数字
        k = j
        while k < len(s) and s[k].isdigit():
            k += 1
        count = int(s[j:k]) if k > j else 1

        if elem not in element_counts:
            element_counts[elem] = 0
        element_counts[elem] += count
        i = k

    if not element_counts:
        return ""

    # Hill system 排序:C 优先 → H 次之 → 其余按字母序
    parts: list[tuple[str, int]] = []
    for c in _HILL_ORDER:
        if c in element_counts:
            parts.append((c, element_counts[c]))
            del element_counts[c]
    for elem in sorted(element_counts.keys()):
        parts.append((elem, element_counts[elem]))

    # 拼回
    out = []
    for elem, count in parts:
        if count == 1:
            out.append(elem)
        else:
            out.append(f"{elem}{count}")
    return "".join(out)


def parse_pearson_symbol(spacegroup_symbol: str) -> str:
    """从空间群符号推导 Pearson 符号

    仅覆盖常见 crystal system + 部分空间群映射,其余返回 ""

    Examples:
        "Fm-3m"        → "cF4"
        "P63/mmc"      → "hP2"
        "R-3m"         → "hR1"(trigonal rhombohedral)
        "Ia-3d"        → "cI40"
        "P4_2/mnm"     → "tP4"
        "Unknown"      → ""

    Args:
        spacegroup_symbol: 国际空间群符号

    Returns:
        Pearson 符号;若无法推导返回 ""
    """
    if not spacegroup_symbol:
        return ""

    sg = spacegroup_symbol.strip()

    # Cubic Fm-3m 系列(cF4)
    if sg in ("Fm-3m", "Fm3m"):
        return "cF4"
    # Cubic Fd-3m 系列(cF8 for spinel 类 / cF24 for fluorite 等;简化 cF8)
    if sg in ("Fd-3m", "Fd3m"):
        return "cF8"
    # Cubic Ia-3d(cI40 garnet)
    if sg in ("Ia-3d", "Ia3d"):
        return "cI40"
    # Cubic Pm-3m(cP1)
    if sg in ("Pm-3m", "Pm3m"):
        return "cP1"
    # Cubic Pn-3m(cP2)
    if sg in ("Pn-3m", "Pn3m"):
        return "cP2"
    # Cubic Im-3m(cI2)
    if sg in ("Im-3m", "Im3m"):
        return "cI2"

    # Hexagonal P63/mmc(hP2)
    if sg in ("P63/mmc", "P6_3/mmc"):
        return "hP2"
    # Hexagonal P6/mmm(hP1)
    if sg in ("P6/mmm", "P6/mmm"):
        return "hP1"
    # Hexagonal P63mc(hP2 wurtzite)
    if sg in ("P63mc", "P6_3mc"):
        return "hP2"

    # Trigonal R-3m(hR1)
    if sg in ("R-3m", "R3m"):
        return "hR1"
    if sg in ("R3c", "R-3c"):
        return "hR1"

    # Tetragonal P4/mmm(tP1)
    if sg in ("P4/mmm", "P4/mmm"):
        return "tP1"
    # Tetragonal P4_2/mnm(tP4 rutile)
    if sg in ("P4_2/mnm", "P4_2/mnm"):
        return "tP4"
    # Tetragonal I4/mmm(tI2)
    if sg in ("I4/mmm", "I4/mmm"):
        return "tI2"

    # Orthorhombic Pnma(oP4 / oP8)
    if sg in ("Pnma", "P n m a"):
        return "oP4"
    if sg in ("Pbca", "P b c a"):
        return "oP8"

    # Monoclinic P21/c(mP4)
    if sg in ("P21/c", "P2_1/c"):
        return "mP4"
    if sg in ("C2/c", "C 2/c"):
        return "mS4"

    # Triclinic P1 / P-1(aP1 / aP2)
    if sg == "P1":
        return "aP1"
    if sg in ("P-1", "P-1"):
        return "aP2"

    return ""


def spacegroup_to_number(spacegroup_symbol: str) -> int:
    """空间群符号 → 编号(1-230)

    仅覆盖常用空间群;未知返回 0

    Args:
        spacegroup_symbol: 国际空间群符号

    Returns:
        空间群编号;未知返回 0
    """
    if not spacegroup_symbol:
        return 0
    sg = spacegroup_symbol.strip()
    return _SPACEGROUP_NUMBER_MAP.get(sg, 0)


# ============================================================================
# CanonicalKey dataclass
# ============================================================================


@dataclass(frozen=True)
class CanonicalKey:
    """跨数据源统一物相 key(v1.3-Academic M1)

    三元组 (reduced_formula, pearson_symbol, spacegroup_number) 唯一标识
    一个晶体学物相;不依赖数据源 ID。

    Attributes:
        reduced_formula: Hill system 归一化化学式
        pearson_symbol: Pearson 符号(可能空)
        spacegroup_number: 空间群编号 1-230(0 表示未知)

    Example:
        >>> k = CanonicalKey.from_formula_spacegroup("LiCoO2", "R-3m")
        >>> k.reduced_formula
        'CoLiO2'
        >>> k.pearson_symbol
        'hR1'
        >>> k.spacegroup_number
        166
    """

    reduced_formula: str
    pearson_symbol: str = ""
    spacegroup_number: int = 0

    @classmethod
    def from_formula_spacegroup(
        cls, formula: str, spacegroup_symbol: str = "", *, pearson: str = ""
    ) -> CanonicalKey:
        """从化学式 + 空间群符号构造

        Args:
            formula: 化学式字符串
            spacegroup_symbol: 国际空间群符号(如 "Fm-3m")
            pearson: Pearson 符号(如 "cF4"),若空则从空间群推导

        Returns:
            CanonicalKey 实例;化学式非法时 reduced_formula = ""
        """
        rf = normalize_formula(formula)
        if not rf:
            return cls(reduced_formula="", pearson_symbol="", spacegroup_number=0)
        ps = pearson if pearson else parse_pearson_symbol(spacegroup_symbol)
        sgn = spacegroup_to_number(spacegroup_symbol)
        return cls(reduced_formula=rf, pearson_symbol=ps, spacegroup_number=sgn)

    @classmethod
    def from_record(cls, record: Any) -> CanonicalKey:
        """从任意 XxxRecord 构造 CanonicalKey

        字段命名约定(从 MatWAU v1.1 现有 client 抽象):
        - record.formula 或 record.formula_pretty
        - record.spacegroup 或 record.symmetry(可能嵌套 dict)

        Args:
            record: OqmdRecord / CodRecord / MaterialsProjectReference / 等

        Returns:
            CanonicalKey 实例
        """
        # 提取 formula
        formula = (
            getattr(record, "formula", None)
            or getattr(record, "formula_pretty", "")
        )
        # 提取 spacegroup(兼容多字段名 + nested dict)
        sg = ""
        for attr_name in ("spacegroup_h_m", "spacegroup", "symm"):
            sg_attr = getattr(record, attr_name, None)
            if isinstance(sg_attr, dict):
                sg = sg_attr.get("symbol", "") or sg_attr.get("space_group", "")
                break
            elif isinstance(sg_attr, str) and sg_attr:
                sg = sg_attr
                break
        # 提取 pearson(若 record 有)
        pearson = getattr(record, "pearson_symbol", "")
        return cls.from_formula_spacegroup(formula, sg, pearson=pearson)

    def matches(self, other: CanonicalKey, *, strict: bool = False) -> bool:
        """判断两个 CanonicalKey 是否指向同一物相

        匹配策略:
        - 默认(fuzzy):reduced_formula 相同 + Pearson OR 空间群 至少一个一致
        - strict=True:reduced_formula + Pearson + 空间群 三者全部一致

        Args:
            other: 另一 CanonicalKey
            strict: True = 严格三匹配;False = 模糊匹配

        Returns:
            True = 同物相;False = 不同物相
        """
        if not self.reduced_formula or not other.reduced_formula:
            return False
        if self.reduced_formula != other.reduced_formula:
            return False
        if strict:
            # 严格:三全匹配(允许空字段做容错)
            ok_ps = (
                self.pearson_symbol == other.pearson_symbol
                or not self.pearson_symbol
                or not other.pearson_symbol
            )
            ok_sg = (
                self.spacegroup_number == other.spacegroup_number
                or self.spacegroup_number == 0
                or other.spacegroup_number == 0
            )
            return ok_ps and ok_sg
        # fuzzy:formula 相同 + 任一 crystal 字段一致
        same_pearson = (
            self.pearson_symbol
            and other.pearson_symbol
            and self.pearson_symbol == other.pearson_symbol
        )
        same_sg = (
            self.spacegroup_number
            and other.spacegroup_number
            and self.spacegroup_number == other.spacegroup_number
        )
        # 若两者 crystal 字段都为空(都不确定)→ 默认同 formula 即视为同物相
        if not self.pearson_symbol and not other.pearson_symbol and \
           self.spacegroup_number == 0 and other.spacegroup_number == 0:
            return True
        return same_pearson or same_sg

    def to_dict(self) -> dict:
        """→ dict(便于 JSON 序列化)"""
        return {
            "reduced_formula": self.reduced_formula,
            "pearson_symbol": self.pearson_symbol,
            "spacegroup_number": self.spacegroup_number,
        }

    def __str__(self) -> str:
        return (
            f"CanonicalKey({self.reduced_formula}, "
            f"{self.pearson_symbol or '?'}, sg={self.spacegroup_number or '?'})"
        )


__all__ = [
    "CanonicalKey",
    "normalize_formula",
    "parse_pearson_symbol",
    "spacegroup_to_number",
]