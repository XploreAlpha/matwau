"""pubchem_client / client.py — PubChem API 真接入(v1.3.3-Academic M1)

支持:
- 真查 PubChem REST API(无需 API key,NIH 公共数据)
- 失败 fallback(连接失败 / timeout / parse 错误)
- LRU cache + gzip 压缩 + 硬上限(per v1.3.2 模板)
- 分子式 / 名称 / CID 查询

PubChem API 文档:https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest

查询 URL 模板:
- By name: GET /compound/name/{name}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES/JSON
- By CID:  GET /compound/cid/{cid}/property/...
- By SMILES: GET /compound/smiles/{smiles}/property/...

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §三 M1
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PUBCHEM_API_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_TIMEOUT_SEC = 8  # 单次 query timeout
PUBCHEM_LRU_CACHE_DEFAULT_SIZE = 128  # v1.3.3 M1: LRU cache 默认容量

# PubChem 支持的 properties 字段(per API docs)
PUBCHEM_PROPERTIES = (
    "MolecularFormula,MolecularWeight,"
    "IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey"
)


# ============================================================================
# PubChemReference dataclass
# ============================================================================


@dataclass
class PubChemReference:
    """1 个 PubChem compound record

    Attributes:
        cid: PubChem CID(如 24789 for LiCoO2)
        name: 检索的化学式 / 名字
        molecular_formula: 分子式(如 "CoLiO2")
        iupac_name: IUPAC 名称
        canonical_smiles: Canonical SMILES
        isomeric_smiles: Isomeric SMILES(含立体信息)
        molecular_weight: 分子量(g/mol)
        inchi: InChI
        inchikey: InChI Key
        url: PubChem URL
    """

    cid: int
    name: str
    molecular_formula: str = ""
    iupac_name: str = ""
    canonical_smiles: str = ""
    isomeric_smiles: str = ""
    molecular_weight: float = 0.0
    inchi: str = ""
    inchikey: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "name": self.name,
            "molecular_formula": self.molecular_formula,
            "iupac_name": self.iupac_name[:200],
            "canonical_smiles": self.canonical_smiles,
            "isomeric_smiles": self.isomeric_smiles,
            "molecular_weight": self.molecular_weight,
            "inchi": self.inchi[:200],
            "inchikey": self.inchikey,
            "url": self.url,
        }


# ============================================================================
# LRU cache(per v1.3.2 arxiv_client 模板)
# ============================================================================


class _LruCache:
    """线程不安全 LRU cache(per arxiv_client 实现)"""

    def __init__(self, capacity: int = PUBCHEM_LRU_CACHE_DEFAULT_SIZE):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, list[PubChemReference]] = OrderedDict()

    def get(self, key: str) -> list[PubChemReference] | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, refs: list[PubChemReference]) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = list(refs)
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


# ============================================================================
# Query 构造
# ============================================================================


def _build_pubchem_query(user_intent: str) -> str:
    """构造 PubChem search name(直接用化学式 / 名字)

    PubChem name lookup 接受化学式 / IUPAC / 通用名,不需要 query 语法构造。
    简单 urlencode + 去掉空格即可。

    Examples:
        "LiCoO2" → "LiCoO2"
        "查询 LiCoO2 分子式" → "LiCoO2"
        "polystyrene" → "polystyrene"
    """
    msg = user_intent.strip()

    # 优先提取化学式(大写 + 小写 + 数字 + 大写开头)
    formulas = re.findall(r"\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+\b", msg)
    if formulas:
        return formulas[0]

    # 提取大写 alias(PMMA / LFP / NMC / ...)
    aliases = re.findall(r"\b[A-Z]{2,6}[0-9]{0,4}\b", msg)
    if aliases:
        return aliases[0]

    # 兜底:用最关键的几个英文/中文词
    # PubChem name lookup 对空格不友好,用第一个词
    words = re.findall(r"\b[A-Za-z]{3,}\b|\b[一-鿿]{2,}\b", msg)
    if words:
        return words[0]

    return msg[:100]


# ============================================================================
# JSON 解析
# ============================================================================


def _parse_pubchem_json(
    json_text: str, query_name: str
) -> list[PubChemReference]:
    """解析 PubChem PUG-REST JSON → List[PubChemReference]

    Response format (per docs):
    {
      "PropertyTable": {
        "Properties": [
          {
            "CID": 24789,
            "MolecularFormula": "CoLiO2",
            "MolecularWeight": 97.87,
            "IUPACName": "cobalt;lithium;oxygen(2-)",
            "CanonicalSMILES": "[Co+2].[Li+].[O-2].[O-2]",
            ...
          }
        ]
      }
    }
    """
    refs: list[PubChemReference] = []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.warning("PubChem JSON 解析失败: %s", e)
        return refs

    properties = (
        data.get("PropertyTable", {}).get("Properties", [])
        if isinstance(data, dict)
        else []
    )
    if not properties:
        return refs

    for p in properties:
        if not isinstance(p, dict):
            continue
        cid = p.get("CID", 0)
        if not cid:
            continue
        refs.append(PubChemReference(
            cid=cid,
            name=query_name,
            molecular_formula=p.get("MolecularFormula", "") or "",
            iupac_name=p.get("IUPACName", "") or "",
            canonical_smiles=p.get("CanonicalSMILES", "") or "",
            isomeric_smiles=p.get("IsomericSMILES", "") or "",
            molecular_weight=float(p.get("MolecularWeight") or 0.0),
            inchi=p.get("InChI", "") or "",
            inchikey=p.get("InChIKey", "") or "",
            url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        ))
    return refs


# ============================================================================
# PubChemClient
# ============================================================================


@dataclass
class PubChemClient:
    """PubChem API 客户端(v1.3.3-Academic M1)

    Attributes:
        timeout: 单次请求超时(秒,默认 8)
        user_agent: User-Agent 头(NIH 礼貌标识)
        enable_fallback: 真查询失败时是否降级到 mock
        max_results: 默认 max_results(每个 query)
        cache_size: LRU cache 容量(默认 128)
        enable_cache: 是否启用 LRU cache(默认 True)
        enable_gzip: 是否启用 gzip 压缩(默认 True)
        hard_max_results: max_results 硬上限保护(默认 20)
    """

    timeout: int = 8
    user_agent: str = "MatWAU/1.0 (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    cache_size: int = PUBCHEM_LRU_CACHE_DEFAULT_SIZE
    enable_cache: bool = True
    enable_gzip: bool = True
    hard_max_results: int = 20

    def __post_init__(self):
        self._cache: _LruCache | None = (
            _LruCache(capacity=self.cache_size) if self.enable_cache else None
        )

    def _cache_key(self, query: str, max_results: int) -> str:
        return f"{query.strip()}|{max_results}"

    def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
    ) -> tuple[list[PubChemReference], bool]:
        """查 PubChem,返回 (refs, is_real_query)

        Args:
            query: 化学式 / 名字 / CID
            max_results: 最多返回多少条(默认 self.max_results,硬上限 20)

        Returns:
            (refs, is_real_query)
            - is_real_query=True:真 PubChem 返回(或 cache hit)
            - is_real_query=False:fallback mock
        """
        max_results = max_results or self.max_results
        if max_results > self.hard_max_results:
            logger.warning(
                "PubChem max_results=%d 超硬上限 %d, 截断",
                max_results, self.hard_max_results,
            )
            max_results = self.hard_max_results

        # LRU cache 命中
        cache_key = self._cache_key(query, max_results)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("PubChem cache hit: %s", cache_key)
                return cached, True

        name = _build_pubchem_query(query)
        if not name:
            return [], False

        url = (
            f"{PUBCHEM_API_URL}/compound/name/{urllib.parse.quote(name)}"
            f"/property/{PUBCHEM_PROPERTIES}/JSON"
        )

        try:
            headers = {"User-Agent": self.user_agent}
            if self.enable_gzip:
                headers["Accept-Encoding"] = "gzip"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"PubChem 返回 {resp.status}")
                raw_bytes = resp.read()
                content_encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in content_encoding:
                    try:
                        json_text = gzip.decompress(raw_bytes).decode(
                            "utf-8", errors="ignore"
                        )
                    except Exception as e:
                        logger.warning("PubChem gzip 解压失败: %s", e)
                        json_text = raw_bytes.decode("utf-8", errors="ignore")
                else:
                    json_text = raw_bytes.decode("utf-8", errors="ignore")

            refs = _parse_pubchem_json(json_text, name)
            if not refs:
                raise RuntimeError("PubChem 返回 0 条")

            if self._cache is not None:
                self._cache.put(cache_key, refs)

            return refs[:max_results], True

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning("PubChem 网络失败: %s", e)
        except Exception as e:
            logger.warning("PubChem 解析失败: %s", e)

        return [], False

    def clear_cache(self) -> None:
        """清 LRU cache"""
        if self._cache is not None:
            self._cache.clear()


# ============================================================================
# Convenience functions
# ============================================================================


def is_pubchem_available() -> bool:
    """检查 PubChem 是否可达(轻量 ping — by name="water")"""
    try:
        url = (
            f"{PUBCHEM_API_URL}/compound/name/water/property/MolecularFormula/JSON"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "MatWAU/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def search_pubchem(
    query: str,
    *,
    max_results: int = 5,
    client: PubChemClient | None = None,
) -> tuple[list[PubChemReference], bool]:
    """便利函数:查 PubChem

    Returns:
        (refs, is_real_query)
    """
    c = client or PubChemClient()
    return c.search(query, max_results=max_results)


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
]  # type: ignore[name-defined]