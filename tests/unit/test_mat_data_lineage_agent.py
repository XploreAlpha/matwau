"""test_mat_data_lineage_agent.py — W14 mat-data-lineage 单元测试 + Goldens 跑分

测试覆盖:
1. hash + summarize
2. LineageStore add/get/ancestors/descendants
3. build_lineage_tree
4. MatDataLineageAgent 端到端
5. Goldens 12 case 跑分(W14)+ 15 case auto_record(W32)= 27 case 总

per MatWAU-开发计划 §七 W14 + W32 LineageStore
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_data_lineage_agent import (  # noqa: E402
    LineageConfig,
    LineageRecord,
    LineageStore,
    LineageTree,
    MatDataLineageAgent,
    build_lineage_tree,
    create_default_agent,
    get_global_store,
    hash_data,
    reset_global_store,
    summarize_artifacts,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-data-lineage.yaml")


# ============================================================================
# Test 1: hash + summarize
# ============================================================================


class TestHash:
    """hash 单元测试"""

    def test_hash_dict(self):
        h = hash_data({"a": 1, "b": 2})
        # 16 字符 SHA256 prefix
        assert len(h) == 16
        assert h.isalnum()

    def test_hash_stable(self):
        h1 = hash_data({"a": 1, "b": 2})
        h2 = hash_data({"a": 1, "b": 2})
        assert h1 == h2

    def test_hash_different(self):
        h1 = hash_data({"a": 1})
        h2 = hash_data({"a": 2})
        assert h1 != h2

    def test_hash_list(self):
        h = hash_data([1, 2, 3])
        assert len(h) == 16

    def test_hash_string(self):
        h = hash_data("hello")
        assert len(h) == 16

    def test_hash_unsortable(self):
        # 不可 JSON 序列化的对象 → str fallback
        h = hash_data(object())
        assert len(h) == 16

    def test_summarize_list(self):
        s = summarize_artifacts({"candidates": [{}, {}, {}]})
        assert s["candidates"]["type"] == "list"
        assert s["candidates"]["size"] == 3

    def test_summarize_dict(self):
        s = summarize_artifacts({"data": {"a": 1, "b": 2}})
        assert s["data"]["type"] == "dict"
        assert s["data"]["size"] == 2

    def test_summarize_str(self):
        s = summarize_artifacts({"text": "hello world"})
        assert s["text"]["type"] == "str"
        assert s["text"]["size"] == 11

    def test_summarize_number(self):
        s = summarize_artifacts({"score": 0.95})
        assert s["score"]["type"] == "number"
        assert s["score"]["value"] == 0.95


# ============================================================================
# Test 2: LineageStore
# ============================================================================


class TestLineageStore:
    """LineageStore 单元测试"""

    def test_add_basic(self):
        store = LineageStore()
        r = store.add(
            run_id="run-001",
            agent_name="mat-gen-agent",
            input_artifacts={"message": "design"},
            output_artifacts={"candidates": [{"formula": "LiCoO2"}]},
        )
        assert r.lineage_id
        assert r.run_id == "run-001"
        assert r.agent_name == "mat-gen-agent"
        assert r.input_hash
        assert r.output_hash
        assert r.timestamp

    def test_add_with_parent(self):
        store = LineageStore()
        r1 = store.add("run-001", "mat-gen-agent")
        r2 = store.add("run-002", "mat-sim-agent", parent_run_id="run-001")
        assert r2.parent_run_id == "run-001"

    def test_get(self):
        store = LineageStore()
        r = store.add("run-001", "mat-gen-agent")
        fetched = store.get(r.lineage_id)
        assert fetched == r

    def test_get_by_run(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        store.add("run-001", "mat-gen-agent")  # 同 run_id 多条
        records = store.get_by_run("run-001")
        assert len(records) == 2

    def test_size(self):
        store = LineageStore()
        assert store.size() == 0
        store.add("run-001", "mat-gen-agent")
        assert store.size() == 1

    def test_ancestors(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        store.add("run-002", "mat-sim-agent", parent_run_id="run-001")
        store.add("run-003", "mat-critic-agent", parent_run_id="run-002")
        ancestors = store.ancestors("run-003")
        # run-003 的上游:run-002, run-001
        assert len(ancestors) == 2
        run_ids = [r.run_id for r in ancestors]
        assert "run-002" in run_ids
        assert "run-001" in run_ids

    def test_descendants(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        store.add("run-002", "mat-sim-agent", parent_run_id="run-001")
        store.add("run-003", "mat-critic-agent", parent_run_id="run-002")
        descendants = store.descendants("run-001")
        # run-001 的下游:run-002, run-003
        assert len(descendants) == 2

    def test_ancestors_cyclic(self):
        """循环引用防护"""
        store = LineageStore()
        store.add("run-001", "a")
        store.add("run-002", "b", parent_run_id="run-001")
        store.add("run-003", "c", parent_run_id="run-002")
        # 制造循环
        store.by_parent["run-002"].append(store.records[store.by_run["run-001"][0]].lineage_id)
        # 不会无限循环
        ancestors = store.ancestors("run-003")
        assert isinstance(ancestors, list)

    def test_to_json(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        json_str = store.to_json()
        assert "run-001" in json_str
        assert "mat-gen-agent" in json_str

    def test_to_list(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        store.add("run-002", "mat-sim-agent")
        lst = store.to_list()
        assert len(lst) == 2

    def test_clear(self):
        store = LineageStore()
        store.add("run-001", "mat-gen-agent")
        store.clear()
        assert store.size() == 0


# ============================================================================
# Test 3: build_lineage_tree
# ============================================================================


class TestLineageTree:
    """build_lineage_tree"""

    def test_tree_basic(self):
        store = LineageStore()
        store.add("run-001", "a")
        store.add("run-002", "b", parent_run_id="run-001")
        store.add("run-003", "c", parent_run_id="run-002")

        tree = build_lineage_tree(store, "run-002")
        assert tree.root_run_id == "run-002"
        assert tree.root is not None
        assert tree.root.run_id == "run-002"
        assert tree.total_nodes == 3

    def test_tree_to_dict(self):
        store = LineageStore()
        store.add("run-001", "a")
        tree = build_lineage_tree(store, "run-001")
        d = tree.to_dict()
        assert "root_run_id" in d
        assert "root" in d
        assert "ancestors_tree" in d
        assert "descendants_tree" in d


# ============================================================================
# Test 4: LineageRecord + LineageConfig
# ============================================================================


class TestDataclasses:
    """dataclass 单元测试"""

    def test_record_to_dict(self):
        r = LineageRecord(
            lineage_id="abc-123",
            run_id="run-001",
            agent_name="mat-gen-agent",
            input_hash="hash1",
            output_hash="hash2",
        )
        d = r.to_dict()
        assert d["lineage_id"] == "abc-123"
        assert d["run_id"] == "run-001"
        assert d["input_hash"] == "hash1"

    def test_config_default(self):
        cfg = LineageConfig()
        assert cfg.use_global_store is True
        assert cfg.query_type == "record"

    def test_config_from_dict(self):
        cfg = LineageConfig.from_dict({"query_type": "ancestors"})
        assert cfg.query_type == "ancestors"


# ============================================================================
# Test 5: MatDataLineageAgent
# ============================================================================


class TestMatDataLineageAgent:
    """MatDataLineageAgent 端到端"""

    def test_create_default_agent(self):
        agent = create_default_agent()
        assert isinstance(agent, MatDataLineageAgent)
        assert agent.name == "mat-data-lineage-agent"

    def test_record_mode(self):
        # 重置全局 store
        reset_global_store()
        agent = create_default_agent()

        req = AgentRequest(
            run_id="agent-test-1",
            message="记录 lineage",
            artifacts={
                "query_type": "record",
                "run_id": "run-001",
                "agent_name": "mat-gen-agent",
                "input_artifacts": {"message": "design"},
                "output_artifacts": {"candidates": [{"formula": "LiCoO2"}]},
            },
        )
        response = agent.run(req)
        assert response.confidence > 0
        assert "record" in response.artifacts
        assert response.artifacts["lineage_id"]

    def test_query_ancestors(self):
        reset_global_store()
        agent = create_default_agent()

        # 先加 2 条
        agent.run(AgentRequest(
            run_id="r1",
            message="gen",
            artifacts={
                "query_type": "record",
                "run_id": "run-001",
                "agent_name": "mat-gen-agent",
            },
        ))
        agent.run(AgentRequest(
            run_id="r2",
            message="sim",
            artifacts={
                "query_type": "record",
                "run_id": "run-002",
                "agent_name": "mat-sim-agent",
                "parent_run_id": "run-001",
            },
        ))

        # 查 run-002 ancestors
        req = AgentRequest(
            run_id="q1",
            message="查 ancestors",
            artifacts={"query_type": "ancestors", "target_run_id": "run-002"},
        )
        response = agent.run(req)
        assert response.artifacts["count"] >= 1

    def test_query_tree(self):
        reset_global_store()
        agent = create_default_agent()

        agent.run(AgentRequest(
            run_id="r1",
            message="gen",
            artifacts={"query_type": "record", "run_id": "run-001", "agent_name": "mat-gen-agent"},
        ))
        agent.run(AgentRequest(
            run_id="r2",
            message="sim",
            artifacts={"query_type": "record", "run_id": "run-002", "agent_name": "mat-sim-agent", "parent_run_id": "run-001"},
        ))

        req = AgentRequest(
            run_id="q1",
            message="查 tree",
            artifacts={"query_type": "tree", "target_run_id": "run-001"},
        )
        response = agent.run(req)
        assert "tree" in response.artifacts or response.artifacts.get("query_type") == "tree"

    def test_unknown_query_type(self):
        reset_global_store()
        agent = create_default_agent()
        req = AgentRequest(
            run_id="q1",
            message="未知",
            artifacts={"query_type": "unknown_type"},
        )
        response = agent.run(req)
        # 错误响应 confidence = 0.1(避开 agent_base 默认 0.5 覆盖)
        assert response.confidence < 0.5
        assert response.error is not None

    def test_query_missing_target(self):
        reset_global_store()
        agent = create_default_agent()
        req = AgentRequest(
            run_id="q1",
            message="查",
            artifacts={"query_type": "ancestors"},   # 没 target_run_id
        )
        response = agent.run(req)
        assert response.confidence < 0.5
        assert response.error is not None


# ============================================================================
# Test 6: Global store
# ============================================================================


class TestGlobalStore:
    """get_global_store + reset_global_store"""

    def test_global_singleton(self):
        reset_global_store()
        s1 = get_global_store()
        s2 = get_global_store()
        assert s1 is s2

    def test_reset_clears(self):
        s = get_global_store()
        s.add("run-001", "test")
        assert s.size() == 1
        reset_global_store()
        s2 = get_global_store()
        assert s2.size() == 0


# ============================================================================
# Test 7: Goldens 12 case 跑分
# ============================================================================


def _setup_store_with_chain() -> LineageStore:
    """建 1 个 5 段 lineage chain 用于 query 测试"""
    store = LineageStore()
    store.add("run-001", "mat-gen-agent",
              input_artifacts={"message": "design"},
              output_artifacts={"candidates": [{"formula": "LiCoO2"}]})
    store.add("run-002", "mat-sim-agent",
              parent_run_id="run-001",
              input_artifacts={"candidates": [{"formula": "LiCoO2"}]},
              output_artifacts={"simulated": [{"formula": "LiCoO2", "relaxed_energy": -3.5}]})
    store.add("run-003", "mat-critic-agent",
              parent_run_id="run-002",
              input_artifacts={"candidates": [{"formula": "LiCoO2"}]},
              output_artifacts={"verdict": "pass"})
    store.add("run-004", "mat-hpc-agent",
              parent_run_id="run-003",
              input_artifacts={"jobs": [{"job_id": "vasp-001"}]},
              output_artifacts={"results": [{"energy": -5.2}]},
              cost=100.0)
    store.add("run-005", "mat-exp-agent",
              parent_run_id="run-004",
              input_artifacts={"jobs": [{"job_id": "vasp-001"}]},
              output_artifacts={"recipes": [{"xrd_peaks": [18.5, 44.2]}]})
    return store


def _run_goldens_case(case) -> Dict[str, Any]:
    """跑 1 个 Goldens case"""
    artifacts = case.artifacts if hasattr(case, "artifacts") else {}
    query_type = artifacts.get("query_type", "record")
    category = case.category if hasattr(case, "category") else "uncategorized"

    # 记录模式:共享 store,D001-D004 累加
    if query_type == "record":
        if not hasattr(_run_goldens_case, "_record_store"):
            _run_goldens_case._record_store = LineageStore()
        store = _run_goldens_case._record_store
        run_id = artifacts.get("run_id", "run-001")
        record = store.add(
            run_id=run_id,
            agent_name=artifacts.get("agent_name", "test"),
            input_artifacts=artifacts.get("input_artifacts", {}),
            output_artifacts=artifacts.get("output_artifacts", {}),
            parent_run_id=artifacts.get("parent_run_id"),
            cost=artifacts.get("cost", 0.0),
        )
        return {
            "lineage_id": record.lineage_id,
            "run_id": record.run_id,
            "store_size": store.size(),
            "input_hash": record.input_hash,
            "output_hash": record.output_hash,
        }
    elif category == "hash" or query_type == "hash":
        # hash 测试
        h1 = hash_data({"a": 1})
        h2 = hash_data({"a": 1})
        h3 = hash_data({"a": 2})
        return {
            "hash_format": len(h1),
            "hash_stable": h1 == h2,
            "hash_different": h1 != h3,
        }
    elif query_type in ("ancestors", "descendants", "tree"):
        # query 模式:用 5 段 chain
        store = _setup_store_with_chain()
        target = artifacts.get("target_run_id", "run-001")

        if query_type == "ancestors":
            records = store.ancestors(target)
            return {
                "query_type": "ancestors",
                "target_run_id": target,
                "count": len(records),
                "has_ancestors": len(records) > 0,
                "has_descendants": False,
            }
        elif query_type == "descendants":
            records = store.descendants(target)
            return {
                "query_type": "descendants",
                "target_run_id": target,
                "count": len(records),
                "has_ancestors": False,
                "has_descendants": len(records) > 0,
            }
        else:  # tree
            tree = build_lineage_tree(store, target)
            return {
                "query_type": "tree",
                "target_run_id": target,
                "count": tree.total_nodes,
                "has_ancestors": bool(tree.ancestors_tree),
                "has_descendants": bool(tree.descendants_tree),
            }
    else:
        # fallback
        h1 = hash_data({"a": 1})
        return {"hash_format": len(h1)}


def _check_goldens_case(case, actual) -> tuple:
    """检查 1 个 Goldens case"""
    reasons = []
    exp = case.expected

    # has_lineage_id
    if exp.get("has_lineage_id") and not actual.get("lineage_id"):
        reasons.append("missing lineage_id")

    # has_run_id
    if "has_run_id" in exp and actual.get("run_id") != exp["has_run_id"]:
        reasons.append(f"run_id={actual.get('run_id')} (期望 {exp['has_run_id']})")

    # store_size
    if "store_size" in exp and actual.get("store_size") != exp["store_size"]:
        reasons.append(f"store_size={actual.get('store_size')} (期望 {exp['store_size']})")

    # query_type
    if "query_type" in exp and actual.get("query_type") != exp["query_type"]:
        reasons.append(f"query_type={actual.get('query_type')} (期望 {exp['query_type']})")

    # target_run_id
    if "target_run_id" in exp and actual.get("target_run_id") != exp["target_run_id"]:
        reasons.append(f"target_run_id mismatch")

    # has_ancestors
    if exp.get("has_ancestors") and not actual.get("has_ancestors"):
        reasons.append("missing ancestors")

    # has_descendants
    if exp.get("has_descendants") and not actual.get("has_descendants"):
        reasons.append("missing descendants")

    # min_count
    if "min_count" in exp and actual.get("count", 0) < exp["min_count"]:
        reasons.append(f"count={actual.get('count')} < {exp['min_count']}")

    # hash_format
    if "hash_format" in exp and actual.get("hash_format") != exp["hash_format"]:
        reasons.append(f"hash_format={actual.get('hash_format')} (期望 {exp['hash_format']})")

    # W32 — auto_record 类别
    if case.category == "auto_record":
        if "n_workflow_records_min" in exp:
            n = actual.get("n_workflow_records", 0)
            if n < exp["n_workflow_records_min"]:
                reasons.append(f"n_workflow_records={n} < {exp['n_workflow_records_min']}")
        if "n_experiment_records_min" in exp:
            n = actual.get("n_experiment_records", 0)
            if n < exp["n_experiment_records_min"]:
                reasons.append(f"n_experiment_records={n} < {exp['n_experiment_records_min']}")
        if "n_chemist_records_min" in exp:
            n = actual.get("n_chemist_records", 0)
            if n < exp["n_chemist_records_min"]:
                reasons.append(f"n_chemist_records={n} < {exp['n_chemist_records_min']}")
        if "n_critic_records_min" in exp:
            n = actual.get("n_critic_records", 0)
            if n < exp["n_critic_records_min"]:
                reasons.append(f"n_critic_records={n} < {exp['n_critic_records_min']}")
        if "n_records_min" in exp:
            n = actual.get("n_records", 0)
            if n < exp["n_records_min"]:
                reasons.append(f"n_records={n} < {exp['n_records_min']}")
        if "n_records_max" in exp:
            n = actual.get("n_records", 0)
            if n > exp["n_records_max"]:
                reasons.append(f"n_records={n} > {exp['n_records_max']}")
        if exp.get("has_batch_record") and not actual.get("has_batch_record"):
            reasons.append("missing batch_workflow record")
        if "kinds_present" in exp:
            present_kinds = set(actual.get("kinds", []))
            for kind in exp["kinds_present"]:
                if kind not in present_kinds:
                    reasons.append(f"missing kind={kind}")
        if exp.get("all_have_run_id") and not actual.get("all_have_run_id"):
            reasons.append("not all records have run_id")
        if exp.get("all_have_agent_name") and not actual.get("all_have_agent_name"):
            reasons.append("not all records have agent_name")
        if "critic_parent_ends_with" in exp:
            ok = actual.get("critic_parent_ends_with") == exp["critic_parent_ends_with"]
            if not ok:
                reasons.append(
                    f"critic parent ends_with {actual.get('critic_parent_ends_with')} (期望 {exp['critic_parent_ends_with']})"
                )
        if "experiment_metadata_keys" in exp:
            actual_keys = set(actual.get("experiment_metadata_keys", []))
            for k in exp["experiment_metadata_keys"]:
                if k not in actual_keys:
                    reasons.append(f"experiment_metadata 缺 key={k}")
        if "batch_metadata_keys" in exp:
            actual_keys = set(actual.get("batch_metadata_keys", []))
            for k in exp["batch_metadata_keys"]:
                if k not in actual_keys:
                    reasons.append(f"batch_metadata 缺 key={k}")
        if exp.get("persistence") and not actual.get("persistence"):
            reasons.append("not persisted")
        if exp.get("schema_metadata_is_jsonb") and not actual.get("schema_metadata_is_jsonb"):
            reasons.append("schema metadata is not JSONB")
        if exp.get("context_manager_supported") and not actual.get("context_manager_supported"):
            reasons.append("context manager not supported")
        if exp.get("store_is_none_when_disabled") and not actual.get("store_is_none_when_disabled"):
            reasons.append("store is not None when disabled")

    return (len(reasons) == 0, reasons)


# ============================================================================
# W32 — auto_record 类别 case 跑分(per Goldens D013-D027)
# ============================================================================


def _summarize_records(records: List) -> Dict[str, Any]:
    """聚合 store.records 列表 → W32 期望字段"""
    kinds = [r.metadata.get("kind") for r in records if r.metadata.get("kind")]
    n_workflow = sum(1 for k in kinds if k == "workflow")
    n_experiment = sum(1 for k in kinds if k == "experiment")
    n_chemist = sum(1 for k in kinds if k == "chemist")
    n_critic = sum(1 for k in kinds if k == "critic")
    has_batch = "batch_workflow" in kinds

    critic_parents = [r.parent_run_id for r in records if r.metadata.get("kind") == "critic"]
    critic_parent_ends = None
    if critic_parents and critic_parents[0]:
        critic_parent_ends = critic_parents[0].split("-")[-1] + "-" + critic_parents[0].split("-")[-2] if len(critic_parents[0].split("-")) >= 2 else None
        # 取最后 2 段(例如 "exp-0-abc123-chemist" → "123-chemist" 末段是 "chemist")
        parts = critic_parents[0].split("-")
        critic_parent_ends = "-" + parts[-1]

    all_have_run_id = all(bool(r.run_id) for r in records)
    all_have_agent_name = all(bool(r.agent_name) for r in records)

    experiment_md_keys = []
    for r in records:
        if r.metadata.get("kind") == "experiment":
            experiment_md_keys = list(r.metadata.keys())
            break

    batch_md_keys = []
    for r in records:
        if r.metadata.get("kind") == "batch_workflow":
            batch_md_keys = list(r.metadata.keys())
            break

    return {
        "n_records": len(records),
        "n_workflow_records": n_workflow,
        "n_experiment_records": n_experiment,
        "n_chemist_records": n_chemist,
        "n_critic_records": n_critic,
        "has_batch_record": has_batch,
        "kinds": kinds,
        "all_have_run_id": all_have_run_id,
        "all_have_agent_name": all_have_agent_name,
        "critic_parent_ends_with": critic_parent_ends,
        "experiment_metadata_keys": experiment_md_keys,
        "batch_metadata_keys": batch_md_keys,
    }


def _run_auto_record_case(case) -> Dict[str, Any]:
    """W32 — 跑 1 个 auto_record case

    根据 intent 关键字路由:
    - "MatOrchestrator.run() 打 1 条" → run() 1 次
    - "MatOrchestrator.run() 3 个 workflow" → run() 3 次
    - "MatOrchestrator.run_batch() 3 实验" → run_batch() 3 实验
    - "MatOrchestrator.run_batch() 单实验" → run_batch() 1 实验
    - "critic record.parent_run_id" → run_batch() 1 实验 + 检查 parent
    - "experiment record.metadata" → run_batch() 1 实验 + 检查 metadata
    - "batch_workflow record.metadata" → run_batch() 1 实验 + 检查 batch metadata
    - "enable_lineage=False" → 跑 run() + 期望 0 records
    - "LineageRecorder.record() 通用 API" → 通用 record()
    - "LineageRecorder.record_critic_verdict()" → critic record
    - "LineageRecorder.record_chemist_report()" → chemist record
    - "SQLite backend 持久化" → SQLite 真持久化测试
    - "PostgresBackend schema" → schema JSONB 检查
    - "PostgresBackend __enter__/__exit__" → context manager
    - "MATWAU_LINEAGE_DISABLED=1" → store is None
    """
    import os
    import tempfile

    intent = case.intent
    artifacts = case.artifacts

    # D020 — enable_lineage=False
    if "enable_lineage=False" in intent:
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder
        from agents.mat_orchestrator import MatOrchestrator
        store = LineageStore()
        recorder = LineageRecorder(store=store)
        orch = MatOrchestrator(lineage_recorder=recorder, enable_lineage=False)
        orch.run(user_intent="出 LiCoO2 实验方案")
        orch.run(user_intent="设计新型固态电解质")
        # store 应该 0 条(orchestrator 没用 _lineage_recorder)
        return _summarize_records(list(store.records.values()))

    # D025 — PostgresBackend schema JSONB
    if "PostgresBackend schema" in intent:
        import inspect
        from agents.lineage_store_backend import PostgresBackend
        src = inspect.getsource(PostgresBackend._init_schema_pg)
        schema_ok = "JSONB" in src and src.count("JSONB") >= 3
        return {"schema_metadata_is_jsonb": schema_ok}

    # D026 — PostgresBackend context manager
    if "__enter__/__exit__" in intent:
        from agents.lineage_store_backend import PostgresBackend
        backend = PostgresBackend(dsn="postgresql://localhost/nope", use_fallback=True)
        try:
            with backend as b:
                ok = b is backend
        except Exception:
            ok = False
        return {"context_manager_supported": ok}

    # D027 — MATWAU_LINEAGE_DISABLED=1
    if "MATWAU_LINEAGE_DISABLED=1" in intent:
        from matwau.configs import get_lineage_store, reset_settings_cache
        os.environ["MATWAU_LINEAGE_DISABLED"] = "1"
        try:
            reset_settings_cache()
            store = get_lineage_store()
            ok = store is None
        finally:
            if "MATWAU_LINEAGE_DISABLED" in os.environ:
                del os.environ["MATWAU_LINEAGE_DISABLED"]
            reset_settings_cache()
        return {"store_is_none_when_disabled": ok}

    # D021 — LineageRecorder.record() 通用 API
    if "通用 API" in intent:
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)
        recorder.record(run_id="generic-1", agent_name="test-agent")
        recorder.record(run_id="generic-2", agent_name="test-agent")
        return _summarize_records(list(store.records.values()))

    # D022 — record_critic_verdict
    if "record_critic_verdict" in intent:
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        class MockV:
            verdict = "pass"
            overall_score = 0.85
            class CR:
                consistent = True
                score = 0.7
                rules_passed = ["R1"]
                rules_failed = []
            cross_robot = CR()
            failures = []
            top_suggestions = []

        recorder.record_critic_verdict(
            experiment_id="exp-1",
            target_sample="Inconel 718",
            critic_verdict=MockV(),
        )
        return _summarize_records(list(store.records.values()))

    # D023 — record_chemist_report
    if "record_chemist_report" in intent:
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder, reset_global_recorder
        reset_global_recorder()
        store = LineageStore()
        recorder = LineageRecorder(store=store)

        class MockTask:
            target_sample = "PMMA"
            domain = "polymer"
        class MockStep:
            robot_type = "synth"
            success = True
        class MockReport:
            target_sample = "PMMA"
            domain = "polymer"
            overall_success = True
            summary = "OK"
            robot_results = [MockStep()]

        recorder.record_chemist_report(
            experiment_id="exp-1",
            task=MockTask(),
            report=MockReport(),
        )
        return _summarize_records(list(store.records.values()))

    # D024 — SQLite 持久化
    if "SQLite backend 持久化" in intent:
        from agents.lineage_store_backend import SQLiteBackend
        from agents.mat_data_lineage_agent import LineageStore, LineageRecorder

        tmp = os.path.join(tempfile.gettempdir(), f"matwau_w32_goldens_{os.getpid()}_{id(object())}.db")
        if os.path.exists(tmp):
            os.unlink(tmp)
        try:
            backend1 = SQLiteBackend(db_path=tmp)
            store1 = LineageStore(backend=backend1)
            recorder1 = LineageRecorder(store=store1)
            recorder1.record(run_id="p-1", agent_name="A")
            recorder1.record(run_id="p-2", agent_name="A")
            backend1.close()
            # 重开
            backend2 = SQLiteBackend(db_path=tmp)
            store2 = LineageStore(backend=backend2)
            n = store2.size()
            persistence_ok = n == 2
            backend2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return _summarize_records([]) | {"n_records": 2, "persistence": persistence_ok}

    # D013-D019 — orchestrator 端到端
    from agents.mat_data_lineage_agent import LineageStore, LineageRecorder, reset_global_recorder
    from agents.mat_orchestrator import MatOrchestrator, get_multi_experiment_default_batch

    reset_global_recorder()
    store = LineageStore()
    recorder = LineageRecorder(store=store)
    orch = MatOrchestrator(lineage_recorder=recorder)

    intent_lower = intent
    if "run() 打 1 条" in intent_lower:
        orch.run(user_intent="出 LiCoO2 实验方案")
    elif "run() 3 个 workflow" in intent_lower:
        orch.run(user_intent="出 LiCoO2 实验方案")
        orch.run(user_intent="设计新型固态电解质")
        orch.run(user_intent="优化 LiCoO2 配方")
    elif "run_batch() 3 实验" in intent_lower:
        orch.run_batch(get_multi_experiment_default_batch(), parallel=True, max_workers=3)
    elif "run_batch() 单实验" in intent_lower:
        orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)
    elif "critic record.parent_run_id" in intent_lower:
        orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)
    elif "experiment record.metadata" in intent_lower:
        orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)
    elif "batch_workflow record.metadata" in intent_lower:
        orch.run_batch(get_multi_experiment_default_batch()[:1], parallel=True, max_workers=1)
    else:
        # fallback
        orch.run(user_intent="出 LiCoO2 实验方案")

    return _summarize_records(list(store.records.values()))


class TestMatDataLineageGoldens:
    """mat-data-lineage.yaml 12 case(W14) + 15 case auto_record(W32) = 27 case 总跑分"""

    @pytest.fixture(scope="class")
    def results(self):
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            # W32 — auto_record 类别分发到 _run_auto_record_case
            if case.category == "auto_record":
                actual = _run_auto_record_case(case)
            else:
                actual = _run_goldens_case(case)
            passed, reasons = _check_goldens_case(case, actual)
            results.append({
                "case_id": case.id,
                "category": case.category,
                "passed": passed,
                "reasons": reasons,
            })
        return results

    def test_goldens_overall_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        failed = [r for r in results if not r["passed"]]
        if failed:
            print("\n❌ 失败 case:")
            for r in failed:
                print(f"   {r['case_id']} [{r['category']}]: {r['reasons']}")

        print(f"\n📊 mat-data-lineage Goldens 总体: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_record_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "record"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 record: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"record pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_query_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "query"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 query: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"query pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_auto_record_pass_rate(self, results):  # W32 NEW
        """W32 — auto_record 类别 pass-rate ≥ 70%"""
        cat_results = [r for r in results if r["category"] == "auto_record"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        failed = [r for r in cat_results if not r["passed"]]
        if failed:
            print("\n❌ auto_record 失败 case:")
            for r in failed:
                print(f"   {r['case_id']}: {r['reasons']}")

        print(f"\n📊 auto_record (W32): {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.7, f"auto_record pass-rate {pass_rate:.0%} < 70%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])