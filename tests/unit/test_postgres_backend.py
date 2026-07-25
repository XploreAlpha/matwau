"""test_postgres_backend.py — W17-B PostgresBackend 测试

覆盖(W17 验证:加 1 个 backend 子类 → 0 改 LineageStore):
1. PostgresBackend 降级策略(无 psycopg 时 → SQLiteBackend)
2. PostgresBackend CRUD 接口
3. PostgresBackend + LineageStore 集成(端到端 — 零改 store)
4. PostgresBackend 重启保留(降级到 SQLite 的行为)
5. LineageBackend 接口一致性(W17 设计核心)
6. (可选,有 psycopg 时)真 PG 路径

per MatWAU-开发计划 §8 W17-B
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.lineage_store_backend import (  # noqa: E402
    InMemoryBackend,
    LineageBackend,
    LineageNotFoundError,
    LineageRecordDTO,
    PostgresBackend,
    SQLiteBackend,
)
from agents.mat_data_lineage_agent.lineage_engine import LineageStore  # noqa: E402


# ============================================================================
# 测试 1: PostgresBackend 降级策略
# ============================================================================


class TestPostgresBackendFallback:
    """PostgresBackend 无 psycopg 时降级"""

    def test_construction_falls_back_when_no_psycopg(self):
        """默认降级模式:无 psycopg → SQLiteBackend"""
        b = PostgresBackend(dsn="postgresql://localhost/matwau", use_fallback=True)
        # 不是真的 PG 连接
        assert b._real_pg is False
        # 内部 _fallback 应该是 SQLiteBackend
        assert isinstance(b._fallback, SQLiteBackend)
        b.close()

    def test_construction_in_memory_fallback(self):
        """use_fallback=False → 降级 InMemory"""
        b = PostgresBackend(dsn="postgresql://localhost/matwau", use_fallback=False)
        assert b._real_pg is False
        assert isinstance(b._fallback, InMemoryBackend)
        b.close()

    def test_repr_shows_mode(self):
        """__repr__ 准确标识模式"""
        b = PostgresBackend(dsn="postgresql://nope:5432/x", use_fallback=True)
        r = repr(b)
        assert "PostgresBackend" in r
        assert "fallback" in r or "SQLiteBackend" in r or "InMemoryBackend" in r
        b.close()

    def test_explicit_fallback_backend(self):
        """显式 fallback_backend 参数生效"""
        explicit = SQLiteBackend(db_path=":memory:")
        b = PostgresBackend(
            dsn="postgresql://never",
            use_fallback=True,
            fallback_backend=explicit,
        )
        assert b._fallback is explicit
        b.close()


# ============================================================================
# 测试 2: PostgresBackend CRUD 接口
# ============================================================================


class TestPostgresBackendCRUD:
    """PostgresBackend(降级路径)CRUD"""

    def _make_backend(self):
        b = PostgresBackend(dsn="postgresql://test/matwau", use_fallback=True)
        return b

    def test_add_and_get(self):
        b = self._make_backend()
        try:
            rec = LineageRecordDTO(
                lineage_id="pg-001",
                run_id="run-PG",
                agent_name="mat-gen-agent",
                cost=0.06,
                metadata={"domain": "metal_alloy"},
            )
            b.add(rec)
            got = b.get("pg-001")
            assert got.lineage_id == "pg-001"
            assert got.run_id == "run-PG"
            assert got.cost == 0.06
            assert got.metadata["domain"] == "metal_alloy"
        finally:
            b.close()

    def test_list_by_run(self):
        b = self._make_backend()
        try:
            for i in range(3):
                b.add(LineageRecordDTO(
                    lineage_id=f"pg-{i:03d}",
                    run_id="run-A" if i < 2 else "run-B",
                    agent_name=f"agent-{i}",
                ))
            assert len(b.list_by_run("run-A")) == 2
            assert len(b.list_by_run("run-B")) == 1
        finally:
            b.close()

    def test_list_by_parent(self):
        b = self._make_backend()
        try:
            b.add(LineageRecordDTO(lineage_id="pg-parent", run_id="run-p", agent_name="gen"))
            b.add(LineageRecordDTO(lineage_id="pg-child-1", run_id="run-c1", parent_run_id="run-p", agent_name="sim"))
            b.add(LineageRecordDTO(lineage_id="pg-child-2", run_id="run-c2", parent_run_id="run-p", agent_name="exp"))
            children = b.list_by_parent("run-p")
            assert len(children) == 2
        finally:
            b.close()

    def test_delete(self):
        b = self._make_backend()
        try:
            b.add(LineageRecordDTO(lineage_id="pg-del", run_id="r", agent_name="x"))
            assert b.get("pg-del").lineage_id == "pg-del"
            b.delete("pg-del")
            with pytest.raises(LineageNotFoundError):
                b.get("pg-del")
        finally:
            b.close()


# ============================================================================
# 测试 3: PostgresBackend + LineageStore 端到端
# ============================================================================


class TestPostgresWithLineageStore:
    """W17 核心验证:换 PostgresBackend 不动 LineageStore"""

    def test_store_with_postgres_backend(self):
        """LineageStore 接 PostgresBackend(零改 store)"""
        # 用唯一 tmp 路径作为显式 fallback,避免 dsn → hash 冲突复用同一 SQLite
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            explicit_db = f.name
        try:
            explicit_sb = SQLiteBackend(db_path=explicit_db)
            b = PostgresBackend(
                dsn="postgresql://localhost/matwau",
                use_fallback=True,
                fallback_backend=explicit_sb,
            )
            try:
                store = LineageStore(backend=b)
                rec = store.add("run-A", "mat-gen-agent", cost=0.06)
                # in-memory 有
                assert len(store.records) == 1
                # 后端有
                got = b.get(rec.lineage_id)
                assert got.lineage_id == rec.lineage_id
                assert got.agent_name == "mat-gen-agent"
            finally:
                b.close()
        finally:
            try:
                os.unlink(explicit_db)
            except OSError:
                pass

    def test_store_with_postgres_persists_across_restart(self):
        """PostgresBackend 重启保留(降级到 SQLite 也支持)"""
        # 用唯一 tmp 路径
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name
        try:
            # 第 1 阶段
            sb1 = SQLiteBackend(db_path=tmp_path)
            b1 = PostgresBackend(
                dsn="postgresql://restart-test/matwau",
                use_fallback=True,
                fallback_backend=sb1,
            )
            s1 = LineageStore(backend=b1)
            r1 = s1.add("run-A", "mat-gen-agent", cost=0.06)
            r2 = s1.add("run-B", "mat-sim-agent", parent_run_id="run-A", cost=0.5)
            b1.close()
            sb1.close()

            # 第 2 阶段:用相同 db_path 重开
            sb2 = SQLiteBackend(db_path=tmp_path)
            b2 = PostgresBackend(
                dsn="postgresql://restart-test/matwau",
                use_fallback=True,
                fallback_backend=sb2,
            )
            try:
                s2 = LineageStore(backend=b2)
                assert len(s2.records) == 2, f"重启后应有 2 条,实际 {len(s2.records)}"
                # ancestors 链还在
                ancestors = s2.ancestors("run-B")
                assert len(ancestors) == 1
            finally:
                b2.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ============================================================================
# 测试 4: 后端可换(W17 设计核心验证)
# ============================================================================


class TestBackendSwap:
    """W17 核心:加 1 个 backend → LineageStore 零修改

    这个 test 证明设计的可扩展性
    """

    @pytest.mark.parametrize("backend_factory", [
        lambda: InMemoryBackend(),
        lambda: SQLiteBackend(db_path=":memory:"),
        lambda: PostgresBackend(dsn="postgresql://test/matwau", use_fallback=True),
    ], ids=["InMemory", "SQLite", "Postgres-fallback"])
    def test_all_backends_swappable(self, backend_factory):
        """3 个 backend 都接 LineageStore(LineageStore 0 改动)"""
        b = backend_factory()
        try:
            # 验证是 LineageBackend 子类
            assert isinstance(b, LineageBackend)
            # 接 LineageStore
            store = LineageStore(backend=b)
            rec = store.add("run-X", "test-agent", cost=1.0)
            # 数据能拿回
            got = b.get(rec.lineage_id)
            assert got.lineage_id == rec.lineage_id
            assert got.cost == 1.0
        finally:
            b.close()


# ============================================================================
# 测试 5: 向后兼容(W14/W16 测试不破)
# ============================================================================


class TestBackwardCompat:
    """W17 加 PostgresBackend 不破 W14/W16 测试"""

    def test_in_memory_still_works(self):
        b = InMemoryBackend()
        b.add(LineageRecordDTO(lineage_id="mem-1", run_id="r", agent_name="x"))
        assert len(b.list()) == 1

    def test_sqlite_still_works(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            b = SQLiteBackend(db_path=db_path)
            try:
                b.add(LineageRecordDTO(lineage_id="sql-1", run_id="r", agent_name="x"))
                assert len(b.list()) == 1
            finally:
                b.close()
        finally:
            os.unlink(db_path)

    def test_lineage_store_no_backend_still_works(self):
        """LineageStore(backend=None) = W14 行为,纯内存"""
        store = LineageStore()
        rec = store.add("r", "x", cost=0.5)
        assert len(store.records) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
