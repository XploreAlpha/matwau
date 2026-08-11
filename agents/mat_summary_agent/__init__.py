"""mat_summary_agent — MatWAU v1.4.2-Academic 新增 agent

职责:
- 接收 user_intent(可以是 "介绍 X"、"什么是 Y"、"compare A 和 B" 等)
- 通过 OpenAI 兼容 LLM(默认 DeepSeek,per MATWAU_LLM_BASE_URL)生成 Markdown 回答
- 包成 matwau_markdown widget 走统一 widget 协议
- Fail-soft:无 API key / LLM 异常 → 返回空 widgets,让 orchestrator 走其他分支

与 v1.4.2-Academic 5 widget(化合物/期刊/物性/全文/跨源)的边界:
- paper_list / compound_list / journal_list / property_table / paper_fulltext 走结构化数据
- cross_source_summary 走多源聚合
- markdown widget 走 free-form LLM 合成 — 用于"无外部数据可查"或"概念解释"类查询

设计原则(per MatWAU-Harness-Loop 心法):
- **失败吞掉**:任何异常 → 返回空 widgets,不阻断 orchestrator
- **可选依赖**:openai 包未装 → LLMClient 仍可构造,只 generate() 抛 SkippedError
- **不污染 act()**:默认 enable_llm=False,显式开启
- **可注入**:测试可传 fake_llm_client 走 mock 路径

per MatWAU-v1.4.2-Academic-dev-plan-20260811.md §Layer 2.3
"""
from __future__ import annotations

from .mat_summary_agent import (
    MatSummaryAgent,
    SummaryAgentConfig,
    SummaryLLMClient,
    OpenAICompatibleSummaryLLMClient,
    create_default_agent,
)

__all__ = [
    "MatSummaryAgent",
    "SummaryAgentConfig",
    "SummaryLLMClient",
    "OpenAICompatibleSummaryLLMClient",
    "create_default_agent",
]
