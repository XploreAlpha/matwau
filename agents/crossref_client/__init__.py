"""crossref_client — CrossRef 期刊 DOI 元数据 API 客户端(v1.3.3-Academic M2)

核心职责:
- 真查 CrossRef REST API(https://api.crossref.org/works)
- 解析 JSON → CrossRefReference dataclass
- 失败 fallback(W14 mock 兼容)
- LRU cache + gzip + 硬上限(per v1.3.2 模板)
- DOI / title / author / journal / year / citations 查询

数据规模:150M+ DOI records(期刊论文 + 书籍 + 会议论文)
许可:公共元数据(per CrossRef etiquette 加 mailto)
速率:宽松(per CrossRef pool),建议加 mailto 标识

用法:
    from agents.crossref_client import CrossRefClient

    client = CrossRefClient()
    refs, is_real = client.search("LiCoO2 lithium-ion battery", max_results=5)
    for r in refs:
        print(r.doi, r.title, r.journal, r.year, r.citations_count)

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §四 M2
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import (
    CROSSREF_API_URL,
    CROSSREF_LRU_CACHE_DEFAULT_SIZE,
    CrossRefClient,
    CrossRefReference,
    _LruCache,
    _build_crossref_query,
    _extract_authors,
    _extract_year,
    _parse_crossref_json,
    _strip_jats_xml,
    is_crossref_available,
    search_crossref,
)

__all__ = [
    "CROSSREF_API_URL",
    "CROSSREF_LRU_CACHE_DEFAULT_SIZE",
    "CrossRefClient",
    "CrossRefReference",
    "_LruCache",
    "_build_crossref_query",
    "_extract_authors",
    "_extract_year",
    "_parse_crossref_json",
    "_strip_jats_xml",
    "is_crossref_available",
    "search_crossref",
]