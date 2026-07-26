"""serve.py — MatWAU 学院版 HTTP API 服务入口

W37.4 — Docker 容器内启动的 HTTP API 服务
- 默认端口:8080
- 端点:
  - GET  /             — 服务信息
  - GET  /health       — 健康检查(学院 IT 用于监控)
  - GET  /version      — 版本信息(v1.1-Academic)
  - POST /intent       — 解析 1 句话材料意图
  - POST /multi-exp    — 跑多实验并行(Stage 3 JARVIS 雏形)
  - GET  /lineage      — 查 lineage 记录

设计原则:
- 学院版零外部依赖:不强制 LLM,不强制 Postgres(默认 SQLite)
- 数据归学校:所有 lineage 写入学院 IT 指定的 volume
- 不收集任何使用数据(学院版范围外)
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
        else:
            _ok(self, 404, {"error": "not found", "path": self.path})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
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
    sys.stderr.write("[matwau-academic] Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[matwau-academic] shutting down\n")
        server.server_close()


if __name__ == "__main__":
    main()