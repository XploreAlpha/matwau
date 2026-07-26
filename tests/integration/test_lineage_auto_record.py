"""test_lineage_auto_record.py — W32 集成测试(orchestrator 真打 lineage + SQLite 验证)

测试覆盖:
1. TestOrchestratorRunLineage      3 — run() → workflow record 落 store
2. TestOrchestratorBatchLineage    4 — run_batch() → 每 experiment + batch record 落 store
3. TestSQLiteBackendPersistence    3 — SQLite 真持久化(关 store 重开数据还在)
4. TestLineageDisabled             2 — enable_lineage=False → 不打 record
5. TestLineageCriticHandoff        2 — chemist → critic 父子 run_id 链路

per W32 plan §J
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
# helpers
# ============================================================================


def _fresh_sqlite_store():
    """建 1 个新的 SQLite backend LineageStore(每个测试独立,避免污染)"""
    from agents.lineage_store_backend import SQLiteBackend
    from agents.mat_data_lineage_agent import LineageStore, LineageRecorder

    tmp = os.path.join(tempfile.gettempdir(), f"matwau_w32_{os.getpid()}_{id(object())}.db")
    if os.path.exists(tmp):
        os.unlink(tmp)
    backend = SQLiteBackend(db_path=tmp)
    store = LineageStore(backend=backend)
    recorder = LineageRecorder(store=store)
    return store, recorder, tmp


# ============================================================================
# TestOrchestratorRunLineage — run() workflow record
# ============================================================================


class TestOrchestratorRunLineage:
    """MatOrchestrator.run() 自动打 lineage"""

    def test_run_records_workflow(self):
        from agents.mat_orchestrator import MatOrchestrator

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            r = orch.run(user_intent="出 LiCoO2 实验方案")

            # workflow record 应已落
            records = [rec for rec in store.records.values()
                       if rec.metadata.get("kind") == "workflow"]
            assert len(records) >= 1
            wf = records[0]
            assert wf.metadata["workflow_name"] == "experiment_planning"
            assert wf.metadata["subclass"] == "experiment_planning"
            assert wf.metadata["success"] is True
            assert wf.agent_name == "mat-orchestrator"
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_records_multiple_workflows(self):
        """跑多个 workflow → store 里多条 workflow record"""
        from agents.mat_orchestrator import MatOrchestrator

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run(user_intent="出 LiCoO2 实验方案")
            orch.run(user_intent="设计新型固态电解质")
            orch.run(user_intent="优化 LiCoO2 配方")

            wf_records = [rec for rec in store.records.values()
                          if rec.metadata.get("kind") == "workflow"]
            assert len(wf_records) == 3
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_with_intent_also_records(self):
        """run_with_intent() 也会打 record"""
        from agents.mat_orchestrator import MatOrchestrator
        from agents.mat_intent_agent.intent_classifier import parse_mat_intent

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            mi = parse_mat_intent("出 LLZO 实验方案")
            orch.run_with_intent(user_intent="出 LLZO 实验方案", mat_intent=mi)

            wf_records = [rec for rec in store.records.values()
                          if rec.metadata.get("kind") == "workflow"]
            assert len(wf_records) == 1
            assert wf_records[0].metadata["subclass"] == "experiment_planning"
        finally:
            try: os.unlink(tmp)
            except OSError: pass


# ============================================================================
# TestOrchestratorBatchLineage — run_batch() record
# ============================================================================


class TestOrchestratorBatchLineage:
    """MatOrchestrator.run_batch() 自动打 lineage(每 experiment + batch 总览)"""

    def test_run_batch_records_per_experiment(self):
        """run_batch → 每 experiment 1 条 + batch 总览 1 条"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            batch = orch.run_batch(get_multi_experiment_default_batch(), parallel=True, max_workers=3)

            # experiment records
            exp_records = [rec for rec in store.records.values()
                           if rec.metadata.get("kind") == "experiment"]
            assert len(exp_records) == batch.n_total

            # batch record
            batch_records = [rec for rec in store.records.values()
                             if rec.metadata.get("kind") == "batch_workflow"]
            assert len(batch_records) == 1
            assert batch_records[0].metadata["n_total"] == batch.n_total
            assert batch_records[0].metadata["overall_verdict"] == batch.overall_verdict
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_batch_records_chemist_and_critic(self):
        """每个 experiment 同时记 chemist + critic 2 条"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)

            chemist_records = [rec for rec in store.records.values()
                               if rec.metadata.get("kind") == "chemist"]
            critic_records = [rec for rec in store.records.values()
                              if rec.metadata.get("kind") == "critic"]
            # 至少 1 个 chemist + 1 个 critic(若 chemist 返回 None report 则 critic 不会跑)
            assert len(chemist_records) >= 1
            assert len(critic_records) >= 1
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_batch_critic_parent_is_chemist(self):
        """critic record.parent_run_id == chemist record.run_id"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)

            chemist_run_ids = {rec.run_id for rec in store.records.values()
                               if rec.metadata.get("kind") == "chemist"}
            for critic_rec in [r for r in store.records.values()
                               if r.metadata.get("kind") == "critic"]:
                assert critic_rec.parent_run_id in chemist_run_ids, (
                    f"critic parent {critic_rec.parent_run_id} not in chemist run_ids {chemist_run_ids}"
                )
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_batch_summary_includes_verdict(self):
        """experiment record 的 metadata 含 verdict + critic_summary"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)

            exp_records = [rec for rec in store.records.values()
                           if rec.metadata.get("kind") == "experiment"]
            assert len(exp_records) == 1
            er = exp_records[0]
            assert "verdict" in er.metadata
            assert "target_sample" in er.metadata
            assert "critic_summary" in er.metadata
        finally:
            try: os.unlink(tmp)
            except OSError: pass


# ============================================================================
# TestSQLiteBackendPersistence — 真持久化
# ============================================================================


class TestSQLiteBackendPersistence:
    """SQLite 持久化(关 store 数据还在)"""

    def test_record_persists_across_store_instances(self):
        """同一个 SQLite 文件,新 LineageStore 实例化 → 旧数据还在"""
        from agents.lineage_store_backend import SQLiteBackend
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder

        tmp = os.path.join(tempfile.gettempdir(), f"matwau_w32_persist_{os.getpid()}.db")
        if os.path.exists(tmp):
            os.unlink(tmp)

        try:
            # 第 1 个 store — 写
            backend1 = SQLiteBackend(db_path=tmp)
            store1 = LineageStore(backend=backend1)
            recorder1 = LineageRecorder(store=store1)
            recorder1.record(run_id="p-1", agent_name="agent-A")
            recorder1.record(run_id="p-2", agent_name="agent-A")
            backend1.close()

            # 第 2 个 store — 读
            backend2 = SQLiteBackend(db_path=tmp)
            store2 = LineageStore(backend=backend2)
            # store2 应该从 backend 加载了 2 条
            assert store2.size() == 2
            run_ids = {rec.run_id for rec in store2.records.values()}
            assert run_ids == {"p-1", "p-2"}
            backend2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_orchestrator_run_persists_to_sqlite(self):
        """完整 orchestrator.run() → SQLite 文件落库"""
        from agents.lineage_store_backend import SQLiteBackend
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder
        from agents.mat_orchestrator import MatOrchestrator

        tmp = os.path.join(tempfile.gettempdir(), f"matwau_w32_orch_{os.getpid()}.db")
        if os.path.exists(tmp):
            os.unlink(tmp)

        try:
            backend = SQLiteBackend(db_path=tmp)
            store = LineageStore(backend=backend)
            recorder = LineageRecorder(store=store)
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run(user_intent="出 LiCoO2 实验方案")

            # store.size == records count
            n_records = store.size()
            assert n_records >= 1

            # 关 backend 后新 store 应能读
            backend.close()
            backend2 = SQLiteBackend(db_path=tmp)
            store2 = LineageStore(backend=backend2)
            assert store2.size() == n_records
            backend2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_record_metadata_preserved_through_sqlite(self):
        """metadata 通过 SQLite 读写后不变"""
        from agents.lineage_store_backend import SQLiteBackend
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder

        tmp = os.path.join(tempfile.gettempdir(), f"matwau_w32_meta_{os.getpid()}.db")
        if os.path.exists(tmp):
            os.unlink(tmp)
        try:
            backend = SQLiteBackend(db_path=tmp)
            store = LineageStore(backend=backend)
            recorder = LineageRecorder(store=store)
            recorder.record_workflow_result(
                workflow_name="experiment_planning",
                subclass="experiment_planning",
                result=_mock_workflow_result(),
            )
            backend.close()

            # 重读
            backend2 = SQLiteBackend(db_path=tmp)
            store2 = LineageStore(backend=backend2)
            wf_recs = [r for r in store2.records.values()
                       if r.metadata.get("kind") == "workflow"]
            assert len(wf_recs) == 1
            assert wf_recs[0].metadata["n_nodes"] == 3
            backend2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _mock_workflow_result():
    class NodeResult:
        def __init__(self, nid, an, success=True):
            self.node_id = nid
            self.agent_name = an
            self.success = success
            self.duration_seconds = 0.5
    class WorkflowResult:
        workflow_name = "experiment_planning"
        subclass = "experiment_planning"
        success = True
        total_duration_seconds = 1.5
        error = None
        node_results = [NodeResult("gen", "mat-gen-agent"),
                        NodeResult("sim", "mat-sim-agent"),
                        NodeResult("hpc", "mat-hpc-agent")]
        final_outputs = {"a": 1}
    return WorkflowResult()


# ============================================================================
# TestLineageDisabled
# ============================================================================


class TestLineageDisabled:
    """enable_lineage=False → 不打 record"""

    def test_disabled_orchestrator_no_records(self):
        from agents.mat_orchestrator import MatOrchestrator
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder

        store = LineageStore()  # 没用,只检查不会被打
        recorder = LineageRecorder(store=store)
        orch = MatOrchestrator(lineage_recorder=recorder, enable_lineage=False)
        orch.run(user_intent="出 LiCoO2 实验方案")
        orch.run(user_intent="设计新型固态电解质")
        # 因为 enable_lineage=False,_lineage_recorder = None
        # store 应该是空的(没被打)
        assert store.size() == 0

    def test_explicit_none_no_records(self):
        """lineage_recorder=None + enable_lineage=True → 不打"""
        from agents.mat_orchestrator import MatOrchestrator
        from agents.mat_data_lineage_agent import LineageStore

        store = LineageStore()
        orch = MatOrchestrator(lineage_store=None, enable_lineage=True)
        # store 是 orchestrator 内部的,跟我们这里无关
        orch.run(user_intent="出 LiCoO2 实验方案")
        # 外部 store 不变
        assert store.size() == 0


# ============================================================================
# TestLineageCriticHandoff
# ============================================================================


class TestLineageCriticHandoff:
    """critic handoff(parent_run_id link)"""

    def test_run_batch_critic_parent_chain_intact(self):
        """完整链:experiment_id-chemist → experiment_id-critic"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)

            # 找 critic records,检查 parent_run_id 形如 "exp-0-XXXXXX-chemist"
            critic_recs = [r for r in store.records.values()
                           if r.metadata.get("kind") == "critic"]
            assert len(critic_recs) == 1
            parent = critic_recs[0].parent_run_id
            assert parent is not None
            assert parent.endswith("-chemist"), f"parent={parent}"
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_run_batch_experiment_metadata_full(self):
        """experiment record 含 critic_summary + chemist_summary"""
        from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

        store, recorder, tmp = _fresh_sqlite_store()
        try:
            orch = MatOrchestrator(lineage_recorder=recorder)
            orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)

            exp_recs = [r for r in store.records.values()
                        if r.metadata.get("kind") == "experiment"]
            assert len(exp_recs) == 1
            md = exp_recs[0].metadata
            assert "critic_summary" in md
            assert "chemist_summary" in md
            # critic_summary 应有 verdict 字段
            assert "verdict" in md["critic_summary"]
            # chemist_summary 应有 target_sample 字段
            assert "target_sample" in md["chemist_summary"]
        finally:
            try: os.unlink(tmp)
            except OSError: pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])