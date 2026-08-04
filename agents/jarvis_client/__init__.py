"""jarvis_client — JARVIS(Joint Automated Reverse Engineering & Scoring
Materials Database)客户端(v1.3-Academic M2)

核心职责:
- 真查 JARVIS REST API(https://jarvis.nist.gov/,可选 Bearer token)
- 解析 JSON → JarvReference dataclass
- 失败 fallback 到 mock DB
- jarvis-tools Python 包作为 **optional**(学院方精简镜像可能装不下,降级到纯 REST)
- LRU cache(per 学院版"在线优先 + cache"原则)
- CanonicalKey 映射(供 mat_critic L4 跨源规则用)

数据规模:~75K 材料(3D + 2D 综合)
引用:Choudhary et al., *Sci. Data* 2020, **1408**
许可:CC-BY 4.0

设计要点(per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 风险):
- **不强制 `pip install jarvis-tools`**(依赖太重,学院方精简镜像装不下)
- 学院方可配环境变量 `MATWAU_JARVIS_API_BASE` / `MATWAU_JARVIS_TOKEN` 覆盖 URL 或 Bearer token
- LRU cache 默认开,断网后自动 fallback mock

用法:
    from agents.jarvis_client import JarvClient

    client = JarvClient()
    refs, is_real = client.search("MoS2", max_results=10)
    for r in refs:
        print(r.jid, r.formula, r.spacegroup_symbol, r.band_gap_eV, "2D" if r.is_2d else "3D")

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 5-6 项
"""

from __future__ import annotations

import logging

from .client import (
    ENV_JARVIS_API_BASE,
    ENV_JARVIS_TOKEN,
    JARVIS_API_URL_DEFAULT,
    JARVIS_TIMEOUT_SEC,
    JarvClient,
    JarvReference,
    is_jarvis_available,
    is_jarvis_tools_available,
    search_jarvis,
)

__all__ = [
    "ENV_JARVIS_API_BASE",
    "ENV_JARVIS_TOKEN",
    "JARVIS_API_URL_DEFAULT",
    "JARVIS_TIMEOUT_SEC",
    "JarvClient",
    "JarvReference",
    "is_jarvis_available",
    "is_jarvis_tools_available",
    "search_jarvis",
]