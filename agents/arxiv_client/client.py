"""arxiv_client / client.py — arXiv API 真接入(W16) + LRU cache(v1.3.2-Academic)

支持:
- 真查 arXiv(urllib + Atom XML 解析)
- 失败 fallback(连接失败 / timeout / parse 错误)
- 3 域关键词构造(per W15 MaterialDomainRouter)
- LRU cache(per v1.3.2-Academic M1)— 同 query < 1ms 命中
- gzip 解压(per v1.3.2-Academic M1)— 大响应省流量

arXiv API 文档:https://info.arxiv.org/help/api/basics.html

Stage 1 行为(W14): mock DB
Stage 2 行为(W16): 默认真查 arXiv,失败 fallback
Stage 2.1 行为(v1.3.2): 加 LRU cache + gzip 支持

per MatWAU-v1.3.2-Academic-dev-plan-20260806.md §三 M1
"""
from __future__ import annotations

import gzip
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_NAMESPACE = "{http://www.w3.org/2005/Atom}"
ARXIV_TIMEOUT_SEC = 8  # 单次 query timeout
ARXIV_LRU_CACHE_DEFAULT_SIZE = 128  # v1.3.2 M1: LRU cache 默认容量


@dataclass
class ArxivReference:
    """1 篇 arXiv 论文的引用(per W14 LitReference 子集)

    Attributes:
        arxiv_id: arXiv ID(如 "2401.12345")
        title: 论文标题
        authors: 作者列表
        year: 出版年份
        summary: 摘要(前 1000 字符)
        url: arXiv URL
        categories: arXiv 分类列表
    """

    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 2024
    summary: str = ""
    url: str = ""
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "summary": self.summary[:200],
            "url": self.url,
            "categories": self.categories,
        }


# ============================================================================
# v1.3.2-Academic M1: LRU cache(per mat-arxiv 复用 nomad_client 模式)
# ============================================================================


class _LruCache:
    """线程不安全 LRU cache(per nomad_client 实现)

    MatWAU 调用都是单线程 OK;若多线程需外加 threading.Lock。

    Attributes:
        _capacity: 最大容量
        _data: OrderedDict(key → list[ArxivReference])
    """

    def __init__(self, capacity: int = ARXIV_LRU_CACHE_DEFAULT_SIZE):
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, list[ArxivReference]] = OrderedDict()

    def get(self, key: str) -> list[ArxivReference] | None:
        """cache hit → 返回 + move to end(LRU 维护);miss → None"""
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, refs: list[ArxivReference]) -> None:
        """写入 + 超容量时 pop 最旧"""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = list(refs)
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)  # FIFO pop 最旧

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        """清空(per 测试用)"""
        self._data.clear()


