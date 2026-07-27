"""wau_protocol_adapter — MatWAU 的 wau 网络层适配器

W37.12 V1.0-Academic(per plan 2026-07-27 wau-integration-test-plan):
让 MatWAU(学院方本机 App)接入 wau 远程网络(43.134.126.126),
让本机 HomeRail(homerail = wau Siri 入口)能远程调 MatWAU 的 multi-agent。

模块构成:
- `wau_client.py`        — 注册 / 心跳 / JWT 签发 / 后台心跳线程
- `dispatch_handler.py` — /wau/dispatch 端点,接 wau-edge JWT 校验 + 转 orchestrator

env vars(从 ~/.matwau/wau_secrets.env 读,chmod 600):
- WAU_JWT_SHARED_SECRET  (必填, HS256 shared secret)
- WAU_TENANT_ID          (默认 "codex-appserver")
- WAU_REGISTRY_URL       (默认 http://43.134.126.126:18401)
- MATWAU_HOST            (默认 localhost)

W37.12 lessons learned:
- ⚠️ BaseHTTPRequestHandler 风格(跟 serve.py 一致,不引入 Flask)
- ⚠️ wau-registry 不要求 JWT, wau-edge 才要求
- ⚠️ tenant_id 默认 "codex-appserver" 跟 homerail + wau-team 一致
- ⚠️ per project-matwau-os-boundary-2026-07-23:MatWAU 数据归学院方

quick start:
    from agents.wau_protocol_adapter import WauClient, make_dispatch_handler
    client = WauClient()
    client.register()                    # 注册到 wau-registry
    client.start_heartbeat()              # 后台心跳
    # ... app.py 在 /wau/dispatch 端点用 make_dispatch_handler() ...
"""
from .wau_client import (
    WauClient,
    WauConfig,
    DEFAULT_REGISTRY_URL,
    DEFAULT_TENANT_ID,
)
from .dispatch_handler import (
    make_dispatch_handler,
    _verify_jwt,
    _load_jwt_secret,
)

__all__ = [
    "WauClient",
    "WauConfig",
    "make_dispatch_handler",
    "DEFAULT_REGISTRY_URL",
    "DEFAULT_TENANT_ID",
    "_verify_jwt",
    "_load_jwt_secret",
]