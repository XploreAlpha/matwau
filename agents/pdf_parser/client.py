"""pdf_parser / client.py — PDF 解析(pdfplumber + LRU cache)(v1.3.4-Academic M1)

支持:
- 本地路径 / URL / bytes 三种入口
- pdfplumber 提取段落(pure Python / MIT)
- LRU cache(同 PDF 不重复 parse)
- 防御性 limit: max_pages=50 / min_paragraph_chars=20
- 扫描版 PDF(text 为空)graceful 失败(返空 paragraphs 不抛异常)

PDF 库选择 rationale:
- pdfplumber: pure Python / MIT / ~5MB
- (放弃 PyMuPDF: GPL/AGPL 商业限制)
- (放弃 pypdf: 段落切分差)

per MatWAU-v1.3.4-Academic-dev-plan-20260806.md §二 M1
"""
from __future__ import annotations

import io
import logging
import re
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PDF_LRU_CACHE_DEFAULT_SIZE = 32  # v1.3.4 M1: LRU cache 默认容量
PDF_DEFAULT_MAX_PAGES = 50  # 防御性上限
PDF_DEFAULT_MIN_PARAGRAPH_CHARS = 20  # 过滤页眉页脚短段
PDF_DEFAULT_DOWNLOAD_TIMEOUT = 30  # URL 下载 timeout(秒)


@dataclass
class PdfParagraph:
    """PDF 中的 1 个段落"""

    paragraph_no: int  # 全局段落序号(0-indexed)
    page_no: int  # 所在页(0-indexed)
    text: str  # 段落文本
    char_count: int = 0  # 用于过滤空段

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraph_no": self.paragraph_no,
            "page_no": self.page_no,
            "text": self.text,
            "char_count": self.char_count,
        }


@dataclass
class PdfDocument:
    """完整 PDF 文档解析结果"""

    paper_id: str  # "arxiv:2401.12345" 或 "user:my_paper"
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 2024
    abstract: str = ""
    paragraphs: list[PdfParagraph] = field(default_factory=list)
    source_url: str | None = None
    n_pages: int = 0
    parse_succeeded: bool = True  # 扫描版 PDF → False(空 text)
    parse_error: str | None = None  # 错误信息(扫描版 / 损坏 / 网络)

    @property
    def n_paragraphs(self) -> int:
        return len(self.paragraphs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "source_url": self.source_url,
            "n_pages": self.n_pages,
            "n_paragraphs": self.n_paragraphs,
            "parse_succeeded": self.parse_succeeded,
            "parse_error": self.parse_error,
        }


# ============================================================================
# LRU cache(per v1.3.2 _LruCache 模板)
# ============================================================================


