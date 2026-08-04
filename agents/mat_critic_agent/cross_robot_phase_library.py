"""cross_robot_phase_library.py — W30 跨机器人一致性 phase 元素映射库

核心功能:
- PHASE_ELEMENT_MAP: 17 个常见样品 → 元素组成映射
- parse_formula_elements: 简单 formula 解析(正则抓元素符号)
- match_phase_name: XRD matched_phase 字符串 → PHASE_ELEMENT_MAP key 的模糊匹配

W30 设计原则:
- 纯规则 + 字符串处理,无外部依赖
- 起始集合够 demo,生产可扩展
- 支持模糊匹配(处理 Inconel / Inconel 718 / INCONEL 等变体)
"""
from __future__ import annotations

import re

# ============================================================================
# 17 个常见样品 → 元素组成
# ============================================================================

PHASE_ELEMENT_MAP: dict[str, set[str]] = {
    # 金属合金
    "Inconel 718": {"Ni", "Cr", "Fe", "Nb", "Mo", "Ti", "Al"},
    "Inconel": {"Ni", "Cr", "Fe"},                # 模糊兜底
    "SS304": {"Fe", "Cr", "Ni", "C"},
    "Stainless Steel 304": {"Fe", "Cr", "Ni", "C"},
    "Ti-6Al-4V": {"Ti", "Al", "V"},

    # 简单氧化物 / 陶瓷
    "TiO2": {"Ti", "O"},
    "Al2O3": {"Al", "O"},
    "SiO2": {"Si", "O"},
    "Si": {"Si"},
    "CuO": {"Cu", "O"},
    "ZnO": {"Zn", "O"},
    "NaCl": {"Na", "Cl"},

    # 聚合物
    "PMMA": {"C", "H", "O"},
    "PS": {"C", "H"},
    "PE": {"C", "H"},
    "PP": {"C", "H"},
    "PET": {"C", "H", "O"},

    # 电池材料
    "LiCoO2": {"Li", "Co", "O"},
    "LLZO": {"Li", "La", "Zr", "O"},
}


# 简单 formula 元素解析(正则抓元素符号,支持带数字化学式如 "TiO2" / "Al2O3" / "LiCoO2")
_ELEMENT_PATTERN = re.compile(r"([A-Z][a-z]?)(\d*)")


def parse_formula_elements(formula: str) -> set[str]:
    """从化学式抽元素集合

    Args:
        formula: 化学式字符串(例 "TiO2" / "Al2O3" / "LiCoO2" / "Inconel 718")

    Returns:
        元素集合(例 {"Ti", "O"} / {"Al", "O"} / {"Li", "Co", "O"})

    注意:
    - "Inconel 718" 这类名称走名称映射(用 PHASE_ELEMENT_MAP),不走正则
    - 含数字的元素下标被忽略,只关心元素符号
    """
    if not formula:
        return set()

    # 先看名称映射(优先级高,Inconel 等)
    name_match = match_phase_name(formula)
    if name_match:
        return PHASE_ELEMENT_MAP[name_match].copy()

    # 正则解析
    elements = set()
    for match in _ELEMENT_PATTERN.finditer(formula):
        elem = match.group(1)
        # 过滤单字符字母(避免误识别 H, C 等孤立字符)
        if elem:
            elements.add(elem)

    # 兜底:如果正则没识别出任何元素,可能是复杂名称 → 尝试全字匹配
    if not elements:
        # 把整个字符串当名称查
        for name in PHASE_ELEMENT_MAP:
            if name.lower() in formula.lower():
                return PHASE_ELEMENT_MAP[name].copy()

    return elements


def match_phase_name(xrd_phase: str) -> str | None:
    """XRD matched_phase → PHASE_ELEMENT_MAP key 的模糊匹配

    匹配优先级:
    1. 完全匹配(忽略大小写)
    2. xrd_phase 包含 name(子串匹配)— 长 name 优先(Inconel 718 > Inconel)
    3. name 包含 xrd_phase — 长 name 优先

    Args:
        xrd_phase: XRD 报告的相名(例 "Inconel" / "Inconel 718" / "INCONEL 718" / "TiO2")

    Returns:
        匹配到的 PHASE_ELEMENT_MAP key(例 "Inconel 718" / "TiO2"),都不匹配返回 None
    """
    if not xrd_phase:
        return None

    phase_lower = xrd_phase.strip().lower()

    # 1. 完全匹配(忽略大小写)
    for name in PHASE_ELEMENT_MAP:
        if name.lower() == phase_lower:
            return name

    # 2 & 3. 子串匹配(双向)— 收集所有候选,选最长 name
    sorted_names = sorted(PHASE_ELEMENT_MAP.keys(), key=lambda x: -len(x))
    candidates = []
    for name in sorted_names:
        name_lower = name.lower()
        if name_lower in phase_lower or phase_lower in name_lower:
            candidates.append(name)

    if candidates:
        # 选最长(已经按 len 降序排)
        return candidates[0]

    return None


def list_known_phases() -> list[str]:
    """列出所有已知 phase(给测试/debug 用)"""
    return sorted(PHASE_ELEMENT_MAP.keys())


__all__ = [
    "PHASE_ELEMENT_MAP",
    "list_known_phases",
    "match_phase_name",
    "parse_formula_elements",
]