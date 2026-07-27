"""serve.py — MatWAU 学院版 HTTP API 服务入口

W37.4 + W37.12 — Docker 容器内启动的 HTTP API 服务
- 默认端口:8080
- 端点:
  - GET  /             — 服务信息
  - GET  /health       — 健康检查(学院 IT 用于监控)
  - GET  /version      — 版本信息(v1.1.1-Academic)
  - POST /intent       — 解析 1 句话材料意图
  - POST /multi-exp    — 跑多实验并行(Stage 3 JARVIS 雏形)
  - GET  /lineage      — 查 lineage 记录
  - GET  /wau/dispatch — wau-edge 健康检查(V1 接公网 wau)
  - POST /wau/dispatch — wau-edge 路由到此,接 JWT 校验 + 转 orchestrator(V1 接公网 wau)

设计原则:
- 学院版零外部依赖:不强制 LLM,不强制 Postgres(默认 SQLite)
- 数据归学校:所有 lineage 写入学院 IT 指定的 volume
- 不收集任何使用数据(学院版范围外)
- V1 可选接 wau 公网:配 WAU_JWT_SHARED_SECRET → 启用,否则 skip(per dispatch_handler)
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# 让 serve.py 能 import matwau 顶层模块
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


def _version_string() -> str:
    """读 VERSION 文件或用默认值"""
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "v1.0-Academic"


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
                records = store.list(limit=10)
                _ok(self, 200, {
                    "n_records": len(records),
                    "records": [r.to_dict() if hasattr(r, "to_dict") else r for r in records],
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
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"

        # W37.12 — /wau/dispatch 端点
        if self.path == "/wau/dispatch":
            self._handle_wau_dispatch(raw)
            return

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            _ok(self, 400, {"error": "invalid JSON"})
            return

        if self.path == "/intent":
            self._handle_intent(payload)
        elif self.path == "/multi-exp":
            self._handle_multi_experiment(payload)
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
            from matwau.core.agent_base import AgentRequest

            orch = MatOrchestrator()
            req = AgentRequest(
                run_id=payload.get("workflow_id", f"wau-dispatch-{os.getpid()}"),
                message=intent,
                artifacts=payload.get("artifacts", {}),
                context={"source": "wau-dispatch", "subclass": payload.get("subclass", "")},
            )
            resp = orch.run(req)
            _ok(self, 200, {
                "status": "ok",
                "workflow_id": payload.get("workflow_id"),
                "subclass": payload.get("subclass"),
                "reply": resp.reply,
                "artifacts_summary": {
                    k: str(v)[:200] for k, v in (resp.artifacts or {}).items()
                },
                "cost": resp.cost,
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


def main():
    host = os.environ.get("MATWAU_HOST", "0.0.0.0")
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