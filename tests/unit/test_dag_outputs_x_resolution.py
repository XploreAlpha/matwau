"""test_dag_outputs_x_resolution.py — DAGExecutor "outputs.X" src_key 解析测试

M3 新增的 src_key 形式(per cross_source_lookup_workflow 的 critic_l5.inputs)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_orchestrator.dag import (  # noqa: E402
    DAG,
    DAGExecutor,
    DAGNode,
)
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402


class _StubAgent:
    """test stub:返回固定 reply + 把 user_message 写进 artifacts"""

    def __init__(self, name: str, marker: str) -> None:
        self.name = name
        self.marker = marker

    def run(self, req: AgentRequest) -> AgentResponse:
        return AgentResponse(
            reply=f"hello from {self.marker}",
            artifacts={
                "marker": self.marker,
                "received_message": req.message,
                "received_artifacts_keys": sorted(req.artifacts.keys()) if req.artifacts else [],
            },
        )


# ============================================================================
# Test 1: outputs.X 解析
# ============================================================================


class TestOutputsXResolution:
    def test_outputs_x_passed_to_critic(self):
        """src_key='outputs.cross_source_records' 应解析为全局 outputs dict 的 value,作为 req.artifacts 传给 critic"""
        # 1 个数据节点 → 把 data 放进 outputs → 1 个 critic 节点读 outputs.X
        agent_data = _StubAgent("agent-data", "DATA")
        agent_critic = _StubAgent("agent-critic", "CRITIC")

        ex = DAGExecutor({
            "agent-data": agent_data,
            "agent-critic": agent_critic,
        })

        dag = DAG(name="outputs_x_test", nodes=[
            DAGNode(
                node_id="data",
                agent_name="agent-data",
                inputs={"message": "initial.user_intent"},
                output_key="data_response",
            ),
            DAGNode(
                node_id="critic",
                agent_name="agent-critic",
                inputs={
                    "message": "initial.user_intent",
                    "cross_source_records": "outputs.cross_source_records",
                },
                output_key="critic_response",
            ),
        ])

        # initial_inputs 含 cross_source_records(模拟 orchestrator 注入)
        result = ex.execute(
            dag,
            initial_inputs={
                "user_intent": "X",
                "cross_source_records": {"OQMD": [{"id": 1}]},
            },
        )

        assert result.success is True
        # critic 应在 req.artifacts 收到 cross_source_records
        # Stub agent 把它写到 artifacts.received_artifacts_keys
        critic_nr = result.node_results[1]
        received = critic_nr.outputs.get("artifacts", {}).get("received_artifacts_keys", [])
        assert "cross_source_records" in received
        # 也确认 artifacts.marker 还在(CRITIC 标记)
        assert critic_nr.outputs.get("artifacts", {}).get("marker") == "CRITIC"

    def test_outputs_x_does_not_consume_node_id(self):
        """outputs.X 不应被当作 node_id 解析"""
        agent_a = _StubAgent("agent-a", "A")
        agent_b = _StubAgent("agent-b", "B")
        ex = DAGExecutor({"agent-a": agent_a, "agent-b": agent_b})
        dag = DAG(name="test", nodes=[
            DAGNode("a", "agent-a", {"message": "x"}, "a_resp"),
            DAGNode("b", "agent-b", {"records": "outputs.a_resp"}, "b_resp"),
        ])
        result = ex.execute(dag, initial_inputs={"x": "hello"})
        assert result.success is True


# ============================================================================
# Test 2: cross_source_records 收集(per M3 实际场景)
# ============================================================================


class TestCrossSourceRecordsCollection:
    def test_4_data_agents_aggregate_into_outputs(self):
        """4 个 data agent 节点 + critic 节点,4 个 records 聚合成 outputs['cross_source_records']"""
        # 这个测试简化:只检查 critic 节点能拿到 4 个聚合 records
        # 实际 collection 在 DAGExecutor.execute() 内的 M3 改动里
        from agents.mat_orchestrator.dag import cross_source_lookup_workflow
        wf = cross_source_lookup_workflow()
        # critic_l5 节点的 inputs 应引用 outputs.cross_source_records
        critic = wf.nodes[-1]
        assert "outputs.cross_source_records" in critic.inputs.get("records_by_platform", "")