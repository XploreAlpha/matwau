"""semantic_search — 本地 TF-IDF 语义搜索(v1.3.4-Academic M3)

支持:
- 段落级 TF-IDF 向量化(sklearn TfidfVectorizer)
- cosine similarity 跨段落排序
- LRU cache(最近 N 个 query)
- LineageStore 持久化(additive 新表 paper_index + paper_paragraphs)

为什么 TF-IDF 而非 sentence-transformers:
- 学院服务器无 GPU
- sentence-transformers 要 torch(~2GB)
- TF-IDF + sklearn(~30MB)够用,且纯 numpy,可解释
- 真 embedding 模型给 v2.0 阶段 1

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §四 M3
"""
from __future__ import annotations

from .client import (
    SEARCH_LRU_CACHE_DEFAULT_SIZE,
    SearchHit,
    SemanticSearchClient,
    _LruCache,
    is_sklearn_available,
    search,
    search_client,
)

__all__ = [
    "SEARCH_LRU_CACHE_DEFAULT_SIZE",
    "SearchHit",
    "SemanticSearchClient",
    "_LruCache",
    "is_sklearn_available",
    "search",
    "search_client",
]