def is_arxiv_available() -> bool:
    """检查 arXiv 是否可达(轻量 ping)"""
    try:
        url = ARXIV_API_URL + "?" + urllib.parse.urlencode({
            "search_query": "all:test",
            "max_results": "1",
        })
        req = urllib.request.Request(url, headers={"User-Agent": "MatWAU/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _parse_arxiv_xml(xml_text: str) -> list[ArxivReference]:
    """解析 arXiv Atom XML → List[ArxivReference]

    Args:
        xml_text: arXiv API 返回的 XML 文本

    Returns:
        论文列表
    """
    refs = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("arXiv XML 解析失败: %s", e)
        return refs

    for entry in root.findall(f"{ARXIV_NAMESPACE}entry"):
        arxiv_id = ""
        id_el = entry.find(f"{ARXIV_NAMESPACE}id")
        if id_el is not None and id_el.text:
            # URL 形式: http://arxiv.org/abs/2401.12345v1
            m = re.search(r"abs/([\d.]+)", id_el.text)
            if m:
                arxiv_id = m.group(1)

        title_el = entry.find(f"{ARXIV_NAMESPACE}title")
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""

        summary_el = entry.find(f"{ARXIV_NAMESPACE}summary")
        summary = summary_el.text.strip() if summary_el is not None and summary_el.text else ""

        published_el = entry.find(f"{ARXIV_NAMESPACE}published")
        year = 2024
        if published_el is not None and published_el.text:
            m = re.search(r"(\d{4})", published_el.text)
            if m:
                year = int(m.group(1))

        authors = []
        for author_el in entry.findall(f"{ARXIV_NAMESPACE}author"):
            name_el = author_el.find(f"{ARXIV_NAMESPACE}name")
            if name_el is not None and name_el.text:
                authors.append(name_el.text)

        categories = []
        for cat_el in entry.findall(f"{ARXIV_NAMESPACE}category"):
            term = cat_el.get("term")
            if term:
                categories.append(term)

        if arxiv_id and title:
            refs.append(ArxivReference(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                year=year,
                summary=summary,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                categories=categories,
            ))

    return refs


def _build_arxiv_query(user_intent: str, *, domain: str | None = None) -> str:
    """构造 arXiv search_query

    策略:
    - 提取引号内容 / 大写 alias / 化学式 → 高优先级字段
    - 简化成 arXiv 兼容的 search_query
    - domain-specific 关键词加权(per W15 MaterialDomainRouter)

    Examples:
        "出 LiCoO2 实验方案" → ti:LiCoO2 OR abs:LiCoO2
        "算 PMMA 玻璃化转变温度" → ti:PMMA AND ti:glass
        "设计 CdSe 量子点" → ti:CdSe AND ti:quantum
    """
    msg = user_intent

    # 提取化学式(简单规则:大写 + 小写 + 数字,如 LiCoO2 / CdSe / PMMA)
    formulas = re.findall(r"\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+\b|\b[A-Z][a-z]?\d{2,}\b", msg)
    formulas = [f for f in formulas if len(f) >= 4]  # 过滤太短的(如 Li)

    # 提取大写 alias(LLZO / LFP / NMC / ...)
    aliases = re.findall(r"\b[A-Z]{2,6}[0-9]{0,4}\b", msg)
    aliases = [a for a in aliases if a not in formulas and len(a) >= 3]

    # 提取属性词(per domain keyword 库,简化)
    prop_keywords = []
    domain_keywords_map = {
        "inorganic_crystal": ["ionic conductivity", "lattice", "DFT", "formation energy", "cathode"],
        "polymer": ["glass transition", "Tg", "tensile strength", "polymer", "PMMA"],
        "nano": ["quantum dot", "graphene", "MoS2", "nanoparticle", "BET"],
    }
    msg_lower = msg.lower()
    for kw in domain_keywords_map.get(domain or "inorganic_crystal", []):
        if kw.lower() in msg_lower:
            prop_keywords.append(kw)

    # 构造 query
    parts = []
    if formulas:
        for f in formulas[:3]:  # 最多 3 个化学式
            parts.append(f'(ti:{f} OR abs:{f})')
    if aliases:
        for a in aliases[:3]:
            parts.append(f'(ti:{a} OR abs:{a})')
    if prop_keywords:
        for kw in prop_keywords[:2]:
            parts.append(f'(ti:"{kw}" OR abs:"{kw}")')

    # 兜底:用整句作为 abs 兜底搜索
    if not parts:
        # 用最关键的几个词
        words = re.findall(r"\b[A-Za-z]{3,}\b|\b[一-鿿]{2,}\b", msg)
        if words:
            parts.append(f'(abs:"{words[0]}")')

    return " OR ".join(parts) if parts else "all:" + msg[:50]


@dataclass
class ArxivClient:
    """arXiv API 客户端(W16 Stage 2 真接入 + v1.3.2 LRU cache + gzip)

    Attributes:
        timeout: 单次请求超时(秒,默认 8)
        user_agent: User-Agent 头(arXiv 要求标识)
        enable_fallback: 真查询失败时是否降级到 mock
        max_results: 默认 max_results(每个 query)
        cache_size: v1.3.2 LRU cache 容量(默认 128)
        enable_cache: v1.3.2 是否启用 LRU cache(默认 True)
        enable_gzip: v1.3.2 是否启用 gzip 压缩(默认 True)
        hard_max_results: v1.3.2 max_results 上限保护(防滥用,默认 20)
    """

    timeout: int = 8
    user_agent: str = "MatWAU/1.0 (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    cache_size: int = ARXIV_LRU_CACHE_DEFAULT_SIZE  # v1.3.2 M1
    enable_cache: bool = True  # v1.3.2 M1
    enable_gzip: bool = True  # v1.3.2 M1
    hard_max_results: int = 20  # v1.3.2 M1: arxiv max_results 上限保护

    def __post_init__(self):
        """初始化 LRU cache(v1.3.2 M1)"""
        self._cache: _LruCache | None = (
            _LruCache(capacity=self.cache_size) if self.enable_cache else None
        )

    def _cache_key(self, user_intent: str, max_results: int, domain: str | None) -> str:
        """构造 cache key(per user_intent + max_results + domain)"""
        return f"{user_intent.strip()}|{max_results}|{domain or 'default'}"

    def search(
        self,
        user_intent: str,
        *,
        max_results: int | None = None,
        domain: str | None = None,
    ) -> tuple[list[ArxivReference], bool]:
        """查 arXiv,返回 (references, is_real_query)

        Args:
            user_intent: 用户原始意图
            max_results: 最多返回多少篇(None → 用 self.max_results,超过 hard_max_results 截断)
            domain: 材料域(per W15)

        Returns:
            (refs, is_real_query)
            - is_real_query=True:真 arXiv 返回(或 LRU cache 命中)
            - is_real_query=False:fallback(网络失败 / 解析失败)
        """
        max_results = max_results or self.max_results
        # v1.3.2 M1: 硬上限保护
        if max_results > self.hard_max_results:
            logger.warning(
                "arXiv max_results=%d 超硬上限 %d, 截断",
                max_results, self.hard_max_results,
            )
            max_results = self.hard_max_results

        # v1.3.2 M1: LRU cache 命中检查
        cache_key = self._cache_key(user_intent, max_results, domain)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("arXiv cache hit: %s", cache_key)
                return cached, True

        query = _build_arxiv_query(user_intent, domain=domain)

        url = ARXIV_API_URL + "?" + urllib.parse.urlencode({
            "search_query": query,
            "max_results": str(max_results),
            "sortBy": "relevance",
            "sortOrder": "descending",
        })

        try:
            # v1.3.2 M1: 加 Accept-Encoding: gzip
            headers = {"User-Agent": self.user_agent}
            if self.enable_gzip:
                headers["Accept-Encoding"] = "gzip"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"arXiv 返回 {resp.status}")
                raw_bytes = resp.read()
                # v1.3.2 M1: gzip 解压
                content_encoding = resp.headers.get("Content-Encoding", "").lower()
                if "gzip" in content_encoding:
                    try:
                        xml_text = gzip.decompress(raw_bytes).decode("utf-8", errors="ignore")
                    except Exception as e:
                        logger.warning("arXiv gzip 解压失败: %s", e)
                        # fallback 到 raw bytes 解码
                        xml_text = raw_bytes.decode("utf-8", errors="ignore")
                else:
                    xml_text = raw_bytes.decode("utf-8", errors="ignore")

            refs = _parse_arxiv_xml(xml_text)
            if not refs:
                # arXiv 偶尔返回空(所有 entry 都解析失败)
                raise RuntimeError("arXiv 返回 0 篇")

            # v1.3.2 M1: 写入 LRU cache
            if self._cache is not None:
                self._cache.put(cache_key, refs)

            return refs[:max_results], True

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning("arXiv 网络失败: %s", e)
        except Exception as e:
            logger.warning("arXiv 解析失败: %s", e)

        # Fallback:返回空,标记 is_real_query=False(让调用方决定用 mock DB)
        return [], False

    def clear_cache(self) -> None:
        """清 LRU cache(v1.3.2 M1,per 测试 / 显式 invalidate 用)"""
        if self._cache is not None:
            self._cache.clear()


def search_arxiv(
    user_intent: str,
    *,
    max_results: int = 5,
    domain: str | None = None,
    client: ArxivClient | None = None,
) -> tuple[list[ArxivReference], bool]:
    """便利函数:查 arXiv

    Returns:
        (refs, is_real_query)
    """
    c = client or ArxivClient()
    return c.search(user_intent, max_results=max_results, domain=domain)


__all__ = [
    "ARXIV_API_URL",
    "ARXIV_LRU_CACHE_DEFAULT_SIZE",
    "ArxivClient",
    "ArxivReference",
    "is_arxiv_available",
    "search_arxiv",
]  # type: ignore[name-defined]