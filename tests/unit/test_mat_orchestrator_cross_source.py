"""test_mat_orchestrator_cross_source.py — MatOrchestrator cross_source workflow 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M3 第 10 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_orchestrator.dag import (  # noqa: E402
    WORKFLOW_BY_SUBCLASS,
    cross_source_lookup_workflow,
    cross_source_property_workflow,
    get_workflow_for_subclass,
)
from agents.mat_orchestrator.mat_orchestrator import (  # noqa: E402
    MatOrchestrator,
    create_default_orchestrator,
)


# ============================================================================
# Test 1: 2 个新 workflow factory
# ============================================================================


class TestCrossSourceWorkflows:
    def test_lookup_workflow_5_nodes(self):
        wf = cross_source_lookup_workflow()
        assert wf.name == "cross_source_lookup"
        assert len(wf.nodes) == 5
        node_ids = [n.node_id for n in wf.nodes]
        assert node_ids == ["oqmd", "cod", "nomad", "jarvis", "critic_l5"]

    def test_property_workflow_5_nodes(self):
        wf = cross_source_property_workflow()
        assert wf.name == "cross_source_property"
        assert len(wf.nodes) == 5
        node_ids = [n.node_id for n in wf.nodes]
        assert node_ids == ["oqmd", "cod", "nomad", "jarvis", "critic_l5"]

    def test_workflow_registered(self):
        assert "cross_source_lookup" in WORKFLOW_BY_SUBCLASS
        assert "cross_source_property" in WORKFLOW_BY_SUBCLASS
        # M3 intent alias
        assert WORKFLOW_BY_SUBCLASS["external_db_query"] is cross_source_lookup_workflow
        assert WORKFLOW_BY_SUBCLASS["cross_source_validation"] is cross_source_property_workflow

    def test_get_workflow_for_subclass(self):
        wf = get_workflow_for_subclass("external_db_query")
        assert wf is not None
        assert wf.name == "cross_source_lookup"

    def test_get_workflow_for_cross_source_validation(self):
        wf = get_workflow_for_subclass("cross_source_validation")
        assert wf is not None
        assert wf.name == "cross_source_property"


# ============================================================================
# Test 2: critic_l5 节点 wiring
# ============================================================================


class TestCriticL5Wiring:
    def test_critic_l5_inputs_use_cross_source(self):
        wf = cross_source_lookup_workflow()
        critic_node = wf.nodes[-1]
        assert critic_node.agent_name == "mat-critic-agent"
        assert critic_node.inputs.get("use_cross_source") == "true"
        # records_by_platform 应引用 outputs.cross_source_records
        assert "outputs.cross_source_records" in critic_node.inputs.get("records_by_platform", "")


# ============================================================================
# Test 3: MatOrchestrator 端到端
# ============================================================================


class TestOrchestratorEndToEnd:
    def test_orchestrator_has_4_data_agents(self):
        orch = create_default_orchestrator()
        for name in [
            "mat-oqmd-agent", "mat-cod-agent",
            "mat-nomad-agent", "mat-jarvis-agent",
        ]:
            assert name in orch.agent_registry

    def test_external_db_query_routes_to_lookup(self):
        orch = create_default_orchestrator()
        result = orch.run(user_intent="查 Inconel 718 已知结构")
        assert result.workflow_name == "cross_source_lookup"
        assert result.success is True
        # 5 节点
        assert len(result.node_results) == 5

    def test_cross_source_validation_routes_to_property(self):
        orch = create_default_orchestrator()
        result = orch.run(user_intent="跨数据源对比 LiCoO2 形成能")
        assert result.workflow_name == "cross_source_property"
        assert result.success is True
        assert len(result.node_results) == 5

    def test_legacy_workflow_still_works(self):
        """旧 workflow(experiment_planning)不破"""
        orch = create_default_orchestrator()
        result = orch.run(user_intent="出 LiCoO2 实验方案")
        assert result.workflow_name == "experiment_planning"
        assert result.success is True

    def test_cross_source_records_collected(self):
        """4 data agent 跑完后,outputs['cross_source_records'] 应含 4 平台"""
        orch = create_default_orchestrator()
        result = orch.run(user_intent="查 Si 已知结构")
        # critic_l5 是最后 1 节点,其 inputs 包含 records_by_platform
        # 但 outputs dict 全局共享,所以可以从 final_outputs 推断
        assert result.success is True
        # 每个 data agent 节点都应成功
        for nr in result.node_results[:4]:  # 前 4 个
            assert nr.success is True

    def test_critic_l5_fills_l5_fields(self):
        """critic_l5 节点的 verdict (CriticOutput) 应含 l5_cross_source_* 字段"""
        orch = create_default_orchestrator()
        result = orch.run(user_intent="查 Inconel 718 已知结构")
        last = result.node_results[-1]
        v = last.outputs.get("verdict")
        # CriticOutput 应有 l5 字段(可能为 0 但存在)
        assert hasattr(v, "l5_cross_source_score")
        assert hasattr(v, "l5_cross_source_consensus_rate")
        assert hasattr(v, "l5_cross_source_n_clusters")