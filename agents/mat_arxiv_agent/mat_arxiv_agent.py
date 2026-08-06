"""mat_arxiv_agent / mat_arxiv_agent.py — arXiv wrapper(继承 MatWAUAgentBase)

业务逻辑:
1. 解析 user_intent → arxiv search_query(per ArxivClient._build_arxiv_query)
2. 调 ArxivClient.search 拉 records(自动 LRU cache 复用)
3. 转 AgentResponse(records + is_real_query + confidence + cost)
4. 默认 confidence 启发:
   - 0 records → 0.3(可能查不到)
   - 1-2 records → 0.6
   - ≥3 records → 0.8

设计:
- 与 mat_oqmd_agent / mat_cod_agent / mat_nomad_agent / mat_jarvis_agent 模式对齐
- v1.3.2 M2 默认走真 arXiv API(per dev-plan §三)
- v1.3.2 M1 LRU cache 已在 ArxivClient 内置(wrapper 无需再加)

per MatWAU-v1.3.2-Academic-dev-plan-20260806.md §三 M2
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.arxiv_client import ArxivClient, ArxivReference
from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard


# ============================================================================
# 配置
# ============================================================================


@dataclass
class ArxivAgentConfig:
    """arXiv 查询配置(per AgentRequest.context)

    Attributes:
        n_results: 期望返回多少篇(per query)
        max_results_hard_cap: arxiv max_results 硬上限(防止滥用)
        domain: 材料域(透传给 ArxivClient,per W15 MaterialDomainRouter)
        enable_cache: 是否启用 LRU cache(v1.3.2 M1)
        cache_size: LRU cache 容量(v1.3.2 M1)
    """

    n_results: int = 5
    max_results_hard_cap: int = 20
    domain: str | None = None
    enable_cache: bool = True
    cache_size: int = 128

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ArxivAgentConfig:
        if not d:
            return cls()
        n_results = int(d.get("n_results", 5))
        # 截断到硬上限
        if n_results > cls.max_results_hard_cap:
            n_results = cls.max_results_hard_cap
        return cls(
            n_results=n_results,
            domain=d.get("domain"),
            enable_cache=d.get("enable_cache", True),
            cache_size=int(d.get("cache_size", 128)),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: list[ArxivReference],
    is_real: bool,
    config: ArxivAgentConfig,
    user_intent: str,
) -> AgentResponse:
    """arXiv 查询结果 → AgentResponse

    Args:
        refs: List[ArxivReference]
        is_real: True = 真 arXiv(API / cache hit);False = fallback mock
        config: ArxivAgentConfig
        user_intent: 原始 user_intent

    Returns:
        AgentResponse 实例(标准 mat_orchestrator / mat_lit_agent 消费)
    """
    records = [r.to_dict() for r in refs]

    # confidence 启发式
    n = len(records)
    if n == 0:
        confidence = 0.3
    elif n <= 2:
        confidence = 0.6
    else:
        confidence = 0.8

    # 自然语言 reply
    source_tag = "🌐 arXiv 实时" if is_real else "🧪 arXiv mock(fallback)"
    lines = [
        f"📚 {source_tag} 文献查询: {user_intent}",
        f"   命中 {n} 篇",
    ]
    if refs:
        lines.append("\n📄 Top 论文:")
        for r in refs[:3]:
            lines.append(
                f"   [{r.year}] {r.title[:80]} | "
                f"arxiv:{r.arxiv_id} | {', '.join(r.authors[:2])}"
                + (" et al." if len(r.authors) > 2 else "")
            )
    if not is_real:
        lines.append("\n⚠️ 真 arXiv 不可达,使用本地 mock 数据(向后兼容 W14)")

    reply = "\n".join(lines)

    # arxiv 免费,无 cost,但真查 > mock 给个象征性 cost
    cost = 0.01 if is_real else 0.001

    return AgentResponse(
        reply=reply,
        artifacts={
            "records": records,
            "canonical_key": None,  # arxiv 是文献非计算数据,无 CanonicalKey
            "sources": ["arxiv"],
            "is_real_query": is_real,
            "n_results": n,
            "source_platform": "arXiv",
            "source_doi": "",  # arxiv 是 preprint,doi 在正式期刊
            "citation": "arXiv preprint (https://arxiv.org/)",
            "user_intent": user_intent,
        },
        confidence=confidence,
        cost=cost,
    )


# ============================================================================
# MatArxivAgent
# ============================================================================


class MatArxivAgent(MatWAUAgentBase):
    """mat-arxiv-agent — arXiv 文献数据查询助手(v1.3.2-Academic M2)

    业务流程:
    1. 解析 user_intent
    2. 调 ArxivClient.search(LRU cache 自动复用)
    3. 转 AgentResponse(含 source attribution + confidence + cost)
    """

    name = "mat-arxiv-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.01,
        use_real_arxiv: bool = True,
        client: ArxivClient | None = None,
        context_manager: ContextManager | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_n_results: 默认返回几条
            cost_per_query: 单次查询估算成本 ¥(arxiv 实际免费)
            use_real_arxiv: True = 真查 arXiv API(W16 Stage 2 + v1.3.2 默认),False = mock
            client: 可选注入 ArxivClient(测试用)
            context_manager / safety_guard: harness 组件
        """
        # 调用 base __init__ 接受 harness
        super().__init__(
            context_manager=context_manager,
            safety_guard=safety_guard,
            **kwargs,
        )
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_arxiv = use_real_arxiv
        # 默认构造 client(LRU cache 默认启用,per v1.3.2 M1)
        self._client = client or ArxivClient(
            max_results=default_n_results,
            enable_cache=True,
        )

        # 默认 harness(per mat_oqmd_agent 模式)
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 arXiv 文献数据查询助手(mat-arxiv-agent)。

