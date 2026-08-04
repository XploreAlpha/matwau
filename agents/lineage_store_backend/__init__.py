"""lineage_store_backend — mat-data-lineage 的存储后端抽象(W16 + W17)

设计目标:
- 抽象 LineageBackend 接口,实现可插拔(in-memory / SQLite / Postgres / 未来 wau-lineage SDK)
- W16: 2 个实现:InMemoryBackend(W14 默认) + SQLiteBackend(W16 真持久化)
- W17: + PostgresBackend(降级策略:无 psycopg 时自动 fallback 到 SQLite)
- 未来换 wau-lineage SDK 时,只需新加 1 个 LineageBackend 子类

Stage 1: 默认 InMemoryBackend(W14 行为不变)
Stage 2(W16): SQLiteBackend 真持久化,关 Python 重启数据还在
Stage 2(W17): PostgresBackend(降级到 SQLite,行为同 SQLite)

用法:
    from agents.lineage_store_backend import SQLiteBackend, PostgresBackend

    # W16 SQLite
    backend = SQLiteBackend(db_path="/tmp/lineage.db")
    # ...写记录...
    # 关闭 + 重开 Python
    backend2 = SQLiteBackend(db_path="/tmp/lineage.db")
    # 数据还在

    # W17 Postgres(降级)
    backend = PostgresBackend(dsn="postgresql://localhost/matwau")
    # 本机无 psycopg → 自动用 SQLite 降级,行为完整
"""

from __future__ import annotations

from .backends import (
    InMemoryBackend,
    LineageBackend,
    LineageNotFoundError,
    LineageRecordDTO,
    PostgresBackend,
    SQLiteBackend,
)

__all__ = [
    "InMemoryBackend",
    "LineageBackend",
    "LineageNotFoundError",
    "LineageRecordDTO",
    "PostgresBackend",
    "SQLiteBackend",
]  # type: ignore[name-defined]