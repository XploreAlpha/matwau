"""mat_crossref_agent / mat_crossref_agent.py — CrossRef wrapper(继承 MatWAUAgentBase)

业务逻辑:
1. 解析 user_intent → 自由文本(CrossRef bibliographic query)
2. 调 CrossRefClient.search 拉 records(自动 LRU cache 复用)
3. 转 AgentResponse(records + is_real_query + confidence + cost)
4. 默认 confidence 启发:
   - 0 records → 0.3(可能查不到)
   - 1 record → 0.6
   - ≥2 records → 0.8

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §四 M2
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.crossref_client import CrossRefClient, CrossRefReference
from agents.widget_helpers import (
    assert_spoken_text_safe,
    attach_widget_protocol,
    make_journal_list_widget,
    summarize_for_voice,
)
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
class CrossRefAgentConfig:
    """CrossRef 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    max_results_hard_cap: int = 20
    enable_cache: bool = True
    cache_size: int = 128

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> CrossRefAgentConfig:
        if not d:
            return cls()
        n_results = int(d.get("n_results", 5))
        if n_results > cls.max_results_hard_cap:
            n_results = cls.max_results_hard_cap
        return cls(
            n_results=n_results,
            enable_cache=d.get("enable_cache", True),
            cache_size=int(d.get("cache_size", 128)),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: list[CrossRefReference],
    is_real: bool,
    config: CrossRefAgentConfig,
    user_intent: str,
) -> AgentResponse:
    """CrossRef 查询结果 → AgentResponse"""
    records = [r.to_dict() for r in refs]

    n = len(records)
    if n == 0:
        confidence = 0.3
    elif n == 1:
        confidence = 0.6
    else:
        confidence = 0.8

    source_tag = "🌐 CrossRef 实时" if is_real else "🧪 CrossRef mock(fallback)"
    lines = [
        f"📖 {source_tag} 期刊查询: {user_intent}",
        f"   命中 {n} 篇论文",
    ]
    if refs:
        lines.append("\n📄 Top 论文:")
        for r in refs[:3]:
            authors_str = ", ".join(r.authors[:2]) + (" et al." if len(r.authors) > 2 else "")
            cite_str = f"cited {r.citations_count}x" if r.citations_count else "no cites"
            lines.append(
                f"   [{r.year}] {r.title[:80]} | "
                f"{r.journal} | DOI:{r.doi} | {authors_str} | {cite_str}"
            )
    if not is_real:
        lines.append("\n⚠️ 真 CrossRef 不可达,使用本地 mock 数据(向后兼容 W14)")

    reply = "\n".join(lines)
    cost = 0.02 if is_real else 0.001

    response = AgentResponse(
        reply=reply,
        artifacts={
            "records": records,
            "canonical_key": None,
            "sources": ["crossref"],
            "is_real_query": is_real,
            "n_results": n,
            "source_platform": "CrossRef",
            "source_doi": "",
            "citation": "CrossRef (https://api.crossref.org)",
            "user_intent": user_intent,
        },
        confidence=confidence,
        cost=cost,
    )

    # v1.4-Academic M3 — attach matwau_journal_list widget
    if records:
        journal_widget = make_journal_list_widget(
            records,
            title=f"CrossRef 期刊文章 ({n} 篇)",
        )
        spoken = summarize_for_voice(records, user_intent, locale="zh", kind="journals")
        attach_widget_protocol(
            response,
            widgets=[journal_widget],
            spoken_text=spoken,
            structured_data={"records": records, "n_results": n, "source_platform": "CrossRef"},
        )
        assert_spoken_text_safe(spoken)

    return response


# ============================================================================
# MatCrossRefAgent
# ============================================================================


class MatCrossRefAgent(MatWAUAgentBase):
    """mat-crossref-agent — CrossRef 期刊 DOI 元数据查询助手(v1.3.3-Academic M2)"""

    name = "mat-crossref-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.02,
        use_real_crossref: bool = True,
        client: CrossRefClient | None = None,
        context_manager: ContextManager | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            context_manager=context_manager,
            safety_guard=safety_guard,
            **kwargs,
        )
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_crossref = use_real_crossref
        self._client = client or CrossRefClient(
            max_results=default_n_results,
            enable_cache=True,
        )

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 CrossRef 期刊 DOI 元数据查询助手(mat-crossref-agent)。

能力:
1. 解析 user_intent → 自由文本(CrossRef bibliographic query)
2. 调 CrossRef works API(https://api.crossref.org/works)查期刊论文
3. 返回字段:DOI / title / authors / journal / year / volume / issue / pages /
   publisher / type / citations_count / abstract(可选)
4. 支持 mailto etiquette(per CrossRef 礼貌使用)
5. LRU cache(v1.3.3):同 query < 1ms 命中
6. 失败 fallback 到 mock(W14 向后兼容)

适用场景:
- "查 LiCoO2 期刊影响因子"
- "lithium-ion battery recent journal papers"
- "PMMA 在 Nature 上的最新论文"
- 任何已知主题的期刊论文查询

约束:
- 不下载全文 PDF(版权问题,只元数据)
- 单次返回最多 5 篇(默认),可通过 context.n_results 调整
- 真查询失败自动 fallback,不报错
- 0 行 UI 代码
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: CrossRefAgentConfig = ctx.get("_input_config") or CrossRefAgentConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        try:
            if self.use_real_crossref:
                refs, is_real = self._client.search(
                    user_message,
                    max_results=config.n_results,
                )
            else:
                refs, is_real = _mock_crossref_response(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"CrossRef 查询失败: {e}")

        response = _results_to_response(refs, is_real, config, user_message)

        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = CrossRefAgentConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-crossref: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "CrossRef"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-crossref 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "CrossRef"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper: mock 模式(W14 向后兼容)
# ============================================================================


def _mock_crossref_response(
    user_intent: str, n: int
) -> tuple[list[CrossRefReference], bool]:
    """mock 模式快捷调用 — 返回假 CrossRef 论文(W14 行为)"""
    refs = []
    for i in range(n):
        refs.append(
            CrossRefReference(
                doi=f"10.0000/mock{i:04d}",
                title=f"Mock CrossRef paper {i + 1} about {user_intent[:30]}",
                authors=[f"Mock Author {i + 1}"],
                year=2024,
                journal="Mock Journal",
                volume=str(100 + i),
                issue="1",
                pages=f"1-{i + 2}",
                publisher="Mock Publisher",
                type="journal-article",
                citations_count=10 + i,
                url=f"https://doi.org/10.0000/mock{i:04d}",
                abstract=f"Mock abstract for {user_intent[:30]}",
            )
        )
    return refs, False


# ============================================================================
# 工厂
# ============================================================================


def create_default_agent() -> MatCrossRefAgent:
    """便利函数:创建默认配置 agent"""
    return MatCrossRefAgent(default_n_results=5)


# ============================================================================
# CLI demo
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatCrossRefAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n📖 Demo 1: CrossRef 真查 LiCoO2")
    req1 = AgentRequest(
        run_id="crossref-demo-1",
        message="LiCoO2 lithium-ion battery",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n📖 Demo 2: CrossRef 真查 PMMA")
    req2 = AgentRequest(
        run_id="crossref-demo-2",
        message="PMMA glass transition polymer",
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n📖 Demo 3: mock 模式")
    agent3 = MatCrossRefAgent(use_real_crossref=False)
    req3 = AgentRequest(
        run_id="crossref-demo-3",
        message="test",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "MatCrossRefAgent",
    "CrossRefAgentConfig",
    "create_default_agent",
]