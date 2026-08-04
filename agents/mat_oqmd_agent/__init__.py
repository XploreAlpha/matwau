"""mat_oqmd_agent — OQMD 数据查询 wrapper agent(v1.3-Academic M1)

负责把 OqmdClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_critic 跨源规则使用。

能力:
1. 解析 user_intent → 化学式(OqmdClient._build_oqmd_query 复用)
2. 调 OqmdClient.search 拉 DFT 形成焓 + 凸包距离 + 体积
3. 转 AgentResponse(records + canonical_key + sources)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 5-6 项
"""

from .mat_oqmd_agent import (  # noqa: F401
    MatOqmdAgent,
    OqmdConfig,
    create_default_agent,
)

__all__ = [
    "MatOqmdAgent",
    "OqmdConfig",
    "create_default_agent",
]