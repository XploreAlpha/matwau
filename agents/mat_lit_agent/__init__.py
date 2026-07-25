"""mat-lit-agent — 材料科学文献综述员

替换 mat-orchestrator literature_review workflow 的 StubAgent(per W14 拍板)。

能力:
1. 解析 user_intent → LitQuery(化学式 + 材料别名 + 属性 + 领域)
2. 检索 mock 数据库(arXiv / Materials Project / ICSD / PubChem)
3. 生成综述 4 部分:background + state_of_art + gaps + suggestions
4. 算 confidence 分 + top-N 文献

Stage 1: 纯 mock + 关键词 + 模板
Stage 2: 接 arXiv + Materials Project + ICSD + PubChem 真 API

per MatWAU-开发计划 §七 W14
"""
from .lit_engine import (
    LitQuery,
    LitReference,
    LitReview,
    MATERIAL_ALIASES,
    parse_lit_query,
    review_literature,
    search_literature,
)
from .mat_lit_agent import (
    LitConfig,
    MatLitAgent,
    create_default_agent,
)

__all__ = [
    "MatLitAgent",
    "LitConfig",
    "LitQuery",
    "LitReference",
    "LitReview",
    "create_default_agent",
    "MATERIAL_ALIASES",
    "parse_lit_query",
    "review_literature",
    "search_literature",
]