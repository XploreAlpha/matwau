"""intent_classifier.py — 5 子类分类 + 3 skill 提取

Stage 1:关键词 + 规则匹配
Stage 2:接 LLM(per wau-python-sdk 的 WauClient)

per MatWAU-开发计划 §六 W9
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 数据结构
# ============================================================================


# 5 子类
SUBCLASSES = [
    "design_new_material",       # 设计新材料
    "optimize_existing",         # 优化现有配方
    "explain_failure",           # 解释失败(XRD 不对 / 合成失败 / ...)
    "literature_review",         # 文献综述
    "experiment_planning",       # 实验规划(默认走 4 段管线)
    # M3 NEW — 跨数据源 2 个子类
    "external_db_query",         # 单源查询(OQMD / COD / NOMAD / JARVIS 任选)
    "cross_source_validation",   # 多源交叉验证(4 个数据源对比)
]

# 9 个 material_system(per W7 demo + W6 exp categories)
MATERIAL_SYSTEMS = [
    "li_ion_cathode",            # 锂电池正极
    "li_ion_anode",              # 锂电池负极
    "solid_electrolyte",         # 固态电解质
    "catalyst_her",              # 析氢催化剂
    "catalyst_oer",              # 析氧催化剂
    "solar_cell",                # 太阳能电池
    "superconductor",            # 超导
    "thermoelectric",            # 热电
    "permanent_magnet",          # 永磁
    "semiconductor",             # 半导体
    "hydrogen_storage",          # 储氢
]

# 8 个目标属性
TARGET_PROPS = [
    "energy_density",            # 能量密度 Wh/kg
    "ionic_conductivity",        # 离子电导率 mS/cm
    "voltage",                   # 电压 V
    "capacity",                  # 容量 mAh/g
    "stability",                 # 稳定性
    "band_gap",                  # 带隙 eV
    "tc",                        # 超导转变温度 K
    "zt",                        # 热电优值
]


@dataclass
class MatIntent:
    """mat-intent 解析结果"""

    subclass: str                                           # 5 子类之一
    material_system: Optional[str] = None                   # 11 类之一
    target_props: List[str] = field(default_factory=list)   # 8 类属性列表
    elements: List[str] = field(default_factory=list)        # 必含元素
    forbidden: List[str] = field(default_factory=list)      # 禁止元素
    n_samples: int = 5                                      # 生成候选数
    confidence: float = 0.5                                 # 解析置信度
    downstream_agent: str = "mat-pipeline"                  # 默认走 4 段管线
    reasoning: str = ""                                     # 解析理由

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subclass": self.subclass,
            "material_system": self.material_system,
            "target_props": self.target_props,
            "elements": self.elements,
            "forbidden": self.forbidden,
            "n_samples": self.n_samples,
            "confidence": self.confidence,
            "downstream_agent": self.downstream_agent,
            "reasoning": self.reasoning,
        }


# ============================================================================
# 子类分类器
# ============================================================================


# 子类关键词映射
SUBCLASS_PATTERNS = {
    "experiment_planning": [
        r"实验方案", r"实验计划", r"实验设计", r"怎么合成", r"怎么制备",
        r"experimental protocol", r"experiment design", r"recipe",
        r"出.*方案", r"做.*实验",
    ],
    "design_new_material": [
        r"设计新", r"寻找新", r"新型", r"新晶体", r"新材料",
        r"design new", r"find new", r"novel material", r"new crystal",
        r"找.*材料", r"探索.*材料",
    ],
    "optimize_existing": [
        r"优化", r"改进", r"改良", r"提升性能", r"提高.*能量密度",
        r"optimize", r"improve", r"enhance",
        r"改性", r"掺杂", r"doping",
    ],
    "explain_failure": [
        r"为什么.*失败", r"为什么.*不对", r"解释.*失败", r"诊断",
        r"why.*fail", r"explain.*fail", r"diagnose",
        r"XRD.*不对", r"烧结.*失败", r"合成.*失败",
    ],
    "literature_review": [
        r"文献", r"综述", r"最新进展", r"研究现状", r"调研",
        r"literature", r"review", r"survey", r"recent progress",
        r"相关工作", r"related work",
    ],
    # M3 NEW — 跨数据源子类
    "external_db_query": [
        r"查.*OQMD", r"查.*COD", r"查.*NOMAD", r"查.*JARVIS",
        r"OQMD.*查询", r"COD.*查询", r"NOMAD.*查询", r"JARVIS.*查询",
        r"数据库.*查", r"external.*db", r"data.*platform",
        r"已知结构.*查", r"查.*已知结构",
    ],
    "cross_source_validation": [
        r"跨.*数据源", r"跨源", r"4.*库", r"四.*库",
        r"交叉验证", r"多源.*对比", r"cross.*source", r"multi.*source",
        r"OQMD.*COD.*NOMAD.*JARVIS", r"对比.*OQMD.*COD",
        r"形成焓.*对比", r"形成能.*对比", r"带隙.*对比",
    ],
}


def classify_subclass(user_intent: str) -> Tuple[str, float, str]:
    """分类 5 子类

    Returns:
        (subclass, confidence, reasoning)
    """
    msg = user_intent
    scores: Dict[str, int] = {}
    matched_patterns: Dict[str, List[str]] = {}

    for subclass, patterns in SUBCLASS_PATTERNS.items():
        hits = []
        for p in patterns:
            if re.search(p, msg, re.IGNORECASE):
                hits.append(p)
        if hits:
            scores[subclass] = len(hits)
            matched_patterns[subclass] = hits

    if not scores:
        # fallback:experiment_planning(默认走 4 段管线)
        return ("experiment_planning", 0.5, "无明确子类,默认走 experiment_planning")

    # 选最高分
    best = max(scores.items(), key=lambda x: x[1])
    subclass = best[0]
    n_hits = best[1]

    # confidence: 1 命中 → 0.7, 2 命中 → 0.85, 3+ → 0.95
    if n_hits >= 3:
        confidence = 0.95
    elif n_hits == 2:
        confidence = 0.85
    else:
        confidence = 0.7

    reasoning = f"匹配关键词: {matched_patterns[subclass]}"
    return (subclass, confidence, reasoning)


# ============================================================================
# Material System 识别
# ============================================================================


MATERIAL_SYSTEM_PATTERNS = {
    "li_ion_cathode": [
        r"锂电.*正极", r"锂电池正极", r"cathode", r"LiCoO2", r"LFP", r"NMC",
        r"锂离子.*正极", r"正极材料",
    ],
    "li_ion_anode": [
        r"锂电.*负极", r"锂电池负极", r"anode", r"负极材料", r"石墨.*负极",
        r"Li4Ti5O12",
    ],
    "solid_electrolyte": [
        r"固态电解质", r"solid electrolyte", r"LLZO", r"LGPS", r"LATP",
        r"硫化物.*电解质", r"氧化物.*电解质",
    ],
    "catalyst_her": [
        r"析氢", r"HER", r"hydrogen evolution", r"氢气产生",
    ],
    "catalyst_oer": [
        r"析氧", r"OER", r"oxygen evolution", r"氧气产生",
    ],
    "solar_cell": [
        r"太阳能", r"solar cell", r"钙钛矿", r"perovskite", r"光伏",
        r"CsPbI3",
    ],
    "superconductor": [
        r"超导", r"superconductor", r"YBCO", r"高温超导",
    ],
    "thermoelectric": [
        r"热电", r"thermoelectric", r"Bi2Te3", r"塞贝克",
    ],
    "permanent_magnet": [
        r"永磁", r"permanent magnet", r"Nd2Fe14B", r"钕铁硼",
    ],
    "semiconductor": [
        r"半导体", r"semiconductor", r"GaN", r"SiC", r"宽禁带",
    ],
    "hydrogen_storage": [
        r"储氢", r"hydrogen storage", r"MgH2", r"LaNi5",
    ],
}


def identify_material_system(user_intent: str) -> Optional[str]:
    """识别 material_system(11 类)"""
    for system, patterns in MATERIAL_SYSTEM_PATTERNS.items():
        for p in patterns:
            if re.search(p, user_intent, re.IGNORECASE):
                return system
    return None


# ============================================================================
# Target Props 识别
# ============================================================================


TARGET_PROP_PATTERNS = {
    "energy_density": [
        r"能量密度", r"energy density", r"Wh/kg", r"Wh·kg",
    ],
    "ionic_conductivity": [
        r"电导率", r"conductivity", r"mS/cm",
    ],
    "voltage": [
        r"电压", r"voltage",
    ],
    "capacity": [
        r"容量", r"capacity", r"mAh/g",
    ],
    "stability": [
        r"稳定", r"stability", r"循环寿命", r"cycle life",
    ],
    "band_gap": [
        r"带隙", r"band gap", r"禁带宽度",
    ],
    "tc": [
        r"超导转变温度", r"Tc", r"临界温度",
    ],
    "zt": [
        r"ZT", r"热电优值",
    ],
}


def identify_target_props(user_intent: str) -> List[str]:
    """识别 target_props(8 类,可多个)"""
    props = []
    for prop, patterns in TARGET_PROP_PATTERNS.items():
        for p in patterns:
            if re.search(p, user_intent, re.IGNORECASE):
                if prop not in props:
                    props.append(prop)
                break
    return props


# ============================================================================
# Constraints 提取(elements / forbidden)
# ============================================================================


# 元素池(per W8 element_pool,2 字符先匹配)
ELEMENT_POOL_2CHAR = [
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
ELEMENT_POOL_1CHAR = ["O", "N", "C", "H", "B", "F", "P", "S", "K", "V", "Y", "I", "W", "U"]
ELEMENT_POOL = sorted(ELEMENT_POOL_2CHAR + ELEMENT_POOL_1CHAR, key=lambda x: (-len(x), x))


def extract_elements(user_intent: str) -> List[str]:
    """提取必含元素(单字符避子串 + 排除单位/英文单词)"""
    elements = []

    # 单位上下文排除(避免 "Wh/kg" 抽 "W", "kWh" 抽 "W" 等)
    cleaned = re.sub(r"\d+\s*(Wh/kg|Wh·kg|Wh/g|mAh/g|kWh|GWh|eV|MPa|℃|nm|μm|Å|cm2|cm³|s/cm|mS/cm)", "", user_intent)
    # 移除 "X 的" 等助词
    cleaned = re.sub(r"的", "", cleaned)

    # 移除常见的英文动作词(避免 "Review" 抽 "Re" / "In" 抽 "In" 等)
    action_words = [
        "Review", "review", "Show", "show", "Find", "find", "Look", "look",
        "Optimize", "optimize", "Search", "search", "Browse", "browse",
        "Help", "help", "Tell", "tell", "Explain", "explain", "Describe",
        "Compare", "compare", "Summarize", "summarize", "List", "list",
        "Please", "please", "About", "about", "Latest", "latest", "Recent",
        "Current", "current", "Status", "status", "Check", "check",
    ]
    for word in action_words:
        cleaned = cleaned.replace(word, "")

    for elem in ELEMENT_POOL:
        if elem not in cleaned:
            continue
        if len(elem) == 1:
            covered = any(len(e2) >= 2 and elem in e2 for e2 in elements)
            if covered:
                continue
        elements.append(elem)
    return elements


def extract_forbidden(user_intent: str) -> List[str]:
    """提取禁止元素(per "无 X" / "no X" / "禁止 X" 模式)"""
    forbidden = []

    # 显式 "禁止: X、Y、Z" / "forbidden: X, Y, Z"
    m_forbid = re.search(
        r"(?:禁止|不含|排除|forbidden)[:：]\s*([^\s,，、。;；]+(?:[、,，;；\s]+[^\s,，、。;；]+)*)",
        user_intent,
    )
    if m_forbid:
        seg = m_forbid.group(1)
        for tok in re.split(r"[、,，;；\s]+", seg):
            tok = tok.strip()
            if tok and tok in ELEMENT_POOL and tok not in forbidden:
                forbidden.append(tok)

    # 关键词
    if re.search(r"无钴|不含钴|无\s*Co|no co|no cobalt|without co", user_intent, re.IGNORECASE):
        if "Co" not in forbidden:
            forbidden.append("Co")
    if re.search(r"无贵金属|no pt|no precious|no noble|without pt|without au", user_intent, re.IGNORECASE):
        for e in ["Pt", "Au", "Ag"]:
            if e not in forbidden:
                forbidden.append(e)
    if re.search(r"无\s*Ni|no nickel|without ni", user_intent, re.IGNORECASE):
        if "Ni" not in forbidden:
            forbidden.append("Ni")

    return forbidden


def extract_n_samples(user_intent: str) -> int:
    """提取生成候选数(默认 5)"""
    m = re.search(r"(\d+)\s*个", user_intent)
    if m:
        n = int(m.group(1))
        return min(max(n, 1), 50)  # 限制 1-50
    return 5


# ============================================================================
# 统一入口
# ============================================================================


def parse_mat_intent(user_intent: str) -> MatIntent:
    """从用户 1 句话解析出 MatIntent(Stage 1 规则版)

    Args:
        user_intent: 用户自然语言意图(中英文都支持)

    Returns:
        MatIntent(子类 + material_system + target_props + constraints + confidence)
    """
    # 1. 子类分类
    subclass, conf_subclass, reason_subclass = classify_subclass(user_intent)

    # 2. material_system
    material_system = identify_material_system(user_intent)

    # 3. target_props
    target_props = identify_target_props(user_intent)

    # 4. constraints
    elements = extract_elements(user_intent)
    forbidden = extract_forbidden(user_intent)
    n_samples = extract_n_samples(user_intent)

    # 5. confidence 聚合
    #    - 有 material_system: +0.1
    #    - 有 target_props: +0.05
    #    - 有 elements: +0.05
    #    - 有 forbidden: +0.05
    bonus = 0.0
    if material_system:
        bonus += 0.1
    if target_props:
        bonus += 0.05
    if elements:
        bonus += 0.05
    if forbidden:
        bonus += 0.05
    confidence = min(conf_subclass + bonus, 0.99)

    # 6. reasoning
    reasoning = (
        f"subclass={subclass}({conf_subclass:.2f} | {reason_subclass}) | "
        f"system={material_system} | "
        f"props={target_props} | "
        f"elements={elements} | "
        f"forbidden={forbidden} | "
        f"n_samples={n_samples}"
    )

    return MatIntent(
        subclass=subclass,
        material_system=material_system,
        target_props=target_props,
        elements=elements,
        forbidden=forbidden,
        n_samples=n_samples,
        confidence=confidence,
        reasoning=reasoning,
    )


__all__ = [
    "SUBCLASSES",
    "MATERIAL_SYSTEMS",
    "TARGET_PROPS",
    "MatIntent",
    "classify_subclass",
    "identify_material_system",
    "identify_target_props",
    "extract_elements",
    "extract_forbidden",
    "extract_n_samples",
    "parse_mat_intent",
]