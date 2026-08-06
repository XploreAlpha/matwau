"""mat_crossref_agent — CrossRef 期刊 DOI 元数据查询 wrapper agent(v1.3.3-Academic M2)

负责把 CrossRefClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_lit_agent / /literature 端点使用。

能力:
1. 解析 user_intent → 自由文本(CrossRef bibliographic query)
2. 调 CrossRefClient.search 拉 DOI + journal + citations(LRU cache 自动复用)
3. 转 AgentResponse(records + is_real_query flag + confidence + cost)
4. 默认 confidence 启发式(n_results: 0→0.3, 1→0.6, ≥2→0.8)
5. 默认走真 CrossRef API(v1.3.3),失败 fallback(向后兼容)
6. 与 mat_arxiv_agent / mat_pubchem_agent / 4 平台模式对齐

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §四 M2
"""

from .mat_crossref_agent import (
    CrossRefAgentConfig,
    MatCrossRefAgent,
    create_default_agent,
)

__all__ = [
    "CrossRefAgentConfig",
    "MatCrossRefAgent",
    "create_default_agent",
]