能力:
1. 解析 user_intent → arxiv search_query(化学式 / alias / 关键词)
2. 调 arXiv API(http://export.arxiv.org/api/query)查文献
3. 返回字段包括:arxiv_id / title / authors / year / summary / categories / url
4. 支持 3 域关键词适配(inorganic_crystal / polymer / nano, per W15)
5. LRU cache(v1.3.2):同 query < 1ms 命中
6. 失败 fallback 到 mock(W14 向后兼容)

适用场景:
- "查 LLZO 离子电导率文献"
- "LiCoO2 锂离子电池 arxiv 论文"
- "CdSe 量子点最新研究"
- 任何材料科学主题的文献综述查询

约束:
- 不下载全文 PDF(版权问题,只 metadata + abstract)
- 单次返回最多 5 篇(默认),可通过 context.n_results 调整
- 真查询失败自动 fallback,不报错
- 0 行 UI 代码
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:arXiv 查询"""
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: ArxivAgentConfig = ctx.get("_input_config") or ArxivAgentConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        # 调 arxiv client
        try:
            if self.use_real_arxiv:
                # 真查(或 cache hit)— per ArxivClient.search 自动 fallback
                refs, is_real = self._client.search(
                    user_message,
                    max_results=config.n_results,
                    domain=config.domain,
                )
            else:
                # mock 模式(向后兼容 W14)
                refs, is_real = _mock_arxiv_response(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"arXiv 查询失败: {e}")

        # 转 response
        response = _results_to_response(refs, is_real, config, user_message)

        # SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1 重写:抽取 user_message + config"""
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = ArxivAgentConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ===== helpers =====

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-arxiv: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "arXiv"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-arxiv 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "arXiv"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper: mock 模式(W14 向后兼容)
# ============================================================================


def _mock_arxiv_response(
    user_intent: str, n: int
) -> tuple[list[ArxivReference], bool]:
    """mock 模式快捷调用 — 返回假 arXiv 文献(W14 行为)

    Args:
        user_intent: 用户原始 query
        n: 多少篇

    Returns:
        (refs, is_real=False)
    """
    refs = []
    for i in range(n):
        refs.append(
            ArxivReference(
                arxiv_id=f"2400.{10000 + i:05d}",
                title=f"Mock arXiv paper {i + 1} about {user_intent[:30]}",
                authors=[f"Mock Author {i + 1}"],
                year=2024,
                summary=f"Mock summary for {user_intent[:50]}",
                url=f"https://arxiv.org/abs/2400.{10000 + i:05d}",
                categories=["cond-mat.mtrl-sci"],
            )
        )
    return refs, False


# ============================================================================
# 工厂
# ============================================================================


def create_default_agent() -> MatArxivAgent:
    """便利函数:创建默认配置 agent"""
    return MatArxivAgent(default_n_results=5)


# ============================================================================
# CLI demo
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatArxivAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n📚 Demo 1: arxiv 真查 LiCoO2 文献")
    req1 = AgentRequest(
        run_id="arxiv-demo-1",
        message="查 LiCoO2 锂离子电池文献",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n📚 Demo 2: arxiv 真查 LLZO")
    req2 = AgentRequest(
        run_id="arxiv-demo-2",
        message="LLZO ionic conductivity",
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n📚 Demo 3: mock 模式(向后兼容)")
    agent3 = MatArxivAgent(use_real_arxiv=False)
    req3 = AgentRequest(
        run_id="arxiv-demo-3",
        message="graphene",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "ArxivAgentConfig",
    "MatArxivAgent",
    "create_default_agent",
]