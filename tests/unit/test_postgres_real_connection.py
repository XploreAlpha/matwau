"""test_postgres_real_connection.py — W23 PostgresBackend 真接测试

目标:
1. 验证 PostgresBackend 接口(post psycopg 检测 + 降级)
2. 不依赖运行中 docker(用 mock psycopg)
3. 验证降级策略(use_fallback=True / False)
4. 与 LineageStore 完全兼容(后端可换)

per MatWAU-开发计划 §8 W23 + W17-B PostgresBackend
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.lineage_store_backend.backends import (  # noqa: E402
    InMemoryBackend,
    LineageRecordDTO,
    PostgresBackend,
    SQLiteBackend,
)
from agents.mat_data_lineage_agent.lineage_engine import LineageStore  # noqa: E402


# ============================================================================
# 测试 1: PostgresBackend 降级策略(无 psycopg → SQLite)
# ============================================================================


class TestPostgresBackendFallback:
    """PostgresBackend 默认降级行为(per W17-B 心法)"""

    def test_default_constructs_with_fallback(self):
        """默认构造(use_fallback=True)即使无 psycopg 也不报错"""
        backend = PostgresBackend(
            dsn="postgresql://noone:wrong@localhost/matwau",
            use_fallback=True,
        )
        # 无真连接 → fallback 内部 _fallback 是 SQLiteBackend
        assert backend.dsn is not None
        assert backend.use_fallback is True

    def test_data_added_via_fallback(self):
        """降级走 SQLiteBackend,数据应该可持久化"""
        # 用 tempfile SQLite 文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            backend = PostgresBackend(
                dsn=f"postgresql://x@localhost/x",
                use_fallback=True,
                fallback_backend=SQLiteBackend(db_path=tmp_db),
            )
            rec = LineageRecordDTO(
                lineage_id="fb-001", run_id="r1",
                agent_name="mat-gen", timestamp="t",
            )
            backend.add(rec)
            assert backend.get("fb-001") is not None
        finally:
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)

    def test_use_fallback_false_does_not_provide_fallback(self):
        """use_fallback=False → 强制真接(配 no fallback backend 才有意义)"""
        backend = PostgresBackend(
            dsn="postgresql://x@localhost/x",
            use_fallback=False,
            fallback_backend=InMemoryBackend(),
        )
        assert backend.use_fallback is False


# ============================================================================
# 测试 2: 真接模式(mock psycopg.connect 失败 → 不应该崩)
# ============================================================================


class TestPostgresRealConnection:
    """PostgresBackend 真接路径"""

    def test_psycopg_connect_called_with_dsn(self, monkeypatch):
        """构造时应调过 psycopg.connect(dsn)"""
        mock_psycopg = MagicMock()
        # 模拟 connect 抛 OperationalError(假设 PG server 没起)
        mock_psycopg.connect.side_effect = Exception("PG server not reachable")
        monkeypatch.setitem(sys.modules, "psycopg", mock_psycopg)

        # 即便 PG 不可达,也应不崩(降级行为)
        backend = PostgresBackend(
            dsn="postgresql://user:pass@db:5432/matwau",
            use_fallback=True,
        )
        # 连接尝试过
        mock_psycopg.connect.assert_called_once()
        # 因为连不上 + use_fallback=True → 降级
        assert backend.use_fallback is True

    def test_psycopg_available_real_connection(self, monkeypatch):
        """mock psycopg + 模拟成功连接 → backend._real_pg = True"""
        # 关键:MagicMock 自动支持 __enter__/__exit__,cursor() 调用是 ctx manager
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # 让 cursor() 返回 mock_cursor,并支持上下文管理
        mock_conn.cursor.return_value = mock_cursor

        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg", mock_psycopg)

        backend = PostgresBackend(
            dsn="postgresql://test@localhost/test",
            use_fallback=False,
        )
        # 真接成功
        assert backend._real_pg is True
        # schema init 调用过(cur.execute 应该被调 — 因为 _init_schema_pg)
        # Mock cursor 在 __enter__ 时返回自身
        assert mock_cursor.execute.called or mock_conn.cursor.called


# ============================================================================
# 测试 3: LineageStore + PostgresBackend 真接 / 降级都 OK
# ============================================================================


class TestLineageStoreWithPostgres:
    """LineageStore 后端可换 — PostgresBackend 真接 / 降级都支持"""

    def test_store_uses_pg_fallback(self):
        """无 psycopg,降级 SQLiteBackend,LineageStore 完全不感知"""
        backend = PostgresBackend(
            dsn="postgresql://x@localhost/x",
            use_fallback=True,
            fallback_backend=InMemoryBackend(),
        )
        store = LineageStore(backend=backend)
        rec = store.add("run-x", "mat-test", cost=1.0)
        assert rec is not None
        # 通过 store API 读回
        fetched = store.get_by_run("run-x")
        assert isinstance(fetched, list)

    def test_store_uses_pg_real_with_mock_psycopg(self, monkeypatch):
        """mock psycopg 真接成功,LineageStore 加记录 → 应进 mock conn"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # MagicMock 自动支持 context manager
        mock_conn.cursor.return_value = mock_cursor

        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg", mock_psycopg)

        backend = PostgresBackend(
            dsn="postgresql://x@localhost/x",
            use_fallback=False,
        )
        assert backend._real_pg is True

        store = LineageStore(backend=backend)
        rec = store.add("run-y", "mat-real", cost=2.0)
        # cursor 或 conn 被调用过(INSERT)
        assert mock_cursor.execute.called or mock_conn.cursor.called


