"""lit_engine.py — mat-lit 的文献综述核心引擎

职责:
1. 从 user_intent 提取关键词(化学式 + 材料名 + 属性词)
2. 模拟 arXiv / Materials Project / ICSD / PubChem 4 个数据库查询(Stage 1 mock)
3. 算每篇文献的 relevance(0-1)
4. 生成文献综述结构:background + state_of_art + gaps + suggestions
5. 输出 LitReview(给 MatLitAgent)

Stage 1 / Phase 1:mock 数据 + 关键词 + 模板
Stage 2(WAU v1.0.0 GA 后):接 arXiv / Materials Project / OpenCitations 真 API
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class LitReference:
    """1 篇文献引用"""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 2024
    source: str = "arXiv"                # arXiv / Materials Project / ICSD / PubChem
    doi: str | None = None
    url: str | None = None
    abstract: str = ""
    relevance: float = 0.5               # 0-1 跟 query 的相关度
    impact: str = "medium"               # high / medium / low

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "source": self.source,
            "doi": self.doi,
            "url": self.url,
            "abstract": self.abstract[:200],
            "relevance": round(self.relevance, 3),
            "impact": self.impact,
        }


@dataclass
class LitReview:
    """完整文献综述输出"""

    query: str
    references: list[LitReference] = field(default_factory=list)
    background: str = ""                # 背景介绍
    state_of_art: str = ""              # 国内外现状
    gaps: list[str] = field(default_factory=list)        # 研究空白
    suggestions: list[str] = field(default_factory=list)  # 给用户的建议
    confidence: float = 0.7             # 综述质量分
    sources_queried: list[str] = field(default_factory=list)  # 用了哪些数据库
    is_real_query: bool = False         # v1.3.2-Academic bug fix: arxiv 真查状态透传(默认 False = 全部 mock)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "references": [r.to_dict() for r in self.references],
            "background": self.background,
            "state_of_art": self.state_of_art,
            "gaps": self.gaps,
            "suggestions": self.suggestions,
            "confidence": round(self.confidence, 3),
            "sources_queried": self.sources_queried,
            "is_real_query": self.is_real_query,
        }


# ============================================================================
# 关键词提取
# ============================================================================


# 元素池(per mat-gen 一致)— 用于识别化学式
ELEMENT_POOL = [
    "H", "Li", "Be", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "Cl",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Br", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd",
    "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W",
    "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
]

# 已知材料/化合物别名(LLZO / LFP / NMC 等)
# W15: 按 domain 分组,默认 inorganic_crystal
_MATERIAL_ALIASES_BY_DOMAIN: dict[str, dict[str, str]] = {
    "inorganic_crystal": {
        "LLZO": "Li7La3Zr2O12",
        "LFP": "LiFePO4",
        "NMC": "LiNiMnCoO2",
        "NMC811": "LiNi0.8Mn0.1Co0.1O2",
        "NMC622": "LiNi0.6Mn0.2Co0.2O2",
        "NMC111": "LiNi0.33Mn0.33Co0.33O2",
        "LCO": "LiCoO2",
        "LMO": "LiMn2O4",
        "NCA": "LiNiCoAlO2",
        "NASICON": "Na3Zr2Si2PO12",
        "LAGP": "Li1.5Al0.5Ge1.5P3O12",
        "LATP": "Li1.3Al0.3Ti1.7P3O12",
        "PZT": "PbZrTiO3",
        "PVDF": "Polyvinylidene fluoride",  # 兼跨 polymer
    },
    "polymer": {
        "PVDF": "Polyvinylidene fluoride",
        "PMMA": "Poly(methyl methacrylate)",
        "PDMS": "Polydimethylsiloxane",
        "PEEK": "Polyetheretherketone",
        "PI": "Polyimide",
        "PEG": "Polyethylene glycol",
        "PAN": "Polyacrylonitrile",
        "PE": "Polyethylene",
        "PP": "Polypropylene",
        "PS": "Polystyrene",
        "PVC": "Polyvinyl chloride",
        "PLA": "Polylactic acid",
        "PEDOT": "Poly(3,4-ethylenedioxythiophene)",
        "PEDOT:PSS": "PEDOT:poly(styrenesulfonate)",
        "PANI": "Polyaniline",
        "PPy": "Polypyrrole",
        "PVA": "Polyvinyl alcohol",
    },
    "nano": {
        # 量子点
        "CdSe": "Cadmium selenide quantum dot",
        "CdTe": "Cadmium telluride quantum dot",
        "PbS": "Lead sulfide quantum dot",
        "PbSe": "Lead selenide quantum dot",
        "ZnS": "Zinc sulfide quantum dot",
        "ZnSe": "Zinc selenide quantum dot",
        "InP": "Indium phosphide quantum dot",
        "InAs": "Indium arsenide quantum dot",
        "CsPbI3": "Cesium lead iodide perovskite QD",
        "CsPbBr3": "Cesium lead bromide perovskite QD",
        # 2D
        "graphene": "Single-layer graphene",
        "GO": "Graphene oxide",
        "rGO": "Reduced graphene oxide",
        "MoS2": "Molybdenum disulfide monolayer",
        "WS2": "Tungsten disulfide monolayer",
        "WSe2": "Tungsten diselenide monolayer",
        "MoSe2": "Molybdenum diselenide monolayer",
        "hBN": "Hexagonal boron nitride",
        "MXene": "Transition metal carbide/nitride",
        "Ti3C2": "Titanium carbide MXene",
        "BP": "Black phosphorus",
        # 纳米结构
        "CNT": "Carbon nanotube",
        "SWCNT": "Single-walled carbon nanotube",
        "MWCNT": "Multi-walled carbon nanotube",
        # 介孔 / MOF
        "MCM-41": "Mesoporous silica MCM-41",
        "SBA-15": "Mesoporous silica SBA-15",
        "ZIF-8": "Zeolitic imidazolate framework 8",
        "HKUST-1": "HKUST-1 MOF",
        "MOF": "Metal-organic framework",
    },
    "metal_alloy": {
        # W17: 金属 / 合金别名表
        # 镍基超合金
        "Inconel": "Inconel nickel-based superalloy",
        "Inconel 718": "Inconel 718 (Ni-Fe-Cr superalloy)",
        "Inconel 625": "Inconel 625 (Ni-Cr-Mo superalloy)",
        "Hastelloy": "Hastelloy nickel-molybdenum alloy",
        "Rene 65": "Rene 65 nickel superalloy",
        "CMSX": "CMSX single crystal superalloy",
        # 钛合金
        "Ti-6Al-4V": "Titanium Grade 5 alloy",
        "Ti-5553": "Ti-5Al-5V-5Mo-3Cr titanium alloy",
        # 高熵合金
        "HEA": "High-entropy alloy",
        "Cantor": "Cantor alloy (Co-Cr-Fe-Mn-Ni)",
        # 形状记忆合金
        "Nitinol": "Ni-Ti shape memory alloy",
        "NiTi": "Nickel-titanium alloy",
        # 不锈钢
        "304": "AISI 304 stainless steel",
        "316": "AISI 316 stainless steel",
        "316L": "AISI 316L stainless steel",
        "321": "AISI 321 stainless steel",
        "310": "AISI 310 stainless steel",
        "Hastelloy C": "Hastelloy C nickel alloy",
        # 铝合金
        "2024": "AA 2024 aluminum alloy",
        "7075": "AA 7075 aluminum alloy",
        "6061": "AA 6061 aluminum alloy",
        # 工具钢
        "M2": "M2 high-speed tool steel",
        "H13": "H13 hot-work tool steel",
        "D2": "D2 cold-work tool steel",
        # 非晶合金
        "Metglas": "Metglas metallic glass",
    },
}


def _get_aliases_for_domain(domain: str) -> dict[str, str]:
    """获取指定域的别名表(向后兼容:不传 domain → 用 inorganic_crystal)"""
    from agents.material_domain_router import DEFAULT_DOMAIN

    d = domain or DEFAULT_DOMAIN
    # 跨域合并:PVDF 在 polymer 和 inorganic_crystal 都出现
    aliases = dict(_MATERIAL_ALIASES_BY_DOMAIN.get(d, {}))
    if d != "inorganic_crystal":
        # 加上 inorganic_crystal 兜底(LLZO 等跨域常用)
        aliases.update(_MATERIAL_ALIASES_BY_DOMAIN.get("inorganic_crystal", {}))
    return aliases


# 向后兼容别名(W14 测试还在 import MATERIAL_ALIASES)
MATERIAL_ALIASES = _MATERIAL_ALIASES_BY_DOMAIN["inorganic_crystal"]

# 属性词(用于关键词)
PROPERTY_KEYWORDS = [
    "电导率", "ionic conductivity", "conductivity",
    "能量密度", "energy density",
    "稳定性", "stability", "stable",
    "容量", "capacity", "capacit",
    "电压", "voltage", "potential",
    "硬度", "hardness",
    "磁性", "magnetic", "ferromagnetic",
    "超导", "superconduct",
    "催化", "catalys", "catalyt",
    "介电", "dielectric",
    "压电", "piezoelectric",
    "热导", "thermal conduct",
    "光学", "optical", "photoluminesc",
    "带隙", "band gap", "bandgap",
    "形成能", "formation energy",
    "吸附", "adsorption", "absorb",
    "扩散", "diffusion", "diffus",
    "弹性", "elastic", "modulus",
    "抗拉", "tensile", "strength",
]

# 应用领域词
DOMAIN_KEYWORDS = [
    "锂电池", "lithium", "battery", "电池",
    "钠电池", "sodium",
    "燃料电池", "fuel cell",
    "太阳能", "solar", "photovolta",
    "催化剂", "catalyst",
    "存储", "storage",
    "传感器", "sensor",
    "陶瓷", "ceramic",
    "玻璃", "glass",
    "合金", "alloy",
    "半导体", "semiconductor",
    "超导体", "superconductor",
    "永磁", "permanent magnet",
    "电解质", "electrolyte",
    "电极", "electrode",
    "隔膜", "separator",
    "正极", "cathode",
    "负极", "anode",
]


@dataclass
class LitQuery:
    """从 user_intent 解析出的查询"""

    raw_query: str
    formulas: list[str] = field(default_factory=list)       # 化学式列表
    material_names: list[str] = field(default_factory=list) # 材料别名(LLZO 等)
    properties: list[str] = field(default_factory=list)     # 属性词
    domains: list[str] = field(default_factory=list)        # 应用领域
    keywords: list[str] = field(default_factory=list)        # 综合关键词
    domain: str = "inorganic_crystal"                        # W15: 材料域

    def has_match(self) -> bool:
        """是否有任何可查询的内容"""
        return bool(self.formulas or self.material_names or self.properties or self.domains)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "formulas": self.formulas,
            "material_names": self.material_names,
            "properties": self.properties,
            "domains": self.domains,
            "keywords": self.keywords,
            "domain": self.domain,
        }


def extract_formulas(text: str) -> list[str]:
    """从文本提取化学式(per 元素池)

    简化:找包含 1-2 个大写字母开头 + 数字的 token
    例:'LiCoO2' 'LiFePO4' 'Na2O'
    """
    # 1. 先提取"单词"(英文 token),用空格/中文/标点分隔
    # 2. 对每个 token 用化学式 regex 尝试匹配
    # 3. 验证含 ELEMENT_POOL 中的元素
    formulas = []

    # 拆分文本为 token(中英混合)
    tokens = re.split(r"[\s,，、。;；()（）\[\]【】]+", text)
    seen = set()

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        # 化学式 regex:大写字母开头,可跟小写 + 数字,重复 1+ 次
        # 例: LiCoO2 / LiFePO4 / NaCl / Al2O3
        matches = re.findall(r"[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+|[A-Z][a-z]?\d{2,}", token)
        for m in matches:
            if m in seen:
                continue
            # 验证:含 2+ ELEMENT_POOL 元素 OR 1 个元素 + 数字
            elems_found = 0
            for elem in ELEMENT_POOL:
                if elem in m:
                    elems_found += 1
            # 单元素如 "Li2" 算 1 个元素
            # 至少 1 个元素被识别
            if elems_found >= 1:
                formulas.append(m)
                seen.add(m)

    return formulas


def extract_material_aliases(text: str, *, domain: str | None = None) -> list[str]:
    """从文本提取材料别名(LLZO / LFP / NMC 等,W15: per domain 词库)

    Args:
        text: 用户文本
        domain: 材料域(None → 默认 inorganic_crystal)

    注:别名匹配大小写不敏感(regex IGNORECASE)
    """
    from agents.material_domain_router import DEFAULT_DOMAIN

    aliases_dict = _get_aliases_for_domain(domain or DEFAULT_DOMAIN)
    found = []
    for alias in aliases_dict:
        # 用 word boundary + IGNORECASE(避免大小写问题)
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", text, re.IGNORECASE):
            found.append(alias)
    return found


def extract_properties(text: str, *, domain: str | None = None) -> list[str]:
    """从文本提取属性关键词(W15: per domain 词库)"""
    from agents.material_domain_router import DEFAULT_DOMAIN, get_property_keywords

    props = get_property_keywords(domain or DEFAULT_DOMAIN)
    text_lower = text.lower()
    found = []
    for prop in props:
        if prop.lower() in text_lower:
            found.append(prop)
    return list(set(found))


def extract_domains(text: str, *, domain: str | None = None) -> list[str]:
    """从文本提取应用领域(W15: per domain 词库)"""
    from agents.material_domain_router import DEFAULT_DOMAIN, get_domain_keywords

    doms = get_domain_keywords(domain or DEFAULT_DOMAIN)
    text_lower = text.lower()
    found = []
    for dom in doms:
        if dom.lower() in text_lower:
            found.append(dom)
    return list(set(found))


def parse_lit_query(user_intent: str, *, domain: str | None = None) -> LitQuery:
    """从 user_intent 解析查询(W15: 支持 domain 参数)

    Args:
        user_intent: 用户原始意图
        domain: 材料域(None → 默认 inorganic_crystal,向后兼容 W14)
    """
    from agents.material_domain_router import DEFAULT_DOMAIN

    if domain is None or domain == "auto":
        domain = DEFAULT_DOMAIN  # 默认无机晶体

    formulas = extract_formulas(user_intent)
    materials = extract_material_aliases(user_intent, domain=domain)
    properties = extract_properties(user_intent, domain=domain)
    domains = extract_domains(user_intent, domain=domain)

    # 综合关键词
    keywords = list(set(
        formulas + materials + properties + domains
        + [k for k in re.findall(r"[一-鿿]+|[a-zA-Z]+", user_intent) if len(k) > 1]
    ))

    return LitQuery(
        raw_query=user_intent,
        formulas=formulas,
        material_names=materials,
        properties=properties,
        domains=domains,
        keywords=keywords[:20],  # 限 20
        domain=domain,  # W15
    )


# ============================================================================
# Mock 文献库(Stage 1 模拟数据库)
# ============================================================================


MOCK_LIT_DB = {
    "LiCoO2": [
        LitReference(
            title="LiCoO2 Cathode Materials for Lithium-Ion Batteries: Recent Progress and Perspectives",
            authors=["Wang, J.", "Chen, Y."],
            year=2023,
            source="arXiv",
            doi="10.1234/lco-2023",
            url="https://arxiv.org/abs/2301.12345",
            abstract="We review the recent progress in LiCoO2 cathode materials, focusing on high-voltage stability and cobalt reduction strategies.",
            relevance=0.95,
            impact="high",
        ),
        LitReference(
            title="Cobalt-free Cathode Materials: A Materials Genome Approach",
            authors=["Liu, X.", "Smith, A.", "Park, J."],
            year=2024,
            source="Materials Project",
            doi="10.5678/mp-2024-001",
            url="https://materialsproject.org/papers/mp-2024-001",
            abstract="High-throughput screening of cobalt-free cathodes using first-principles calculations and machine learning potentials.",
            relevance=0.88,
            impact="high",
        ),
        LitReference(
            title="Stability of LiCoO2 at High Voltage: A Combined XRD and DFT Study",
            authors=["Zhang, L."],
            year=2022,
            source="ICSD",
            doi="10.5678/icsd-2022",
            url="https://icsd.fiz-karlsruhe.de/",
            abstract="X-ray diffraction combined with density functional theory reveals phase transitions in LiCoO2 above 4.3V.",
            relevance=0.78,
            impact="medium",
        ),
    ],
    "LiFePO4": [
        LitReference(
            title="Olivine LiFePO4: The Workhorse of Lithium-Ion Batteries",
            authors=["Padhi, A.K."],
            year=2023,
            source="arXiv",
            doi="10.1234/lfp-2023",
            url="https://arxiv.org/abs/2302.23456",
            abstract="A comprehensive review of LiFePO4 cathode materials, from discovery to industrial production.",
            relevance=0.92,
            impact="high",
        ),
        LitReference(
            title="High-Rate LiFePO4 via Carbon Coating and Nano-sizing",
            authors=["Chen, M.", "Wang, Y."],
            year=2024,
            source="Materials Project",
            doi="10.5678/mp-2024-002",
            url="https://materialsproject.org/papers/mp-2024-002",
            abstract="Carbon-coated LiFePO4 nanoparticles demonstrate rate capability up to 20C.",
            relevance=0.85,
            impact="medium",
        ),
    ],
    "LLZO": [
        LitReference(
            title="Garnet-type Li7La3Zr2O12 Solid Electrolytes: Recent Advances and Challenges",
            authors=["Thangadurai, V."],
            year=2024,
            source="arXiv",
            doi="10.1234/llzo-2024",
            url="https://arxiv.org/abs/2401.34567",
            abstract="Comprehensive review of LLZO solid electrolytes, including Ta-doped and Al-doped variants for high ionic conductivity.",
            relevance=0.97,
            impact="high",
        ),
        LitReference(
            title="Interface Engineering for LLZO / Lithium Metal Anode",
            authors=["Kim, S."],
            year=2023,
            source="arXiv",
            doi="10.1234/llzo-2023",
            url="https://arxiv.org/abs/2303.45678",
            abstract="Buffer layer engineering at LLZO / Li interface to suppress dendrite formation.",
            relevance=0.88,
            impact="high",
        ),
    ],
    "NMC": [
        LitReference(
            title="High-Nickel NMC Cathodes: From NMC111 to NMC811",
            authors=["Manthiram, A."],
            year=2024,
            source="arXiv",
            doi="10.1234/nmc-2024",
            url="https://arxiv.org/abs/2402.56789",
            abstract="Evolution of NMC cathodes toward higher Ni content for energy density improvement.",
            relevance=0.93,
            impact="high",
        ),
    ],
    "NaCl": [
        LitReference(
            title="NaCl as a Model Ionic Compound: Revisiting the Rocksalt Structure",
            authors=["Klein, M."],
            year=2020,
            source="ICSD",
            doi="10.5678/nacl-2020",
            url="https://icsd.fiz-karlsruhe.de/",
            abstract="Reference data for the rocksalt structure of NaCl.",
            relevance=0.70,
            impact="low",
        ),
    ],
    "_generic_": [
        LitReference(
            title="Materials Genome Initiative: A Decade of Progress",
            authors=["de Pablo, J.J."],
            year=2024,
            source="arXiv",
            doi="10.1234/mgi-2024",
            url="https://arxiv.org/abs/2410.00001",
            abstract="Ten years of the Materials Genome Initiative: high-throughput computing, experiments, and databases.",
            relevance=0.60,
            impact="high",
        ),
    ],
}

# 主题相关 mock 文献(无具体化学式时用)
TOPIC_MOCK_DB = {
    "电导率": [
        LitReference(
            title="Ionic Conductivity in Solid Electrolytes: A Review",
            authors=["Janek, J."],
            year=2023,
            source="arXiv",
            abstract="Comprehensive review of ionic conductivity mechanisms in solid electrolytes.",
            relevance=0.85,
            impact="high",
        ),
    ],
    "锂电池": [
        LitReference(
            title="Lithium-Ion Batteries: From Materials to Systems",
            authors=["Goodenough, J.B."],
            year=2023,
            source="arXiv",
            abstract="A holistic view of lithium-ion battery research, from cathode materials to pack engineering.",
            relevance=0.88,
            impact="high",
        ),
    ],
    "稳定性": [
        LitReference(
            title="Stability Predictions from First Principles",
            authors=["Sun, W."],
            year=2024,
            source="Materials Project",
            abstract="Energy above hull as a predictor of synthesizability.",
            relevance=0.80,
            impact="high",
        ),
    ],
}


# ============================================================================
# 文献检索(Stage 1 mock)
# ============================================================================


def search_literature(
    query: LitQuery,
    n_results: int = 5,
    sources: list[str] | None = None,
) -> list[LitReference]:
    """检索文献(Stage 1 mock)

    Args:
        query: LitQuery(从 user_intent 解析)
        n_results: 返回几条
        sources: 用哪些数据库(默认全用)

    Returns:
        List[LitReference],按 relevance 降序
    """
    if sources is None:
        # v1.3.3-Academic: sources 改为 [arXiv, PubChem, CrossRef](真接 3 源)
        # Materials Project / ICSD 字符串占位保留但未真接
        sources = ["arXiv", "PubChem", "CrossRef"]

    results: list[LitReference] = []
    seen_titles = set()

    # 1. 按化学式检索
    for formula in query.formulas:
        refs = MOCK_LIT_DB.get(formula, [])
        for r in refs:
            if r.title not in seen_titles:
                results.append(r)
                seen_titles.add(r.title)

    # 2. 按材料别名(优先查 alias 本身,再展开化学式)
    for alias in query.material_names:
        # 2a. 直接用 alias 作 key 查(LLZO / LFP 等)
        refs = MOCK_LIT_DB.get(alias, [])
        for r in refs:
            if r.title not in seen_titles:
                results.append(r)
                seen_titles.add(r.title)
        # 2b. 展开化学式后再查
        full_formula = MATERIAL_ALIASES.get(alias, "")
        if full_formula and full_formula != alias:
            for r in MOCK_LIT_DB.get(full_formula, []):
                if r.title not in seen_titles:
                    results.append(r)
                    seen_titles.add(r.title)

    # 3. 按属性 / 领域查主题
    for prop in query.properties + query.domains:
        for topic_key in TOPIC_MOCK_DB:
            if prop in topic_key or topic_key in prop:
                for r in TOPIC_MOCK_DB[topic_key]:
                    if r.title not in seen_titles:
                        results.append(r)
                        seen_titles.add(r.title)

    # 4. 没匹配到任何东西 → 返通用
    if not results:
        for r in MOCK_LIT_DB.get("_generic_", []):
            if r.title not in seen_titles:
                results.append(r)
                seen_titles.add(r.title)

    # 5. 按 relevance 降序 + 取 top-N
    results.sort(key=lambda r: r.relevance, reverse=True)
    return results[:n_results]


# ============================================================================
# W16: 真 arXiv 接入 + mock fallback
# ============================================================================


def _arxiv_search_real(query: LitQuery, n_results: int = 5) -> tuple[list[LitReference], bool]:
    """W16: 真查 arXiv(per agents.arxiv_client)

    Returns:
        (refs, is_real)
        - is_real=True: arXiv 真返回
        - is_real=False: 网络失败,返回空(调用方决定 fallback)
    """
    try:
        from agents.arxiv_client import search_arxiv
    except ImportError:
        return [], False

    try:
        arxiv_refs, is_real = search_arxiv(
            user_intent=query.raw_query,
            max_results=n_results,
            domain=query.domain,
        )
    except Exception:
        return [], False

    if not is_real or not arxiv_refs:
        return [], False

    results: list[LitReference] = []
    for r in arxiv_refs:
        results.append(LitReference(
            title=r.title,
            authors=r.authors[:5],
            year=r.year,
            source="arXiv",
            doi=None,
            url=r.url,
            abstract=r.summary[:500] if r.summary else "",
            relevance=0.85,
            impact="high",
        ))
    return results, True


def search_literature_with_arxiv_priority(
    query: LitQuery,
    n_results: int = 5,
    sources: list[str] | None = None,
) -> list[LitReference]:
    """W16: 真 arXiv 优先 + mock fallback

    Args:
        query: LitQuery
        n_results: 最多返回几条
        sources: 用哪些库

    Returns:
        List[LitReference] — 真 arXiv 论文优先,不够时 mock 补
    """
    if sources is None:
        # v1.3.3-Academic: sources 改为 [arXiv, PubChem, CrossRef](真接 3 源)
        # Materials Project / ICSD 字符串占位保留但未真接
        sources = ["arXiv", "PubChem", "CrossRef"]

    results: list[LitReference] = []
    seen_titles = set()

    # 1. 真 arXiv 优先
    if "arXiv" in sources:
        arxiv_refs, is_real = _arxiv_search_real(query, n_results)
        if is_real:
            for r in arxiv_refs:
                if r.title not in seen_titles:
                    results.append(r)
                    seen_titles.add(r.title)

    # 2. mock fallback(W14 search_literature 行为)
    mock_results = search_literature(query, n_results=n_results, sources=sources)
    for r in mock_results:
        if r.title not in seen_titles:
            results.append(r)
            seen_titles.add(r.title)

    results.sort(key=lambda r: r.relevance, reverse=True)
    return results[:n_results]


# ============================================================================
# 综述生成
# ============================================================================


def _format_background(query: LitQuery, refs: list[LitReference]) -> str:
    """生成背景介绍(2-3 段)"""
    parts = []
    parts.append(f"用户查询:{query.raw_query}")

    if query.formulas:
        parts.append(f"涉及化学式:{', '.join(query.formulas)}")
    if query.material_names:
        parts.append(f"材料别名:{', '.join(query.material_names)}(展开:{', '.join(MATERIAL_ALIASES.get(a, '?') for a in query.material_names)})")
    if query.properties:
        parts.append(f"目标属性:{', '.join(query.properties[:5])}")
    if query.domains:
        parts.append(f"应用领域:{', '.join(query.domains[:5])}")

    if refs:
        n_total = len(refs)
        year_range = f"{min(r.year for r in refs)}-{max(r.year for r in refs)}"
        parts.append(f"检索到 {n_total} 篇相关文献({year_range})")

    return " | ".join(parts)


def _format_state_of_art(query: LitQuery, refs: list[LitReference]) -> str:
    """生成国内外现状(2-3 段)"""
    if not refs:
        return "无相关文献,建议扩展检索关键词或查询具体材料名/化学式。"

    # 按 source 分组
    by_source: dict[str, list[LitReference]] = {}
    for r in refs:
        by_source.setdefault(r.source, []).append(r)

    parts = ["📚 国内外现状:"]
    for source, src_refs in by_source.items():
        avg_rel = sum(r.relevance for r in src_refs) / len(src_refs)
        parts.append(f"  • {source}({len(src_refs)} 篇,平均相关度 {avg_rel:.2f}):")
        for r in src_refs[:3]:
            authors_str = ", ".join(r.authors[:2]) + (" et al." if len(r.authors) > 2 else "")
            parts.append(f"    - [{r.year}] {r.title} ({authors_str}, relevance={r.relevance:.2f})")

    return "\n".join(parts)


def _identify_gaps(query: LitQuery, refs: list[LitReference]) -> list[str]:
    """识别研究空白"""
    gaps = []

    # 1. 检索结果少
    if len(refs) < 3:
        gaps.append(f"相关文献仅 {len(refs)} 篇,可能该方向研究较新或关键词过窄")

    # 2. 缺特定属性研究
    if query.properties:
        covered = set()
        for r in refs:
            for prop in query.properties:
                if prop.lower() in r.abstract.lower():
                    covered.add(prop)
        missing = set(query.properties) - covered
        if missing:
            gaps.append(f"以下属性研究较少:{', '.join(list(missing)[:3])}")

    # 3. 时效性
    if refs:
        recent = [r for r in refs if r.year >= 2023]
        if len(recent) < len(refs) * 0.3:
            gaps.append("2023 年后新文献占比 < 30%,建议关注最新进展")

    # 4. 影响力
    high_impact = [r for r in refs if r.impact == "high"]
    if len(high_impact) < len(refs) * 0.2:
        gaps.append("高影响力文献较少,需进一步检索权威期刊( Nature / Science / Sci. Adv.)")

    if not gaps:
        gaps.append("未发现明显研究空白")

    return gaps


def _generate_suggestions(query: LitQuery, refs: list[LitReference]) -> list[str]:
    """给用户的建议(2-3 条)"""
    suggestions = []

    if query.formulas or query.material_names:
        suggestions.append(
            "建议先用 mat-gen / mat-sim 模拟生成候选,再用 mat-critic 3 路交叉验证"
        )
        suggestions.append(
            "如需 HPC 验证,优先选 top-3 稳定候选(mat-hpc-agent 走 VASP)"
        )

    if query.properties:
        if "电导率" in query.properties or "ionic conductivity" in [p.lower() for p in query.properties]:
            suggestions.append(
                "电导率优化:可考虑 mat-bayesian 主动学习,GP/TPE 找最优掺杂"
            )
        if "稳定性" in query.properties or "stability" in [p.lower() for p in query.properties]:
            suggestions.append(
                "稳定性预测:对接 Materials Project 的 energy above hull"
            )

    if "锂电池" in query.domains or "battery" in [d.lower() for d in query.domains]:
        suggestions.append(
            "锂电池场景:可考虑 LLZO 固态电解质 / NMC811 高镍正极 / 硅碳负极 3 大方向"
        )

    if not suggestions:
        suggestions.append("可结合 mat-gen 候选 + mat-critic 评估 + mat-hpc 验证 三段流程")

    return suggestions[:3]


def _calc_confidence(query: LitQuery, refs: list[LitReference]) -> float:
    """算综述质量分 0-1"""
    base = 0.5

    # 检索到文献 → +0.1 ~ +0.3
    if refs:
        base += min(0.3, len(refs) * 0.05)

    # 高相关度文献多 → +
    if refs:
        avg_rel = sum(r.relevance for r in refs) / len(refs)
        base += (avg_rel - 0.5) * 0.3

    # 关键词命中 → +
    if query.has_match():
        base += 0.1

    return min(1.0, max(0.0, base))


# ============================================================================
# 主接口
# ============================================================================


def review_literature(
    user_intent: str,
    n_results: int = 5,
    sources: list[str] | None = None,
    *,
    domain: str | None = None,
    use_real_arxiv: bool = True,
    use_real_mp: bool = False,
) -> LitReview:
    """主接口:从 user_intent 生成文献综述(W15: 支持 domain;W17: 2 个真实 source)

    Args:
        user_intent: 用户原始 query
        n_results: 引用文献数
        sources: 数据库列表(默认 4 个全用)
        domain: 材料域(per W15;None → 自动 detect / 默认 inorganic_crystal)
        use_real_arxiv: v1.3.2-Academic 起默认 True = 真查 arXiv API(失败自动 fallback mock)
        use_real_mp: W17-C — 是否真查 Materials Project API(默认 False = 行为不变)

    Returns:
        LitReview
    """
    from agents.material_domain_router import DEFAULT_DOMAIN, detect_domain

    if sources is None:
        # v1.3.3-Academic: sources 改为 [arXiv, PubChem, CrossRef](真接 3 源)
        # Materials Project / ICSD 字符串占位保留但未真接
        sources = ["arXiv", "PubChem", "CrossRef"]

    # W15: domain 解析(显式 > auto-detect > 默认)
    if domain is None or domain == "auto":
        domain = detect_domain(user_intent)
    if domain is None:
        domain = DEFAULT_DOMAIN

    # 1. 解析查询
    query = parse_lit_query(user_intent, domain=domain)

    # 2. 检索文献(W17:arXiv 或 MP 任一真查都走专属路径,否则纯 mock)
    # v1.3.2-Academic bug fix: 用 return_is_real=True 拿 is_real 状态(向后兼容老调用者)
    if use_real_arxiv or use_real_mp:
        refs, is_real_per_source = search_literature_with_real_sources(
            query,
            n_results=n_results,
            sources=sources,
            use_real_arxiv=use_real_arxiv,
            use_real_mp=use_real_mp,
            return_is_real=True,
        )
        # arxiv 真查状态(per v1.3.2 focus)— MP 真查暂未实现,只看 arxiv
        is_real_query = is_real_per_source.get("arxiv", False)
    else:
        refs = search_literature(query, n_results=n_results, sources=sources)
        is_real_query = False

    # 3. 生成综述各部分
    background = _format_background(query, refs)
    state_of_art = _format_state_of_art(query, refs)
    gaps = _identify_gaps(query, refs)
    suggestions = _generate_suggestions(query, refs)
    confidence = _calc_confidence(query, refs)

    return LitReview(
        query=user_intent,
        references=refs,
        background=background,
        state_of_art=state_of_art,
        gaps=gaps,
        suggestions=suggestions,
        confidence=confidence,
        sources_queried=sources,
        is_real_query=is_real_query,
    )


def search_literature_with_real_sources(
    query: LitQuery,
    n_results: int = 5,
    sources: list[str] | None = None,
    *,
    use_real_arxiv: bool = True,
    use_real_mp: bool = False,
    return_is_real: bool = False,
) -> list[LitReference] | tuple[list[LitReference], dict[str, bool]]:
    """W17-C: 多源真查(arXiv + Materials Project 任选)+ mock 兜底

    Args:
        query: LitQuery
        n_results: 总数
        sources: 列出要查的 source(只对真查的有效,mock 全跑)
        use_real_arxiv: v1.3.2-Academic 起默认 True = 真查 arXiv(失败 fallback mock)
        use_real_mp: 是否真查 Materials Project
        return_is_real: v1.3.2-Academic 新增 — True 时返回 tuple (refs, is_real_per_source)
                       is_real_per_source 是 dict[str, bool],key 是 source 名("arxiv" / "mp")
                       False 时(默认)只返回 refs,向后兼容老调用者

    Returns:
        - return_is_real=False(默认):List[LitReference](真查 + mock 合并,向后兼容)
        - return_is_real=True:tuple[list[LitReference], dict[str, bool]](per source 真查状态)
    """
    from agents.material_domain_router import DEFAULT_DOMAIN
    raw_user_intent = query.raw_query
    domain = query.domain or DEFAULT_DOMAIN

    combined: list[LitReference] = []
    # v1.3.2-Academic bug fix: 记录每个 source 真查状态(per source 维度)
    is_real_per_source: dict[str, bool] = {"arxiv": False, "mp": False}

    # A. arXiv 真查 + fallback
    if use_real_arxiv:
        try:
            from agents.arxiv_client import search_arxiv
            refs, is_real = search_arxiv(raw_user_intent, max_results=n_results, domain=domain)
            is_real_per_source["arxiv"] = is_real
            for r in refs:
                combined.append(LitReference(
                    title=r.title,
                    authors=r.authors,
                    year=r.year,
                    source="arXiv",
                    url=r.url,
                    abstract=r.summary[:200],
                    relevance=0.85 if is_real else 0.5,
                    impact="high" if is_real else "medium",
                ))
        except Exception:
            pass

    # B. Materials Project 真查 + fallback(W17-C 新增)
    if use_real_mp:
        try:
            from agents.materials_project_client import search_materials_project
            mp_refs, is_real = search_materials_project(raw_user_intent, max_results=n_results, domain=domain)
            is_real_per_source["mp"] = is_real
            for mpr in mp_refs:
                combined.append(LitReference(
                    title=f"{mpr.formula} ({mpr.spacegroup}, mp_id={mpr.mp_id})",
                    authors=["Materials Project"],
                    year=2024,
                    source="Materials Project",
                    url=mpr.url,
                    abstract=(
                        f"Energy above hull: {mpr.energy_above_hull:.3f} eV/atom, "
                        f"band gap: {mpr.band_gap:.2f} eV, "
                        f"density: {mpr.density:.2f} g/cm³, "
                        f"{'stable' if mpr.is_stable else 'metastable'}"
                    ),
                    relevance=0.9 if is_real else 0.5,
                    impact="high",
                ))
        except Exception:
            pass

    # C. 没找到任一条才走 mock 兜底(避免空 results)
    if not combined:
        refs = search_literature(query, n_results=n_results, sources=sources)
        if return_is_real:
            return refs, is_real_per_source
        return refs

    # 截断到 n_results
    truncated = combined[:n_results] if len(combined) > n_results else combined
    if return_is_real:
        return truncated, is_real_per_source
    return truncated


__all__ = [
    "MATERIAL_ALIASES",
    "LitQuery",
    "LitReference",
    "LitReview",
    "parse_lit_query",
    "review_literature",
    "search_literature",
]