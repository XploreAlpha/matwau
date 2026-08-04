"""mat_cod_agent — COD 实验晶体结构查询 wrapper agent(v1.3-Academic M1)

负责把 CodClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_critic 跨源规则使用。

能力:
1. 解析 user_intent → 化学式(CodClient._build_cod_query 复用)
2. 调 CodClient.search 拉实验晶体结构 + 空间群 + 晶格常数
3. 拉 CIF 文本(CodClient.fetch_cif)
4. 转 AgentResponse(records + canonical_key + sources)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 7-8 项
"""

from .mat_cod_agent import (  # noqa: F401
    MatCodAgent,
    CodConfig,
    create_default_agent,
)

__all__ = [
    "MatCodAgent",
    "CodConfig",
    "create_default_agent",
]