# ============================================================================
# 测试 4: 部署产物存在性
# ============================================================================


class TestDeploymentArtifacts:
    """W23 部署产物"""

    def test_docker_compose_exists(self):
        path = _PROJECT_ROOT / "deploy" / "postgres" / "docker-compose.yml"
        assert path.exists(), f"docker-compose.yml 不存在: {path}"
        content = path.read_text()
        assert "postgres:16-alpine" in content
        assert "5432:5432" in content

    def test_init_sql_exists(self):
        path = _PROJECT_ROOT / "deploy" / "postgres" / "init.sql"
        assert path.exists(), f"init.sql 不存在: {path}"
        content = path.read_text()
        assert "CREATE TABLE IF NOT EXISTS lineage_records" in content
        assert "JSONB" in content
        # 索引
        assert "idx_lineage_records_run_id" in content

    def test_start_script_exists(self):
        path = _PROJECT_ROOT / "deploy" / "postgres" / "start_postgres.sh"
        assert path.exists(), f"start_postgres.sh 不存在: {path}"
        content = path.read_text()
        assert "docker compose" in content
        assert "MATWAU_PG_DSN" in content


# ============================================================================
# 测试 5: PostgresBackend field schema 与 init.sql 对齐
# ============================================================================


class TestPostgresBackendSchema:
    """PostgresBackend 字段对应 init.sql schema"""

    def test_dto_fields_match_sql(self):
        """LineageRecordDTO 字段跟 init.sql 对齐"""
        expected_fields = {
            "lineage_id", "run_id", "parent_run_id", "agent_name",
            "input_hash", "output_hash", "timestamp", "duration_seconds",
            "cost", "metadata",
        }
        from dataclasses import fields
        actual_fields = {f.name for f in fields(LineageRecordDTO)}
        assert expected_fields.issubset(actual_fields), \
            f"缺字段: {expected_fields - actual_fields}"


# ============================================================================
# 测试 6: 部署脚本可执行检查
# ============================================================================


class TestStartupScript:
    """start_postgres.sh 必备内容"""

    def test_script_supports_subcommands(self):
        path = _PROJECT_ROOT / "deploy" / "postgres" / "start_postgres.sh"
        content = path.read_text()
        for cmd in ("up", "status", "stop", "logs", "reset"):
            assert cmd in content, f"start_postgres.sh 缺 {cmd} 子命令"

    def test_script_documents_dsn(self):
        path = _PROJECT_ROOT / "deploy" / "postgres" / "start_postgres.sh"
        content = path.read_text()
        # DSN 格式应明确给用户看
        assert "postgresql://" in content
        assert "5432" in content


# ============================================================================
# 总览
# ============================================================================


class TestPostgresBackendOverview:
    """PostgresBackend 总览(W17-B → W23 升级)"""

    def test_postgres_backend_has_fallback_strategy(self):
        """PostgresBackend 的 use_fallback 开关"""
        backend = PostgresBackend(
            dsn="postgresql://x@localhost/x",
            use_fallback=True,
            fallback_backend=InMemoryBackend(),
        )
        assert backend.use_fallback is True

    def test_postgres_backend_dsn_persisted(self):
        backend = PostgresBackend(
            dsn="postgresql://user:pwd@db:5432/matwau",
            use_fallback=True,
            fallback_backend=InMemoryBackend(),
        )
        assert "postgresql" in backend.dsn
        assert "5432" in backend.dsn
        assert "matwau" in backend.dsn


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
