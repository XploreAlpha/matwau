"""matwau.configs — MatWAU 全局配置(W32 引入)

包含:
- matwau_settings: 读环境变量(MATWAU_PG_DSN / MATWAU_LINEAGE_BACKEND)工厂函数
- get_lineage_store(): 自动选 backend(in-memory / SQLite / Postgres)
- get_orchestrator(): 默认 orchestrator 工厂

per W32 LineageStore 自动记录
"""
from .matwau_settings import (
    get_lineage_store,
    get_orchestrator,
    get_default_settings,
    MatWAUSettings,
    reset_settings_cache,
    DEFAULT_LLM_BASE_URL,        # W33
    DEFAULT_LLM_MODEL,            # W33
    DEFAULT_PG_DSN,
    DEFAULT_SQLITE_PATH,
    BACKEND_POSTGRES,
    BACKEND_SQLITE,
    BACKEND_MEMORY,
)

__all__ = [
    "get_lineage_store",
    "get_orchestrator",
    "get_default_settings",
    "MatWAUSettings",
    "reset_settings_cache",
    "DEFAULT_LLM_BASE_URL",       # W33
    "DEFAULT_LLM_MODEL",           # W33
    "DEFAULT_PG_DSN",
    "DEFAULT_SQLITE_PATH",
    "BACKEND_POSTGRES",
    "BACKEND_SQLITE",
    "BACKEND_MEMORY",
]