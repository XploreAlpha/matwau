"""lineage_store_backend / backends.py — 后端抽象 + 3 个实现(W16 + W17)

抽象接口 LineageBackend:
- add(record) → None
- get(lineage_id) → record
- list() → List[record]
- list_by_run(run_id) → List[record]
- list_by_parent(parent_run_id) → List[record]
- delete(lineage_id) → None(测试用)
- close() → None(资源清理)

3 个实现:
- InMemoryBackend(W14 行为,默认)— 进程 dict,快,W14 测试用
- SQLiteBackend(W16 真持久化)— 磁盘文件,关 Python 重开数据还在
- PostgresBackend(W17)— 同接口,可接 PG(若装 psycopg)/ 或降级用 SQLite Backend 类比

设计核心(W17 验证):**后端可换,LineageStore 0 改动**
换 PG / wau-lineage SDK 时,只需新加 1 个 LineageBackend 子类。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class LineageNotFoundError(KeyError):
    """找不到 lineage 记录时抛"""


# ============================================================================
# 数据类 — 与 mat_data_lineage_agent/lineage_engine.py 兼容
# ============================================================================


@dataclass
class LineageRecordDTO:
    """lineage record DTO(跟 mat-data-lineage 内部 LineageRecord 同形)

    字段:
    - lineage_id: 唯一 ID
    - run_id: 业务 run ID
    - parent_run_id: 上游 run ID
    - agent_name: agent 名
    - input_hash / output_hash: SHA256 prefix
    - timestamp: ISO 8601
    - 其他元数据:metadata dict
    """

    lineage_id: str
    run_id: str
    parent_run_id: Optional[str] = None
    agent_name: str = ""
    input_hash: str = ""
    output_hash: str = ""
    timestamp: str = ""
    duration_seconds: float = 0.0
    cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    # W16: input_artifacts / output_artifacts 简版
    input_artifacts_summary: Dict[str, Any] = field(default_factory=dict)
    output_artifacts_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 抽象接口
# ============================================================================


class LineageBackend(ABC):
    """Lineage 存储后端抽象接口

    所有后端实现必须继承这个类,保证接口一致
    (未来换 PG / wau-lineage SDK 时,只需新加 1 个子类)
    """

    @abstractmethod
    def add(self, record: LineageRecordDTO) -> None:
        """添加 1 条 lineage 记录"""

    @abstractmethod
    def get(self, lineage_id: str) -> LineageRecordDTO:
        """按 lineage_id 查"""

    @abstractmethod
    def list(self) -> List[LineageRecordDTO]:
        """列出所有记录"""

    @abstractmethod
    def list_by_run(self, run_id: str) -> List[LineageRecordDTO]:
        """按 run_id 查"""

    @abstractmethod
    def list_by_parent(self, parent_run_id: str) -> List[LineageRecordDTO]:
        """按 parent_run_id 查(下游)"""

    @abstractmethod
    def delete(self, lineage_id: str) -> None:
        """删 1 条记录(测试用)"""

    @abstractmethod
    def close(self) -> None:
        """关闭后端,释放资源"""


# ============================================================================
# In-Memory Backend(W14 行为,默认)
# ============================================================================


class InMemoryBackend(LineageBackend):
    """内存 dict 后端(W14 已有,Stage 1 默认)

    特点:
    - 快(纯 dict 查)
    - 进程死了数据没了(W14 限制)
    - 测试隔离好(每个实例独立)
    """

    def __init__(self) -> None:
        self._records: Dict[str, LineageRecordDTO] = {}
        self._by_run: Dict[str, List[str]] = {}
        self._by_parent: Dict[str, List[str]] = {}
        self._lock = threading.Lock()

    def add(self, record: LineageRecordDTO) -> None:
        with self._lock:
            self._records[record.lineage_id] = record
            self._by_run.setdefault(record.run_id, []).append(record.lineage_id)
            if record.parent_run_id:
                self._by_parent.setdefault(record.parent_run_id, []).append(record.lineage_id)

    def get(self, lineage_id: str) -> LineageRecordDTO:
        if lineage_id not in self._records:
            raise LineageNotFoundError(lineage_id)
        return self._records[lineage_id]

    def list(self) -> List[LineageRecordDTO]:
        return list(self._records.values())

    def list_by_run(self, run_id: str) -> List[LineageRecordDTO]:
        ids = self._by_run.get(run_id, [])
        return [self._records[i] for i in ids if i in self._records]

    def list_by_parent(self, parent_run_id: str) -> List[LineageRecordDTO]:
        ids = self._by_parent.get(parent_run_id, [])
        return [self._records[i] for i in ids if i in self._records]

    def delete(self, lineage_id: str) -> None:
        with self._lock:
            if lineage_id in self._records:
                rec = self._records.pop(lineage_id)
                if rec.run_id in self._by_run:
                    self._by_run[rec.run_id] = [i for i in self._by_run[rec.run_id] if i != lineage_id]
                if rec.parent_run_id and rec.parent_run_id in self._by_parent:
                    self._by_parent[rec.parent_run_id] = [
                        i for i in self._by_parent[rec.parent_run_id] if i != lineage_id
                    ]

    def close(self) -> None:
        # 内存无需关
        pass


# ============================================================================
# SQLite Backend(W16 真持久化)
# ============================================================================


class SQLiteBackend(LineageBackend):
    """SQLite 持久化后端(W16 Stage 2 真接入)

    特点:
    - 数据写到磁盘文件(默认 ~/.matwau/lineage.db,或指定 db_path)
    - 关 Python 重启数据还在(Stage 2 验证点)
    - 无外部依赖(Python 内置 sqlite3)
    - 未来换 PG:只需新加 PostgresBackend(同接口)

    Schema:
        CREATE TABLE lineage_records (
            lineage_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            parent_run_id TEXT,
            agent_name TEXT,
            input_hash TEXT,
            output_hash TEXT,
            timestamp TEXT,
            duration_seconds REAL,
            cost REAL,
            metadata TEXT,  -- JSON
            input_artifacts_summary TEXT,  -- JSON
            output_artifacts_summary TEXT  -- JSON
        );
        CREATE INDEX idx_run ON lineage_records(run_id);
        CREATE INDEX idx_parent ON lineage_records(parent_run_id);
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """构造

        Args:
            db_path: SQLite 文件路径(None → 默认 ~/.matwau/lineage.db)
        """
        import os

        if db_path is None:
            home = os.path.expanduser("~")
            db_dir = os.path.join(home, ".matwau")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "lineage.db")
        else:
            # W37.9 v1.1.1-Academic patch: caller may pass "~/..." literal
            # (e.g. MATWAU_LINEAGE_SQLITE_PATH env var),expand it so
            # sqlite3.connect doesn't choke on raw "~/" prefix.
            db_path = os.path.expanduser(db_path)
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化表结构(幂等)"""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lineage_records (
                    lineage_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    agent_name TEXT,
                    input_hash TEXT,
                    output_hash TEXT,
                    timestamp TEXT,
                    duration_seconds REAL,
                    cost REAL,
                    metadata TEXT,
                    input_artifacts_summary TEXT,
                    output_artifacts_summary TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_run ON lineage_records(run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_parent ON lineage_records(parent_run_id)")
            self._conn.commit()

    def add(self, record: LineageRecordDTO) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO lineage_records
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.lineage_id,
                record.run_id,
                record.parent_run_id,
                record.agent_name,
                record.input_hash,
                record.output_hash,
                record.timestamp,
                record.duration_seconds,
                record.cost,
                json.dumps(record.metadata, ensure_ascii=False),
                json.dumps(record.input_artifacts_summary, ensure_ascii=False),
                json.dumps(record.output_artifacts_summary, ensure_ascii=False),
            ))
            self._conn.commit()

    def get(self, lineage_id: str) -> LineageRecordDTO:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM lineage_records WHERE lineage_id = ?", (lineage_id,))
            row = cur.fetchone()
        if row is None:
            raise LineageNotFoundError(lineage_id)
        return self._row_to_dto(row)

    def list(self) -> List[LineageRecordDTO]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM lineage_records")
            rows = cur.fetchall()
        return [self._row_to_dto(r) for r in rows]

    def list_by_run(self, run_id: str) -> List[LineageRecordDTO]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM lineage_records WHERE run_id = ?", (run_id,))
            rows = cur.fetchall()
        return [self._row_to_dto(r) for r in rows]

    def list_by_parent(self, parent_run_id: str) -> List[LineageRecordDTO]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM lineage_records WHERE parent_run_id = ?", (parent_run_id,))
            rows = cur.fetchall()
        return [self._row_to_dto(r) for r in rows]

    def delete(self, lineage_id: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM lineage_records WHERE lineage_id = ?", (lineage_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _row_to_dto(self, row: tuple) -> LineageRecordDTO:
        """SQLite row → LineageRecordDTO"""
        return LineageRecordDTO(
            lineage_id=row[0],
            run_id=row[1],
            parent_run_id=row[2],
            agent_name=row[3],
            input_hash=row[4],
            output_hash=row[5],
            timestamp=row[6],
            duration_seconds=row[7],
            cost=row[8],
            metadata=json.loads(row[9]) if row[9] else {},
            input_artifacts_summary=json.loads(row[10]) if row[10] else {},
            output_artifacts_summary=json.loads(row[11]) if row[11] else {},
        )


# ============================================================================
# Postgres Backend(W17 — 第 3 后端实例化)
# ============================================================================


class PostgresBackend(LineageBackend):
    """PostgreSQL 后端(W17 — 第 3 个 LineageBackend 实现)

    设计要点:
    1. **降级策略**(本机无 psycopg 时):用 SQLiteBackend 作为 fallback,接口完全一致
       — LineageStore 完全不在乎底层是 PG 还是 SQLite
    2. **真连接模式**(本机装了 psycopg 时):走 psycopg2/psycopg3
    3. **接口完全遵循 LineageBackend** — 加这个 backend 不需要改 LineageStore 任何代码
    4. **未来 Stage 3**:换 WauLineageBackend(走 wau-lineage Go 服务)时,
       同样只新加 1 个 LineageBackend 子类,不动 store

    用法:
        # 模式 1:无 psycopg → 降级 SQLite(本机默认)
        backend = PostgresBackend(dsn="postgresql://...", use_fallback=True)

        # 模式 2:有 psycopg → 直连 PG
        backend = PostgresBackend(dsn="postgresql://...", use_fallback=False)

    不论哪种,LineageStore 完全一样调用:
        store = LineageStore(backend=PostgresBackend(...))
        # ... 完全一样
    """

    def __init__(
        self,
        dsn: str = "postgresql://localhost/matwau",
        *,
        use_fallback: bool = True,
        fallback_backend: Optional[LineageBackend] = None,
    ) -> None:
        """构造

        Args:
            dsn: PostgreSQL DSN(等同 connection string)
                例 "postgresql://user:pwd@localhost:5432/matwau"
            use_fallback: 无 psycopg / PG server 时,降级用什么
                True → 用 SQLiteBackend(磁盘,真持久化)
                False → 用 InMemoryBackend(纯内存)
            fallback_backend: 显式指定 fallback backend(None → 按 use_fallback 自动选)
        """
        self.dsn = dsn
        self.use_fallback = use_fallback
        self._real_pg = False
        self._conn = None

        # 尝试连接真 PG
        try:
            import psycopg  # type: ignore
            conn = psycopg.connect(dsn)
            self._conn = conn
            self._init_schema_pg(conn)
            self._real_pg = True
        except (ImportError, Exception):
            # 无 psycopg 或连不上 → 降级
            if fallback_backend is not None:
                self._fallback = fallback_backend
            elif use_fallback:
                # 默认降级 SQLite(路径 = dsn 末尾 path 或 temp 文件)
                fallback_path = self._dsn_to_db_path(dsn)
                self._fallback = SQLiteBackend(db_path=fallback_path)
            else:
                self._fallback = InMemoryBackend()

    @staticmethod
    def _dsn_to_db_path(dsn: str) -> str:
        """从 PG DSN 推一个 SQLite 路径(用于 fallback)
        例 'postgresql://localhost/matwau' → '/tmp/matwau_lineage.db'
        """
        import hashlib
        import tempfile

        h = hashlib.md5(dsn.encode()).hexdigest()[:8]
        return os.path.join(tempfile.gettempdir(), f"matwau_pgfallback_{h}.db")

    def _init_schema_pg(self, conn) -> None:
        """初始化 PG 表结构(若用 real PG)

        W32 — metadata / input_artifacts_summary / output_artifacts_summary
        统一改 JSONB(对齐 deploy/postgres/init.sql + k8s configmap),
        并加 GIN 索引,方便按 metadata 字段查
        """
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lineage_records (
                    lineage_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    agent_name TEXT,
                    input_hash TEXT,
                    output_hash TEXT,
                    timestamp TEXT,
                    duration_seconds REAL,
                    cost REAL,
                    metadata JSONB,
                    input_artifacts_summary JSONB,
                    output_artifacts_summary JSONB
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_run ON lineage_records(run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_parent ON lineage_records(parent_run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_name ON lineage_records(agent_name)")
            # GIN 索引让 metadata 字段查询可走索引(否则 JSONB 字段全表扫)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_metadata_gin ON lineage_records USING GIN (metadata)")
        conn.commit()

    def add(self, record: LineageRecordDTO) -> None:
        if self._real_pg:
            # W32 — 改 psycopg.types.json.Json() 让 PG 收到 JSONB(不是 TEXT)
            from psycopg.types.json import Json
            with self._conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO lineage_records
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lineage_id) DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        parent_run_id = EXCLUDED.parent_run_id,
                        agent_name = EXCLUDED.agent_name,
                        input_hash = EXCLUDED.input_hash,
                        output_hash = EXCLUDED.output_hash,
                        timestamp = EXCLUDED.timestamp,
                        duration_seconds = EXCLUDED.duration_seconds,
                        cost = EXCLUDED.cost,
                        metadata = EXCLUDED.metadata,
                        input_artifacts_summary = EXCLUDED.input_artifacts_summary,
                        output_artifacts_summary = EXCLUDED.output_artifacts_summary
                """, (
                    record.lineage_id,
                    record.run_id,
                    record.parent_run_id,
                    record.agent_name,
                    record.input_hash,
                    record.output_hash,
                    record.timestamp,
                    record.duration_seconds,
                    record.cost,
                    Json(record.metadata),
                    Json(record.input_artifacts_summary),
                    Json(record.output_artifacts_summary),
                ))
            self._conn.commit()
        else:
            # 降级路径
            self._fallback.add(record)

    def get(self, lineage_id: str) -> LineageRecordDTO:
        if self._real_pg:
            with self._conn.cursor() as cur:
                cur.execute("SELECT * FROM lineage_records WHERE lineage_id = %s", (lineage_id,))
                row = cur.fetchone()
            if row is None:
                raise LineageNotFoundError(lineage_id)
            # 与 SQLiteBackend._row_to_dto 字段顺序一致
            return LineageRecordDTO(
                lineage_id=row[0],
                run_id=row[1],
                parent_run_id=row[2],
                agent_name=row[3],
                input_hash=row[4],
                output_hash=row[5],
                timestamp=row[6],
                duration_seconds=row[7],
                cost=row[8],
                metadata=json.loads(row[9]) if row[9] else {},
                input_artifacts_summary=json.loads(row[10]) if row[10] else {},
                output_artifacts_summary=json.loads(row[11]) if row[11] else {},
            )
        else:
            return self._fallback.get(lineage_id)

    def list(self) -> List[LineageRecordDTO]:
        if self._real_pg:
            with self._conn.cursor() as cur:
                cur.execute("SELECT * FROM lineage_records")
                rows = cur.fetchall()
            return [
                LineageRecordDTO(
                    lineage_id=r[0],
                    run_id=r[1],
                    parent_run_id=r[2],
                    agent_name=r[3],
                    input_hash=r[4],
                    output_hash=r[5],
                    timestamp=r[6],
                    duration_seconds=r[7],
                    cost=r[8],
                    metadata=json.loads(r[9]) if r[9] else {},
                    input_artifacts_summary=json.loads(r[10]) if r[10] else {},
                    output_artifacts_summary=json.loads(r[11]) if r[11] else {},
                ) for r in rows
            ]
        else:
            return self._fallback.list()

    def list_by_run(self, run_id: str) -> List[LineageRecordDTO]:
        if self._real_pg:
            with self._conn.cursor() as cur:
                cur.execute("SELECT * FROM lineage_records WHERE run_id = %s", (run_id,))
                rows = cur.fetchall()
            return [
                LineageRecordDTO(
                    lineage_id=r[0],
                    run_id=r[1],
                    parent_run_id=r[2],
                    agent_name=r[3],
                    input_hash=r[4],
                    output_hash=r[5],
                    timestamp=r[6],
                    duration_seconds=r[7],
                    cost=r[8],
                    metadata=json.loads(r[9]) if r[9] else {},
                    input_artifacts_summary=json.loads(r[10]) if r[10] else {},
                    output_artifacts_summary=json.loads(r[11]) if r[11] else {},
                ) for r in rows
            ]
        else:
            return self._fallback.list_by_run(run_id)

    def list_by_parent(self, parent_run_id: str) -> List[LineageRecordDTO]:
        if self._real_pg:
            with self._conn.cursor() as cur:
                cur.execute("SELECT * FROM lineage_records WHERE parent_run_id = %s", (parent_run_id,))
                rows = cur.fetchall()
            return [
                LineageRecordDTO(
                    lineage_id=r[0],
                    run_id=r[1],
                    parent_run_id=r[2],
                    agent_name=r[3],
                    input_hash=r[4],
                    output_hash=r[5],
                    timestamp=r[6],
                    duration_seconds=r[7],
                    cost=r[8],
                    metadata=json.loads(r[9]) if r[9] else {},
                    input_artifacts_summary=json.loads(r[10]) if r[10] else {},
                    output_artifacts_summary=json.loads(r[11]) if r[11] else {},
                ) for r in rows
            ]
        else:
            return self._fallback.list_by_parent(parent_run_id)

    def delete(self, lineage_id: str) -> None:
        if self._real_pg:
            with self._conn.cursor() as cur:
                cur.execute("DELETE FROM lineage_records WHERE lineage_id = %s", (lineage_id,))
            self._conn.commit()
        else:
            self._fallback.delete(lineage_id)

    def close(self) -> None:
        if self._real_pg and self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        else:
            self._fallback.close()

    # ----------------------------------------------------------------
    # W32 — Context manager 支持:`with PostgresBackend(...) as backend:`
    # ----------------------------------------------------------------
    def __enter__(self) -> "PostgresBackend":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __repr__(self) -> str:
        mode = "real PG" if self._real_pg else f"fallback → {type(self._fallback).__name__}"
        return f"PostgresBackend(dsn='{self.dsn}', mode={mode})"


__all__ = [
    "LineageBackend",
    "InMemoryBackend",
    "SQLiteBackend",
    "PostgresBackend",   # W17 新增
    "LineageNotFoundError",
    "LineageRecordDTO",
]  # type: ignore[name-defined]  # noqa: F821