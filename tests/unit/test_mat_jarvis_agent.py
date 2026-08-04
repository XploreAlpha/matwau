"""test_mat_jarvis_agent.py — MatJarvAgent wrapper agent 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 12 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_jarvis_agent import (  # noqa: E402
    MatJarvAgent,
    JarvConfig,
    create_default_agent,
)


# ============================================================================
# Test 1: 基本端到端
# ============================================================================


class TestMatJarvAgentBasic:
    def test_default_agent(self):
        agent = create_default_agent()
        assert agent.name == "mat-jarvis-agent"
        assert isinstance(agent, MatJarvAgent)

    def test_run_empty_message(self):
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(run_id="j-empty", message="")
        resp = agent.run(req)
        assert resp.confidence <= 0.5
        assert "empty" in resp.reply.lower() or "为空" in resp.reply

    def test_run_known_compound_mock(self):
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-mock-1",
            message="查 MoS2 2D 带隙",
        )
        resp = agent.run(req)
        assert resp.artifacts["source_platform"] == "JARVIS"
        assert resp.artifacts["source_doi"] == "10.1038/s41597-020-00673-3"
        assert resp.artifacts["n_results"] >= 1

    def test_run_citation(self):
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-cit",
            message="GaN bulk modulus",
        )
        resp = agent.run(req)
        # reply 含平台名
        assert "JARVIS" in resp.reply
        # artifacts 含 citation(per M1 模式)
        assert resp.artifacts["source_platform"] == "JARVIS"
        assert "Choudhary" in resp.artifacts["citation"] or "Sci. Data" in resp.artifacts["citation"]


# ============================================================================
# Test 2: JarvConfig
# ============================================================================


class TestJarvConfig:
    def test_defaults(self):
        c = JarvConfig()
        assert c.n_results == 5
        assert c.include_canonical is True
        assert c.include_2d_only is False

    def test_from_dict_overrides(self):
        c = JarvConfig.from_dict({
            "n_results": 10,
            "include_2d_only": True,
        })
        assert c.n_results == 10
        assert c.include_2d_only is True


# ============================================================================
# Test 3: 2D 标记 + filter
# ============================================================================


class TestJarvAgent2D3D:
    def test_artifacts_n_2d_records(self):
        """artifacts 含 n_2d_records 字段"""
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-2d",
            message="MoS2",
        )
        resp = agent.run(req)
        assert "n_2d_records" in resp.artifacts
        assert "n_3d_records" in resp.artifacts
        assert isinstance(resp.artifacts["n_2d_records"], int)
        assert isinstance(resp.artifacts["n_3d_records"], int)

    def test_2d_marker_in_reply(self):
        """reply 含 2D 标记(per mock MoS2)"""
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-2d-mark",
            message="MoS2 2D 材料",
        )
        resp = agent.run(req)
        # MoS2 mock → 2D
        if resp.artifacts["n_results"] > 0:
            assert "2D" in resp.reply

    def test_include_2d_only_true(self):
        """include_2d_only=True → 只保留 2D"""
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-2d-only",
            message="Si",  # Si 是 3D mock
            context={"include_2d_only": True},
        )
        resp = agent.run(req)
        # Si 全 3D → filter 后 n_results=0
        assert resp.artifacts["n_results"] == 0


# ============================================================================
# Test 4: canonical_key
# ============================================================================


class TestJarvAgentCanonical:
    def test_artifacts_contain_canonical_keys(self):
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-can",
            message="MoS2",
        )
        resp = agent.run(req)
        assert "canonical_keys" in resp.artifacts
        cks = resp.artifacts["canonical_keys"]
        assert isinstance(cks, list)
        assert len(cks) >= 1


# ============================================================================
# Test 5: jarvis-tools 包状态
# ============================================================================


class TestJarvisToolsStatus:
    def test_jarvis_tools_available_in_artifacts(self):
        """artifacts 含 jarvis_tools_available 字段"""
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-tools",
            message="GaN",
        )
        resp = agent.run(req)
        assert "jarvis_tools_available" in resp.artifacts
        assert isinstance(resp.artifacts["jarvis_tools_available"], bool)


# ============================================================================
# Test 6: error handling
# ============================================================================


class TestJarvAgentErrors:
    def test_error_response_format(self):
        agent = MatJarvAgent(use_real_jarvis=True)

        class _ExplodingClient:
            enable_fallback = True
            def search(self, *args, **kwargs):
                raise RuntimeError("jarvis exploded")

        agent._client = _ExplodingClient()
        req = AgentRequest(run_id="j-err", message="MoS2")
        resp = agent.run(req)
        # 错误 response 应含 error 字段
        assert resp.error is not None
        assert "jarvis exploded" in resp.error
        assert resp.artifacts["source_platform"] == "JARVIS"


# ============================================================================
# Test 7: n_results
# ============================================================================


class TestJarvAgentNResults:
    def test_n_results_override(self):
        agent = MatJarvAgent(use_real_jarvis=False)
        req = AgentRequest(
            run_id="j-1",
            message="MoS2",
            context={"n_results": 1},
        )
        resp = agent.run(req)
        assert resp.artifacts["n_results"] <= 1


# ============================================================================
# Test 8: 系统提示
# ============================================================================


class TestJarvAgentSystemPrompt:
    def test_system_prompt_mentions_jarvis(self):
        agent = MatJarvAgent()
        sp = agent.system_prompt()
        assert "JARVIS" in sp
        assert "2D" in sp or "3D" in sp