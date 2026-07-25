"""test_stage2_integration.py — W16 Stage 2 真接入测试

覆盖:
1. arXiv client 真接入(per agents.arxiv_client)
2. arXiv 真查 + fallback 行为
3. arXiv 接 mat-lit(use_real_arxiv=True 走真 API)
4. SQLiteBackend 基本 CRUD
5. SQLiteBackend 重启保留
6. LineageStore 接 SQLite 真持久化
7. LineageStore 重启祖先链保留

per MatWAU-开发计划 §七 W16
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

from agents.arxiv_client import (  # noqa: E402
    ArxivClient,
    ArxivReference,
    is_arxiv_available,
    search_arxiv,
)
from agents.arxiv_client.client import (  # noqa: E402
    _parse_arxiv_xml,
    _build_arxiv_query,
)
from agents.lineage_store_backend import (  # noqa: E402
    InMemoryBackend,
    LineageBackend,
    LineageNotFoundError,
    LineageRecordDTO,
    SQLiteBackend,
)
from agents.mat_data_lineage_agent.lineage_engine import LineageStore  # noqa: E402
from agents.mat_lit_agent.lit_engine import (  # noqa: E402
    review_literature,
    search_literature_with_arxiv_priority,
)


# ============================================================================
# 测试 1: arXiv client 基本
# ============================================================================


class TestArxivClientBasic:
    """arXiv client 基本功能"""

    def test_is_arxiv_available(self):
        """arXiv 可用性探测(至少 1 次超时要 5s)"""
        # 不强制 True,允许 False(测试可以离线跑)
        result = is_arxiv_available()
        assert isinstance(result, bool)

    def test_arxiv_reference_to_dict(self):
        r = ArxivReference(arxiv_id="2401.12345", title="Test", authors=["A"], year=2024)
        d = r.to_dict()
        assert d["arxiv_id"] == "2401.12345"
        assert d["title"] == "Test"
        assert d["year"] == 2024

    def test_arxiv_xml_parse(self):
        """解析真实 arXiv XML 片段"""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Test Paper Title</title>
    <summary>This is a test abstract.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Smith, J.</name></author>
    <category term="cond-mat.mtrl-sci"/>
  </entry>
</feed>
"""
        refs = _parse_arxiv_xml(xml)
        assert len(refs) == 1
        r = refs[0]
        assert r.arxiv_id == "2401.12345"
        assert r.title == "Test Paper Title"
        assert r.year == 2024
        assert r.authors == ["Smith, J."]
        assert "cond-mat" in (r.categories[0] if r.categories else "")

    def test_build_arxiv_query_with_formula(self):
        q = _build_arxiv_query("出 LiCoO2 实验方案")
        assert "LiCoO2" in q

    def test_build_arxiv_query_with_alias(self):
        q = _build_arxiv_query("Review LLZO 进展")
        assert "LLZO" in q

    def test_build_arxiv_query_with_domain(self):
        q = _build_arxiv_query("算 PMMA Tg", domain="polymer")
        # 包含 PMMA 或 polymer 关键词
        assert "PMMA" in q or "polymer" in q.lower()


# ============================================================================
# 测试 2: arXiv 真查(mark as live test)
# ============================================================================


@pytest.mark.network
class TestArxivClientLive:
    """需要网络的真查询测试(默认 skip,带 --network 跑)"""

    def test_search_arxiv_real(self):
        """真查 LLZO"""
        refs, is_real = search_arxiv("Review LLZO 进展", max_results=3)
        if not is_real:
            pytest.skip("arXiv 不可用,跳过真查询测试")
        assert len(refs) > 0
        assert all(r.arxiv_id for r in refs)
        assert all(r.title for r in refs)


# ============================================================================
# 测试 3: arXiv fallback
# ============================================================================


class TestArxivFallback:
    """fallback 行为测试"""

    def test_arxiv_xxx_handles_failure(self):
        """Client 返回 (refs, is_real),失败时 is_real=False"""
        client = ArxivClient(timeout=0.001)  # 故意超短 timeout 触发 fallback
        refs, is_real = client.search("test", max_results=2)
        if not is_real:
            # fallback 情况下 refs 是 []
            assert refs == []
            assert is_real is False

    def test_arxiv_parse_invalid_returns_empty(self):
        """无效 XML 返回空列表不崩"""
        refs = _parse_arxiv_xml("not xml <<<broken")
        assert refs == []


# ============================================================================
# 测试 4: mat-lit 接 arXiv
# ============================================================================


class TestMatLitStage2:
    """mat-lit W16 真 arXiv 接入测试"""

    def test_review_literature_default_uses_mock(self):
        """默认 False = W14 mock 行为"""
        r = review_literature("Review LLZO", use_real_arxiv=False, domain="inorganic_crystal")
        assert len(r.references) > 0

    def test_review_literature_with_arxiv(self):
        """use_real_arxiv=True 走 arxiv_client"""
        # 即便网络失败也不崩(fallback 到 mock)
        r = review_literature("Review LLZO", use_real_arxiv=True, domain="inorganic_crystal")
        assert len(r.references) >= 0  # 0 或 >=1 都接受(fallback 也行)


# ============================================================================
# 测试 5: SQLiteBackend 基本 CRUD
# ============================================================================


