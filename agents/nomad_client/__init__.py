"""nomad_client — NOMAD(Novel Materials Discovery)API 客户端(v1.3-Academic M2)

核心职责:
- 真查 NOMAD REST API(https://nomad-lab.eu/prod/v1/api/v1/,免费 signup 可选)
- 解析 NOMAD metainfo → 标准化字段(per metainfo_mapping 模块)
- 失败 fallback 到 mock DB
- LRU cache(per 学院版"在线优先 + cache"原则)
- CanonicalKey 映射(供 mat_critic L4 跨源规则用)

数据规模:千万级(DFT + 实验,全模态 + workflow)
引用:Draxl & Scheffler, *J. Phys. Mater.* 2019, **2**
许可:CC-BY 4.0(各数据集各异)

设计要点(per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2):
- NOMAD metainfo ontology 复杂,本模块只覆盖 ~30 关键字段(metainfo_mapping.MAPPED_METAINFO_PATHS)
- 学院方可配环境变量 `MATWAU_NOMAD_API_BASE` / `MATWAU_NOMAD_TOKEN` 覆盖 URL 或 Bearer token
- LRU cache 默认开(use_cache=True),断网后自动 fallback mock

用法:
    from agents.nomad_client import NomadClient

    client = NomadClient()
    refs, is_real = client.search("Ni3Cr2Fe2Mo", max_results=10)
    for r in refs:
        print(r.entry_id, r.formula, r.spacegroup_symbol, r.band_gap_eV)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 1-4 项
"""

from __future__ import annotations

import logging

from .client import (  # noqa: F401
    ENV_NOMAD_API_BASE,
    ENV_NOMAD_TOKEN,
    NOMAD_API_URL_DEFAULT,
    NOMAD_TIMEOUT_SEC,
    NomadClient,
    NomadReference,
    is_nomad_available,
    search_nomad,
)
from .metainfo_mapping import (  # noqa: F401
    KNOWN_PROPERTY_GROUPS,
    KNOWN_SECTIONS,
    MAPPED_METAINFO_PATHS,
    UNMAPPED_PATTERNS,
    count_mapped_metainfo_paths,
    extract_nomad_record,
)

__all__ = [
    "NOMAD_API_URL_DEFAULT",
    "NOMAD_TIMEOUT_SEC",
    "ENV_NOMAD_API_BASE",
    "ENV_NOMAD_TOKEN",
    "NomadClient",
    "NomadReference",
    "is_nomad_available",
    "search_nomad",
    "KNOWN_SECTIONS",
    "KNOWN_PROPERTY_GROUPS",
    "MAPPED_METAINFO_PATHS",
    "UNMAPPED_PATTERNS",
    "count_mapped_metainfo_paths",
    "extract_nomad_record",
]