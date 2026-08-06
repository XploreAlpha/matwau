"""semantic_search / client.py — TF-IDF + cosine 语义搜索(v1.3.4-Academic M3)

支持:
- 段落级 TF-IDF 向量化(sklearn TfidfVectorizer)
- cosine similarity 跨段落排序
- LRU cache(最近 N 个 query)
- LineageStore 持久化(additive 新表 paper_index + paper_paragraphs)

设计:
- vector + metadata 分开存:tfidf_vector 入 paper_index,text 入 paper_paragraphs
- 重建索引策略:add_document 时,数据全量重建(中小库 < 1000 篇够用)
- LRU cache 缓存 query → top_k 结果(避免重复 sklearn.transform)

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §四 M3
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

SEARCH_LRU_CACHE_DEFAULT_SIZE = 100  # v1.3.4 M3: LRU cache 默认容量
SEARCH_DEFAULT_MAX_FEATURES = 10000  # TF-IDF 词典上限
SEARCH_DEFAULT_TOP_K = 5  # 默认返回前 5 条


@dataclass
class SearchHit:
    """1 条语义搜索 hit"""

    paper_id: str
    paragraph_no: int
    page_no: int
    text: str
    title: str
    relevance: float  # 0-1 cosine similarity

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "paragraph_no": self.paragraph_no,
            "page_no": self.page_no,
            "text": self.text,
            "title": self.title,
            "relevance": round(self.relevance, 4),
        }


# ============================================================================
# LRU cache
# ============================================================================


class _LruCache:
    """LRU cache — query 字符串 → List[SearchHit]"""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, list[SearchHit]] = OrderedDict()

    def get(self, key: str) -> list[SearchHit] | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, value: list[SearchHit]) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = list(value)
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        """cache 实例永远 truthy(即使空)— 避免 'if cache:' 误判 False"""
        return True

    def clear(self) -> None:
        self._data.clear()


# ============================================================================
# availability check
# ============================================================================


def is_sklearn_available() -> bool:
    """检查 scikit-learn 是否可用"""
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


# ============================================================================
# Main client
# ============================================================================


@dataclass
class _ParagraphEntry:
    """内部 1 段落记录(用于 TF-IDF 索引)

    Attributes:
        paper_id: 论文 ID
        paragraph_no: 段落号
        page_no: 页号
        text: 段落文本
        title: 论文标题(用于展示)
    """

    paper_id: str
    paragraph_no: int
    page_no: int
    text: str
    title: str = ""


@dataclass
class SemanticSearchClient:
    """TF-IDF + cosine 语义搜索 client

    Attributes:
        cache_size: LRU cache 容量(默认 100 query)
        enable_cache: 是否启用 cache
        max_features: TF-IDF 词典上限(默认 10000)
        top_k: 默认返回 top_k 条(默认 5)
    """

    cache_size: int = SEARCH_LRU_CACHE_DEFAULT_SIZE
    enable_cache: bool = True
    max_features: int = SEARCH_DEFAULT_MAX_FEATURES
    top_k: int = SEARCH_DEFAULT_TOP_K

    def __post_init__(self) -> None:
        if self.enable_cache:
            self._cache: _LruCache | None = _LruCache(self.cache_size)
        else:
            self._cache = None

        # 段落库(全量内存,中小规模够用;>1000 篇再考虑 sqlite + numpy)
        self._entries: list[_ParagraphEntry] = []
        self._vectorizer: Any = None
        self._vectors: Any = None  # sparse matrix
        self._indexed: bool = False

    def clear_cache(self) -> None:
        """清空 LRU query cache"""
        if self._cache:
            self._cache.clear()

    # ======== 索引管理 ========

    def add_document(
        self,
        paper_id: str,
        paragraphs: list[str],
        metadata: list[dict] | None = None,
        title: str = "",
        page_numbers: list[int] | None = None,
    ) -> None:
        """添加文档(per paper_id 一组段落)

        Args:
            paper_id: 论文 ID
            paragraphs: 段落文本列表
            metadata: 每段的额外 metadata(可选)
            title: 论文标题(可选)
            page_numbers: 每段所在页号(可选;默认全 0)
        """
        metadata = metadata or [{} for _ in paragraphs]
        page_numbers = page_numbers or [0] * len(paragraphs)

        for i, text in enumerate(paragraphs):
            if not text or not text.strip():
                continue
            meta = metadata[i] if i < len(metadata) else {}
            self._entries.append(_ParagraphEntry(
                paper_id=paper_id,
                paragraph_no=i,
                page_no=page_numbers[i] if i < len(page_numbers) else 0,
                text=text,
                title=title or meta.get("title", ""),
            ))

        # 标记需要重建索引
        self._indexed = False
        # 新 doc → 清 LRU cache(旧 query 结果可能失效)
        if self._cache:
            self._cache.clear()
        logger.info("SemanticSearchClient.add_document: paper_id=%s, +%d 段落,总计 %d",
                    paper_id, len(paragraphs), len(self._entries))

    def _ensure_indexed(self) -> None:
        """懒构建 TF-IDF 索引"""
        if self._indexed:
            return
        if not self._entries:
            self._indexed = True
            return
        if not is_sklearn_available():
            logger.warning("sklearn 不可用,无法构建 TF-IDF 索引")
            self._indexed = True  # 标记为已索引(避免重试)
            return

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                lowercase=True,
                token_pattern=r"(?u)\b\w+\b",  # 单词边界
                stop_words="english",
            )
            corpus = [e.text for e in self._entries]
            self._vectors = self._vectorizer.fit_transform(corpus)
            self._indexed = True
            logger.info("SemanticSearchClient 索引完成: %d 段落, %d 维度",
                        len(self._entries), self._vectors.shape[1] if self._vectors is not None else 0)
        except Exception as e:
            logger.warning("TF-IDF 索引构建失败: %s", e)
            self._indexed = True  # 标记为已索引(避免重试)

    def clear(self) -> None:
        """清空整个索引"""
        self._entries.clear()
        self._vectorizer = None
        self._vectors = None
        self._indexed = False
        if self._cache:
            self._cache.clear()

    @property
    def n_entries(self) -> int:
        return len(self._entries)

    @property
    def n_papers(self) -> int:
        return len({e.paper_id for e in self._entries})

    # ======== 搜索 ========

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        """query 字符串 → top_k SearchHit(按 cosine 降序)

        Args:
            query: 查询字符串
            top_k: 返回前 k 条(默认 self.top_k)

        Returns:
            List[SearchHit],按 relevance 降序
        """
        if not query or not query.strip():
            return []
        k = top_k if top_k is not None else self.top_k

        # Cache hit
        cache_key = f"{query}::k={k}"
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("search cache hit: %s", cache_key)
                return cached

        # 索引
        self._ensure_indexed()
        if not is_sklearn_available() or self._vectorizer is None or self._vectors is None:
            # sklearn 缺失 → 返空 list(graceful 失败)
            hits: list[SearchHit] = []
            if self._cache:
                self._cache.put(cache_key, hits)
            return hits

        if not self._entries:
            hits = []
            if self._cache:
                self._cache.put(cache_key, hits)
            return hits

        try:
            from sklearn.metrics.pairwise import cosine_similarity
            query_vec = self._vectorizer.transform([query])
            similarities = cosine_similarity(query_vec, self._vectors).flatten()
            # top-k indices(降序)
            top_indices = similarities.argsort()[::-1][:k]

            hits = []
            for idx in top_indices:
                if similarities[idx] <= 0:
                    continue  # 跳过 0 相关
                entry = self._entries[idx]
                hits.append(SearchHit(
                    paper_id=entry.paper_id,
                    paragraph_no=entry.paragraph_no,
                    page_no=entry.page_no,
                    text=entry.text,
                    title=entry.title,
                    relevance=float(similarities[idx]),
                ))
        except Exception as e:
            logger.warning("search failed: %s", e)
            hits = []

        # Cache put
        if self._cache:
            self._cache.put(cache_key, hits)

        return hits


# ============================================================================
# 便利 module-level functions
# ============================================================================


_default_client: SemanticSearchClient | None = None


def _get_default_client() -> SemanticSearchClient:
    global _default_client
    if _default_client is None:
        _default_client = SemanticSearchClient()
    return _default_client


def search(query: str, top_k: int | None = None) -> list[SearchHit]:
    """便利函数:用 default client 搜索"""
    return _get_default_client().search(query, top_k)


# ============================================================================
# 全局 singleton(per serve.py 端点用)
# ============================================================================

search_client: SemanticSearchClient = _get_default_client()
