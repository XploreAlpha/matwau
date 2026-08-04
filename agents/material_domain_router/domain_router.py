"""domain_router.py — MatWAU 材料域路由器核心(W15 + W17)

4 个材料域(W17 加 metal_alloy):
- inorganic_crystal — 无机晶体(默认,W3-W14 行为)
- polymer — 高分子聚合物
- nano — 纳米材料
- metal_alloy — 金属 / 合金(W17 新增,默认最低优先级)

域检测:
- 关键词匹配(化学式 / 材料名 / 属性词 / 应用领域)
- 优先级:nano > polymer > metal_alloy > inorganic_crystal

Stage 1: 关键词 + 规则
Stage 2: wau-domain-registry SDK 注入 + LLM 二次校验
"""
from __future__ import annotations

import re
from typing import Any

# ============================================================================
# 域常量
# ============================================================================


DOMAINS = ["inorganic_crystal", "polymer", "nano", "metal_alloy"]
DEFAULT_DOMAIN = "inorganic_crystal"


# ============================================================================
# 域关键词检测(per 域独立,优先级 nano > polymer > inorganic_crystal)
# ============================================================================


DOMAIN_PATTERNS = {
    "nano": [
        # 纳米材料关键词
        r"纳米", r"nanoparticle", r"纳米线", r"nanowire", r"纳米管", r"nanotube",
        r"纳米片", r"nanosheet", r"纳米结构", r"nanostructure",
        r"量子点", r"quantum dot", r"\bQD\b", r"qdot",
        r"石墨烯", r"graphene", r"氧化石墨烯", r"\bGO\b", r"\brGO\b",
        r"MoS2", r"MoS_2", r"二硫化钼", r"过渡金属硫族", r"\bTMDC?\b",
        r"介孔", r"mesoporous", r"多孔", r"porous",
        r"比表面积", r"specific surface area", r"\bBET\b",
        r"量子限域", r"quantum confinement", r"Brus",
        r"表面等离子体", r"surface plasmon", r"\bLSPR\b",
        r"原子层沉积", r"\bALD\b", r"化学气相沉积", r"\bCVD\b",
        r"纳米晶", r"nanocrystal", r"纳米团簇", r"nanocluster",
        r"0D", r"1D", r"2D 材料",
        # 介孔 / MOF / COF
        r"MOF", r"ZIF", r"COF", r"ZIF-8", r"ZIF-67",
        r"HKUST-1", r"MIL-101", r"UiO-66",
        # 异质结
        r"异质结", r"heterojunction", r"范德华", r"\bvdW\b",
    ],
    "polymer": [
        # 高分子关键词
        r"高分子", r"聚合物", r"polymer", r"polymeric",
        r"PMMA", r"聚甲基丙烯酸甲酯",
        r"PDMS", r"聚二甲基硅氧烷",
        r"PEEK", r"聚醚醚酮",
        r"\bPI\b", r"聚酰亚胺", r"polyimide",
        r"PEG", r"聚乙二醇", r"polyethylene glycol",
        r"PAN", r"聚丙烯腈", r"polyacrylonitrile",
        r"PVDF", r"聚偏氟乙烯", r"polyvinylidene fluoride",
        r"PVDF-HFP",
        r"PE\b", r"聚乙烯", r"polyethylene",
        r"\bPP\b", r"聚丙烯", r"polypropylene",
        r"PS\b", r"聚苯乙烯", r"polystyrene",
        r"PVC", r"聚氯乙烯",
        r"\bPLA\b", r"聚乳酸", r"polylactic acid",  # W15 加 PLA alias
        r"PEDOT", r"PEDOT:PSS",  # W15 加 PEDOT alias
        r"水凝胶", r"hydrogel",
        r"导电聚合物", r"conducting polymer", r"聚苯胺", r"polyaniline",
        r"热塑性", r"thermoplastic", r"热固性", r"thermoset",
        r"弹性体", r"elastomer",
        r"玻璃化转变", r"\bTg\b", r"glass transition",
        r"熔体流动", r"\bMFI\b", r"melt flow index",
        r"聚合度", r"degree of polymerization",
        r"分子量分布", r"MWD", r"polydispersity", r"Ð", r"\bPDI\b",
        r"Mark-Houwink", r"Fox-Flory",
        r"柔性电子", r"flexible electronics",
        r"静电纺丝", r"electrospin",
        r"注塑", r"injection molding",
        r"3D 打印", r"FDM", r"\bSLA\b",  # W15: 3D 打印通常是高分子
        # 注意:SLM/LPBF/EBM/DED 是金属 3D 打印,放 metal_alloy
    ],
    "inorganic_crystal": [
        # 无机晶体关键词(兜底,W3-W14 已有,这里只保留领域强标识)
        r"锂电池", r"lithium.*battery", r"锂离子",
        r"正极材料", r"负极材料", r"cathode", r"anode",
        r"固态电解质", r"solid electrolyte", r"LLZO", r"LGPS", r"LATP",
        r"NASICON", r"LAGP",
        r"晶格", r"lattice", r"晶胞", r"unit cell",
        r"析氢", r"\bHER\b", r"析氧", r"\bOER\b",
        r"钙钛矿", r"perovskite", r"CsPbI3", r"MAPbI3",
        r"超导", r"superconductor", r"YBCO",
        r"热电", r"thermoelectric", r"Bi2Te3",
        r"永磁", r"permanent magnet", r"Nd2Fe14B",
        r"半导体", r"semiconductor", r"GaN", r"SiC",
        r"储氢", r"hydrogen storage", r"MgH2",
        r"形成能", r"formation energy",
        r"弛豫", r"relax",
        r"VASP", r"DFT",
        r"CHGNet", r"MatterGen",
        r"烧结", r"sintering",
        r"XRD", r"布拉格", r"Bragg",
    ],
    "metal_alloy": [
        # W17 金属 / 合金关键词(优先级低于 nano / polymer)
        # 元素符号(只列常见 alloy 元素,避开跟 nano/inorganic 重叠 — Ni/Nb 等共享元素)
        r"合金", r"alloy", r"金合金", r"钢铁", r"钛合金", r"镍基",
        r"\bsteel\b", r"\bstainless\b", r"\binconel\b", r"\bHastelloy\b",
        r"高熵合金", r"high entropy alloy", r"\bHEA\b",
        r"非晶合金", r"amorphous.*alloy", r"metallic glass",
        r"形状记忆合金", r"shape memory", r"\bSMA\b", r"Nitinol",
        r"超合金", r"superalloy",
        r"相图", r"phase diagram",
        r"TTT", r"CCT", r"TTT 图", r"CCT 图",
        r"马氏体", r"martensite", r"奥氏体", r"austenite",
        r"珠光体", r"pearlite", r"贝氏体", r"bainite",
        r"铁素体", r"ferrite", r"渗碳体", r"cementite",
        r"固溶体", r"solid solution",
        r"析出强化", r"沉淀强化", r"precipitation strengthening",
        r"位错", r"dislocation",
        r"屈服强度", r"yield strength",
        r"抗拉强度", r"ultimate tensile strength", r"\bUTS\b",
        r"断后伸长率", r"elongation", r"断面收缩",
        r"夏比冲击", r"Charpy", r"断裂韧性", r"K_IC", r"KIC",
        r"硬度", r"\bHB\b", r"\bHV\b", r"\bHRC\b",
        r"蠕变", r"creep",
        r"疲劳", r"fatigue", r"S-N 曲线",
        r"加工硬化", r"应变硬化", r"work hardening",
        r"热处理", r"heat treatment", r"正火", r"退火", r"淬火", r"回火",
        r"锻造", r"forging", r"轧制", r"rolling",
        r"铸造", r"casting",
        r"焊接", r"welding",
        # 金属增材制造(per W17)
        r"\bSLM\b", r"\bLPBF\b", r"\bEBM\b", r"\bDED\b",
        r"金属增材", r"金属粉末",
        # 常见 metal alloy 元素标签(放在 lower 优先级,被 nano/polymer 高优先级词覆盖)
        # 例 "纳米 Fe 颗粒" → nano 优先; "Fe 合金" → metal_alloy
        # 这里只列合金强信号(不只元素符号,避免重叠)
    ],
}


