"""mat_jarvis_agent — JARVIS 综合材料性质查询 wrapper agent(v1.3-Academic M2)

负责把 JarvClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_critic 跨源规则使用。

能力:
1. 解析 user_intent → 化学式(JarvClient._build_jarvis_query 复用)
2. 调 JarvClient.search 拉 JARVIS 3D / 2D 材料 entry
3. 可选 filter 2D-only(per include_2d_only 配置)
4. 检测 jarvis-tools 包状态(降级到纯 REST 仍可工作)
5. 转 AgentResponse(records + canonical_key + 2D/3D 标记 + sources)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 7-8 项
"""

from .mat_jarvis_agent import (
    JarvConfig,
    MatJarvAgent,
    create_default_agent,
)

__all__ = [
    "JarvConfig",
    "MatJarvAgent",
    "create_default_agent",
]