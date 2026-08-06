"""arxiv_client — arXiv API 客户端(W16 Stage 2 真接入 + v1.3.2-Academic LRU/gzip)

核心职责:
- 真查 arXiv API(http://export.arxiv.org/api/query)
- 解析 Atom XML → ArxivReference dataclass
- 失败 fallback 到 mock DB(向后兼容 W14)
- 3 域关键词适配(per W15 MaterialDomainRouter)
- LRU cache(v1.3.2 M1)— 同 query < 1ms 命中
- gzip 压缩支持(v1.3.2 M1)— 大响应省 70% 流量

Stage 1: 接收 lit_backend 参数 → 选择 mock_materials / mock_polymers / mock_nano
Stage 2(W16): 默认走 arXiv 真 API,失败 fallback
Stage 2.1(v1.3.2-Academic): 加 LRU cache + gzip 支持(per MatWAU-v1.3.2-Academic-dev-plan M1)

用法:
    from agents.arxiv_client import ArxivClient

    client = ArxivClient()  # 默认 cache_size=128, enable_gzip=True
    refs, is_real = client.search("LLZO ionic conductivity", max_results=5)
    for r in refs:
        print(r.title, r.year, r.url)
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import (
    ARXIV_LRU_CACHE_DEFAULT_SIZE,
    ArxivClient,
    ArxivReference,
    _LruCache,
    _build_arxiv_query,
    is_arxiv_available,
    search_arxiv,
)

__all__ = [
    "ARXIV_LRU_CACHE_DEFAULT_SIZE",
    "ArxivClient",
    "ArxivReference",
    "_LruCache",
    "_build_arxiv_query",
    "is_arxiv_available",
    "search_arxiv",
]