"""mat-pdf-agent — 本地 PDF 解析 wrapper(v1.3.4-Academic M1)

继承 MatWAUAgentBase,调 PdfParserClient 把 PDF 拆段落 + metadata,
返回结构化 PdfDocument 给 /literature parse_full_text 端点用。

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §二 M1
"""
from .mat_pdf_agent import (
    MatPdfAgent,
    PdfAgentConfig,
    create_default_agent,
)

__all__ = [
    "MatPdfAgent",
    "PdfAgentConfig",
    "create_default_agent",
]
