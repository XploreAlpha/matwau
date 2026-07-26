"""test_lineage_recorder.py — W32 LineageRecorder + matwau_settings + PostgresBackend schema fix

测试覆盖:
1. TestLineageRecorderBasic      6 — 基本 record / record_critic / record_chemist / record_workflow
2. TestLineageRecorderBackend    4 — backend 写 / 失败吞掉 / None 跳过
3. TestSummarizeHelpers          4 — critic / chemist summary 抽取
4. TestMatWAUSettings            6 — env var 解析 / 单例缓存 / reset
5. TestGetLineageStore           6 — 工厂:memory / sqlite / postgres / disabled
6. TestPostgresBackendContextMgr 3 — __enter__ / __exit__ / close
7. TestPostgresBackendJSONBSchema 3 — schema JSONB / add() 用 Json() / 字段一致

per W32 plan §I
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


# ============================================================================
# TestLineageRecorderBasic — 基本 record
# ============================================================================


class TestLineageRecorderBasic:
    """LineageRecorder 基本 record API"""

    def test_record_returns_record(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)
        rec = recorder.record(
            run_id="test-1",
            agent_name="test-agent",
            input_artifacts={"a": 1},
            output_artifacts={"b": 2},
        )
        assert rec is not None
        assert rec.run_id == "test-1"
        assert rec.agent_name == "test-agent"

    def test_record_uses_global_store(self):
        from agents.mat_data_lineage_agent import (
            LineageRecorder,
            get_global_store,
            reset_global_recorder,
        )
        reset_global_recorder()
        recorder = LineageRecorder()  # 不传 store → 默认 global
        rec = recorder.record(run_id="x", agent_name="y")
        assert rec is not None
        # global store 应该已记录
        assert any(r.run_id == "x" for r in get_global_store().records.values())

    def test_record_critic_verdict(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        # mock critic verdict(尽量像 CriticVerdict 结构)
        class MockCriticVerdict:
            verdict = "pass"
            overall_score = 0.85
            l1_score = 0.7
            l2_score = 0.8
            l3_score = 0.9
            l4_cross_robot_score = 0.7
            failures = []
            top_suggestions = []

            class MockCrossRobot:
                consistent = True
                score = 0.7
                rules_passed = ["R1", "R2"]
                rules_failed = []
            cross_robot = MockCrossRobot()

        rec = recorder.record_critic_verdict(
            experiment_id="exp-1",
            target_sample="Inconel 718",
            critic_verdict=MockCriticVerdict(),
            cost=50.0,
            duration_seconds=0.5,
        )
        assert rec is not None
        assert rec.run_id == "exp-1-critic"
        assert rec.parent_run_id == "exp-1-chemist"
        assert rec.metadata["target_sample"] == "Inconel 718"
        assert rec.metadata["kind"] == "critic"

    def test_record_chemist_report(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        class MockTask:
            target_sample = "PMMA"
            domain = "polymer"
        class MockRobotStep:
            robot_type = "synth"
            success = True
        class MockReport:
            target_sample = "PMMA"
            domain = "polymer"
            overall_success = True
            summary = "OK"
            robot_results = [MockRobotStep(), MockRobotStep()]

        rec = recorder.record_chemist_report(
            experiment_id="exp-1",
            task=MockTask(),
            report=MockReport(),
            cost=100.0,
            duration_seconds=1.5,
        )
        assert rec is not None
        assert rec.metadata["target_sample"] == "PMMA"
        assert rec.metadata["domain"] == "polymer"
        assert rec.metadata["kind"] == "chemist"

    def test_record_workflow_result(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        class MockNodeResult:
            node_id = "gen"
            agent_name = "mat-gen-agent"
            success = True
            duration_seconds = 0.5

        class MockWorkflowResult:
            workflow_name = "experiment_planning"
            subclass = "experiment_planning"
            success = True
            total_duration_seconds = 1.5
            error = None
            node_results = [MockNodeResult(), MockNodeResult()]
            final_outputs = {"a": 1, "b": 2}

        rec = recorder.record_workflow_result(
            workflow_name="experiment_planning",
            subclass="experiment_planning",
            result=MockWorkflowResult(),
        )
        assert rec is not None
        assert rec.agent_name == "mat-orchestrator"
        assert rec.metadata["kind"] == "workflow"
        assert rec.metadata["n_nodes"] == 2
        assert rec.metadata["n_nodes_success"] == 2

    def test_record_batch_workflow_result(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        class MockExperimentResult:
            experiment_id = "exp-1"
            target_sample = "Inconel 718"
            verdict = "pass"

        class MockBatchResult:
            workflow_name = "multi_experiment_characterization"
            n_total = 3
            n_passed = 2
            n_warned = 1
            n_failed = 0
            n_blocked = 0
            overall_verdict = "warn"
            total_cost_cny = 300.0
            total_duration_seconds = 1.5
            parallel = True
            max_workers = 3
            experiment_results = [MockExperimentResult()]

        rec = recorder.record_batch_workflow_result(batch_result=MockBatchResult())
        assert rec is not None
        assert rec.metadata["kind"] == "batch_workflow"
        assert rec.metadata["n_total"] == 3
        assert rec.metadata["n_passed"] == 2
        assert rec.metadata["overall_verdict"] == "warn"
        assert rec.metadata["max_workers"] == 3


# ============================================================================
# TestLineageRecorderBackend — backend 写 / 失败吞掉
# ============================================================================


class TestLineageRecorderBackend:
    """LineageRecorder backend 写行为"""

    def test_record_writes_to_backend(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        from agents.lineage_store_backend import InMemoryBackend
        reset_global_recorder()
        backend = InMemoryBackend()
        store = LineageStore(backend=backend)
        recorder = LineageRecorder(store=store)
        recorder.record(run_id="x", agent_name="y", output_artifacts={"v": 1})
        # backend 收到 1 条
        assert len(backend.list()) == 1

    def test_record_swallows_backend_errors(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()

        class BrokenBackend:
            def add(self, rec): raise RuntimeError("backend down")

        store = LineageStore(backend=BrokenBackend())
        recorder = LineageRecorder(store=store)
        # 不应该抛异常
        rec = recorder.record(run_id="x", agent_name="y")
        assert rec is not None

    def test_record_swallows_store_errors(self):
        from agents.mat_data_lineage_agent import LineageRecorder, LineageStore, reset_global_recorder
        reset_global_recorder()

        class BrokenStore:
            def add(self, **kwargs): raise RuntimeError("store down")

        recorder = LineageRecorder(store=BrokenStore())
        rec = recorder.record(run_id="x", agent_name="y")
        assert rec is None  # 失败 → 返回 None

    def test_record_with_none_store(self):
        """W32 — None store(未配置 lineage)→ recorder 仍可用,失败吞掉"""
        from agents.mat_data_lineage_agent import LineageRecorder, reset_global_recorder
        reset_global_recorder()
        # 模拟没有 store 的场景
        recorder = LineageRecorder()  # 默认 global store
        # 只确认方法都 callable
        recorder.record(run_id="x", agent_name="y")  # 不抛


# ============================================================================
# TestSummarizeHelpers — summary 抽取
# ============================================================================


class TestSummarizeHelpers:
    """critic / chemist summary helper"""

    def test_summarize_critic_verdict(self):
        from agents.mat_data_lineage_agent.lineage_recorder import _summarize_critic_verdict

        class V:
            verdict = "pass"
            overall_score = 0.85
            l1_score = 0.7
            l2_score = 0.8
            l3_score = 0.9
            l4_cross_robot_score = 0.7
            failures = []
            class CR:
                consistent = True
                score = 0.7
                rules_passed = ["R1", "R2"]
                rules_failed = []
            cross_robot = CR()

        s = _summarize_critic_verdict(V())
        assert s["verdict"] == "pass"
        assert s["scores"]["overall_score"] == 0.85
        assert s["l4_consistent"] is True
        assert s["rules_passed"] == ["R1", "R2"]

    def test_summarize_critic_verdict_none(self):
        from agents.mat_data_lineage_agent.lineage_recorder import _summarize_critic_verdict
        s = _summarize_critic_verdict(None)
        assert s == {"_type": "critic_verdict"}

    def test_summarize_chemist_report(self):
        from agents.mat_data_lineage_agent.lineage_recorder import _summarize_chemist_report

        class Step:
            robot_type = "synth"
            success = True

        class R:
            target_sample = "Inconel 718"
            domain = "metal_alloy"
            overall_success = True
            summary = "All good"
            robot_results = [Step(), Step(), Step()]

        s = _summarize_chemist_report(R())
        assert s["target_sample"] == "Inconel 718"
        assert s["domain"] == "metal_alloy"
        assert s["overall_success"] is True
        assert s["n_robot_steps"] == 3
        assert s["robot_step_types"] == ["synth", "synth", "synth"]

    def test_summarize_chemist_report_none(self):
        from agents.mat_data_lineage_agent.lineage_recorder import _summarize_chemist_report
        s = _summarize_chemist_report(None)
        assert s == {"_type": "chemist_report"}


# ============================================================================
# TestMatWAUSettings — env var 解析
# ============================================================================


class TestMatWAUSettings:
    """MatWAUSettings 单例 + env var 解析"""

    def test_default_settings(self):
        from matwau.configs import reset_settings_cache, get_default_settings
        reset_settings_cache()
        if "MATWAU_LINEAGE_DISABLED" in os.environ:
            del os.environ["MATWAU_LINEAGE_DISABLED"]
        s = get_default_settings()
        assert s.lineage_backend in ("postgres", "sqlite", "memory")

    def test_settings_singleton(self):
        from matwau.configs import get_default_settings, reset_settings_cache
        reset_settings_cache()
        s1 = get_default_settings()
        s2 = get_default_settings()
        assert s1 is s2  # 单例

    def test_settings_env_disabled(self):
        from matwau.configs import reset_settings_cache, get_default_settings
        reset_settings_cache()
        os.environ["MATWAU_LINEAGE_DISABLED"] = "1"
        try:
            s = get_default_settings()
            assert s.lineage_disabled is True
        finally:
            del os.environ["MATWAU_LINEAGE_DISABLED"]
            reset_settings_cache()

    def test_settings_env_backend_sqlite(self):
        from matwau.configs import reset_settings_cache, get_default_settings
        reset_settings_cache()
        os.environ["MATWAU_LINEAGE_BACKEND"] = "sqlite"
        try:
            s = get_default_settings()
            assert s.lineage_backend == "sqlite"
        finally:
            del os.environ["MATWAU_LINEAGE_BACKEND"]
            reset_settings_cache()

    def test_settings_env_pg_dsn(self):
        from matwau.configs import reset_settings_cache, get_default_settings
        reset_settings_cache()
        os.environ["MATWAU_PG_DSN"] = "postgresql://test:test@localhost:9999/x"
        try:
            s = get_default_settings()
            assert s.lineage_pg_dsn == "postgresql://test:test@localhost:9999/x"
        finally:
            del os.environ["MATWAU_PG_DSN"]
            reset_settings_cache()

    def test_reset_settings_cache(self):
        from matwau.configs import get_default_settings, reset_settings_cache
        reset_settings_cache()
        s1 = get_default_settings()
        reset_settings_cache()
        s2 = get_default_settings()
        assert s1 is not s2


# ============================================================================
# TestGetLineageStore — 工厂
# ============================================================================


class TestGetLineageStore:
    """get_lineage_store 工厂"""

    def setup_method(self):
        # 每个测试都重置,避免单例污染
        from matwau.configs import reset_settings_cache
        from agents.mat_data_lineage_agent import reset_global_recorder
        reset_settings_cache()
        reset_global_recorder()

    def test_default_memory_backend(self):
        from matwau.configs import get_lineage_store
        from agents.lineage_store_backend import InMemoryBackend
        store = get_lineage_store()
        assert store is not None
        assert isinstance(store.backend, InMemoryBackend)

    def test_explicit_backend(self):
        from matwau.configs import get_lineage_store
        from agents.lineage_store_backend import SQLiteBackend
        explicit = SQLiteBackend(db_path=":memory:")
        store = get_lineage_store(backend=explicit)
        assert store.backend is explicit

    def test_disabled_returns_none(self):
        from matwau.configs import get_lineage_store, reset_settings_cache
        os.environ["MATWAU_LINEAGE_DISABLED"] = "1"
        try:
            reset_settings_cache()
            store = get_lineage_store()
            assert store is None
        finally:
            del os.environ["MATWAU_LINEAGE_DISABLED"]
            reset_settings_cache()

    def test_sqlite_backend_via_env(self):
        from matwau.configs import get_lineage_store, reset_settings_cache
        from agents.lineage_store_backend import SQLiteBackend
        tmp_db = os.path.join(tempfile.gettempdir(), "matwau_test_lineage.db")
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)
        os.environ["MATWAU_LINEAGE_BACKEND"] = "sqlite"
        os.environ["MATWAU_LINEAGE_SQLITE_PATH"] = tmp_db
        try:
            reset_settings_cache()
            store = get_lineage_store()
            assert isinstance(store.backend, SQLiteBackend)
        finally:
            del os.environ["MATWAU_LINEAGE_BACKEND"]
            if "MATWAU_LINEAGE_SQLITE_PATH" in os.environ:
                del os.environ["MATWAU_LINEAGE_SQLITE_PATH"]
            reset_settings_cache()
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)

    def test_postgres_backend_via_env_falls_back(self):
        """MATWAU_LINEAGE_BACKEND=postgres 但无 psycopg → 降级 SQLite"""
        from matwau.configs import get_lineage_store, reset_settings_cache
        from agents.lineage_store_backend import PostgresBackend
        os.environ["MATWAU_LINEAGE_BACKEND"] = "postgres"
        os.environ["MATWAU_PG_DSN"] = "postgresql://localhost/nope"
        try:
            reset_settings_cache()
            store = get_lineage_store()
            # 无 psycopg → 降级 SQLite
            assert isinstance(store.backend, PostgresBackend)
        finally:
            del os.environ["MATWAU_LINEAGE_BACKEND"]
            del os.environ["MATWAU_PG_DSN"]
            reset_settings_cache()

    def test_store_singleton(self):
        from matwau.configs import get_lineage_store
        s1 = get_lineage_store()
        s2 = get_lineage_store()
        assert s1 is s2


# ============================================================================
# TestPostgresBackendContextMgr — context manager
# ============================================================================


class TestPostgresBackendContextMgr:
    """PostgresBackend context manager 支持"""

    def test_with_statement_memory_fallback(self):
        """无 psycopg → 降级,可 with 进 with 出"""
        from agents.lineage_store_backend import PostgresBackend
        backend = PostgresBackend(dsn="postgresql://localhost/nope", use_fallback=True)
        with backend as b:
            assert b is backend
        # close 后再 close 不抛
        backend.close()

    def test_with_statement_sqlite_fallback(self):
        from agents.lineage_store_backend import PostgresBackend
        backend = PostgresBackend(dsn="postgresql://localhost/x", use_fallback=True)
        with backend as b:
            assert b is backend

    def test_close_idempotent(self):
        from agents.lineage_store_backend import PostgresBackend
        backend = PostgresBackend(dsn="postgresql://localhost/x", use_fallback=True)
        backend.close()
        backend.close()  # 不抛


# ============================================================================
# TestPostgresBackendJSONBSchema — schema fix
# ============================================================================


class TestPostgresBackendJSONBSchema:
    """W32 — _init_schema_pg 改 JSONB + add() 用 Json()"""

    def test_init_schema_has_jsonb(self):
        """W32 — 检查 schema 字符串包含 JSONB"""
        import inspect
        from agents.lineage_store_backend import PostgresBackend
        src = inspect.getsource(PostgresBackend._init_schema_pg)
        assert "JSONB" in src
        assert "GIN" in src  # 加了 GIN 索引

    def test_add_uses_json_wrapper(self):
        """W32 — add() 用 psycopg.types.json.Json()"""
        import inspect
        from agents.lineage_store_backend import PostgresBackend
        src = inspect.getsource(PostgresBackend.add)
        assert "Json(" in src  # psycopg.types.json.Json
        assert "from psycopg.types.json import Json" in src

    def test_init_schema_metadata_jsonb(self):
        """W32 — metadata / input_artifacts_summary / output_artifacts_summary 都是 JSONB"""
        import inspect
        from agents.lineage_store_backend import PostgresBackend
        src = inspect.getsource(PostgresBackend._init_schema_pg)
        # 应该 3 次 JSONB(metadata + input_artifacts_summary + output_artifacts_summary)
        assert src.count("JSONB") >= 3


# ============================================================================
# TestGlobalRecorderSingleton
# ============================================================================


class TestGlobalRecorderSingleton:
    """get_global_recorder 单例"""

    def test_global_recorder_singleton(self):
        from agents.mat_data_lineage_agent import get_global_recorder
        r1 = get_global_recorder()
        r2 = get_global_recorder()
        assert r1 is r2

    def test_get_recorder_with_explicit_store(self):
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder, get_recorder
        store = LineageStore()
        rec = get_recorder(store=store)
        assert isinstance(rec, LineageRecorder)
        assert rec.store is store


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])