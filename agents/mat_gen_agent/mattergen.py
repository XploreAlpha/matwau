"""mattergen.py — MatterGen 扩散模型 mock(per 开发计划 §5.2)

Stage 1 / Phase 1 用 mock 生成 CIF(本机不需 GPU)。
Stage 2(WAU v1.0.0 GA + 服务器有 GPU 后)切真 MatterGen 模型。

mock 行为:
- 接受 elements 约束 + property_target + n_samples
- 生成 n_samples 个假 CIF 字符串
- 每个 CIF 含要求元素
"""

from __future__ import annotations

import functools
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenConstraints:
    """mat-gen 生成约束(per 用户 query)"""

    elements: list[str] = field(default_factory=list)
    n_samples: int = 10
    target_property: str | None = None  # "ionic_conductivity" / "energy_density" / None
    forbidden_elements: list[str] = field(default_factory=list)
    user_message: str = ""  # 2026-08-05 bug fix:用于 seed 唯一性,避免不同 query 返同样占位


@dataclass
class GenCandidate:
    """1 个候选结构"""

    cif: str  # CIF 字符串
    formula: str  # 化学式
    estimated_energy: float = 0.0  # eV/atom(mllp 估算)
    confidence: float = 0.0  # 0-1


def parse_constraints(user_message: str, context: dict[str, Any] | None = None) -> GenConstraints:
    """从用户消息解析约束(LLM 调用,Stage 1 用规则解析)

    Stage 1 简版:关键词匹配
    Stage 2 升级:走 wau-python-sdk 调 LLM
    """
    msg = user_message.lower()

    # 元素提取(双字符元素先匹配,避免 "Bi" 拆成 "B"+"i" / "Te" 拆成 "T"+"e")
    elements = []
    # 长度降序(2 字符先匹配)
    element_pool_2char = [
        "Li", "Na", "Mg", "Al", "Si", "Cl", "Ca", "Sc", "Ti", "Cr",
        "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se",
        "Br", "Kr", "Rb", "Sr", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh",
        "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs",
        "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
        "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re",
        "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At",
        "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am",
        "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db",
        "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc",
        "Lv", "Ts", "Og",
    ]
    element_pool_1char = ["O", "N", "C", "H", "B", "F", "P", "S", "K", "V", "Y", "I", "W", "U"]
    # 合并 + 排序(2 字符先)
    element_pool = sorted(element_pool_2char + element_pool_1char, key=lambda x: (-len(x), x))

    for elem in element_pool:
        # 大小写敏感(化学式)
        if elem not in user_message:
            continue
        # 单字符元素不能是多字符元素的子串("Bi" 含 "B" 但用户要 Bi 不要 B)
        if len(elem) == 1:
            # 检查是否被任何 2 字符元素覆盖
            covered = False
            for e2 in elements:
                if len(e2) >= 2 and elem in e2:
                    covered = True
                    break
            if covered:
                continue
        elements.append(elem)

    # 数量推断
    n_samples = 10
    if "10" in user_message:
        n_samples = 10
    elif "20" in user_message:
        n_samples = 20
    elif "50" in user_message:
        n_samples = 50

    # 目标属性
    target_prop = None
    if "电导率" in user_message or "ionic" in msg or "conduct" in msg:
        target_prop = "ionic_conductivity"
    elif "能量密度" in user_message or "energy" in msg:
        target_prop = "energy_density"
    elif "稳定" in user_message or "stabl" in msg:
        target_prop = "stability"

    # 禁止元素(per query 关键词)
    forbidden = []
    if "无钴" in user_message or "不含钴" in user_message or "无 Co" in user_message or "无Co" in user_message or "no co" in msg or "no cobalt" in msg or "without co" in msg:
        forbidden.append("Co")
    if "无贵金属" in user_message or "无 Pt" in user_message or "no pt" in msg or "no precious" in msg or "without pt" in msg:
        forbidden.extend(["Pt", "Au", "Ag"])
    if "无 Ni" in user_message or "no ni" in msg or "no nickel" in msg or "without ni" in msg:
        forbidden.append("Ni")

    # 显式禁止列表(per "禁止: X、Y、Z" 格式)
    # per matwau.pipeline 拼装 message 的约定:"禁止: Pt、Au、Ag"
    import re as _re

    m_forbid = _re.search(r"禁止[:：]\s*([^\s,，、。;；]+(?:[、,，;；\s]+[^\s,，、。;；]+)*)", user_message)
    if m_forbid:
        seg = m_forbid.group(1)
        for tok in _re.split(r"[、,，;；\s]+", seg):
            tok = tok.strip()
            if tok and tok in element_pool and tok not in forbidden:
                forbidden.append(tok)

    # 强制必含元素(must_contain_all)
    must_all = []
    if "LFP" in user_message or "磷酸铁锂" in user_message:
        must_all = ["Li", "Fe", "P", "O"]
    if "LLZO" in user_message or "锂镧锆氧" in user_message:
        must_all = ["Li", "La", "Zr", "O"]

    # 合并 must_all 到 elements(确保生成)
    elements = list(set(elements + must_all))
    # 排除 forbidden 元素(per MatWAU pipeline 拼装约定:message 含 forbidden 元素名)
    if forbidden:
        elements = [e for e in elements if e not in forbidden]
    if not elements:
        elements = ["Li", "O"]  # 默认

    return GenConstraints(
        elements=elements,
        n_samples=n_samples,
        target_property=target_prop,
        forbidden_elements=forbidden,
        user_message=user_message,  # 2026-08-05 bug fix
    )


