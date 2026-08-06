"""mat_arxiv_agent — arXiv 文献数据查询 wrapper agent(v1.3.2-Academic M2)

负责把 ArxivClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_lit_agent / literature_review workflow 使用。

能力:
1. 解析 user_intent → arxiv search_query(per ArxivClient._build_arxiv_query)
2. 调 ArxivClient.search 拉文献(LRU cache 自动复用)
3. 转 AgentResponse(records + is_real_query flag + confidence + cost)
4. 默认 confidence 启发式(per n_results: 0→0.3, 1-2→0.6, ≥3→0.8)
5. 默认走真 arXiv API(v1.3.2),失败 fallback(向后兼容)
6. 与 mat_oqmd_agent / mat_cod_agent / mat_nomad_agent / mat_jarvis_agent 模式对齐

per MatWAU-v1.3.2-Academic-dev-plan-20260806.md §三 M2
"""

from .mat_arxiv_agent import (
    ArxivAgentConfig,
    MatArxivAgent,
    create_default_agent,
)

__all__ = [
    "ArxivAgentConfig",
    "MatArxivAgent",
    "create_default_agent",
]