"""mat_pdf_agent / mat_pdf_agent.py — PDF 解析 wrapper(继承 MatWAUAgentBase)

业务逻辑:
1. 从 ctx 拿 pdf_path / pdf_url / pdf_bytes
2. 调 PdfParserClient 解析(PdfDocument + paragraphs + metadata)
3. 转 AgentResponse(artifacts: pdf_document + summary + parse_succeeded)

3 种入口:
- pdf_path: 本地文件路径(用于本地已有 PDF 库)
- pdf_url: HTTP(S) URL(用于 arxiv 真 PDF URL)
- pdf_bytes: 字节流(用于 /papers/upload 端点上传)

设计:
- 与 mat_arxiv_agent 模式对齐(继承 MatWAUAgentBase + 业务方法 + act/perceive)
- LRU cache 已在 PdfParserClient 内置(wrapper 无需再加)

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §二 M1
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.pdf_parser import (
    PDF_LRU_CACHE_DEFAULT_SIZE,
    PdfDocument,
    PdfParserClient,
)
from agents.widget_helpers import (
    assert_spoken_text_safe,
    attach_widget_protocol,
    make_paper_fulltext_widget,
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
class PdfAgentConfig:
    """PDF 解析配置(per AgentRequest.context)

    Attributes:
        cache_size: LRU cache 容量(默认 32)
        enable_cache: 是否启用 cache
        max_pages: PDF 最大页数(防御性上限,默认 50)
        download_timeout: URL 下载 timeout 秒数
        paper_id: 显式 paper_id(可选;默认用 path/url 自身)
    """

    cache_size: int = PDF_LRU_CACHE_DEFAULT_SIZE
    enable_cache: bool = True
    max_pages: int = 50
    download_timeout: int = 30
    paper_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PdfAgentConfig:
        if not d:
            return cls()
        return cls(
            cache_size=int(d.get("cache_size", PDF_LRU_CACHE_DEFAULT_SIZE)),
            enable_cache=bool(d.get("enable_cache", True)),
            max_pages=int(d.get("max_pages", 50)),
            download_timeout=int(d.get("download_timeout", 30)),
            paper_id=d.get("paper_id"),
        )


# ============================================================================
# helper
# ============================================================================


def _document_to_response(
    doc: PdfDocument,
    user_intent: str,
    cost: float = 0.05,
) -> AgentResponse:
    """PdfDocument → AgentResponse"""
    # confidence 启发式:有 30+ 段落 = 0.9,< 5 = 0.4
    n_para = doc.n_paragraphs
    if doc.parse_succeeded:
        if n_para >= 30:
            confidence = 0.9
        elif n_para >= 10:
            confidence = 0.7
        elif n_para >= 5:
            confidence = 0.5
        else:
            confidence = 0.4
    else:
        confidence = 0.0  # parse 失败

    # 自然语言 reply
    if doc.parse_succeeded:
        source_tag = "🌐 PDF 实时解析" if doc.source_url else "📄 PDF 本地解析"
        lines = [
            f"📚 {source_tag}: {doc.title or doc.paper_id}",
            f"   命中 {n_para} 段落,共 {doc.n_pages} 页",
            f"   作者: {', '.join(doc.authors[:3]) or '(未知)'}"
            + (" et al." if len(doc.authors) > 3 else ""),
        ]
        if doc.abstract:
            lines.append(f"\n📋 摘要: {doc.abstract[:200]}...")
        if doc.paragraphs:
            lines.append("\n📄 Top 段落:")
            for p in doc.paragraphs[:3]:
                lines.append(
                    f"   [段 {p.paragraph_no} / 页 {p.page_no}] "
                    f"{p.text[:80]}..."
                )
    else:
        lines = [
            f"⚠️ PDF 解析失败: {doc.paper_id}",
            f"   错误: {doc.parse_error or '(未知)'}",
        ]

    reply = "\n".join(lines)

    response = AgentResponse(
        reply=reply,
        artifacts={
            "pdf_document": doc,
            "pdf_dict": doc.to_dict(),
            "paper_id": doc.paper_id,
            "title": doc.title,
            "authors": doc.authors,
            "year": doc.year,
            "abstract": doc.abstract,
            "n_paragraphs": n_para,
            "n_pages": doc.n_pages,
            "paragraphs": [p.to_dict() for p in doc.paragraphs],
            "source_url": doc.source_url,
            "parse_succeeded": doc.parse_succeeded,
            "parse_error": doc.parse_error,
            "user_intent": user_intent,
        },
        confidence=confidence,
        cost=cost if doc.parse_succeeded else 0.0,
    )

    # v1.4-Academic M3 — attach matwau_paper_fulltext widget(only if parse_succeeded)
    if doc.parse_succeeded and doc.paragraphs:
        # 转 paragraphs → sections[{heading, text}]
        sections = []
        for p in doc.paragraphs[:50]:  # 限 50 段
            heading = f"段 {p.paragraph_no} / 页 {p.page_no}"
            sections.append({"heading": heading, "text": p.text[:2000]})
        widget = make_paper_fulltext_widget(
            arxiv_id=doc.paper_id,
            title=doc.title or doc.paper_id,
            authors=doc.authors,
            abstract=doc.abstract or "",
            sections=sections,
            url=doc.source_url or "",
            parser="pdfplumber",
        )
        spoken = summarize_for_voice(sections, user_intent, locale="zh", kind="fulltext")
        attach_widget_protocol(
            response,
            widgets=[widget],
            spoken_text=spoken,
            structured_data={
                "paper_id": doc.paper_id,
                "title": doc.title,
                "authors": doc.authors,
                "year": doc.year,
                "abstract": doc.abstract,
                "sections": sections,
                "n_paragraphs": n_para,
                "n_pages": doc.n_pages,
                "source_url": doc.source_url,
            },
        )
        assert_spoken_text_safe(spoken)

    return response


# ============================================================================
# MatPdfAgent
# ============================================================================


class MatPdfAgent(MatWAUAgentBase):
    """mat-pdf-agent — PDF 解析助手(v1.3.4-Academic M1)

    业务流程:
    1. 从 ctx 拿 pdf_path / pdf_url / pdf_bytes(三选一)
    2. 调 PdfParserClient.parse_pdf_* 对应入口
    3. 转 AgentResponse(artifacts 含完整 pdf_document)
    """

    name = "mat-pdf-agent"

    def __init__(
        self,
        *,
        cost_per_parse: float = 0.05,
        client: PdfParserClient | None = None,
        context_manager: ContextManager | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            cost_per_parse: 单次 PDF 解析估算成本 ¥
            client: 可注入自定义 PdfParserClient(测试用)
        """
        super().__init__(**kwargs)
        self.cost_per_parse = cost_per_parse
        self.client = client or PdfParserClient()

        # 默认注入 harness
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是 PDF 解析 agent(mat-pdf-agent),从 PDF 文件提取段落 + metadata。