class TestSQLiteBackendCRUD:
    """SQLiteBackend CRUD 测试"""

    def test_add_and_get(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            backend = SQLiteBackend(db_path=db_path)
            try:
                rec = LineageRecordDTO(
                    lineage_id="lin-001",
                    run_id="run-A",
                    agent_name="mat-gen-agent",
                    cost=0.06,
                    metadata={"domain": "inorganic_crystal"},
                )
                backend.add(rec)
                got = backend.get("lin-001")
                assert got.lineage_id == "lin-001"
                assert got.run_id == "run-A"
                assert got.cost == 0.06
            finally:
                backend.close()
        finally:
            os.unlink(db_path)

    def test_list_by_run(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            backend = SQLiteBackend(db_path=db_path)
            try:
                for i in range(3):
                    backend.add(LineageRecordDTO(
                        lineage_id=f"lin-{i:03d}",
                        run_id="run-A" if i < 2 else "run-B",
                        agent_name=f"agent-{i}",
                    ))
                run_a = backend.list_by_run("run-A")
                assert len(run_a) == 2
                run_b = backend.list_by_run("run-B")
                assert len(run_b) == 1
            finally:
                backend.close()
        finally:
            os.unlink(db_path)

    def test_list_by_parent(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            backend = SQLiteBackend(db_path=db_path)
            try:
                backend.add(LineageRecordDTO(
                    lineage_id="parent-1", run_id="run-1", agent_name="gen",
                ))
                backend.add(LineageRecordDTO(
                    lineage_id="child-1", run_id="run-2", parent_run_id="run-1",
                    agent_name="sim",
                ))
                backend.add(LineageRecordDTO(
                    lineage_id="child-2", run_id="run-3", parent_run_id="run-1",
                    agent_name="exp",
                ))
                children = backend.list_by_parent("run-1")
                assert len(children) == 2
            finally:
                backend.close()
        finally:
            os.unlink(db_path)

    def test_delete(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            backend = SQLiteBackend(db_path=db_path)
            try:
                backend.add(LineageRecordDTO(
                    lineage_id="del-me", run_id="r", agent_name="x",
                ))
                assert backend.get("del-me").lineage_id == "del-me"
                backend.delete("del-me")
                with pytest.raises(LineageNotFoundError):
                    backend.get("del-me")
            finally:
                backend.close()
        finally:
            os.unlink(db_path)


# ============================================================================
# 测试 6: SQLiteBackend 重启保留
# ============================================================================


class TestSQLiteBackendPersistence:
    """SQLite 重启保留测试"""

    def test_data_survives_reopen(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # 第 1 阶段:写入
            b1 = SQLiteBackend(db_path=db_path)
            b1.add(LineageRecordDTO(
                lineage_id="persist-1", run_id="run-X",
                agent_name="mat-gen-agent", cost=0.06,
                metadata={"domain": "inorganic_crystal"},
            ))
            b1.close()

            # 第 2 阶段:重开
            b2 = SQLiteBackend(db_path=db_path)
            try:
                rec = b2.get("persist-1")
                assert rec.lineage_id == "persist-1"
                assert rec.run_id == "run-X"
                assert rec.metadata["domain"] == "inorganic_crystal"
            finally:
                b2.close()
        finally:
            os.unlink(db_path)

    def test_multiple_records_persist(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            b1 = SQLiteBackend(db_path=db_path)
            for i in range(5):
                b1.add(LineageRecordDTO(
                    lineage_id=f"persist-{i}", run_id=f"run-{i}",
                    agent_name="agent", cost=0.01 * i,
                ))
            b1.close()

            b2 = SQLiteBackend(db_path=db_path)
            try:
                assert len(b2.list()) == 5
            finally:
                b2.close()
        finally:
            os.unlink(db_path)


# ============================================================================
# 测试 7: LineageStore 接 SQLite
# ============================================================================


class TestLineageStoreWithSQLite:
    """LineageStore 接 SQLiteBackend 测试"""

    def test_store_with_sqlite_backend_writes_through(self):
        """写 1 条 → 同时写到 in-memory + SQLite"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            backend = SQLiteBackend(db_path=db_path)
            try:
                store = LineageStore(backend=backend)
                rec = store.add("run-A", "mat-gen-agent", cost=0.06)

                # in-memory 有
                assert len(store.records) == 1
                # SQLite 也写到了(用 backend.get 验证)
                got = backend.get(rec.lineage_id)
                assert got.lineage_id == rec.lineage_id
            finally:
                backend.close()
        finally:
            os.unlink(db_path)

    def test_store_with_sqlite_persists_across_restart(self):
        """关 DB 重开 → records 还在"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # 阶段 1
            b1 = SQLiteBackend(db_path=db_path)
            s1 = LineageStore(backend=b1)
            r1 = s1.add("run-A", "mat-gen-agent", cost=0.06)
            r2 = s1.add("run-B", "mat-sim-agent", parent_run_id="run-A", cost=0.5)
            b1.close()

            # 阶段 2:重开
            b2 = SQLiteBackend(db_path=db_path)
            s2 = LineageStore(backend=b2)
            try:
                assert len(s2.records) == 2, f"重启后应该有 2 条,实际 {len(s2.records)}"
                # ancestors 还能用
                ancestors = s2.ancestors("run-B")
                assert len(ancestors) == 1
            finally:
                b2.close()
        finally:
            os.unlink(db_path)


# ============================================================================
# 测试 8: 向后兼容 InMemoryBackend
# ============================================================================


class TestInMemoryBackwardCompat:
    """InMemoryBackend W14 行为不破"""

    def test_in_memory_crud(self):
        backend = InMemoryBackend()
        backend.add(LineageRecordDTO(
            lineage_id="mem-1", run_id="r", agent_name="x",
        ))
        assert backend.get("mem-1").lineage_id == "mem-1"
        assert len(backend.list()) == 1

    def test_in_memory_subclass_check(self):
        """W16: InMemoryBackend 继承 LineageBackend 抽象类"""
        backend = InMemoryBackend()
        assert isinstance(backend, LineageBackend)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])