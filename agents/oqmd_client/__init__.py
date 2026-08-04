"""oqmd_client — OQMD(Open Quantum Materials Database)API 客户端(v1.3-Academic M1)

核心职责:
- 真查 OQMD REST API(https://oqmd.org/oqmdapi/,**无需 API key**)
- 解析 JSON → OqmdRecord dataclass
- 失败 fallback 到 mock DB(向后兼容 Stage 1)
- CanonicalKey 映射(供 mat_critic L4 跨源规则用)

数据规模:~1M DFT 计算,金属 / 合金为主
引用:Kirklin et al., *Sci. Data* 2013, **1405**
许可:CC-BY 4.0

用法:
    from agents.oqmd_client import OqmdClient

    client = OqmdClient()
    refs, is_real = client.search("Ni3Cr2Fe2Mo", limit=10)
    for r in refs:
        print(r.oqmd_id, r.formula, r.formation_energy_per_atom)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 2-4 项
"""

from __future__ import annotations

import logging

from .client import (
    OQMD_API_URL,
    OQMD_TIMEOUT_SEC,
    OqmdClient,
    OqmdReference,
    is_oqmd_available,
    search_oqmd,
)

__all__ = [
    "OQMD_API_URL",
    "OQMD_TIMEOUT_SEC",
    "OqmdClient",
    "OqmdReference",
    "is_oqmd_available",
    "search_oqmd",
]