能力:
1. 接受本地路径 / HTTP URL / 字节流 三种入口
2. pdfplumber 提取段落(per min_paragraph_chars 过滤短段)
3. 提取 metadata(title / authors / year)
4. 检测扫描版 PDF(无文本层)graceful 失败
5. LRU cache 同 PDF 不重复解析

输出: PdfDocument(paper_id + title + authors + year + abstract + paragraphs[] + n_pages + parse_succeeded)

适用场景:
- arxiv 真 PDF URL 下载 + 解析
- 用户上传 PDF(.pdf multipart)
- 学院方批量入库老 paper

约束:
- 0 行 UI 代码
- max_pages=50 防御性上限
- 扫描版 PDF → parse_succeeded=false,不抛异常
- 1 次调用 = 1 次单 PDF 解析(< 5s for 20 pages)
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — PDF 解析特有业务逻辑"""
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: PdfAgentConfig = ctx.get("_input_config") or PdfAgentConfig()

        # 3 种入口
        pdf_path = ctx.get("pdf_path")
        pdf_url = ctx.get("pdf_url")
        pdf_bytes = ctx.get("pdf_bytes")

        if not any([pdf_path, pdf_url, pdf_bytes]):
            return self._error_response("缺 pdf_path / pdf_url / pdf_bytes")

        # 按优先级:bytes > path > url
        try:
            if pdf_bytes is not None:
                doc = self.client.parse_pdf_from_bytes(
                    data=pdf_bytes,
                    paper_id=config.paper_id or "uploaded",
                )
            elif pdf_path:
                doc = self.client.parse_pdf(
                    pdf_path=pdf_path,
                    paper_id=config.paper_id,
                )
            else:  # pdf_url
                doc = self.client.parse_pdf_from_url(
                    url=pdf_url,
                    paper_id=config.paper_id,
                    timeout=config.download_timeout,
                )
        except Exception as e:
            return self._error_response(f"PDF 解析异常: {e}")

        # 转 response
        response = _document_to_response(doc, user_message, cost=self.cost_per_parse)

        # SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1 重写:抽取 user_message + config + PDF 输入"""
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = PdfAgentConfig.from_dict(req.context)
        # PDF 输入 3 种入口(per AgentRequest.context 或 artifacts)
        ctx["pdf_path"] = req.context.get("pdf_path") if req.context else None
        ctx["pdf_url"] = req.context.get("pdf_url") if req.context else None
        ctx["pdf_bytes"] = req.context.get("pdf_bytes") if req.context else None
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ========================================================================
    # 业务方法(对外可直接调,不走 act)
    # ========================================================================

    def parse_pdf(
        self,
        pdf_path: str,
        paper_id: str | None = None,
    ) -> PdfDocument:
        """业务方法:从本地路径解析"""
        return self.client.parse_pdf(pdf_path, paper_id)

    def parse_pdf_from_url(
        self,
        url: str,
        paper_id: str | None = None,
        timeout: int | None = None,
    ) -> PdfDocument:
        """业务方法:从 URL 解析"""
        return self.client.parse_pdf_from_url(url, paper_id, timeout)

    def parse_pdf_from_bytes(
        self,
        data: bytes,
        paper_id: str,
    ) -> PdfDocument:
        """业务方法:从 bytes 解析"""
        return self.client.parse_pdf_from_bytes(data, paper_id)

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应"""
        return AgentResponse(
            reply=f"❌ mat-pdf 错误: {error}",
            artifacts={"pdf_document": None, "n_paragraphs": 0, "parse_succeeded": False},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatPdfAgent:
    """便利函数"""
    return MatPdfAgent()


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatPdfAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    # Demo 1: 不存在的 PDF(测错误路径)
    print("\n📄 Demo 1: 不存在的 PDF")
    req1 = AgentRequest(
        run_id="pdf-demo-1",
        message="Parse a non-existent PDF",
        context={"pdf_path": "/nonexistent.pdf", "paper_id": "demo:missing"},
    )
    r1 = agent.run(req1)
    print(r1.reply)

    # Demo 2: 缺入口
    print("\n\n📄 Demo 2: 缺入口")
    req2 = AgentRequest(
        run_id="pdf-demo-2",
        message="No PDF input",
    )
    r2 = agent.run(req2)
    print(r2.reply)


__all__ = [
    "MatPdfAgent",
    "PdfAgentConfig",
    "create_default_agent",
]