# ============================================================================
# 域检测函数
# ============================================================================


def detect_domain(
    user_intent: str,
    *,
    default: str | None = None,
) -> str:
    """从 user_intent 识别材料域

    优先级: nano > polymer > inorganic_crystal(避免 PMMA 量子点误判)

    Args:
        user_intent: 用户原始意图
        default: 兜底域(默认 "inorganic_crystal")

    Returns:
        3 域之一
    """
    if default is None:
        default = DEFAULT_DOMAIN

    msg = user_intent or ""

    # 按优先级匹配(per W17 加 metal_alloy)
    for domain in ["nano", "polymer", "metal_alloy", "inorganic_crystal"]:
        patterns = DOMAIN_PATTERNS.get(domain, [])
        for p in patterns:
            if re.search(p, msg, re.IGNORECASE):
                return domain

    return default


def list_domains() -> list[str]:
    """列出所有支持的材料域"""
    return list(DOMAINS)


def is_valid_domain(domain: str) -> bool:
    """校验是否是有效材料域"""
    return domain in DOMAINS


def get_keywords_for_domain(domain: str) -> list[str]:
    """获取指定域的检测关键词"""
    return list(DOMAIN_PATTERNS.get(domain, []))


def get_property_keywords(domain: str) -> list[str]:
    """获取指定域的属性词(从 profiles 拿)"""
    from .profiles import get_profile

    p = get_profile(domain)
    return list(p.get("property_keywords", []))


def get_domain_keywords(domain: str) -> list[str]:
    """获取指定域的应用领域词(从 profiles 拿)"""
    from .profiles import get_profile

    p = get_profile(domain)
    return list(p.get("domain_keywords", []))


def get_profile(domain: str) -> dict[str, Any]:
    """获取指定域的完整 profile(委托给 profiles 模块)

    Raises:
        ValueError: 未知 domain
    """
    from .profiles import get_profile as _get_profile

    return _get_profile(domain)


__all__ = [
    "DEFAULT_DOMAIN",
    "DOMAINS",
    "DOMAIN_PATTERNS",
    "detect_domain",
    "get_domain_keywords",
    "get_keywords_for_domain",
    "get_profile",
    "get_property_keywords",
    "is_valid_domain",
    "list_domains",
]