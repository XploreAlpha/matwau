"""xrd_sintering.py — XRD 理论谱 + 烧结参数推荐 mock

Stage 1 / Phase 1:本地 mock,不需要真 XRD 仪器
Stage 2(WAU v1.0.0 GA + 真实验设备后)切真仪器 + 反馈学习

XRD Bragg 方程(per 开发计划 §5.5):
- nλ = 2d sin(θ)
- λ = 1.5406 Å(Cu Kα,标准 XRD 波长)
- d = 晶面间距
- 2θ = 2 * arcsin(λ / 2d)

烧结参数经验数据库(per 行业标准):
- 锂电池正极:750-900℃ / 空气 / 12-24h
- 固态电解质:1000-1200℃ / 空气 / 24-48h
- 钙钛矿:500-700℃ / 空气 / 4-8h
- 催化剂:400-600℃ / 空气 / 2-6h
- 等
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class XRDPeak:
    """单条 XRD 衍射峰"""

    hkl: str  # Miller 指数,如 "(110)" / "(111)" / "(200)"
    two_theta: float  # 衍射角 2θ(度)
    intensity: float  # 相对强度 0-100


@dataclass
class XRDPattern:
    """XRD 衍射谱"""

    formula: str
    wavelength_angstrom: float  # Å,Cu Kα = 1.5406
    lattice_a: float  # Å,立方晶格常数
    peaks: List[XRDPeak] = field(default_factory=list)

    @property
    def top_3_2theta(self) -> List[float]:
        """主峰 top-3 的 2θ"""
        return [p.two_theta for p in self.peaks[:3]]

    @property
    def main_peak_hkl(self) -> str:
        """主峰 (hkl)"""
        return self.peaks[0].hkl if self.peaks else "(?)"


@dataclass
class SinteringRecipe:
    """烧结参数方案(实验 pre-flight)"""

    formula: str
    temperature_celsius: float  # ℃
    pressure_mpa: float  # MPa
    time_hours: float  # h
    atmosphere: str  # "air" / "N2" / "Ar" / "O2" / "vacuum" / "H2/N2"
    reference: str = ""  # 参考依据(LiCoO2 标准条件 / etc.)


@dataclass
class ExpRecipe:
    """1 个实验方案(XRD + 烧结合并)"""

    formula: str
    xrd: XRDPattern
    sintering: SinteringRecipe


# ============================================================================
# XRD 元素 → 晶格常数经验表(Stage 1 mock)
# ============================================================================
# 简化:按"主导元素"给典型晶格常数
# 真实应该从 Materials Project 查,Stage 2 升级

ELEMENT_LATTICE_A = {
    "LiCoO2": 4.20, "LiFePO4": 10.32, "LiMn2O4": 8.24, "LiNiO2": 4.72,
    "Li2MnO3": 4.92, "Li4Ti5O12": 8.36, "LiFeSO4F": 10.30, "Li2FeSiO4": 8.20,
    "Li7La3Zr2O12": 12.97, "Li3PS4": 10.20, "Li6PS5Cl": 10.20, "Li10GeP2S12": 10.20,
    "LiPON": 9.50, "Li3YCl6": 9.50, "Li3OCl": 3.85, "Li2ZrCl6": 10.40,
    "NaCl": 5.64, "MgO": 4.21, "MgH2": 4.50, "MoS2": 3.16, "Co3O4": 8.08,
    "NiFe": 2.87, "Cu2O": 4.27, "ZrO2": 5.07, "MnO2": 4.40,
    "CsPbI3": 6.29, "LaNi5": 5.01, "YBa2Cu3O7": 3.85, "Bi2Te3": 4.38,
    "Nd2Fe14B": 8.80, "SmCo5": 5.00, "GaN": 4.51, "SiC": 4.36,
    "Pt": 3.92, "Fe": 2.87, "Co": 3.55, "Ni": 3.52, "Cu": 3.61,
    "Au": 4.08, "Ag": 4.09, "Pd": 3.89,
    "NMC": 4.20, "LFP": 10.32, "LLZO": 12.97, "LGPS": 10.20,
    "Al": 4.05, "Si": 5.43, "Ge": 5.66, "Ti": 2.95, "V": 3.03,
    "Cr": 2.88, "Mn": 8.91, "Nb": 3.30, "Mo": 3.15, "Sn": 5.83,
    "La": 5.31, "Ce": 5.16, "Nd": 5.65, "Sm": 8.95, "W": 3.16,
    "Bi": 4.55, "Y": 5.05, "Ba": 5.02,
}


# 元素 → 烧结参数经验表
# 优先按"主导材料类别"匹配,Stage 2 接真实验数据库

SINTERING_TABLE = [
    # (关键词匹配列表, 温度, 压力, 时间, 气氛, 参考)
    (["LiCoO2", "LiNiO2", "LiMn", "NMC", "Li-rich"], 850, 10, 12, "air", "锂电池正极标准条件"),
    (["LiFePO4", "LFP", "LiFeSi", "LiFeSO"], 700, 8, 12, "Ar", "磷酸铁锂标准条件"),
    (["Li4Ti5O12"], 800, 5, 16, "air", "钛酸锂负极标准条件"),
    (["Li7La3Zr2O12", "LLZO"], 1100, 20, 24, "air", "LLZO 烧结(致密化)"),
    (["Li3PS4", "Li6PS5Cl", "Li10GeP2S12", "LGPS", "argyrodite"], 300, 5, 8, "Ar", "硫化物固态电解质(冷压)"),
    (["LiPON", "Li3YCl6", "Li2ZrCl6", "Li3OCl"], 400, 10, 12, "Ar", "卤化物 / 薄膜固态电解质"),
    (["Na3Zr2Si2PO12"], 1200, 30, 24, "air", "Na 超离子导体"),
    (["CsPbI3", "CH3NH3PbI3", "钙钛矿"], 550, 5, 4, "N2", "卤化物钙钛矿太阳能"),
    (["MgH2"], 350, 5, 12, "H2", "MgH2 储氢(脱氢 + 球磨)"),
    (["LaNi5"], 1100, 20, 12, "Ar", "LaNi5 储氢合金"),
    (["YBa2Cu3O7", "YBCO"], 950, 30, 24, "O2", "YBCO 超导(氧气氛退火)"),
    (["Bi2Te3"], 500, 20, 8, "Ar", "热电 Bi2Te3(SPS 烧结)"),
    (["Nd2Fe14B", "SmCo5"], 1100, 50, 4, "vacuum", "永磁合金"),
    (["GaN", "SiC"], 1500, 30, 12, "N2", "宽禁带半导体"),
    (["Pt"], 800, 5, 6, "air", "Pt 催化剂(煅烧)"),
    (["MoS2"], 800, 10, 6, "H2/N2", "MoS2 析氢"),
    (["Co3O4", "NiFe", "MnO2", "Cu2O", "ZrO2", "BiVO4"], 500, 5, 6, "air", "氧化物催化剂"),
    (["Fe-N-C", "单原子"], 900, 5, 4, "N2", "单原子催化剂(热解)"),
    (["Pt", "Au", "Ag", "贵金属"], 600, 5, 6, "air", "贵金属催化剂"),
]


# 通用烧结(没匹配时 fallback)
DEFAULT_SINTERING = SinteringRecipe(
    formula="",
    temperature_celsius=800,
    pressure_mpa=10,
    time_hours=12,
    atmosphere="air",
    reference="通用 fallback(未匹配类别)",
)


# ============================================================================
# 元素提取
# ============================================================================


def _extract_elements(formula: str) -> List[str]:
    """从化学式提取元素列表"""
    tokens = re.findall(r"([A-Z][a-z]?)", formula)
    seen = set()
    elements = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            elements.append(tok)
    return elements


def _count_atoms(formula: str) -> int:
    """估算原子数"""
    total = 0
    for match in re.finditer(r"([A-Z][a-z]?)(\d*)", formula):
        count_str = match.group(2)
        count = int(count_str) if count_str else 1
        total += count
    return total


# ============================================================================
# XRD Bragg 方程 mock
# ============================================================================


# 立方晶系常见 (hkl) 列表
COMMON_HKL = [
    (1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0), (2, 1, 1),
    (2, 2, 0), (3, 0, 0), (3, 1, 0), (3, 1, 1), (2, 2, 2), (3, 2, 0),
    (3, 2, 1), (4, 0, 0), (4, 1, 0), (3, 3, 0), (3, 3, 1), (4, 1, 1),
]


def _estimate_lattice_a(formula: str) -> float:
    """估算晶格常数 a(Å)

    优先查 ELEMENT_LATTICE_A,否则用经验 fallback:
    - 单质 → ~4.0 Å(典型 FCC / BCC)
    - 化合物 → 元素原子半径平均 × 1.5
    """
    if formula in ELEMENT_LATTICE_A:
        return ELEMENT_LATTICE_A[formula]

    # Fallback:元素原子半径平均(粗略)
    ATOMIC_RADIUS = {
        "Li": 1.52, "Na": 1.86, "Mg": 1.60, "Al": 1.43, "Si": 1.11, "P": 1.07,
        "S": 1.05, "K": 2.34, "Ca": 1.97, "Sc": 1.62, "Ti": 1.47, "V": 1.34,
        "Cr": 1.28, "Mn": 1.27, "Fe": 1.26, "Co": 1.25, "Ni": 1.24, "Cu": 1.28,
        "Zn": 1.34, "Ga": 1.22, "Ge": 1.23, "Y": 1.80, "Zr": 1.55, "Nb": 1.46,
        "Mo": 1.39, "Ag": 1.44, "Sn": 1.40, "Sb": 1.40, "La": 1.87, "Ce": 1.83,
        "Nd": 1.81, "Sm": 1.80, "W": 1.39, "Pt": 1.39, "Au": 1.44, "Pb": 1.75,
        "Bi": 1.55, "O": 0.66, "N": 0.71, "C": 0.77, "H": 0.53, "B": 0.84,
        "F": 0.71, "Cl": 0.99, "Br": 1.14, "I": 1.33, "Yb": 1.94,
    }

    elements = _extract_elements(formula)
    radii = [ATOMIC_RADIUS.get(e, 1.4) for e in elements]
    if not radii:
        return 4.0
    avg_radius = sum(radii) / len(radii)
    # 简化:晶格常数 ≈ 2 × 平均原子半径 × 缩放因子
    return round(2 * avg_radius * 1.5, 2)


def compute_bragg_2theta(
    lattice_a: float,
    h: int,
    k: int,
    l: int,
    wavelength: float = 1.5406,
) -> Optional[float]:
    """Bragg 方程:2θ = 2 * arcsin(λ / 2d)

    d = a / sqrt(h² + k² + l²)(立方晶系)

    Returns:
        2θ 度数;若 λ > 2d(无法衍射)→ None
    """
    h2k2l2 = h**2 + k**2 + l**2
    if h2k2l2 == 0:
        return None

    d = lattice_a / math.sqrt(h2k2l2)
    # 2d >= λ 才能衍射
    if 2 * d < wavelength:
        return None

    sin_theta = wavelength / (2 * d)
    if sin_theta > 1.0:
        return None

    theta_rad = math.asin(sin_theta)
    two_theta_deg = math.degrees(theta_rad) * 2

    return round(two_theta_deg, 2)


def _estimate_intensity(h: int, k: int, l: int, n_atoms: int) -> float:
    """估算 XRD 峰强度(Stage 1 mock)

    简化模型:
    - (hkl) 全偶或全奇 → 强(100)
    - 全偶 → 100
    - 全奇 → 90
    - 混合 → 60-80
    - 多重因子(h²+k²+l² 大)→ 强度降低
    """
    # 简化:用晶面族多重性
    multiplicity = (
        48 if (h != k and h != l and k != l) else  # (hkl) 全不同
        24 if (h == k and h != l) or (h == l and h != k) or (k == l and k != h) else  # (hhl)
        12 if (h == k and k == l) else  # (hhh)
        6 if (h == 0 and k == 0 and l != 0) or (k == 0 and l == 0 and h != 0) or (h == 0 and l == 0 and k != 0) else  # (00l)
        24 if (h == k and l == 0) or (h == l and k == 0) or (k == l and h == 0) else  # (hh0)
        8
    )

    # 强度因子
    if h % 2 == 0 and k % 2 == 0 and l % 2 == 0:
        base = 100  # 全偶最强
    elif h % 2 != 0 and k % 2 != 0 and l % 2 != 0:
        base = 85  # 全奇次强
    else:
        base = 50  # 混合弱

    # 多重性加权
    intensity = base * (multiplicity / 48) * 100

    # 原子数修正(复杂体系结构因子大)
    if n_atoms > 10:
        intensity *= 1.2

    return min(100.0, round(intensity, 1))


def generate_xrd_pattern(formula: str, cif: str = "") -> XRDPattern:
    """生成 XRD 理论谱(Stage 1 mock)

    1. 估算晶格常数 a
    2. 对常见 (hkl) 计算 2θ
    3. 估算 intensity
    4. 按 intensity 降序排序
    5. 保留 top-N(5-10)峰

    Args:
        formula: 化学式
        cif: CIF 字符串(Stage 1 mock 不解析)

    Returns:
        XRDPattern
    """
    lattice_a = _estimate_lattice_a(formula)
    n_atoms = _count_atoms(formula)
    wavelength = 1.5406  # Cu Kα

    peaks: List[XRDPeak] = []
    rng = random.Random(hash(formula))

    for (h, k, l) in COMMON_HKL:
        two_theta = compute_bragg_2theta(lattice_a, h, k, l, wavelength)
        if two_theta is None:
            continue

        # 过滤 2θ > 90°(per 标准 XRD 扫描范围 5-90°,高角度峰信噪比差)
        if two_theta > 90.0:
            continue

        # 强度(Stage 1 mock 加 ±10 噪声)
        intensity = _estimate_intensity(h, k, l, n_atoms)
        intensity = max(0.0, min(100.0, intensity + rng.uniform(-10, 10)))

        hkl_str = f"({h}{k}{l})"
        peaks.append(
            XRDPeak(hkl=hkl_str, two_theta=two_theta, intensity=round(intensity, 1))
        )

    # 按 intensity 降序
    peaks.sort(key=lambda p: p.intensity, reverse=True)

    # 保留 top-10
    peaks = peaks[:10]

    return XRDPattern(
        formula=formula,
        wavelength_angstrom=wavelength,
        lattice_a=lattice_a,
        peaks=peaks,
    )


# ============================================================================
# 烧结参数推荐(经验数据库)
# ============================================================================


def recommend_sintering(formula: str) -> SinteringRecipe:
    """根据 formula 推荐烧结参数(经验数据库)

    Args:
        formula: 化学式

    Returns:
        SinteringRecipe
    """
    # 关键词匹配
    for keywords, temp, pressure, time_h, atmosphere, reference in SINTERING_TABLE:
        for kw in keywords:
            if kw in formula:
                return SinteringRecipe(
                    formula=formula,
                    temperature_celsius=temp,
                    pressure_mpa=pressure,
                    time_hours=time_h,
                    atmosphere=atmosphere,
                    reference=reference,
                )

    # Fallback
    return SinteringRecipe(
        formula=formula,
        temperature_celsius=DEFAULT_SINTERING.temperature_celsius,
        pressure_mpa=DEFAULT_SINTERING.pressure_mpa,
        time_hours=DEFAULT_SINTERING.time_hours,
        atmosphere=DEFAULT_SINTERING.atmosphere,
        reference=DEFAULT_SINTERING.reference,
    )


# ============================================================================
# 批量生成实验方案
# ============================================================================


def generate_exp_recipes(
    candidates: List,
    seed_base: int = 0,
) -> List[ExpRecipe]:
    """批量生成实验方案

    Args:
        candidates: List[HPCJobResult] / List[SimCandidate] / List[GenCandidate] / List[dict]
        seed_base: 起始种子

    Returns:
        List[ExpRecipe]
    """
    recipes = []
    for i, cand in enumerate(candidates):
        # 兼容 dataclass 和 dict
        if hasattr(cand, "formula"):
            formula = cand.formula
            cif = getattr(cand, "cif", "")
        elif isinstance(cand, dict):
            formula = cand.get("formula", f"X{i}")
            cif = cand.get("cif", "")
        else:
            formula = f"X{i}"
            cif = ""

        # 生成 XRD
        xrd = generate_xrd_pattern(formula, cif)

        # 推荐烧结
        sintering = recommend_sintering(formula)

        recipes.append(
            ExpRecipe(formula=formula, xrd=xrd, sintering=sintering)
        )

    return recipes


def parse_constraints(user_message: str) -> Dict[str, Any]:
    """从用户消息解析约束(Stage 1 规则解析)

    Stage 2 升级:走 wau-python-sdk 调 LLM
    """
    msg = user_message.lower()

    # 提取公式
    formula_match = re.search(r"\b([A-Z][a-z]?\d*[A-Z][a-z]?\d*)\b", user_message)
    formula = formula_match.group(1) if formula_match else ""

    # 实验类型
    exp_type = "both"  # "xrd" / "sintering" / "both"
    if "XRD" in user_message or "xrd" in msg:
        exp_type = "xrd" if "烧结" not in user_message else "both"
    elif "烧结" in user_message or "sinter" in msg:
        exp_type = "sintering"

    return {
        "formula": formula,
        "exp_type": exp_type,
    }


__all__ = [
    "XRDPeak",
    "XRDPattern",
    "SinteringRecipe",
    "ExpRecipe",
    "generate_xrd_pattern",
    "recommend_sintering",
    "generate_exp_recipes",
    "parse_constraints",
    "ELEMENT_LATTICE_A",
    "SINTERING_TABLE",
]