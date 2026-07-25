"""arxiv_client — arXiv API 客户端(W16 Stage 2 真接入)

核心职责:
- 真查 arXiv API(http://export.arxiv.org/api/query)
- 解析 Atom XML → LitReference dataclass
- 失败 fallback 到 mock DB(向后兼容 W14)
- 3 域关键词适配(per W15 MaterialDomainRouter)

Stage 1: 接收 lit_backend 参数 → 选择 mock_materials / mock_polymers / mock_nano
Stage 2(W16): 默认走 arXiv 真 API,失败 fallback

用法:
    from agents.arxiv_client import ArxivClient

    client = ArxivClient()
    refs = client.search("LLZO ionic conductivity", max_results=5)
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

from .client import (  # noqa: F401
    ArxivClient,
    ArxivReference,
    search_arxiv,
    is_arxiv_available,
)

__all__ = [
    "ArxivClient",
    "ArxivReference",
    "search_arxiv",
    "is_arxiv_available",
]