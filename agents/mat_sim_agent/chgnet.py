"""chgnet.py — CHGNet MLIP(机器学习原子间势)模拟器 mock

Stage 1 / Phase 1:本机不需 GPU,用 mock 估算弛豫后能量
Stage 2(WAU v1.0.0 GA + 服务器 GPU 后)切真 CHGNet 模型

CHGNet 是 MatSim 的核心引擎(per 开发计划 §5.3):
- 输入:CIF 字符串 + 化学式
- 输出:弛豫后总能(eV/atom)+ 收敛标志 + 最大原子受力(eV/Å)

mock 行为:
- relaxed_energy ≈ 元素数 × 元素基线能 + 修正(±0.5 eV)
- relaxation_converged:约 85% 收敛(per doc §3.2)
- forces_max:0.001 - 0.5 eV/Å
- 3 档稳定性:stable(<-3.5) / metastable(-3.5~-2.5) / unstable(>-2.5)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class SimResult:
    """单候选的 MLIP 弛豫结果"""

    formula: str
    cif: str  # 原始 CIF(弛豫后 CIF 同输入,Stage 1 mock)
    relaxed_energy: float  # eV/atom
    forces_max: float  # eV/Å,最大原子受力
    relaxation_converged: bool  # 弛豫是否收敛
    stability: str  # stable / metastable / unstable
    confidence: float = 0.5  # 0-1


@dataclass
class SimConstraints:
    """mat-sim 任务约束(从用户 query 解析)"""

    formula: str = ""
    n_candidates: int = 1
    target_property: Optional[str] = None  # "energy_low" / "stable" / "band_gap"
    forbidden_elements: List[str] = field(default_factory=list)


# ============================================================================
# 元素基线能量表(Stage 1 mock,Stage 2 替换为真 DFT)
# ============================================================================
# 简化:每元素的"典型化合物形成能"基准(单位 eV/atom)
# 真实数据应该从 Materials Project 查,但 Stage 1 mock 用近似值

ELEMENT_BASELINE_EV = {
    "H": -0.5, "Li": -1.8, "Be": -1.5, "B": -1.0, "C": -0.5, "N": -0.3, "O": -2.5,
    "F": -1.0, "Na": -1.2, "Mg": -2.0, "Al": -2.5, "Si": -2.0, "P": -2.2, "S": -1.8,
    "Cl": -1.0, "K": -1.0, "Ca": -2.5, "Sc": -3.0, "Ti": -3.5, "V": -3.5, "Cr": -3.0,
    "Mn": -3.0, "Fe": -3.0, "Co": -3.0, "Ni": -3.0, "Cu": -2.5, "Zn": -2.0,
    "Ga": -2.0, "Ge": -2.5, "As": -2.0, "Se": -1.8, "Br": -1.0, "Rb": -1.0, "Sr": -3.0,
    "Y": -3.5, "Zr": -4.0, "Nb": -3.5, "Mo": -3.5, "Tc": -3.0, "Ru": -3.5,
    "Rh": -3.0, "Pd": -2.5, "Ag": -1.5, "Cd": -1.5, "In": -2.0, "Sn": -2.5,
    "Sb": -2.5, "Te": -2.0, "I": -1.0, "Cs": -1.0, "Ba": -3.0, "La": -4.0,
    "Ce": -4.0, "Pr": -4.0, "Nd": -4.0, "Sm": -4.0, "Eu": -3.5, "Gd": -4.0,
    "Tb": -4.0, "Dy": -4.0, "Ho": -4.0, "Er": -4.0, "Tm": -4.0, "Yb": -3.5,
    "Lu": -4.0, "Hf": -4.5, "Ta": -4.0, "W": -4.5, "Re": -3.5, "Os": -4.0,
    "Ir": -3.5, "Pt": -3.5, "Au": -2.0, "Hg": -1.0, "Tl": -2.0, "Pb": -2.5,
    "Bi": -2.5, "Po": -1.5, "At": -1.0,
}


# ============================================================================
# 解析化学式元素
# ============================================================================


def _extract_elements(formula: str) -> List[str]:
    """从化学式提取元素列表(去重,保序)

    例:'LiFePO4' → ['Li', 'Fe', 'P', 'O']
       'Na2Cl2' → ['Na', 'Cl']
    """
    # 匹配元素符号(大写字母开头,后跟 0+ 小写)
    tokens = re.findall(r"([A-Z][a-z]?)", formula)
    seen = set()
    elements = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            elements.append(tok)
    return elements


# ============================================================================
# CHGNet mock 核心
# ============================================================================


def _estimate_relaxed_energy(formula: str, seed: int) -> float:
    """估算弛豫后总能(eV/atom)

    逻辑:
    1. 取所有元素的基线能
    2. 加 ±0.5 eV/atom 的随机修正(模拟 CHGNet 真实弛豫)
    3. 加 1-2 个原子间相互作用修正(Stage 1 简单近似)

    Stage 2 替换:真 CHGNet 推理 → 输出真实 DFT 总能
    """
    rng = random.Random(seed + hash(formula))
    elements = _extract_elements(formula)

    if not elements:
        return -1.0  # fallback

    # 元素平均基线能
    base_energies = [ELEMENT_BASELINE_EV.get(e, -2.0) for e in elements]
    avg_base = sum(base_energies) / len(base_energies)

    # 随机修正(±0.5)
    noise = rng.uniform(-0.5, 0.5)

    # 原子对相互作用修正(简化为 ±0.3)
    pair_correction = rng.uniform(-0.3, 0.3)

    return round(avg_base + noise + pair_correction, 3)


def _forces_max(seed: int) -> float:
    """估算最大原子受力(eV/Å)

    Stage 1 mock:用偏分布,约 80% < 0.05 eV/Å(收敛)
    - 80% 概率:0.001 - 0.045(收敛,forces < 0.05)
    - 20% 概率:0.05 - 0.5(不收敛,真实模拟失败的样本)

    Stage 2:真 CHGNet 推理 → 输出精确受力
    """
    rng = random.Random(seed * 7 + 13)
    if rng.random() < 0.8:
        # 收敛:受力小
        return round(rng.uniform(0.001, 0.045), 4)
    else:
        # 不收敛:受力大(模拟失败的样本)
        return round(rng.uniform(0.05, 0.5), 4)


def _relaxation_converged(forces_max: float, threshold: float = 0.05) -> bool:
    """是否收敛(forces_max < threshold)"""
    return forces_max < threshold


def _classify_stability(energy: float) -> str:
    """3 档稳定性分类

    stable: relaxed_energy < -3.5 eV/atom(典型稳定结构)
    metastable: -3.5 <= energy < -2.5(亚稳)
    unstable: energy >= -2.5(可能不稳定)
    """
    if energy < -3.5:
        return "stable"
    if energy < -2.5:
        return "metastable"
    return "unstable"


def _estimate_confidence(stability: str, converged: bool) -> float:
    """置信度:stable + converged > metastable + converged > unstable

    Stage 1:基于稳定性 + 收敛标志打分
    Stage 2:接真 CHGNet 输出的 uncertainty
    """
    base = {
        "stable": 0.9,
        "metastable": 0.6,
        "unstable": 0.3,
    }[stability]
    if not converged:
        base *= 0.7  # 不收敛扣 30%
    return round(base, 2)


def relax(
    cif: str,
    formula: str,
    seed: int = 0,
) -> SimResult:
    """CHGNet mock:对 1 个 CIF 跑弛豫

    Args:
        cif: CIF 字符串
        formula: 化学式
        seed: 随机种子(可重现)

    Returns:
        SimResult
    """
    energy = _estimate_relaxed_energy(formula, seed)
    forces = _forces_max(seed)
    converged = _relaxation_converged(forces)
    stability = _classify_stability(energy)
    confidence = _estimate_confidence(stability, converged)

    return SimResult(
        formula=formula,
        cif=cif,
        relaxed_energy=energy,
        forces_max=forces,
        relaxation_converged=converged,
        stability=stability,
        confidence=confidence,
    )


def relax_batch(
    candidates: List,
    seed_base: int = 0,
) -> List[SimResult]:
    """批量弛豫

    Args:
        candidates: List[GenCandidate](mat-gen 输出)或 dict 列表
        seed_base: 起始种子

    Returns:
        List[SimResult](按 relaxed_energy 升序)
    """
    results = []
    for i, cand in enumerate(candidates):
        # 兼容 dataclass 和 dict
        if hasattr(cand, "cif"):
            cif = cand.cif
            formula = cand.formula
        elif isinstance(cand, dict):
            cif = cand.get("cif", f"data_{cand.get('formula', 'X')}")
            formula = cand.get("formula", "X")
        else:
            cif = f"data_X{i}"
            formula = f"X{i}"

        result = relax(cif=cif, formula=formula, seed=seed_base + i)
        results.append(result)

    # 按能量升序排序(最稳定在前)
    results.sort(key=lambda r: r.relaxed_energy)
    return results


def parse_constraints(user_message: str) -> SimConstraints:
    """从用户消息解析约束(Stage 1 规则解析)

    Stage 2:走 wau-python-sdk 调 LLM
    """
    msg = user_message.lower()

    # 提取公式(简化:取第一个看起来像公式的 token)
    formula_match = re.search(r"\b([A-Z][a-z]?\d*[A-Z][a-z]?\d*)\b", user_message)
    formula = formula_match.group(1) if formula_match else ""

    # 目标属性
    target_prop = None
    if "稳定" in user_message or "stabl" in msg:
        target_prop = "stable"
    elif "能带" in user_message or "band" in msg:
        target_prop = "band_gap"
    elif "能量低" in user_message or "low energy" in msg:
        target_prop = "energy_low"

    # 禁止元素
    forbidden = []
    if "无钴" in user_message or "no co" in msg:
        forbidden.append("Co")
    if "无贵金属" in user_message:
        forbidden.extend(["Pt", "Au", "Ag"])

    return SimConstraints(
        formula=formula,
        target_property=target_prop,
        forbidden_elements=forbidden,
    )


def stats(results: List[SimResult]) -> Dict[str, int]:
    """统计弛豫结果"""
    stats_dict = {
        "total": len(results),
        "converged": sum(1 for r in results if r.relaxation_converged),
        "stable": sum(1 for r in results if r.stability == "stable"),
        "metastable": sum(1 for r in results if r.stability == "metastable"),
        "unstable": sum(1 for r in results if r.stability == "unstable"),
    }
    return stats_dict


__all__ = [
    "SimResult",
    "SimConstraints",
    "relax",
    "relax_batch",
    "parse_constraints",
    "stats",
    "ELEMENT_BASELINE_EV",
]