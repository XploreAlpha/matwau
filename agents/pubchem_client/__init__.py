"""pubchem_client — PubChem(NIH)化合物 API 客户端(v1.3.3-Academic M1)

核心职责:
- 真查 PubChem REST API(https://pubchem.ncbi.nlm.nih.gov/rest/pug/)
- 解析 JSON → PubChemReference dataclass
- 失败 fallback(W14 mock 兼容)
- LRU cache + gzip + 硬上限(per v1.3.2 模板)
- 分子式 / 名称 → SMILES / IUPACName / MolecularFormula / MolecularWeight

数据规模:~110M compound records(NIH 公共数据)
许可:CC-BY 4.0
速率:5 req/sec(per PubChem docs)

用法:
    from agents.pubchem_client import PubChemClient

    client = PubChemClient()
    refs, is_real = client.search("LiCoO2")
    for r in refs:
        print(r.cid, r.molecular_formula, r.canonical_smiles)

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §三 M1
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
    PUBCHEM_API_URL,
    PUBCHEM_LRU_CACHE_DEFAULT_SIZE,
    PubChemClient,
    PubChemReference,
    _LruCache,
    _build_pubchem_query,
    _parse_pubchem_json,
    is_pubchem_available,
    search_pubchem,
)

__all__ = [
    "PUBCHEM_API_URL",
    "PUBCHEM_LRU_CACHE_DEFAULT_SIZE",
    "PubChemClient",
    "PubChemReference",
    "_LruCache",
    "_build_pubchem_query",
    "_parse_pubchem_json",
    "is_pubchem_available",
    "search_pubchem",
]