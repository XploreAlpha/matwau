"""mat-lit-agent — 材料科学文献综述员(per dev plan §七 W14)

Stage 1 / Phase 1:mock 文献库 + 关键词提取 + 模板生成
Stage 2(WAU v1.0.0 GA 后):接 arXiv + PubChem + CrossRef 真 API

业务流程(per act() 实现):
1. 解析 user_intent → LitQuery(formula + material + property + domain)
2. 调 lit_engine.review_literature 生成综述
3. 返回 LitReview(background + state_of_art + gaps + suggestions + references)

替换 mat-orchestrator literature_review workflow 的 StubAgent(per W14 拍板)

用法:
    from agents.mat_lit_agent.mat_lit_agent import MatLitAgent
    from matwau.core.agent_base import AgentRequest

    agent = MatLitAgent()
    req = AgentRequest(
        run_id="lit-001",
        message="Review 一下 LLZO 最新进展,关注电导率和稳定性",
    )
    response = agent.run(req)
    print(response.artifacts["review"])  # LitReview
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard

from .lit_engine import (
    LitReview,
    review_literature,
)

# ============================================================================
# 配置
# ============================================================================


@dataclass
class LitConfig:
    """用户配置(per AgentRequest.context)"""

    n_results: int = 5
    sources: list[str] = None
    include_query_echo: bool = True

    def __post_init__(self) -> None:
        if self.sources is None:
            # v1.3.3-Academic: 真接 3 源(arXiv + PubChem + CrossRef)
            # Materials Project / ICSD 字符串占位保留但未真接
            self.sources = ["arXiv", "PubChem", "CrossRef"]

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LitConfig:
        if not d:
            return cls()
        return cls(
            n_results=d.get("n_results", 5),
            # v1.3.3-Academic: 同步 lit_engine 默认 sources 列表
            sources=d.get("sources", ["arXiv", "PubChem", "CrossRef"]),
            include_query_echo=d.get("include_query_echo", True),
        )


# ============================================================================
# 内部 helper
# ============================================================================


def _review_to_response(review: LitReview, config: LitConfig) -> AgentResponse:
    """LitReview → AgentResponse"""
    # 自然语言 reply
    lines = [
        f"📚 mat-lit 综述: {review.query}",
        f"   检索到 {len(review.references)} 篇相关文献(置信度 {review.confidence:.2f})",
        f"   数据库: {', '.join(review.sources_queried)}",
    ]

    if review.references:
        lines.append("\n🔍 Top 引用:")
        for r in review.references[:3]:
            authors_str = ", ".join(r.authors[:2]) + (" et al." if len(r.authors) > 2 else "")
            lines.append(f"   [{r.year}] {r.title} ({authors_str})")
            lines.append(f"          {r.source} | rel={r.relevance:.2f} | impact={r.impact}")

    if review.gaps:
        lines.append(f"\n⚠️ 研究空白({len(review.gaps)} 条):")
        for g in review.gaps[:3]:
            lines.append(f"   - {g}")

    if review.suggestions:
        lines.append(f"\n💡 建议({len(review.suggestions)} 条):")
        for s in review.suggestions[:3]:
            lines.append(f"   - {s}")

    reply = "\n".join(lines)
    cost = 0.1  # mock 数据库几乎免费

    return AgentResponse(
        reply=reply,
        artifacts={
            "review": review,
            "review_dict": review.to_dict(),
            "references": [r.to_dict() for r in review.references],
            "background": review.background,
            "state_of_art": review.state_of_art,
            "gaps": review.gaps,
            "suggestions": review.suggestions,
            "query": review.query,
            "n_results": len(review.references),
            "sources_queried": review.sources_queried,
            "is_real_query": review.is_real_query,  # v1.3.2-Academic bug fix
        },
        confidence=review.confidence,
        cost=cost,
    )


# ============================================================================
# MatLitAgent 主体
# ============================================================================


class MatLitAgent(MatWAUAgentBase):
    """mat-lit-agent — 材料科学文献综述员

    业务流程:
    1. 解析 user_intent → LitQuery
    2. 调 lit_engine.review_literature 生成综述
    3. 返回 LitReview(给用户 + 给 mat-orchestrator downstream)
    """

    name = "mat-lit-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_review: float = 0.1,
        domain: str | None = None,
        use_real_arxiv: bool = True,  # v1.3.2-Academic: 默认 True = 真 arXiv API(失败 fallback mock)
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_n_results: 默认引用文献数
            cost_per_review: 单次综述估算成本 ¥
            domain: 材料域(W15)
            use_real_arxiv: v1.3.2-Academic 起默认 True = 真查 arXiv API(失败 fallback mock);
                          设 False 可强制走 mock DB(向后兼容)
        """
        super().__init__(**kwargs)
        self.default_n_results = default_n_results
        self.cost_per_review = cost_per_review
        # W15: 域路由
        from agents.material_domain_router import DEFAULT_DOMAIN
        self.domain = domain or DEFAULT_DOMAIN
        # W16: arXiv 开关;v1.3.2-Academic 起默认 True(失败 fallback mock,W14 兼容)
        self.use_real_arxiv = use_real_arxiv

        # 默认注入 harness
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学文献综述员 agent(mat-lit-agent),从用户 query 生成结构化文献综述。

