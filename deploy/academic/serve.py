"""serve.py — MatWAU 学院版 HTTP API 服务入口

W37.4 + W37.12 + v1.3.4 — Docker 容器内启动的 HTTP API 服务
- 默认端口:8080
- 端点:
  - GET  /             — 服务信息
  - GET  /health       — 健康检查(学院 IT 用于监控)
  - GET  /version      — 版本信息(v1.3.4-Academic)
  - POST /intent       — 解析 1 句话材料意图
  - POST /multi-exp    — 跑多实验并行(Stage 3 JARVIS 雏形)
  - POST /literature   — 专用文献综述(per v1.3.3-Academic;v1.3.4 加 parse_full_text + top_k)
  - POST /papers/upload — PDF 上传入库(per v1.3.4-Academic,multipart/form-data + JSON)
  - POST /papers/search — 跨论文语义搜索(per v1.3.4-Academic,TF-IDF + cosine)
  - GET  /lineage      — 查 lineage 记录
  - GET  /wau/dispatch — wau-edge 健康检查(V1 接公网 wau)
  - POST /wau/dispatch — wau-edge 路由到此,接 JWT 校验 + 转 orchestrator(V1 接公网 wau)

设计原则:
- 学院版零外部依赖:不强制 LLM,不强制 Postgres(默认 SQLite)
- 数据归学校:所有 lineage 写入学院 IT 指定的 volume
- 不收集任何使用数据(学院版范围外)
- V1 可选接 wau 公网:配 WAU_JWT_SHARED_SECRET → 启用,否则 skip(per dispatch_handler)
- v1.3.4-Academic 起可 parse 真实 PDF(学院方上传 / arxiv 真 PDF URL 下载)
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# v1.3.4-Academic — module-level singletons(端点 + 测试都引用)
from agents.semantic_search import search_client  # noqa: E402

# 让 serve.py 能 import matwau 顶层模块
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


def _version_string() -> str:
    """读 VERSION 文件或用默认值"""
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "v1.3.4-Academic"  # 2026-08-06 patch: PDF parse + semantic search + /papers/* 端点


def _ok(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class MatWAUAcademicHandler(BaseHTTPRequestHandler):
    """学院版 HTTP 处理器"""

    # W37.12 — wau dispatch handler(懒加载,sys.path 修了再 import)
    _wau_dispatch_handler = None

    def log_message(self, fmt, *args):
        """简化日志(学院 IT 友好)"""
        sys.stderr.write(f"[matwau] {self.address_string()} - {fmt % args}\n")

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path == "/" or self.path == "/health":
            _ok(self, 200, {
                "status": "ok",
                "service": "matwau-academic",
                "version": _version_string(),
                "license": "Apache-2.0",
                "maintainer": "XploreAlpha",
            })
        elif self.path == "/version":
            _ok(self, 200, {
                "version": _version_string(),
                "license": "Apache-2.0",
                "maintainer": "XploreAlpha",
                "donation_notice": (
                    "This service is part of the MatWAU Academic Edition "
                    "donated by XploreAlpha. Data ownership belongs to the "
                    "deployed institution. See LICENSE for full terms."
                ),
            })
        elif self.path == "/lineage":
            # 查 lineage(默认 SQLite;如配 Postgres 则走 Postgres)
            try:
                from matwau.configs.matwau_settings import get_lineage_store
                store = get_lineage_store()
                # LineageStore 真实 API: to_list() 返回 list[dict],size() 返回 int
                # 不支持 limit 参数,这里手工切前 10 条
                all_records = store.to_list()
                records = all_records[:10]
                _ok(self, 200, {
                    "n_records": store.size(),
                    "n_returned": len(records),
                    "records": [r if isinstance(r, dict) else r.to_dict() for r in records],
                })
            except Exception as e:
                _ok(self, 500, {"error": str(e)})
        elif self.path == "/wau/dispatch":
            # W37.12 — wau-edge health check via GET
            try:
                from agents.wau_protocol_adapter.dispatch_handler import (
                    make_dispatch_handler,
                )
                Mixin = make_dispatch_handler()
                # 临时挂载:instance 复用 do_GET 流程
                _ok(self, 200, {
                    "status": "ok",
                    "agent": "matwau",
                    "version": _version_string(),
                    "endpoint": "/wau/dispatch",
                    "note": "POST /wau/dispatch 接 wau-edge dispatch",
                })
            except Exception as e:
                _ok(self, 500, {"error": str(e)})
        else:
            _ok(self, 404, {"error": "not found", "path": self.path})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        content_type = self.headers.get("Content-Type", "application/json")

        # W37.12 — /wau/dispatch 端点
        if self.path == "/wau/dispatch":
            # dispatch 可能 JSON 或其他,按字符串处理
            self._handle_wau_dispatch(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return

        # v1.3.4-Academic — /papers/upload 支持 multipart/form-data
        if self.path == "/papers/upload" and content_type.startswith("multipart/form-data"):
            self._handle_papers_upload_multipart(raw, content_type, length)
            return

        # 其他端点按 JSON 处理
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except json.JSONDecodeError:
            _ok(self, 400, {"error": "invalid JSON"})
            return

        if self.path == "/intent":
            self._handle_intent(payload)
        elif self.path == "/multi-exp":
            self._handle_multi_experiment(payload)
        elif self.path == "/literature":
            self._handle_literature(payload)
        elif self.path == "/papers/upload":
            # JSON 入口:支持 pdf_base64 / pdf_url / pdf_path
            self._handle_papers_upload_json(payload)
        elif self.path == "/papers/search":
            self._handle_papers_search(payload)
        else:
            _ok(self, 404, {"error": "not found", "path": self.path})

    def _handle_wau_dispatch(self, raw: str) -> None:
        """W37.12 — 接 wau-edge dispatch(JWT 校验 + 转 orchestrator)"""
        try:
            from agents.wau_protocol_adapter.dispatch_handler import (
                _verify_jwt,
                _load_jwt_secret,
            )
        except Exception as e:
            _ok(self, 500, {"error": f"wau_protocol_adapter import fail: {e}"})
            return

        # 1. 读 body
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            _ok(self, 400, {"error": f"invalid JSON: {e}"})
            return

        # 2. JWT 校验
        jwt_secret = _load_jwt_secret()
        if jwt_secret:
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                _ok(self, 401, {"error": "missing Authorization Bearer"})
                return
            token = auth_header[len("Bearer "):]
            expected_tenant = os.environ.get("WAU_TENANT_ID", "codex-appserver")
            ok, err, claims = _verify_jwt(token, jwt_secret, expected_tenant)
            if not ok:
                _ok(self, 401, {"error": err})
                return
            payload_tenant = payload.get("tenant_id", "")
            if payload_tenant and claims.get("tenant_id") != payload_tenant:
                _ok(self, 403, {"error": "tenant_id payload/JWT mismatch"})
                return
        else:
            sys.stderr.write("[matwau] WAU_JWT_SHARED_SECRET 未配,skip JWT 校验(开发模式)\n")

        # 3. 转给 MatOrchestrator
        intent = payload.get("intent", "")
        if not intent:
            _ok(self, 400, {"error": "missing 'intent'"})
            return

        try:
            from agents.mat_orchestrator import MatOrchestrator

            orch = MatOrchestrator()
            wf_result = orch.run(user_intent=intent)
            _ok(self, 200, {
                "status": "ok" if wf_result.success else "fail",
                "workflow_id": payload.get("workflow_id"),
                "subclass": payload.get("subclass") or wf_result.subclass,
                "workflow_name": wf_result.workflow_name,
                "success": wf_result.success,
                "error": wf_result.error,
                "total_duration_seconds": wf_result.total_duration_seconds,
                "final_outputs": {
                    k: str(v)[:200] for k, v in (wf_result.final_outputs or {}).items()
                },
                "node_results_count": len(wf_result.node_results),
            })
        except Exception as e:
            sys.stderr.write(f"[matwau] orchestrator run fail: {e}\n")
            _ok(self, 500, {"error": str(e)})

    def _handle_intent(self, payload: dict) -> None:
        """解析 1 句话材料意图"""
        message = payload.get("message", "").strip()
        if not message:
            _ok(self, 400, {"error": "missing 'message'"})
            return

        try:
            from agents.mat_intent_agent import MatIntentAgent
            from matwau.core.agent_base import AgentRequest

            agent = MatIntentAgent()
            req = AgentRequest(
                run_id=f"intent-{os.getpid()}",
                message=message,
                artifacts={},
                context={},
            )
            resp = agent.run(req)
            _ok(self, 200, {
                "reply": resp.reply,
                "mat_intent": str(resp.artifacts.get("mat_intent", "")),
                "downstream_agent": resp.artifacts.get("downstream_agent", "mat-pipeline"),
                "cost": resp.cost,
            })
        except Exception as e:
            _ok(self, 500, {"error": str(e)})

    def _handle_multi_experiment(self, payload: dict) -> None:
        """跑多实验并行(Stage 3 JARVIS 雏形)"""
        n_experiments = int(payload.get("n_experiments", 1))
        parallel = bool(payload.get("parallel", True))

        try:
            from agents.mat_orchestrator import (
                MatOrchestrator,
                get_multi_experiment_default_batch,
            )

            orch = MatOrchestrator()
            experiments = get_multi_experiment_default_batch()[:n_experiments]
            batch = orch.run_batch(experiments, parallel=parallel, max_workers=4)
            _ok(self, 200, {
                "n_total": batch.n_total,
                "n_passed": batch.n_passed,
                "n_warned": batch.n_warned,
                "n_failed": batch.n_failed,
                "overall_verdict": batch.overall_verdict,
                "total_cost_cny": batch.total_cost_cny,
                "total_duration_seconds": batch.total_duration_seconds,
                "experiment_results": [
                    {
                        "target_sample": r.target_sample,
                        "verdict": r.verdict,
                        "cost_cny": r.cost_cny,
                    }
                    for r in batch.experiment_results
                ],
            })
        except Exception as e:
            _ok(self, 500, {"error": str(e)})

    def _handle_literature(self, payload: dict) -> None:
        """v1.3.3-Academic — 专用 literature_review 端点

        v1.3.4-Academic 扩展:
        - parse_full_text: bool = False → 真接 PDF 全文 + 返 full_text_sections
        - top_k: int = 3 → 语义搜索返回段落数

        POST /literature
        {
          "message": "查 LiCoO2 锂离子电池文献",
          "n_results": 5,             # 可选,默认 5
          "domain": "inorganic_crystal",  # 可选
          "parse_full_text": true,    # v1.3.4 新增,默认 false
          "top_k": 3                  # v1.3.4 新增,默认 3
        }
        → 200
        {
          "reply": "...",
          "is_real_query": true,
          "n_results": 5,
          "sources_queried": ["arXiv", "PubChem", "CrossRef"],
          "references": [...],
          "background": "...",
          "state_of_art": "...",
          "gaps": [...],
          "suggestions": [...],
          "cost": 0.1,
          "full_text_sections": [...],   # v1.3.4 新增(parse_full_text=true 时填)
          "semantic_hits": [...],        # v1.3.4 新增(跨段落语义搜索)
          "parse_full_text_succeeded": true  # v1.3.4 新增(失败时 false)
        }
        """
        message = payload.get("message", "").strip()
        if not message:
            _ok(self, 400, {"error": "missing 'message'"})
            return

        parse_full_text = bool(payload.get("parse_full_text", False))
        top_k = int(payload.get("top_k", 3))

        try:
            from agents.mat_lit_agent import MatLitAgent
            from matwau.core.agent_base import AgentRequest

            agent = MatLitAgent()  # 默认 use_real_arxiv=True(v1.3.2)
            req = AgentRequest(
                run_id=f"literature-{os.getpid()}",
                message=message,
                artifacts={},
                context={
                    "n_results": int(payload.get("n_results", 5)),
                    "domain": payload.get("domain"),
                },
            )
            resp = agent.run(req)

            response_payload: dict = {
                "reply": resp.reply,
                "is_real_query": resp.artifacts.get("is_real_query"),
                "n_results": resp.artifacts.get("n_results"),
                "sources_queried": resp.artifacts.get("sources_queried"),
                "references": resp.artifacts.get("references", []),
                "background": resp.artifacts.get("background", ""),
                "state_of_art": resp.artifacts.get("state_of_art", ""),
                "gaps": resp.artifacts.get("gaps", []),
                "suggestions": resp.artifacts.get("suggestions", []),
                "cost": resp.cost,
            }

            # v1.3.4: parse_full_text 扩展(可选)
            if parse_full_text:
                full_text_sections, semantic_hits, parse_ok = _do_parse_full_text(
                    references=resp.artifacts.get("references", []),
                    message=message,
                    top_k=top_k,
                )
                response_payload["full_text_sections"] = full_text_sections
                response_payload["semantic_hits"] = semantic_hits
                response_payload["parse_full_text_succeeded"] = parse_ok

            _ok(self, 200, response_payload)
        except Exception as e:
            sys.stderr.write(f"[matwau] literature endpoint fail: {e}\n")
            _ok(self, 500, {"error": str(e)})

    # ========================================================================
    # v1.3.4-Academic — /papers/upload + /papers/search 端点
    # ========================================================================

    def _handle_papers_upload_multipart(self, raw: bytes, content_type: str, length: int) -> None:
        """POST /papers/upload(multipart/form-data)— 接收 .pdf 文件 + metadata

        curl -X POST http://localhost:8080/papers/upload \
            -F "file=@my_paper.pdf" \
            -F "title=Novel BaTiO3 dielectric" \
            -F "year=2024" \
            -F "paper_id=user:my_paper"
        """
        # Size limit(防御性)
        if length > 50 * 1024 * 1024:  # 50MB
            _ok(self, 413, {"error": "file too large (>50MB)"})
            return

        try:
            from email.parser import BytesParser
            from email.policy import default as email_default_policy
        except ImportError:
            _ok(self, 500, {"error": "email.parser unavailable"})
            return

        try:
            # email.parser 需要完整 RFC822 头,所以拼一个 minimal header
            raw_msg = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8") + raw
            msg = BytesParser(policy=email_default_policy).parsebytes(raw_msg)

            pdf_bytes: bytes | None = None
            metadata: dict = {}

            for part in msg.iter_parts():
                # 拿 form field name
                cd = part.get("Content-Disposition", "")
                # 简单解析: name="xxx" 或 filename="xxx"
                filename = part.get_filename()
                name_param = None
                for token in cd.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name_param = token[5:].strip('"')
                        break

                if filename:
                    # 文件 part
                    if not filename.lower().endswith(".pdf"):
                        _ok(self, 400, {"error": f"only .pdf accepted, got {filename}"})
                        return
                    pdf_bytes = part.get_payload(decode=True)
                elif name_param:
                    # 普通 form 字段
                    metadata[name_param] = part.get_content()

            if pdf_bytes is None:
                _ok(self, 400, {"error": "missing 'file' field with .pdf"})
                return

            paper_id = metadata.get("paper_id", f"user:{int(os.times().system)}")
            title = metadata.get("title", "")
            year_str = metadata.get("year", "2024")
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                year = 2024

            # 入 PDF 库
            from agents.pdf_parser import parse_pdf_from_bytes, is_pdfplumber_available
            doc = parse_pdf_from_bytes(pdf_bytes, paper_id=paper_id)
            if title:
                doc.title = title
            if year:
                doc.year = year

            # 入 semantic_search 索引(若有段落)
            if doc.parse_succeeded and doc.paragraphs:
                from agents.semantic_search import search_client
                paragraphs_text = [p.text for p in doc.paragraphs]
                page_numbers = [p.page_no for p in doc.paragraphs]
                search_client.add_document(
                    paper_id=paper_id,
                    paragraphs=paragraphs_text,
                    title=doc.title or title,
                    page_numbers=page_numbers,
                )

            _ok(self, 200, {
                "paper_id": paper_id,
                "n_paragraphs": doc.n_paragraphs,
                "n_pages": doc.n_pages,
                "stored": True,
                "parse_succeeded": doc.parse_succeeded,
                "parse_error": doc.parse_error,
                "pdfplumber_available": is_pdfplumber_available(),
            })
        except Exception as e:
            sys.stderr.write(f"[matwau] papers/upload multipart fail: {e}\n")
            _ok(self, 500, {"error": str(e)})

    def _handle_papers_upload_json(self, payload: dict) -> None:
        """POST /papers/upload(JSON)— 支持 pdf_base64 / pdf_url / pdf_path

        {
          "paper_id": "user:my_paper",
          "title": "...",
          "year": 2024,
          "pdf_base64": "JVBERi0xLjQK...",  # 三选一
          "pdf_url": "https://arxiv.org/pdf/...",
          "pdf_path": "/srv/matwau/data/papers/..."
        }
        """
        try:
            import base64
            from agents.pdf_parser import (
                parse_pdf_from_bytes,
                parse_pdf_from_url,
                parse_pdf,
            )

            paper_id = payload.get("paper_id", f"user:{int(os.times().system)}")
            title = payload.get("title", "")
            year = int(payload.get("year", 2024))

            pdf_base64 = payload.get("pdf_base64")
            pdf_url = payload.get("pdf_url")
            pdf_path = payload.get("pdf_path")

            if pdf_base64:
                data = base64.b64decode(pdf_base64)
                doc = parse_pdf_from_bytes(data, paper_id=paper_id)
            elif pdf_url:
                doc = parse_pdf_from_url(pdf_url, paper_id=paper_id)
            elif pdf_path:
                doc = parse_pdf(pdf_path, paper_id=paper_id)
            else:
                _ok(self, 400, {"error": "need pdf_base64 / pdf_url / pdf_path"})
                return

            if title:
                doc.title = title
            if year:
                doc.year = year

            # 入 semantic_search 索引
            if doc.parse_succeeded and doc.paragraphs:
                from agents.semantic_search import search_client
                paragraphs_text = [p.text for p in doc.paragraphs]
                page_numbers = [p.page_no for p in doc.paragraphs]
                search_client.add_document(
                    paper_id=paper_id,
                    paragraphs=paragraphs_text,
                    title=doc.title or title,
                    page_numbers=page_numbers,
                )

            _ok(self, 200, {
                "paper_id": paper_id,
                "n_paragraphs": doc.n_paragraphs,
                "n_pages": doc.n_pages,
                "stored": True,
                "parse_succeeded": doc.parse_succeeded,
                "parse_error": doc.parse_error,
            })
        except Exception as e:
            sys.stderr.write(f"[matwau] papers/upload json fail: {e}\n")
            _ok(self, 500, {"error": str(e)})

    def _handle_papers_search(self, payload: dict) -> None:
        """POST /papers/search 语义搜索

        {
          "query": "LLZO 锂金属负极界面问题",
          "top_k": 5     # 可选,默认 3
        }
        → 200
        {
          "query": "...",
          "n_results": 5,
          "hits": [
            {"paper_id": "...", "paragraph_no": 5, "page_no": 3,
             "text": "...", "title": "...", "relevance": 0.87}
          ]
        }
        """
        query = payload.get("query", "").strip()
        if not query:
            _ok(self, 400, {"error": "missing 'query'"})
            return

        top_k = int(payload.get("top_k", 3))
        try:
            from agents.semantic_search import search_client
            hits = search_client.search(query, top_k=top_k)
            _ok(self, 200, {
                "query": query,
                "n_results": len(hits),
                "top_k": top_k,
                "hits": [h.to_dict() for h in hits],
            })
        except Exception as e:
            sys.stderr.write(f"[matwau] papers/search fail: {e}\n")
            _ok(self, 500, {"error": str(e)})


def _do_parse_full_text(
    references: list[dict],
    message: str,
    top_k: int = 3,
) -> tuple[list[dict], list[dict], bool]:
    """v1.3.4 — 对 arxiv 真查的 references 逐个下载 PDF + 解析 + 入 semantic 索引

    Args:
        references: /literature 返回的 references 列表
        message: 用户 query(用作 semantic search query)
        top_k: 语义搜索返回段落数

    Returns:
        (full_text_sections, semantic_hits, parse_ok)
        - full_text_sections: List[dict](paper_id + paragraph_no + page_no + text)
        - semantic_hits: List[dict](SearchHit.to_dict())
        - parse_ok: bool(任一 PDF 解析成功)
    """
    from agents.pdf_parser import parse_pdf_from_url
    from agents.semantic_search import search_client

    full_text_sections: list[dict] = []
    parse_ok = False

    # 1. 对每个 reference(有 url 的)下载 PDF
    for ref in references:
        url = ref.get("url") or ""
        paper_id = ref.get("url", "").split("/")[-1] if url else None
        if not paper_id or not url.endswith(".pdf"):
            # arxiv url 可能是 https://arxiv.org/abs/2401.12345 → 转 PDF
            if "/abs/" in url:
                arxiv_id = url.split("/")[-1]
                url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                paper_id = f"arxiv:{arxiv_id}"
            else:
                continue

        try:
            doc = parse_pdf_from_url(url, paper_id=paper_id, timeout=20)
        except Exception:
            continue

        if not doc.parse_succeeded:
            continue
        parse_ok = True

        # 段落入库
        for p in doc.paragraphs:
            full_text_sections.append({
                "paper_id": doc.paper_id,
                "title": doc.title or ref.get("title", ""),
                "paragraph_no": p.paragraph_no,
                "page_no": p.page_no,
                "text": p.text[:500],  # 截断,避免响应过大
                "char_count": p.char_count,
            })

        # semantic 索引
        paragraphs_text = [p.text for p in doc.paragraphs]
        page_numbers = [p.page_no for p in doc.paragraphs]
        search_client.add_document(
            paper_id=doc.paper_id,
            paragraphs=paragraphs_text,
            title=doc.title or ref.get("title", ""),
            page_numbers=page_numbers,
        )

    # 2. semantic search(用用户 query)
    semantic_hits: list[dict] = []
    if parse_ok:
        hits = search_client.search(message, top_k=top_k)
        semantic_hits = [h.to_dict() for h in hits]

    return full_text_sections, semantic_hits, parse_ok


def main():
    host = os.environ.get("MATWAU_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("MATWAU_PORT", "8080"))
    server = HTTPServer((host, port), MatWAUAcademicHandler)
    sys.stderr.write(
        f"[matwau-academic] starting {_version_string()} on {host}:{port}\n"
    )
    sys.stderr.write("[matwau-academic] License: Apache 2.0\n")
    sys.stderr.write("[matwau-academic] Maintainer: XploreAlpha\n")

    # W37.12 V1 — 启动 wau-registry 心跳(可选,如配 WAU_JWT_SHARED_SECRET 自动启用)
    wau_client = None
    try:
        from agents.wau_protocol_adapter import WauClient, _load_jwt_secret
        if _load_jwt_secret():
            wau_client = WauClient()
            wau_client.start_heartbeat()
            sys.stderr.write(
                f"[matwau-academic] wau heartbeat started "
                f"(instance={wau_client.config.instance_id[:8]}, "
                f"interval={wau_client.config.heartbeat_interval}s, "
                f"registry={wau_client.config.registry_url})\n"
            )
        else:
            sys.stderr.write(
                "[matwau-academic] WAU_JWT_SHARED_SECRET 未配,skip wau heartbeat\n"
            )
    except Exception as e:
        sys.stderr.write(f"[matwau-academic] wau heartbeat init fail: {e}\n")

    sys.stderr.write("[matwau-academic] Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[matwau-academic] shutting down\n")
        if wau_client:
            wau_client.stop()
        server.server_close()


if __name__ == "__main__":
    main()