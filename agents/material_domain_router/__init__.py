"""material_domain_router — MatWAU 材料域路由(W15 + W17)

核心职责:
- 定义 4 个材料域 profile(W17 加 metal_alloy):
  inorganic_crystal / polymer / nano / metal_alloy
- 提供 domain 关键词识别(domain detection)
- 提供 per-domain 路由决策(给 gen / sim / hpc / lit / cost / intent)

设计原则(per MatWAU-Harness-Loop-工程心法实践.md):
- 15 agent 对外接口不变,domain 通过 AgentRequest.context["domain"] 传入
- 不传 domain → 默认 "inorganic_crystal"(W3-W14 行为,向后兼容)
- 加第 N+1 个域(复合材料 / 生物材料)只需在 PROFILES 加 1 个 dict 项

Stage 1: 纯 Python dict + 关键词
Stage 2(WAU v1.0.0 GA 后): wau-domain-registry SDK 注入实际后端

用法:
    from agents.material_domain_router import detect_domain, get_profile

    domain = detect_domain("算 PMMA 玻璃化转变温度")  # "polymer"
    profile = get_profile(domain)
    print(profile["gen_backend"])  # "polymer_rnn"

    # W17 metal_alloy
    domain = detect_domain("Inconel 718 屈服强度")  # "metal_alloy"
    profile = get_profile(domain)
    print(profile["gen_backend"])  # "alloy_diffusion"
"""

from __future__ import annotations

from .domain_router import (  # noqa: F401
    DOMAINS,
    DEFAULT_DOMAIN,
    DOMAIN_PATTERNS,
    detect_domain,
    get_profile,
    list_domains,
    is_valid_domain,
    get_keywords_for_domain,
    get_property_keywords,
    get_domain_keywords,
)
from .profiles import (  # noqa: F401
    INORGANIC_CRYSTAL_PROFILE,
    POLYMER_PROFILE,
    NANO_PROFILE,
    METAL_ALLOY_PROFILE,
    PROFILES,
    get_gen_backend,
    get_sim_backend,
    get_hpc_engine,
    get_lit_backend,
    get_unit_cost_table,
)

__all__ = [
    "DOMAINS",
    "DEFAULT_DOMAIN",
    "DOMAIN_PATTERNS",
    "detect_domain",
    "get_profile",
    "list_domains",
    "is_valid_domain",
    "get_keywords_for_domain",
    "get_property_keywords",
    "get_domain_keywords",
    "INORGANIC_CRYSTAL_PROFILE",
    "POLYMER_PROFILE",
    "NANO_PROFILE",
    "METAL_ALLOY_PROFILE",
    "PROFILES",
    "get_gen_backend",
    "get_sim_backend",
    "get_hpc_engine",
    "get_lit_backend",
    "get_unit_cost_table",
]