@functools.lru_cache(maxsize=1024)
def _build_formula(elements_tuple: tuple, seed: int) -> str:
    """构造 1 个假化学式(满足 elements + 随机)

    per W8 性能优化:同 (elements, seed) 必产同 formula,用 LRU 缓存避免重复计算
    注:用 tuple 替代 list 以便 hashable
    """
    rng = random.Random(seed)
    counts = []
    for e in elements_tuple:
        c = rng.randint(1, 4)
        counts.append(f"{e}{c}" if c > 1 else e)
    # 加 1-2 个辅助元素
    extras = ["O", "N", "C", "H", "S"]
    for _ in range(rng.randint(0, 2)):
        ex = rng.choice(extras)
        if ex not in elements_tuple:
            c = rng.randint(1, 3)
            counts.append(f"{ex}{c}" if c > 1 else ex)
    return "".join(counts)


def _build_formula_unpacked(elements: list[str], seed: int) -> str:
    """对外接口(自动转 tuple 给 lru_cache)"""
    return _build_formula(tuple(elements), seed)


def _estimate_energy(formula: str, seed: int) -> float:
    """估算形成能(Stage 1 mock,Stage 2 接 CHGNet / MatterSim)"""
    rng = random.Random(seed + hash(formula))
    # 真实形成能大多在 -5 到 0 eV/atom
    return round(rng.uniform(-5.0, -0.5), 3)


def _estimate_confidence(energy: float) -> float:
    """置信度:形成能越负 → 越稳定 → 置信度越高"""
    if energy < -3.0:
        return 0.9
    if energy < -2.0:
        return 0.7
    if energy < -1.0:
        return 0.5
    return 0.3


def generate(constraints: GenConstraints) -> list[GenCandidate]:
    """MatterGen 模拟生成(per dev plan §5.2)

    2026-08-05 bug fix: seed_base 现在同时考虑 user_message,
    避免不同 query(尤其 elements=[] 时)返同样占位(Li2O3/O3LiCo)。
    """
    candidates: list[GenCandidate] = []
    used_formulas = set()
    # 2026-08-05 bug fix: 加 user_message 进 seed,让 query 不同 → formula 不同
    seed_base = (
        hash(tuple(sorted(constraints.elements)))
        + hash(tuple(sorted(constraints.forbidden_elements))) * 7
        + hash(constraints.user_message or "") * 13
    )

    for i in range(constraints.n_samples):
        seed = seed_base + i
        formula = _build_formula_unpacked(constraints.elements, seed)

        # 跳过重复 + 包含禁止元素
        if formula in used_formulas:
            continue
        if any(f in formula for f in constraints.forbidden_elements):
            continue

        used_formulas.add(formula)
        energy = _estimate_energy(formula, seed)
        confidence = _estimate_confidence(energy)

        # 假 CIF 字符串(满足语法但不代表真实结构)
        cif = (
            f"data_{formula}\n"
            f"_chemical_name_common '{formula}'\n"
            f"_cell_length_a 4.5\n"
            f"_cell_length_b 4.5\n"
            f"_cell_length_c 4.5\n"
            f"_cell_angle_alpha 90\n"
            f"_cell_angle_beta 90\n"
            f"_cell_angle_gamma 90\n"
            f"_space_group_name_H-M_alt 'P1'\n"
            f"loop_\n"
            f"_atom_site_label\n"
            f"_atom_site_fract_x\n"
            f"_atom_site_fract_y\n"
            f"_atom_site_fract_z\n"
        )
        # 加原子坐标
        rng = random.Random(seed)
        for j, sym in enumerate(formula):
            if sym.isalpha():
                cif += f"{sym}1 {rng.random():.4f} {rng.random():.4f} {rng.random():.4f}\n"

        candidates.append(
            GenCandidate(
                cif=cif,
                formula=formula,
                estimated_energy=energy,
                confidence=confidence,
            )
        )

    # 按形成能排序(最稳定的在前)
    candidates.sort(key=lambda c: c.estimated_energy)

    return candidates


__all__ = [
    "GenCandidate",
    "GenConstraints",
    "generate",
    "parse_constraints",
]