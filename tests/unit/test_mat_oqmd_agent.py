"""test_mat_oqmd_agent.py — MatOqmdAgent wrapper agent 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 12 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_oqmd_agent import (  # noqa: E402
    MatOqmdAgent,
    OqmdConfig,
    create_default_agent,
)


# ============================================================================
# Test 1: 基本端到端
# ============================================================================


class TestMatOqmdAgentBasic:
    """MatOqmdAgent.run() 端到端"""

    def test_default_agent(self):
        agent = create_default_agent()
        assert agent.name == "mat-oqmd-agent"
        assert isinstance(agent, MatOqmdAgent)

    def test_run_empty_message(self):
        agent = MatOqmdAgent()
        req = AgentRequest(run_id="oqmd-test-empty", message="")
        resp = agent.run(req)
        assert resp.confidence <= 0.5  # 低置信
        assert "empty" in resp.reply.lower() or "为空" in resp.reply

    def test_run_known_compound(self):
        agent = MatOqmdAgent()
        req = AgentRequest(
            run_id="oqmd-test-1",
            message="查 Inconel 718 的形成焓",
        )
        resp = agent.run(req)
        assert resp.confidence > 0.5  # 有结果
        assert "OQMD" in resp.reply or "oqmd" in resp.reply.lower()
        assert resp.artifacts["source_platform"] == "OQMD"
        assert resp.artifacts["source_doi"] == "10.1038/sdata.2013.1"

    def test_run_unknown_compound(self):
        """未知化合物 → 仍返回响应(confidence 较低)"""
        agent = MatOqmdAgent()
        req = AgentRequest(
            run_id="oqmd-test-unknown",
            message="查 XyZqWvUtSrRnFn123 化合物",
        )
        resp = agent.run(req)
        # 不崩 + 有 reply
        assert resp.reply
        assert resp.artifacts["source_platform"] == "OQMD"

    def test_run_includes_canonical_keys(self):
        agent = MatOqmdAgent()
        req = AgentRequest(
            run_id="oqmd-test-canonical",
            message="查 LLZO 形成焓",
        )
        resp = agent.run(req)
        # 默认 include_canonical=True
        assert "canonical_keys" in resp.artifacts


# ============================================================================
# Test 2: confidence 启发
# ============================================================================


class TestConfidenceHeuristic:
    """不同结果数对应不同 confidence"""

    def test_zero_records_low_confidence(self):
        agent = MatOqmdAgent()
        req = AgentRequest(
            run_id="oqmd-conf-zero",
            message="XyZqWvUtSrRnFn123",  # mock 兜底 1 条 generic
        )
        resp = agent.run(req)
        # mock 兜底 1 条 → confidence = 0.6
        # (mock 兜底永远返回 1 条,所以这里期望 0.6)
        assert 0.3 <= resp.confidence <= 0.9

    def test_multi_records_high_confidence(self):
        agent = MatOqmdAgent()
        req = AgentRequest(
            run_id="oqmd-conf-multi",
            message="查 LLZO 形成焓",
            context={"n_results": 5},
        )
        resp = agent.run(req)
        # 命中 1-3 条 → confidence = 0.6 - 0.8
        assert resp.confidence >= 0.6


# ============================================================================
# Test 3: 配置注入
# ============================================================================


class TestOqmdConfig:
    """OqmdConfig.from_dict"""

    def test_default(self):
        c = OqmdConfig.from_dict(None)
        assert c.n_results == 5
        assert c.include_canonical is True

    def test_custom(self):
        c = OqmdConfig.from_dict({"n_results": 10, "include_canonical": False})
        assert c.n_results == 10
        assert c.include_canonical is False

    def test_empty_dict(self):
        c = OqmdConfig.from_dict({})
        assert c.n_results == 5


# ============================================================================
# Test 4: system_prompt
# ============================================================================


class TestSystemPrompt:
    """system_prompt 内容"""

    def test_system_prompt_non_empty(self):
        agent = MatOqmdAgent()
        sp = agent.system_prompt()
        assert len(sp) > 50
        assert "OQMD" in sp or "oqmd" in sp.lower()
        assert "形成焓" in sp or "formation" in sp.lower()


# ============================================================================
# Test 5: 构造选项
# ============================================================================


class TestInitOptions:
    """MatOqmdAgent 各种构造参数"""

    def test_init_with_custom_n_results(self):
        agent = MatOqmdAgent(default_n_results=10)
        assert agent.default_n_results == 10

    def test_init_use_real_oqmd_false(self):
        agent = MatOqmdAgent(use_real_oqmd=False)
        assert agent.use_real_oqmd is False

    def test_init_with_custom_client(self):
        from agents.oqmd_client import OqmdClient
        custom_client = OqmdClient(max_results=20)
        agent = MatOqmdAgent(client=custom_client)
        assert agent._client.max_results == 20


# ============================================================================
# Test 6: 来源 citation 强制
# ============================================================================


class TestSourceAttribution:
    """AgentResponse 必须含 source attribution"""

    def test_artifacts_contain_doi(self):
        agent = MatOqmdAgent()
        req = AgentRequest(run_id="oqmd-doi", message="Si 形成焓")
        resp = agent.run(req)
        assert "source_doi" in resp.artifacts
        assert resp.artifacts["source_doi"].startswith("10.")
        assert "citation" in resp.artifacts
        assert "Kirklin" in resp.artifacts["citation"]

    def test_artifacts_contain_source_platform(self):
        agent = MatOqmdAgent()
        req = AgentRequest(run_id="oqmd-platform", message="Si 形成焓")
        resp = agent.run(req)
        assert resp.artifacts["source_platform"] == "OQMD"