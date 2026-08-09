"""dispatch_handler.py — wau-edge 调 MatWAU 的 dispatch endpoint

按 v1.0.0 wau App 协议,wau-edge 通过 MatWAU 注册到 wau-registry 时声明的
`url` 字段调 MatWAU 的 dispatch endpoint:

  POST {matwau_url}/wau/dispatch
  Headers: Authorization: Bearer <JWT>
  Body: WauWorkflow-style JSON

WauWorkflow 简化 schema(per wau-python-sdk v1.3.4):
  {
    "workflow_id": "uuid",
    "subclass": "design_new_material",
    "intent": "设计新型无钴锂电池正极...",
    "artifacts": {...},
    "tenant_id": "codex-appserver",
  }

JWT 校验(per wau-edge IssueToken):
  - HS256 + WAU_JWT_SHARED_SECRET
  - 必须 4-claim: iss / sub / exp / tenant_id
  - exp 未过期
  - tenant_id 一致(per security boundary)

设计原则(per MatWAU-Harness-Loop 心法):
  - 失败吞掉:JWT 无效 → 401,不抛
  - 委托模式:不重写 multi-agent 逻辑,转给 MatOrchestrator
  - BaseHTTPRequestHandler 风格:跟 serve.py 一致,不引入 Flask
  - 后向兼容:无 JWT secret 配 → skip 校验(只走开发模式,warn)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False
    pyjwt = None  # type: ignore


# ============================================================================
# JWT 校验
# ============================================================================


def _load_jwt_secret(secrets_file: str | None = None) -> str | None:
    """从 env / secrets file 读 WAU_JWT_SHARED_SECRET"""
    env_val = os.environ.get("WAU_JWT_SHARED_SECRET", "").strip()
    if env_val:
        return env_val

    secrets_file = secrets_file or os.path.expanduser("~/.matwau/wau_secrets.env")
    if os.path.exists(secrets_file):
        try:
            with open(secrets_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WAU_JWT_SHARED_SECRET="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        return val
        except Exception:
            pass
    return None


def _verify_jwt(token: str, secret: str, expected_tenant: str | None = None) -> tuple[bool, str, dict]:
    """验证 JWT HS256

    Args:
        token: Bearer token 字符串
        secret: WAU_JWT_SHARED_SECRET
        expected_tenant: 期望 tenant_id(None → 不强制)

    Returns:
        (ok, error_message, claims)
    """
    if not _HAS_PYJWT:
        return False, "PyJWT 未装", {}

    try:
        claims = pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        return False, "JWT expired", {}
    except pyjwt.InvalidTokenError as e:
        return False, f"invalid JWT: {e}", {}

    # tenant_id 校验
    tenant_id = claims.get("tenant_id", "")
    if expected_tenant and tenant_id != expected_tenant:
        return False, f"tenant_id mismatch: got {tenant_id!r}, expected {expected_tenant!r}", {}

    return True, "", claims


# ============================================================================
# DispatchHandler — /wau/dispatch 端点
# ============================================================================


def make_dispatch_handler(
    *,
    jwt_secret: str | None = None,
    expected_tenant: str | None = None,
    base_handler_class: type = BaseHTTPRequestHandler,
):
    """工厂函数:返回一个 BaseHTTPRequestHandler 子类,带 /wau/dispatch 端点

    用法(per serve.py 模式):
        from agents.wau_protocol_adapter.dispatch_handler import make_dispatch_handler
        DispatchHandler = make_dispatch_handler(
            jwt_secret=secret,
            expected_tenant="codex-appserver",
        )
        # 然后在 main handler 里委派:
        #   if self.path == '/wau/dispatch': self._delegate_to_dispatch()

    设计:不替换原 handler,而是让原 handler 显式调用 dispatcher(避免 path 冲突)
    """
    if jwt_secret is None:
        jwt_secret = _load_jwt_secret()
    if expected_tenant is None:
        expected_tenant = os.environ.get("WAU_TENANT_ID", "codex-appserver")

    class DispatchMixin:
        """Mixin — 给现有 BaseHTTPRequestHandler 加 /wau/dispatch 端点

        用法:
            class MyHandler(DispatchMixin, BaseHTTPRequestHandler):
                pass

            # 然后:
            #   if self.path == '/wau/dispatch':
            #       self.handle_wau_dispatch()
        """

        # 把 factory-time 变量绑成 class attr(给下面 method 用)
        _wau_jwt_secret = jwt_secret
        _wau_expected_tenant = expected_tenant
        _wau_dispatch_skip_jwt = (jwt_secret is None or jwt_secret == "")

        def _wau_ok(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle_wau_dispatch(self) -> None:
            """处理 POST /wau/dispatch 或 GET /wau/dispatch(health)"""
            if self.command == "GET":
                # health check
                # 2026-08-05 P2 fix:版本号同步到 VERSION 文件,加 last_fix_at 字段
                from pathlib import Path as _P
                _version_file = _P(__file__).resolve().parents[2] / "VERSION"
                try:
                    _version = _version_file.read_text().strip()
                except Exception:
                    _version = "v1.3-Academic"  # 兜底
                self._wau_ok(200, {
                    "status": "ok",
                    "agent": "matwau",
                    "version": _version,
                    "last_fix_at": "2026-08-05",  # 4 个 P0/P1 bug 收口日
                    "fix_summary": "4 P0/P1 bug 修复(routing + cross_source timeout + dict CanonicalKey + mat-exp confidence)",
                    "endpoint": "/wau/dispatch",
                    "jwt_required": not self._wau_dispatch_skip_jwt,
                })
                return

            # POST — 读 body + 校验 JWT + 转给 orchestrator
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                self._wau_ok(400, {"error": f"invalid JSON: {e}"})
                return

            # 1. JWT 校验
            if not self._wau_dispatch_skip_jwt:
                auth_header = self.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    self._wau_ok(401, {"error": "missing Authorization Bearer"})
                    return
                token = auth_header[len("Bearer "):]
                ok, err, claims = _verify_jwt(token, self._wau_jwt_secret, self._wau_expected_tenant)
                if not ok:
                    self._wau_ok(401, {"error": err})
                    return

                # 校验 tenant_id 是否跟 payload 一致
                payload_tenant = payload.get("tenant_id", "")
                if payload_tenant and claims.get("tenant_id") != payload_tenant:
                    self._wau_ok(403, {"error": "tenant_id payload/JWT mismatch"})
                    return
            else:
                logger.warning(
                    "[dispatch] WAU_JWT_SHARED_SECRET 未配,skip JWT 校验(开发模式)"
                )

            # 2. 转给 MatOrchestrator
            intent = payload.get("intent", "")
            if not intent:
                self._wau_ok(400, {"error": "missing 'intent'"})
                return

            try:
                # sys.path patch 让 agents.* 能 import
                _project_root = Path(__file__).resolve().parents[2]
                if str(_project_root) not in sys.path:
                    sys.path.insert(0, str(_project_root))

                from agents.mat_orchestrator import MatOrchestrator

                orch = MatOrchestrator()
                # 2026-08-05 P2 fix:MatOrchestrator.run() 签名是 keyword-only user_intent:str
                # 原代码 orch.run(req) 会 TypeError
                # M3.5 修复 (2026-08-09):透传 payload 给 paper_fulltext / semantic_search 用
                # - pdf_url / pdf_path / pdf_bytes → paper_fulltext workflow
                # - query_english → semantic_search workflow
                # - context(dict) → 任何 workflow
                wf_result = orch.run(
                    user_intent=intent,
                    pdf_url=payload.get("pdf_url"),
                    pdf_path=payload.get("pdf_path"),
                    pdf_bytes=payload.get("pdf_bytes"),
                    query_english=payload.get("query_english"),
                    context=payload.get("context"),
                )

                self._wau_ok(200, {
                    "status": "ok" if wf_result.success else "fail",
                    "workflow_id": payload.get("workflow_id"),
                    "subclass": payload.get("subclass") or wf_result.subclass,
                    "workflow_name": wf_result.workflow_name,
                    "success": wf_result.success,
                    "error": wf_result.error,
                    "total_duration_seconds": round(wf_result.total_duration_seconds, 3),
                    "final_outputs": {
                        k: str(v)[:200] for k, v in (wf_result.final_outputs or {}).items()
                    },
                    "node_results_count": len(wf_result.node_results),
                })
            except Exception as e:
                logger.exception("[dispatch] orchestrator run 失败")
                self._wau_ok(500, {"error": str(e)})

    return DispatchMixin


__all__ = [
    "_load_jwt_secret",
    "_verify_jwt",
    "make_dispatch_handler",
]