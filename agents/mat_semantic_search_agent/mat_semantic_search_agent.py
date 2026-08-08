"""mat_semantic_search_agent / mat_semantic_search_agent.py — semantic_search wrapper

v1.4-Academic M3 — matwau_semantic_hits widget

业务流程:
1. 解析 user_intent → query
2. 可选 context["query_english"](中文→英文翻译结果)直接传
3. 调 search_client.search(query_english or query, top_k)
4. adapter SearchHit → wire shape {arxiv_id, title, authors, year, snippet, score}
5. attach matwau_semantic_hits widget

per MatWAU-v1.4-Academic-dev-plan-20260808.md §3.4
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.semantic_search import (
    SearchHit,
    search_client,
)
from agents.widget_helpers import (
    assert_spoken_text_safe,
    attach_widget_protocol,
    make_semantic_hits_widget,
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
class SemanticSearchConfig:
    """semantic_search 配置(per AgentRequest.context)"""

    top_k: int = 8
    min_relevance: float = 0.0  # 0 = 不过滤

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> SemanticSearchConfig:
        if not d:
            return cls()
        return cls(
            top_k=int(d.get("top_k", 8)),
            min_relevance=float(d.get("min_relevance", 0.0)),
        )


# ============================================================================
# helper: SearchHit → wire records
# ============================================================================


def _hits_to_records(hits: list[SearchHit]) -> list[dict]:
    """adapter SearchHit → homerail FE 期望的 wire shape

    wire fields(per VoiceDynamicWidget.test.ts):
    - arxiv_id: str — "arxiv:2401.12345" → "2401.12345"
    - title: str
    - authors: list[str] — SearchHit 没有,默认 []
    - year: int | None — SearchHit 没有,默认 None
    - snippet: str — SearchHit.text 的前 200 字
    - score: float — SearchHit.relevance
    """
    records = []
    for h in hits:
        arxiv_id = h.paper_id
        if arxiv_id.startswith("arxiv:"):
            arxiv_id = arxiv_id[len("arxiv:"):]
        records.append({
            "arxiv_id": arxiv_id,
            "title": h.title or "(untitled)",
            "authors": [],
            "year": None,
            "snippet": h.text[:200],
            "score": round(h.relevance, 4),
        })
    return records


# ============================================================================
# MatSemanticSearchAgent
# ============================================================================


class MatSemanticSearchAgent(MatWAUAgentBase):
    """mat-semantic-search-agent — 学院版论文语义检索助手

    业务流程:
    1. 从 ctx 拿 user_message + 可选 query_english
    2. 调 search_client.search
    3. adapter SearchHit → wire
    4. attach matwau_semantic_hits widget
    """

    name = "mat-semantic-search-agent"

    def __init__(
        self,
        *,
        cost_per_query: float = 0.01,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.cost_per_query = cost_per_query

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学论文语义检索助手(mat-semantic-search-agent)。

能力:
1. 接受 user_message(中文/英文均可)
2. 优先使用 context["query_english"] 调 search_client(若是中文)
3. 调 search_client.search() 拉 top_k 段落级 hit
4. adapter SearchHit → homerail wire format
5. attach matwau_semantic_hits widget(给 FE 渲染)

适用场景:
- "查关于钙钛矿稳定性的论文"
- "Inconel 718 疲劳"
- 任何已知 query 在已入库论文中找段落

约束:
- 0 行 UI 代码
- top_k 默认 8,min_relevance 默认 0(不过滤)
- 复用 search_client singleton(已在 serve.py /papers/ingest 时 add_document)
- 不引入新 LRU cache(SearchClient 已有)
- 中文 → 英文翻译由 caller 在 context["query_english"] 单独传
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: SemanticSearchConfig = ctx.get("_input_config") or SemanticSearchConfig()

        # 优先 query_english(中文 + 翻译),否则 raw chinese / english
        query_english = ctx.get("query_english") or ""
        query = query_english or user_message

        if not query:
            return self._empty_response("用户 query 为空")

        try:
            hits = search_client.search(query, top_k=config.top_k)
        except Exception as e:
            return self._error_response(f"semantic_search 失败: {e}")

        # 过滤 min_relevance
        if config.min_relevance > 0:
            hits = [h for h in hits if h.relevance >= config.min_relevance]

        records = _hits_to_records(hits)

        # confidence: 有 hits → 0.7,无 → 0.3
        confidence = 0.7 if hits else 0.3
        cost = self.cost_per_query if hits else 0.001

        # 自然语言 reply
        if records:
            reply = f"🔍 语义检索 '{user_message}': 命中 {len(records)} 个段落"
            if query_english and query_english != user_message:
                reply += f"(翻译: {query_english})"
        else:
            reply = f"🔍 语义检索 '{user_message}': 索引暂无命中"

        response = AgentResponse(
            reply=reply,
            artifacts={
                "query": user_message,
                "query_english": query_english or user_message,
                "hits": [h.to_dict() for h in hits],
                "n_hits": len(hits),
                "source_platform": "semantic_search",
                "top_k": config.top_k,
            },
            confidence=confidence,
            cost=cost,
        )

        # v1.4-Academic M3 — attach matwau_semantic_hits widget
        widget = make_semantic_hits_widget(
            query=user_message,
            query_english=query_english or user_message,
            hits=records,
        )
        spoken = summarize_for_voice(records, user_message, locale="zh", kind="semantic")
        attach_widget_protocol(
            response,
            widgets=[widget],
            spoken_text=spoken,
            structured_data={
                "query": user_message,
                "query_english": query_english or user_message,
                "hits": records,
                "n_hits": len(records),
                "source_platform": "semantic_search",
            },
        )
        assert_spoken_text_safe(spoken)

        # SafetyGuard
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
        ctx["_input_config"] = SemanticSearchConfig.from_dict(req.context)
        ctx["query_english"] = (req.context or {}).get("query_english", "")
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-semantic-search: {reason}",
            artifacts={"hits": [], "n_hits": 0, "source_platform": "semantic_search"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-semantic-search 错误: {error}",
            artifacts={"hits": [], "n_hits": 0, "source_platform": "semantic_search"},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatSemanticSearchAgent:
    """便利函数"""
    return MatSemanticSearchAgent()


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatSemanticSearchAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    # Demo 1: 英文 query
    print("\n🔍 Demo 1: 英文 query")
    req1 = AgentRequest(
        run_id="sem-demo-1",
        message="band gap perovskite",
        context={"top_k": 5},
    )
    r1 = agent.run(req1)
    print(r1.reply)
    print(f"   widgets: {len(r1.widgets)}")
    if r1.widgets:
        print(f"   widget[0].type: {r1.widgets[0].type}")
        print(f"   n_hits: {r1.artifacts['n_hits']}")

    # Demo 2: 中文 query + 翻译
    print("\n\n🔍 Demo 2: 中文 query + 翻译")
    req2 = AgentRequest(
        run_id="sem-demo-2",
        message="钙钛矿稳定性",
        context={"query_english": "perovskite stability", "top_k": 3},
    )
    r2 = agent.run(req2)
    print(r2.reply)


__all__ = [
    "MatSemanticSearchAgent",
    "SemanticSearchConfig",
    "create_default_agent",
]