class _LruCache:
    """LRU cache — capacity 容量,超容 FIFO pop 最旧

    key: paper_id
    value: PdfDocument
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._data: OrderedDict[str, PdfDocument] = OrderedDict()

    def get(self, key: str) -> PdfDocument | None:
        """cache hit → 返回 + move to end(LRU 维护);miss → None"""
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, doc: PdfDocument) -> None:
        """写入 + 超容量时 pop 最旧"""
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = doc
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        """cache 实例永远 truthy(即使空)— 避免 'if cache:' 误判 False"""
        return True

    def clear(self) -> None:
        """清空(per 测试用)"""
        self._data.clear()


# ============================================================================
# availability check
# ============================================================================


def is_pdfplumber_available() -> bool:
    """检查 pdfplumber 是否可用"""
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


# ============================================================================
# Main client
# ============================================================================


@dataclass
class PdfParserClient:
    """PDF 解析 client

    Attributes:
        cache_size: LRU cache 容量(默认 32)
        enable_cache: 是否启用 cache(测试可关)
        max_pages: PDF 最大页数(防御性上限)
        min_paragraph_chars: 段落最少字符数(过滤页眉页脚)
        download_timeout: URL 下载 timeout(秒)
        user_agent: HTTP User-Agent(arxiv / 其他)
    """

    cache_size: int = PDF_LRU_CACHE_DEFAULT_SIZE
    enable_cache: bool = True
    max_pages: int = PDF_DEFAULT_MAX_PAGES
    min_paragraph_chars: int = PDF_DEFAULT_MIN_PARAGRAPH_CHARS
    download_timeout: int = PDF_DEFAULT_DOWNLOAD_TIMEOUT
    user_agent: str = "MatWAU-Academic/1.3.4"

    def __post_init__(self) -> None:
        if self.enable_cache:
            self._cache: _LruCache | None = _LruCache(self.cache_size)
        else:
            self._cache = None

    def clear_cache(self) -> None:
        """清空 cache"""
        if self._cache:
            self._cache.clear()

    # ======== 内部 helpers ========

    def _split_into_paragraphs(
        self,
        page_text: str,
        page_no: int,
        base_paragraph_no: int,
    ) -> list[PdfParagraph]:
        """从 1 页文本切分段落

        启发式:
        - 按双换行(\\n\\n+)切段
        - 单换行也算段(很多 PDF 每行单独一段)
        - 过滤短段(< min_paragraph_chars)
        """
        if not page_text or not page_text.strip():
            return []

        # 按 1+ 换行切段(\n\n 优先)
        raw_chunks = re.split(r"\n\s*\n", page_text)
        paragraphs = []
        paragraph_no = base_paragraph_no

        for chunk in raw_chunks:
            text = chunk.strip()
            # 过滤纯空白 / 短段
            if len(text) < self.min_paragraph_chars:
                continue
            paragraphs.append(PdfParagraph(
                paragraph_no=paragraph_no,
                page_no=page_no,
                text=text,
                char_count=len(text),
            ))
            paragraph_no += 1

        return paragraphs

    def _extract_metadata(self, pdf: Any, paper_id: str) -> tuple[str, list[str], int, str]:
        """从 PDF 提 metadata(title / authors / year / abstract)

        pdfplumber 的 metadata 是 dict:
        - /Title: 论文标题
        - /Author: 作者(可能 "Name1; Name2")
        - /CreationDate: 创建日期(D:20240115...)

        Returns:
            (title, authors, year, abstract)
            abstract 通常 metadata 里没有,留给 caller 从正文提取
        """
        title = ""
        authors: list[str] = []
        year = 2024

        try:
            metadata = pdf.metadata or {}
        except Exception:
            metadata = {}

        # Title
        raw_title = metadata.get("Title", "") or metadata.get("/Title", "")
        if raw_title and isinstance(raw_title, str):
            title = raw_title.strip()

        # Authors(pdfplumber 通常以 "; " 或 ", " 分隔)
        raw_authors = metadata.get("Author", "") or metadata.get("/Author", "")
        if raw_authors and isinstance(raw_authors, str):
            for sep in ["; ", ", and ", ","]:
                if sep in raw_authors:
                    authors = [a.strip() for a in raw_authors.split(sep) if a.strip()]
                    break
            else:
                authors = [raw_authors.strip()] if raw_authors.strip() else []

        # Year(from CreationDate)
        raw_date = metadata.get("CreationDate", "") or metadata.get("/CreationDate", "")
        if raw_date and isinstance(raw_date, str):
            m = re.search(r"(\d{4})", raw_date)
            if m:
                try:
                    year = int(m.group(1))
                except ValueError:
                    pass

        return title, authors, year, ""

    def _extract_abstract(self, paragraphs: list[PdfParagraph]) -> str:
        """从首段提取 abstract(启发式:首段含 'Abstract' 关键字)

        简化:取第 1 段作为 abstract
        """
        if not paragraphs:
            return ""
        return paragraphs[0].text[:1000]  # 限 1000 字符

    # ======== 公共 API ========

    def parse_pdf(
        self,
        pdf_path: str,
        paper_id: str | None = None,
    ) -> PdfDocument:
        """从本地路径解析 PDF

        Args:
            pdf_path: 本地 PDF 文件路径
            paper_id: 唯一 ID(默认用 pdf_path 作为 key)
        """
        key = paper_id or pdf_path

        # Cache hit
        if self._cache:
            cached = self._cache.get(key)
            if cached:
                logger.debug("PDF cache hit: %s", key)
                return cached

        # Parse
        path = Path(pdf_path)
        if not path.exists():
            doc = PdfDocument(
                paper_id=key,
                title="",
                parse_succeeded=False,
                parse_error=f"file not found: {pdf_path}",
            )
        else:
            with open(path, "rb") as f:
                data = f.read()
            doc = self._parse_bytes(data, key)

        # Cache put
        if self._cache:
            self._cache.put(key, doc)

        return doc

    def parse_pdf_from_url(
        self,
        url: str,
        paper_id: str | None = None,
        timeout: int | None = None,
    ) -> PdfDocument:
        """从 URL 下载 + 解析 PDF

        Args:
            url: PDF 的 HTTP(S) URL
            paper_id: 唯一 ID
            timeout: 超时秒数(None → 用 self.download_timeout)
        """
        key = paper_id or url

        # Cache hit
        if self._cache:
            cached = self._cache.get(key)
            if cached:
                logger.debug("PDF cache hit: %s", key)
                return cached

        # Download
        actual_timeout = timeout if timeout is not None else self.download_timeout
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=actual_timeout) as resp:
                data = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            doc = PdfDocument(
                paper_id=key,
                title="",
                source_url=url,
                parse_succeeded=False,
                parse_error=f"download failed: {e}",
            )
            if self._cache:
                self._cache.put(key, doc)
            return doc
        except Exception as e:
            doc = PdfDocument(
                paper_id=key,
                title="",
                source_url=url,
                parse_succeeded=False,
                parse_error=f"unexpected error: {e}",
            )
            if self._cache:
                self._cache.put(key, doc)
            return doc

        # Parse
        doc = self._parse_bytes(data, key)
        doc.source_url = url

        # Cache put
        if self._cache:
            self._cache.put(key, doc)

        return doc

    def parse_pdf_from_bytes(
        self,
        data: bytes,
        paper_id: str,
    ) -> PdfDocument:
        """从 bytes 解析 PDF(per /papers/upload 端点)

        Args:
            data: PDF 二进制
            paper_id: 唯一 ID
        """
        # Cache hit
        if self._cache:
            cached = self._cache.get(paper_id)
            if cached:
                logger.debug("PDF cache hit: %s", paper_id)
                return cached

        doc = self._parse_bytes(data, paper_id)

        if self._cache:
            self._cache.put(paper_id, doc)

        return doc

    # ======== 内部 parse ========

    def _parse_bytes(self, data: bytes, paper_id: str) -> PdfDocument:
        """真正调 pdfplumber 解析"""
        if not is_pdfplumber_available():
            return PdfDocument(
                paper_id=paper_id,
                title="",
                parse_succeeded=False,
                parse_error="pdfplumber not installed",
            )

        try:
            import pdfplumber
        except ImportError:
            return PdfDocument(
                paper_id=paper_id,
                title="",
                parse_succeeded=False,
                parse_error="pdfplumber not installed",
            )

        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                n_pages_total = len(pdf.pages)
                # 防御性 limit
                if n_pages_total > self.max_pages:
                    logger.warning("PDF %s 有 %d 页,超过 max_pages=%d,截断",
                                   paper_id, n_pages_total, self.max_pages)
                    n_pages = self.max_pages
                else:
                    n_pages = n_pages_total

                # Metadata
                title, authors, year, _ = self._extract_metadata(pdf, paper_id)

                # 段落(按页面 + 页内顺序)
                paragraphs: list[PdfParagraph] = []
                base_no = 0
                for i in range(n_pages):
                    page = pdf.pages[i]
                    try:
                        page_text = page.extract_text() or ""
                    except Exception as e:
                        logger.warning("PDF %s 第 %d 页 extract_text 失败: %s",
                                       paper_id, i, e)
                        page_text = ""
                    page_paragraphs = self._split_into_paragraphs(
                        page_text, page_no=i, base_paragraph_no=base_no,
                    )
                    paragraphs.extend(page_paragraphs)
                    base_no += len(page_paragraphs)

                # Abstract
                abstract = self._extract_abstract(paragraphs)

                # 扫描版 PDF 检测
                if not paragraphs:
                    return PdfDocument(
                        paper_id=paper_id,
                        title=title,
                        authors=authors,
                        year=year,
                        n_pages=n_pages_total,
                        parse_succeeded=False,
                        parse_error="scanned PDF (no text layer) or empty PDF",
                    )

                return PdfDocument(
                    paper_id=paper_id,
                    title=title,
                    authors=authors,
                    year=year,
                    abstract=abstract,
                    paragraphs=paragraphs,
                    n_pages=n_pages_total,
                    parse_succeeded=True,
                )
        except Exception as e:
            logger.warning("PDF %s 解析失败: %s", paper_id, e)
            return PdfDocument(
                paper_id=paper_id,
                title="",
                parse_succeeded=False,
                parse_error=f"parse failed: {e}",
            )


# ============================================================================
# 便利 module-level functions(per arxiv_client.search_arxiv 模板)
# ============================================================================


_default_client: PdfParserClient | None = None


def _get_default_client() -> PdfParserClient:
    global _default_client
    if _default_client is None:
        _default_client = PdfParserClient()
    return _default_client


def parse_pdf(pdf_path: str, paper_id: str | None = None) -> PdfDocument:
    """便利函数:从本地路径解析"""
    return _get_default_client().parse_pdf(pdf_path, paper_id)


def parse_pdf_from_url(url: str, paper_id: str | None = None, timeout: int | None = None) -> PdfDocument:
    """便利函数:从 URL 解析"""
    return _get_default_client().parse_pdf_from_url(url, paper_id, timeout)


def parse_pdf_from_bytes(data: bytes, paper_id: str) -> PdfDocument:
    """便利函数:从 bytes 解析"""
    return _get_default_client().parse_pdf_from_bytes(data, paper_id)
