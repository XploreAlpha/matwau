"""pdf_parser — PDF URL 解析客户端(v1.4.1-Academic)

支持:
- URL 入口(per v1.4.1-Academic 移除本地路径 / bytes 入口)
- pdfplumber 提取段落(pure Python / MIT License)
- LRU cache(同 URL 不重复 parse)
- 防御性 limit: max_pages / min_paragraph_chars
- 扫描版 PDF(text 为空)graceful 失败

PDF 库选择 rationale:
- pdfplumber: pure Python, MIT License, 体积 ~5MB, 学院版再分发友好
- (放弃 PyMuPDF: GPL/AGPL 商业限制;放弃 pypdf: 段落切分差)

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §二 M1 + v1.4.1-Academic 收紧到 URL-only
"""
from __future__ import annotations

from .client import (
    PDF_LRU_CACHE_DEFAULT_SIZE,
    PdfDocument,
    PdfParagraph,
    PdfParserClient,
    _LruCache,
    is_pdfplumber_available,
    parse_pdf_from_url,
)

__all__ = [
    "PDF_LRU_CACHE_DEFAULT_SIZE",
    "PdfDocument",
    "PdfParagraph",
    "PdfParserClient",
    "_LruCache",
    "is_pdfplumber_available",
    "parse_pdf_from_url",
]
