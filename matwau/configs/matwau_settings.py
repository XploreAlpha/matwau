"""matwau_settings.py — W32 MatWAU 全局配置 + 工厂函数

核心功能:
1. **get_lineage_store()** — 自动选 backend:
   - MATWAU_LINEAGE_BACKEND=postgres + MATWAU_PG_DSN=<dsn> → PostgresBackend
   - MATWAU_LINEAGE_BACKEND=sqlite → SQLiteBackend(`~/.matwau/lineage.db`)
   - 默认 / 其它 → InMemoryBackend(进程内 dict)

2. **get_orchestrator()** — 默认 MatOrchestrator 工厂,自动接 get_lineage_store()

3. **环境变量**(per W23/W29 已就绪):
   - MATWAU_PG_DSN — Postgres 连接串(默认 `postgresql://localhost:5432/matwau`)
   - MATWAU_LINEAGE_BACKEND — 强制指定 backend("postgres" / "sqlite" / "memory")
   - MATWAU_LINEAGE_DISABLED=1 — 关闭 lineage(测试 / CI 友好)

设计原则:
- 单例缓存(default settings + default store)— 多次调 get_*() 返回同一对象
- reset_settings_cache() — 测试用,重置缓存
- 显式 None / 工厂注入 — 测试时可显式注入 InMemoryBackend / mock backend

per W32 plan §D
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


# ============================================================================
# 默认 / 环境变量常量
# ============================================================================

# 默认 PG DSN(若没设 MATWAU_PG_DSN) — 本机起 docker-compose 默认值
DEFAULT_PG_DSN = "postgresql://matwau:matwau_dev_pw@localhost:5432/matwau"

# 默认 SQLite 路径
DEFAULT_SQLITE_PATH = "~/.matwau/lineage.db"

# 合法 backend 值
BACKEND_POSTGRES = "postgres"
BACKEND_SQLITE = "sqlite"
BACKEND_MEMORY = "memory"


# ============================================================================
# W33 — LLM 配置常量(DeepSeek 默认 per user-confirmed 2026-07-26)
# ============================================================================

# 默认 base URL(DeepSeek)
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"

# 默认 model(deepseek-v4-flash per user-confirmed)
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


# ============================================================================
# M3 — 4 个数据源 env var 常量
# ============================================================================

# 默认 API URL(per M2 设计)
DEFAULT_NOMAD_API_BASE = "https://nomad-lab.eu/prod/v1/api/v1"
DEFAULT_JARVIS_API_BASE = "https://jarvis.nist.gov/api"

# 默认 token(空字符串 = 不带 Bearer;NOMAD / JARVIS 是可选认证)
DEFAULT_NOMAD_TOKEN = ""
DEFAULT_JARVIS_TOKEN = ""


# ============================================================================
# MatWAUSettings dataclass — 不可变配置快照
# ============================================================================


@dataclass(frozen=True)
class MatWAUSettings:
    """MatWAU 全局配置(不可变)

    字段:
    - lineage_backend: 'postgres' / 'sqlite' / 'memory'
    - lineage_pg_dsn: Postgres 连接串
    - lineage_sqlite_path: SQLite 文件路径
    - lineage_disabled: 全局关闭 lineage(测试用)
    - log_level: 'DEBUG' / 'INFO' / 'WARNING'
    - W33:
      - llm_api_key: LLM API key(无则跳过 LLM review)
      - llm_base_url: LLM API base URL(默认 DeepSeek)
      - llm_model: model 名(默认 deepseek-v4-flash)
      - llm_enabled: 是否启用 LLM review(默认 False — 需显式开)
    - M3 NEW — 4 个数据源 env vars:
      - nomad_api_base / jarvis_api_base: API URL 覆盖
      - nomad_token / jarvis_token: Bearer token(可选)
    """
    lineage_backend: str = BACKEND_MEMORY
    lineage_pg_dsn: str = DEFAULT_PG_DSN
    lineage_sqlite_path: str = DEFAULT_SQLITE_PATH
    lineage_disabled: bool = False
    log_level: str = "INFO"
    # W33 — LLM 配置
    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_enabled: bool = False
    # M3 NEW — 4 数据源配置
    nomad_api_base: str = DEFAULT_NOMAD_API_BASE
    jarvis_api_base: str = DEFAULT_JARVIS_API_BASE
    nomad_token: str = DEFAULT_NOMAD_TOKEN
    jarvis_token: str = DEFAULT_JARVIS_TOKEN

    @property
    def use_postgres(self) -> bool:
        return self.lineage_backend == BACKEND_POSTGRES and not self.lineage_disabled

    @property
    def use_sqlite(self) -> bool:
        return self.lineage_backend == BACKEND_SQLITE and not self.lineage_disabled

    @property
    def llm_configured(self) -> bool:
        """LLM 是否完整配置(API key + enabled)"""
        return self.llm_enabled and bool(self.llm_api_key)


# ============================================================================
# 从环境变量读 settings(单例缓存)
# ============================================================================

_settings_cache: Optional[MatWAUSettings] = None
_settings_lock = threading.Lock()


def get_default_settings() -> MatWAUSettings:
    """读环境变量,返回 MatWAUSettings(单例缓存)

    Env vars 优先级:
    - MATWAU_LINEAGE_DISABLED=1 → lineage_disabled=True
    - MATWAU_LINEAGE_BACKEND=postgres/sqlite/memory → lineage_backend
    - MATWAU_PG_DSN=<dsn> → lineage_pg_dsn
    - MATWAU_LINEAGE_SQLITE_PATH=<path> → lineage_sqlite_path
    - MATWAU_LOG_LEVEL=DEBUG/INFO/WARNING → log_level
    - W33:
      - MATWAU_LLM_API_KEY=<key> → llm_api_key
      - MATWAU_LLM_BASE_URL=<url> → llm_base_url
      - MATWAU_LLM_MODEL=<model> → llm_model
      - MATWAU_LLM_ENABLED=1/true/yes → llm_enabled=True
    """
    global _settings_cache

    if _settings_cache is not None:
        return _settings_cache

    with _settings_lock:
        if _settings_cache is not None:  # double-check
            return _settings_cache

        backend_env = os.environ.get("MATWAU_LINEAGE_BACKEND", "").strip().lower()
        valid_backends = {BACKEND_POSTGRES, BACKEND_SQLITE, BACKEND_MEMORY}
        backend = backend_env if backend_env in valid_backends else BACKEND_MEMORY

        # W33 — LLM env vars
        llm_api_key = os.environ.get("MATWAU_LLM_API_KEY", "").strip()
        llm_base_url = os.environ.get("MATWAU_LLM_BASE_URL", "").strip() or DEFAULT_LLM_BASE_URL
        llm_model = os.environ.get("MATWAU_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
        llm_enabled = os.environ.get("MATWAU_LLM_ENABLED", "").strip().lower() in ("1", "true", "yes")

        settings = MatWAUSettings(
            lineage_backend=backend,
            lineage_pg_dsn=os.environ.get("MATWAU_PG_DSN", DEFAULT_PG_DSN).strip() or DEFAULT_PG_DSN,
            lineage_sqlite_path=os.environ.get("MATWAU_LINEAGE_SQLITE_PATH", DEFAULT_SQLITE_PATH).strip() or DEFAULT_SQLITE_PATH,
            lineage_disabled=os.environ.get("MATWAU_LINEAGE_DISABLED", "").strip() in ("1", "true", "yes"),
            log_level=os.environ.get("MATWAU_LOG_LEVEL", "INFO").strip() or "INFO",
            # W33
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_enabled=llm_enabled,
            # M3 NEW
            nomad_api_base=os.environ.get("MATWAU_NOMAD_API_BASE", DEFAULT_NOMAD_API_BASE).strip() or DEFAULT_NOMAD_API_BASE,
            jarvis_api_base=os.environ.get("MATWAU_JARVIS_API_BASE", DEFAULT_JARVIS_API_BASE).strip() or DEFAULT_JARVIS_API_BASE,
            nomad_token=os.environ.get("MATWAU_NOMAD_TOKEN", DEFAULT_NOMAD_TOKEN).strip(),
            jarvis_token=os.environ.get("MATWAU_JARVIS_TOKEN", DEFAULT_JARVIS_TOKEN).strip(),
        )
        # 直接设(锁内)
        globals()["_settings_cache"] = settings
        return settings


def reset_settings_cache() -> None:
    """重置 settings 缓存(测试用)"""
    global _settings_cache
    with _settings_lock:
        _settings_cache = None


# ============================================================================
# get_lineage_store() — 工厂函数
# ============================================================================


_store_cache: Any = None  # LineageStore / None
_store_cache_settings_hash: Optional[int] = None  # 缓存时的 settings hash(检测变化)
_store_lock = threading.Lock()


def _settings_hash(settings: MatWAUSettings) -> int:
    """算 settings 的 hash(检测变化用)"""
    return hash((
        settings.lineage_backend,
        settings.lineage_pg_dsn,
        settings.lineage_sqlite_path,
        settings.lineage_disabled,
    ))


def get_lineage_store(backend: Optional[Any] = None, *, force_recreate: bool = False):
    """获取默认 LineageStore(单例,但 settings 变化时自动重建)

    Args:
        backend: 显式注入 backend 实例(优先于环境变量)
            None → 根据 MatWAUSettings 自动选
        force_recreate: 强制重建(测试用)

    Returns:
        LineageStore 实例(backend 可能是 InMemoryBackend / SQLiteBackend / PostgresBackend)
        若 lineage_disabled=True → 返回 None(hook 自动跳过)
    """
    global _store_cache, _store_cache_settings_hash

    settings = get_default_settings()
    if settings.lineage_disabled:
        return None

    if backend is not None:
        # 显式 backend — 立即造 1 个新 store,不缓存
        from agents.mat_data_lineage_agent import LineageStore
        return LineageStore(backend=backend)

    settings_hash = _settings_hash(settings)

    if _store_cache is not None and not force_recreate:
        if _store_cache_settings_hash == settings_hash:
            return _store_cache
        # settings 变了 → 重建
        try:
            _store_cache.backend.close()
        except Exception:
            pass

    with _store_lock:
        if _store_cache is not None and not force_recreate and _store_cache_settings_hash == settings_hash:
            return _store_cache

        from agents.lineage_store_backend import (
            InMemoryBackend,
            SQLiteBackend,
            PostgresBackend,
        )
        from agents.mat_data_lineage_agent import LineageStore

        chosen_backend = None
        if settings.use_postgres:
            try:
                chosen_backend = PostgresBackend(
                    dsn=settings.lineage_pg_dsn,
                    use_fallback=True,  # 无 psycopg 或连不上 → 降级 SQLite
                )
            except Exception:
                # 构造失败 → 降级 SQLite
                chosen_backend = SQLiteBackend(db_path=settings.lineage_sqlite_path)
        elif settings.use_sqlite:
            chosen_backend = SQLiteBackend(db_path=settings.lineage_sqlite_path)
        else:
            chosen_backend = InMemoryBackend()

        store = LineageStore(backend=chosen_backend)
        # 直接设(锁内)
        globals()["_store_cache"] = store
        globals()["_store_cache_settings_hash"] = settings_hash
        return store


# ============================================================================
# get_orchestrator() — 默认 orchestrator 工厂(自动接 lineage)
# ============================================================================


def get_orchestrator(*, with_lineage: bool = True, **kwargs):
    """获取默认 MatOrchestrator 实例(自动接 lineage store)

    Args:
        with_lineage: True → 自动传 lineage_store=W32 hook
        kwargs: 透传给 MatOrchestrator.__init__

    Returns:
        MatOrchestrator 实例
    """
    from agents.mat_orchestrator import MatOrchestrator

    if with_lineage and "lineage_store" not in kwargs:
        kwargs["lineage_store"] = get_lineage_store()

    return MatOrchestrator(**kwargs)


__all__ = [
    "MatWAUSettings",
    "get_default_settings",
    "reset_settings_cache",
    "get_lineage_store",
    "get_orchestrator",
    "DEFAULT_PG_DSN",
    "DEFAULT_SQLITE_PATH",
    "BACKEND_POSTGRES",
    "BACKEND_SQLITE",
    "BACKEND_MEMORY",
    # W33
    "DEFAULT_LLM_BASE_URL",
    "DEFAULT_LLM_MODEL",
    # M3 NEW
    "DEFAULT_NOMAD_API_BASE",
    "DEFAULT_JARVIS_API_BASE",
    "DEFAULT_NOMAD_TOKEN",
    "DEFAULT_JARVIS_TOKEN",
]