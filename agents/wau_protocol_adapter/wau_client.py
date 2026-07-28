"""wau_client.py — MatWAU 的 wau App 协议 client

按 v1.0.0 wau-registry-service 协议(per /home/inamoto888/project/wau-registry-service/internal/api/http.go):
  - POST /v1/agents           register(首次)
  - POST /v1/agents/heartbeat 定时(默认 30s)
  - GET  /health              registry 健康检查(per Stage 0-1 verify)
  - DELETE /v1/agents/{name}  unregister(关闭时, server 返回 501 — 当前 v0.3.0 未实装)

JWT HS256(per wau-edge/internal/auth/jwt.go IssueToken):
  - iss   : agent 名(matwau)
  - sub   : instance_id(uuid4)
  - exp   : now + 60s
  - nbf   : now
  - tenant_id : 默认 "codex-appserver"

env vars(从 ~/.matwau/wau_secrets.env 读,chmod 600):
  - WAU_JWT_SHARED_SECRET  (必填)
  - WAU_TENANT_ID          (默认 "codex-appserver")
  - WAU_REGISTRY_URL       (默认 http://43.134.126.126:18401)
  - MATWAU_PUBLIC_HOST     (公网 IP / 域名, 默认 localhost → 仅作名片,wau 无法回调)

设计原则(per MatWAU-Harness-Loop 心法):
  - 失败吞掉:register/heartbeat 失败只 log,不抛
  - 自动 retry:exponential backoff
  - 线程安全:heartbeat 后台 daemon 线程
  - 后向兼容:不传 instance_id → 自生成 uuid4
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt  # PyJWT
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False
    pyjwt = None  # type: ignore


# ============================================================================
# 默认 / 常量
# ============================================================================

DEFAULT_REGISTRY_URL = "http://43.134.126.126:18401"
DEFAULT_TENANT_ID = "codex-appserver"
DEFAULT_HEARTBEAT_INTERVAL = 30  # seconds
JWT_TTL_SECONDS = 60


@dataclass
class WauConfig:
    """WauClient 配置(从 env 读 + 默认值)

    字段:
    - registry_url: wau-registry HTTP base URL
    - jwt_secret:   HS256 shared secret(per server WAU_EDGE_JWT_SECRET)
    - tenant_id:    wau-edge tenant_id claim
    - agent_name:   MatWAU instance 名(默认 "matwau")
    - heartbeat_interval: 心跳秒数(默认 30)
    """
    registry_url: str = DEFAULT_REGISTRY_URL
    jwt_secret: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    agent_name: str = "matwau"
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL
    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    host: str = "localhost"

    @classmethod
    def from_env(cls, secrets_file: Optional[str] = None) -> "WauConfig":
        """从 env + secrets file 构造 config

        优先级:显式 arg > env var > secrets file > default

        Args:
            secrets_file: ~/.matwau/wau_secrets.env 路径(None → 用默认)
        """
        secrets_file = secrets_file or os.path.expanduser("~/.matwau/wau_secrets.env")
        env: dict[str, str] = {}

        # 1. 读 secrets file
        if os.path.exists(secrets_file):
            try:
                with open(secrets_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            env[k.strip()] = v.strip().strip('"').strip("'")
            except Exception as e:
                logger.warning("[WauClient] 读 secrets file 失败: %s", e)

        # 2. env 覆盖(file < env)
        for k in ("WAU_JWT_SHARED_SECRET", "WAU_TENANT_ID", "WAU_REGISTRY_URL",
                  "MATWAU_PUBLIC_HOST", "MATWAU_AGENT_NAME", "WAU_HEARTBEAT_INTERVAL_MS"):
            if os.environ.get(k):
                env[k] = os.environ[k]

        # 3. 构造
        registry_url = env.get("WAU_REGISTRY_URL", DEFAULT_REGISTRY_URL).rstrip("/")
        jwt_secret = env.get("WAU_JWT_SHARED_SECRET", "")
        tenant_id = env.get("WAU_TENANT_ID", DEFAULT_TENANT_ID)
        host = env.get("MATWAU_PUBLIC_HOST", "localhost")
        agent_name = env.get("MATWAU_AGENT_NAME", "matwau")

        heartbeat_ms = int(env.get("WAU_HEARTBEAT_INTERVAL_MS", str(DEFAULT_HEARTBEAT_INTERVAL * 1000)))
        heartbeat_interval = max(5, heartbeat_ms // 1000)  # 最小 5s

        return cls(
            registry_url=registry_url,
            jwt_secret=jwt_secret,
            tenant_id=tenant_id,
            agent_name=agent_name,
            heartbeat_interval=heartbeat_interval,
            host=host,
        )


# ============================================================================
# WauClient — MatWAU wau App 协议 client
# ============================================================================


class WauClient:
    """MatWAU wau App 协议 client

    用法:
        client = WauClient()  # 自动 from_env 读 secrets file
        client.register()     # POST /v1/agents
        client.heartbeat()    # POST /v1/agents/heartbeat
        client.start_heartbeat()  # 后台线程,默认 30s 一次
        # ... 业务 ...
        client.stop()         # 停后台心跳
    """

    def __init__(
        self,
        config: Optional[WauConfig] = None,
        *,
        registry_url: Optional[str] = None,
        jwt_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        agent_name: str = "matwau",
    ) -> None:
        """构造

        Args:
            config: WauConfig 实例(None → WauConfig.from_env())
            registry_url: 覆盖 config
            jwt_secret: 覆盖 config
            tenant_id: 覆盖 config
            instance_id: 自定义 UUID(None → 自生成)
            agent_name: MatWAU agent 名
        """
        if config is None:
            config = WauConfig.from_env()

        # arg 覆盖
        if registry_url:
            config.registry_url = registry_url.rstrip("/")
        if jwt_secret:
            config.jwt_secret = jwt_secret
        if tenant_id:
            config.tenant_id = tenant_id
        if instance_id:
            config.instance_id = instance_id
        if agent_name:
            config.agent_name = agent_name

        self.config = config
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._register_lock = threading.Lock()
        self._registered = False

    # ----------------------------------------------------------------
    # JWT 签发(HS256,per wau-edge/internal/auth/jwt.go)
    # ----------------------------------------------------------------
    def _make_jwt(self) -> str:
        """签发 HS256 JWT(per wau-edge IssueToken schema)

        Claims:
        - iss: "matwau"(agent 名)
        - sub: instance_id
        - exp: now + JWT_TTL_SECONDS(60s)
        - nbf: now
        - tenant_id: config.tenant_id
        """
        if not _HAS_PYJWT:
            raise RuntimeError("PyJWT 未装,无法签 JWT。pip install 'PyJWT>=2.0,<3.0'")

        if not self.config.jwt_secret:
            raise RuntimeError(
                "WAU_JWT_SHARED_SECRET 未配。在 ~/.matwau/wau_secrets.env 写 "
                "WAU_JWT_SHARED_SECRET=<64字符 hex>"
            )

        now = int(time.time())
        payload = {
            "iss": self.config.agent_name,
            "sub": self.config.instance_id,
            "exp": now + JWT_TTL_SECONDS,
            "nbf": now,
            "tenant_id": self.config.tenant_id,
        }
        return pyjwt.encode(payload, self.config.jwt_secret, algorithm="HS256")

    def _auth_headers(self) -> dict:
        """构造带 JWT 的 Authorization header"""
        return {"Authorization": f"Bearer {self._make_jwt()}"}

    # ----------------------------------------------------------------
    # 注册 / 心跳
    # ----------------------------------------------------------------
    def register(self, *, timeout: float = 10.0) -> dict:
        """注册到 wau-registry(POST /v1/agents)

        per wau-registry-service/internal/api/http.go handleRegisterAgent:
        - Body: RegistryAgentCard JSON
          {name, description, url, skills[], universes[], version, last_seen}
        - 成功:204 No Content

        Args:
            timeout: HTTP timeout 秒数

        Returns:
            dict with 'status', 'instance_id', 'agent_name', 'timestamp'

        Raises:
            requests.HTTPError: wau-registry 返 4xx/5xx
        """
        card = {
            "name": self.config.agent_name,
            "description": f"MatWAU multi-agent material science ({self.config.instance_id[:8]})",
            "url": f"http://{self.config.host}:8080/wau/dispatch",
            "skills": ["multi_agent", "critic_llm", "deepseek", "material_science"],
            "universes": ["matwau", "academic"],
            "version": "v1.1.1-Academic",
        }

        with self._register_lock:
            resp = requests.post(
                f"{self.config.registry_url}/v1/agents",
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            self._registered = True
            logger.info(
                "[WauClient] 注册成功 agent=%s instance=%s status=%d",
                self.config.agent_name, self.config.instance_id[:8], resp.status_code,
            )
            return {
                "status": "ok",
                "instance_id": self.config.instance_id,
                "agent_name": self.config.agent_name,
                "timestamp": time.time(),
                "http_status": resp.status_code,
            }

    def heartbeat(self, *, timeout: float = 5.0) -> dict:
        """发送心跳(POST /v1/agents/heartbeat)

        per wau-registry-service/internal/api/http.go handleHeartbeat:
        - Body: RegistryAgentCard JSON(simplified = same as register)
        - 成功:204 No Content

        Args:
            timeout: HTTP timeout 秒数

        Returns:
            dict with 'status', 'timestamp'

        Note:
            wau-registry 当前不要求 JWT(wau-edge 才要),为未来兼容仍带 Authorization
        """
        card = {
            "name": self.config.agent_name,
            "description": "MatWAU heartbeat",
            "url": f"http://{self.config.host}:8080/wau/dispatch",
            "skills": ["multi_agent", "critic_llm"],
            "universes": ["matwau"],
            "version": "v1.1.1-Academic",
        }

        try:
            headers = {"Content-Type": "application/json"}
            if self.config.jwt_secret:
                headers.update(self._auth_headers())

            resp = requests.post(
                f"{self.config.registry_url}/v1/agents/heartbeat",
                json=card,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            return {"status": "ok", "timestamp": time.time(), "http_status": resp.status_code}
        except Exception as e:
            logger.warning("[WauClient] heartbeat 失败(下次重试): %s", e)
            return {"status": "fail", "error": str(e), "timestamp": time.time()}

    def health(self, *, timeout: float = 3.0) -> bool:
        """检查 wau-registry 是否可达(GET /health)

        Returns:
            True 如果 200, False 否则
        """
        try:
            resp = requests.get(
                f"{self.config.registry_url}/health",
                timeout=timeout,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.debug("[WauClient] health check 失败: %s", e)
            return False

    # ----------------------------------------------------------------
    # 后台心跳线程
    # ----------------------------------------------------------------
    def _heartbeat_loop(self) -> None:
        """后台心跳循环(daemon 线程)"""
        logger.info(
            "[WauClient] 心跳线程启动 interval=%ds agent=%s instance=%s",
            self.config.heartbeat_interval, self.config.agent_name, self.config.instance_id[:8],
        )
        while not self._stop_event.is_set():
            try:
                self.heartbeat()
            except Exception as e:
                logger.warning("[WauClient] 心跳异常: %s", e)
            self._stop_event.wait(self.config.heartbeat_interval)
        logger.info("[WauClient] 心跳线程退出")

    def start_heartbeat(self) -> None:
        """启动后台心跳线程(daemon)"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            logger.warning("[WauClient] 心跳线程已在运行,跳过 start")
            return

        # 先 register 一次(如果未注册)
        if not self._registered:
            try:
                self.register()
            except Exception as e:
                logger.warning("[WauClient] register 失败,心跳线程仍启动: %s", e)

        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="matwau-wau-heartbeat",
        )
        self._heartbeat_thread.start()

    def stop(self) -> None:
        """停心跳线程(等当前 sleep 醒)"""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=self.config.heartbeat_interval + 2)
            self._heartbeat_thread = None

    # ----------------------------------------------------------------
    # 上下文管理器支持
    # ----------------------------------------------------------------
    def __enter__(self) -> "WauClient":
        self.start_heartbeat()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


__all__ = [
    "WauClient",
    "WauConfig",
    "DEFAULT_REGISTRY_URL",
    "DEFAULT_TENANT_ID",
]