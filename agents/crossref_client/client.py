"""crossref_client / client.py — CrossRef API 真接入(v1.3.3-Academic M2)

支持:
- 真查 CrossRef works API(无需 API key,公共元数据)
- 失败 fallback(连接失败 / timeout / parse 错误)
- LRU cache + gzip 压缩 + 硬上限(per v1.3.2 模板)
- DOI / title / author / journal / year / citations 查询

CrossRef API 文档:https://api.crossref.org/swagger-ui/index.html

查询 URL 模板:
GET /works?query.bibliographic={query}&rows={rows}&mailto={mailto}

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §四 M2
"""
from __future__ import annotations

import gzip
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CROSSREF_API_URL = "https://api.crossref.org"
CROSSREF_TIMEOUT_SEC = 10  # CrossRef 响应慢,10s
CROSSREF_LRU_CACHE_DEFAULT_SIZE = 128  # v1.3.3 M2: LRU cache 默认容量


# ============================================================================
# CrossRefReference dataclass
# ============================================================================


@dataclass
class CrossRefReference:
    """1 篇 CrossRef 论文

    Attributes:
        doi: DOI(如 "10.1038/nature12373")
        title: 论文标题
        authors: 作者列表
        year: 出版年份
        journal: 期刊名(container-title[0])
        volume: 卷
        issue: 期
        pages: 页
        publisher: 出版商
        type: 类型("journal-article" / "book-chapter" / ...)
        citations_count: 被引次数
        url: DOI URL
        abstract: 摘要(如有,JATS XML → plain text)
    """

    doi: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 2024
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    type: str = ""
    citations_count: int = 0
    url: str = ""
    abstract: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "publisher": self.publisher,
            "type": self.type,
            "citations_count": self.citations_count,
            "url": self.url,
            "abstract": self.abstract[:300],
        }


# ============================================================================
# LRU cache(per v1.3.2 模板)
# ============================================================================


class _LruCache:
    """线程不安全 LRU cache"""

    def __init__(self, capacity: int = CROSSREF_LRU_CACHE_DEFAULT_SIZE):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, list[CrossRefReference]] = OrderedDict()

    def get(self, key: str) -> list[CrossRefReference] | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, refs: list[CrossRefReference]) -> None:
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


def _build_crossref_query(user_intent: str) -> str:
    """构造 CrossRef query.bibliographic 字符串

    CrossRef bibliographic query 接受自由文本。直接用 user_intent 原句
    (URL encoded)。化学式 / alias 提取由 CrossRef 服务端做。

    Examples:
        "LiCoO2 锂离子电池" → "LiCoO2 锂离子电池"
        "lithium-ion cathode" → "lithium-ion cathode"
    """
    return user_intent.strip()[:200]  # CrossRef 限制 ~200 字符


# ============================================================================
# JSON 解析
# ============================================================================


def _extract_year(issued: dict | list | None) -> int:
    """从 CrossRef issued.date-parts 提取年份"""
    if not isinstance(issued, dict):
        return 2024
    date_parts = issued.get("date-parts", [])
    if isinstance(date_parts, list) and date_parts:
        first = date_parts[0]
        if isinstance(first, list) and first:
            try:
                return int(first[0])
            except (ValueError, TypeError):
                return 2024
    return 2024


def _extract_authors(author_list: list | None) -> list[str]:
    """从 CrossRef author 数组提取名字"""
    if not isinstance(author_list, list):
        return []
    names = []
    for a in author_list:
        if not isinstance(a, dict):
            continue
        given = a.get("given", "") or ""
        family = a.get("family", "") or ""
        full = f"{given} {family}".strip()
        if full:
            names.append(full)
    return names


def _strip_jats_xml(text: str) -> str:
    """简单 strip JATS XML 标签(abstract 可能含 XML)"""
    import re
    # 移除所有 XML 标签
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_crossref_json(
    json_text: str, query: str
) -> list[CrossRefReference]:
    """解析 CrossRef works API JSON → List[CrossRefReference]

    Response format (per docs):
    {
      "status": "ok",
      "message": {
        "items": [
          {
            "DOI": "10.1038/nature12373",
            "title": ["Title"],
            "author": [{"given": "...", "family": "..."}],
            "container-title": ["Journal Name"],
            "issued": {"date-parts": [[2024, 1, 15]]},
            "volume": "525",
            "issue": "7568",
            "page": "65-68",
            "publisher": "Nature Publishing Group",
            "type": "journal-article",
            "is-referenced-by-count": 123,
            "abstract": "<jats:p>...</jats:p>"  # 可选
          }
        ]
      }
    }
    """
    refs: list[CrossRefReference] = []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.warning("CrossRef JSON 解析失败: %s", e)
        return refs

    items = data.get("message", {}).get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return refs

    for item in items:
        if not isinstance(item, dict):
            continue
        doi = item.get("DOI", "")
        if not doi:
            continue
        titles = item.get("title", [])
        title = titles[0] if titles and isinstance(titles[0], str) else ""
        journals = item.get("container-title", [])
        journal = journals[0] if journals and isinstance(journals[0], str) else ""

        abstract_raw = item.get("abstract", "") or ""
        abstract = _strip_jats_xml(abstract_raw)

        refs.append(CrossRefReference(
            doi=doi,
            title=title,
            authors=_extract_authors(item.get("author")),
            year=_extract_year(item.get("issued")),
            journal=journal,
            volume=str(item.get("volume", "") or ""),
            issue=str(item.get("issue", "") or ""),
            pages=str(item.get("page", "") or ""),
            publisher=str(item.get("publisher", "") or ""),
            type=str(item.get("type", "") or ""),
            citations_count=int(item.get("is-referenced-by-count") or 0),
            url=f"https://doi.org/{doi}",
            abstract=abstract,
        ))
    return refs


