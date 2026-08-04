"""mat_nomad_agent — NOMAD archive 综合数据查询 wrapper agent(v1.3-Academic M2)

负责把 NomadClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_critic 跨源规则使用。

能力:
1. 解析 user_intent → 化学式(NomadClient._build_nomad_query 复用)
2. 调 NomadClient.search 拉 archive entry + 标准化 metainfo 字段
3. 转 AgentResponse(records + canonical_key + metainfo_unmapped + sources)
4. confidence 启发(同 oqmd / cod)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 7-8 项
"""

from .mat_nomad_agent import (
    MatNomadAgent,
    NomadConfig,
    create_default_agent,
)

__all__ = [
    "MatNomadAgent",
    "NomadConfig",
    "create_default_agent",
]