能力:
1. 解析 user_intent → LitQuery(化学式 + 材料别名 + 属性 + 领域)
2. 检索 mock + 真 API 数据库(arXiv / PubChem / CrossRef,v1.3.3-Academic 起真接 3 源)
3. 算每篇文献的 relevance(0-1)按降序取 top-N
4. 生成综述 4 部分:
   - background:背景介绍(查询要素 + 检索结果概览)
   - state_of_art:国内外现状(按 source 分组列文献)
   - gaps:研究空白(2-4 条)
   - suggestions:给用户建议(2-3 条,跟 mat-gen / mat-sim / mat-bayesian 联动)
5. 算 confidence 分(0-1)

输出: LitReview(query + references + 4 部分 + confidence + sources_queried)

适用场景:
- 学术综述:Review 一下 LLZO 最新进展
- 调研:固态电解质国内外现状
- 入门:什么是 LLZO,有什么应用

约束:
- 0 行 UI 代码(无头架构)
- 1 次调用 = 1 次 Goldens 跑分(mat-lit.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-lit 特有业务逻辑"""
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: LitConfig = ctx.get("_input_config") or LitConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        # W15: 域路由
        from agents.material_domain_router import detect_domain, get_lit_backend
        ctx_domain = ctx.get("domain") or self.domain
        if not ctx_domain or ctx_domain == "auto":
            ctx_domain = detect_domain(user_message)
        lit_backend = get_lit_backend(ctx_domain)

        # 1. 跑综述(W15: 透传 domain;W16: 透传 use_real_arxiv)
        try:
            review = review_literature(
                user_intent=user_message,
                n_results=config.n_results,
                sources=config.sources,
                domain=ctx_domain,
                use_real_arxiv=self.use_real_arxiv,
            )
        except Exception as e:
            return self._error_response(f"[{lit_backend}] 综述失败: {e}")

        # 2. 转 response
        response = _review_to_response(review, config)

        # 3. SafetyGuard
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
        ctx["_input_config"] = LitConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _empty_response(self, reason: str) -> AgentResponse:
        """空响应"""
        return AgentResponse(
            reply=f"⚠️ mat-lit: {reason}",
            artifacts={"review": None, "n_results": 0},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应"""
        return AgentResponse(
            reply=f"❌ mat-lit 错误: {error}",
            artifacts={"review": None, "n_results": 0},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatLitAgent:
    """便利函数"""
    return MatLitAgent(
        default_n_results=5,
        cost_per_review=0.1,
    )


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatLitAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    # Demo 1: LLZO 综述
    print("\n📚 Demo 1: LLZO 最新进展综述")
    req1 = AgentRequest(
        run_id="lit-demo-1",
        message="Review 一下 LLZO 最新进展,关注电导率和稳定性",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    # Demo 2: LiCoO2 + 无钴
    print("\n\n📚 Demo 2: 无 Co 锂电池正极综述")
    req2 = AgentRequest(
        run_id="lit-demo-2",
        message="出无 Co 锂电池正极,关注能量密度",
        context={"n_results": 3},
    )
    r2 = agent.run(req2)
    print(r2.reply)

    # Demo 3: 通用属性查询
    print("\n\n📚 Demo 3: 稳定性预测综述")
    req3 = AgentRequest(
        run_id="lit-demo-3",
        message="材料稳定性预测有哪些方法",
    )
    r3 = agent.run(req3)
    print(r3.reply)


__all__ = [
    "LitConfig",
    "MatLitAgent",
    "create_default_agent",
]