# ============================================================================
# CrossRefClient
# ============================================================================


@dataclass
class CrossRefClient:
    """CrossRef API 客户端(v1.3.3-Academic M2)

    Attributes:
        timeout: 单次请求超时(秒,默认 10)
        user_agent: User-Agent 头
        mailto: 联系邮箱(per CrossRef etiquette,标识礼貌使用)
        enable_fallback: 真查询失败时是否降级到 mock
        max_results: 默认 max_results
        cache_size: LRU cache 容量(默认 128)
        enable_cache: 是否启用 LRU cache
        enable_gzip: 是否启用 gzip
        hard_max_results: max_results 硬上限(默认 20)
    """

    timeout: int = 10
    user_agent: str = "MatWAU/1.0 (research; mailto:contact@matwau.local)"
    mailto: str = "contact@matwau.local"  # CrossRef etiquette
    enable_fallback: bool = True
    max_results: int = 5
    cache_size: int = CROSSREF_LRU_CACHE_DEFAULT_SIZE
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
    ) -> tuple[list[CrossRefReference], bool]:
        """查 CrossRef,返回 (refs, is_real_query)

        Args:
            query: 文献查询字符串(自由文本)
            max_results: 最多返回多少篇(默认 self.max_results,硬上限 20)

        Returns:
            (refs, is_real_query)
            - is_real_query=True:真 CrossRef 返回(或 cache hit)
            - is_real_query=False:fallback mock
        """
        max_results = max_results or self.max_results
        if max_results > self.hard_max_results:
            logger.warning(
                "CrossRef max_results=%d 超硬上限 %d, 截断",
                max_results, self.hard_max_results,
            )
            max_results = self.hard_max_results

        cache_key = self._cache_key(query, max_results)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("CrossRef cache hit: %s", cache_key)
                return cached, True

        bibliographic = _build_crossref_query(query)
        if not bibliographic:
            return [], False

        url = (
            f"{CROSSREF_API_URL}/works"
            f"?query.bibliographic={urllib.parse.quote(bibliographic)}"
            f"&rows={max_results}"
            f"&mailto={urllib.parse.quote(self.mailto)}"
        )

        try:
            headers = {"User-Agent": self.user_agent}
            if self.enable_gzip:
                headers["Accept-Encoding"] = "gzip"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"CrossRef 返回 {resp.status}")
                raw_bytes = resp.read()
                content_encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in content_encoding:
                    try:
                        json_text = gzip.decompress(raw_bytes).decode(
                            "utf-8", errors="ignore"
                        )
                    except Exception as e:
                        logger.warning("CrossRef gzip 解压失败: %s", e)
                        json_text = raw_bytes.decode("utf-8", errors="ignore")
                else:
                    json_text = raw_bytes.decode("utf-8", errors="ignore")

            refs = _parse_crossref_json(json_text, bibliographic)
            if not refs:
                raise RuntimeError("CrossRef 返回 0 条")

            if self._cache is not None:
                self._cache.put(cache_key, refs)

            return refs[:max_results], True

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning("CrossRef 网络失败: %s", e)
        except Exception as e:
            logger.warning("CrossRef 解析失败: %s", e)

        return [], False

    def clear_cache(self) -> None:
        if self._cache is not None:
            self._cache.clear()


# ============================================================================
# Convenience functions
# ============================================================================


def is_crossref_available() -> bool:
    """检查 CrossRef 是否可达(轻量 ping — bibliographic=hello)"""
    try:
        url = (
            f"{CROSSREF_API_URL}/works?query.bibliographic=hello"
            f"&rows=1&mailto=contact@matwau.local"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "MatWAU/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def search_crossref(
    query: str,
    *,
    max_results: int = 5,
    client: CrossRefClient | None = None,
) -> tuple[list[CrossRefReference], bool]:
    """便利函数:查 CrossRef

    Returns:
        (refs, is_real_query)
    """
    c = client or CrossRefClient()
    return c.search(query, max_results=max_results)


__all__ = [
    "CROSSREF_API_URL",
    "CROSSREF_LRU_CACHE_DEFAULT_SIZE",
    "CrossRefClient",
    "CrossRefReference",
    "_LruCache",
    "_build_crossref_query",
    "_extract_year",
    "_extract_authors",
    "_strip_jats_xml",
    "_parse_crossref_json",
    "is_crossref_available",
    "search_crossref",
]  # type: ignore[name-defined]