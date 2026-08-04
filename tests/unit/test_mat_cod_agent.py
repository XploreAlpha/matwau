"""test_mat_cod_agent.py — MatCodAgent wrapper agent 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 13 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_cod_agent import (  # noqa: E402
    MatCodAgent,
    CodConfig,
    create_default_agent,
)


# ============================================================================
# Test 1: 基本端到端
# ============================================================================


class TestMatCodAgentBasic:
    """MatCodAgent.run() 端到端"""

    def test_default_agent(self):
        agent = create_default_agent()
        assert agent.name == "mat-cod-agent"
        assert isinstance(agent, MatCodAgent)

    def test_run_empty_message(self):
        agent = MatCodAgent()
        req = AgentRequest(run_id="cod-test-empty", message="")
        resp = agent.run(req)
        assert resp.confidence <= 0.5
        assert "empty" in resp.reply.lower() or "为空" in resp.reply

    def test_run_known_compound(self):
        agent = MatCodAgent()
        req = AgentRequest(
            run_id="cod-test-1",
            message="查 Si 已知实验结构",
        )
        resp = agent.run(req)
        assert resp.confidence > 0.5
        assert "COD" in resp.reply or "cod" in resp.reply.lower()
        assert resp.artifacts["source_platform"] == "COD"
        assert resp.artifacts["source_doi"] == "10.1107/S0108768111046701"

    def test_run_unknown_compound(self):
        agent = MatCodAgent()
        req = AgentRequest(
            run_id="cod-test-unknown",
            message="查 XyZqWvUtSrRnFn123 结构",
        )
        resp = agent.run(req)
        assert resp.reply
        assert resp.artifacts["source_platform"] == "COD"

    def test_run_includes_canonical_keys(self):
        agent = MatCodAgent()
        req = AgentRequest(
            run_id="cod-test-canonical",
            message="Si 已知结构",
        )
        resp = agent.run(req)
        assert "canonical_keys" in resp.artifacts


# ============================================================================
# Test 2: confidence 启发
# ============================================================================


class TestCodConfidenceHeuristic:
    """confidence 启发逻辑"""

    def test_known_silicon_high_confidence(self):
        agent = MatCodAgent()
        req = AgentRequest(
            run_id="cod-conf-si",
            message="Si 已知结构",
        )
        resp = agent.run(req)
        assert resp.confidence >= 0.6


# ============================================================================
# Test 3: CodConfig
# ============================================================================


class TestCodConfig:
    """CodConfig.from_dict"""

    def test_default(self):
        c = CodConfig.from_dict(None)
        assert c.n_results == 5
        assert c.include_canonical is True
        assert c.fetch_cif_inline is False

    def test_custom(self):
        c = CodConfig.from_dict({
            "n_results": 3,
            "include_canonical": False,
            "fetch_cif_inline": True,
        })
        assert c.n_results == 3
        assert c.include_canonical is False
        assert c.fetch_cif_inline is True


# ============================================================================
# Test 4: system_prompt
# ============================================================================


class TestCodSystemPrompt:
    """system_prompt 内容"""

    def test_system_prompt_non_empty(self):
        agent = MatCodAgent()
        sp = agent.system_prompt()
        assert len(sp) > 50
        assert "COD" in sp or "cod" in sp.lower()
        assert "实验" in sp or "experimental" in sp.lower() or "crystal" in sp.lower()


# ============================================================================
# Test 5: 构造选项
# ============================================================================


class TestCodInitOptions:
    """MatCodAgent 构造参数"""

    def test_init_default(self):
        agent = MatCodAgent()
        assert agent.default_n_results == 5
        assert agent.use_real_cod is True

    def test_init_use_real_cod_false(self):
        agent = MatCodAgent(use_real_cod=False)
        assert agent.use_real_cod is False

    def test_init_with_custom_client(self):
        from agents.cod_client import CodClient
        custom_client = CodClient(max_results=20)
        agent = MatCodAgent(client=custom_client)
        assert agent._client.max_results == 20


# ============================================================================
# Test 6: 来源 citation
# ============================================================================


class TestCodSourceAttribution:
    """COD 数据来源强制"""

    def test_artifacts_contain_doi(self):
        agent = MatCodAgent()
        req = AgentRequest(run_id="cod-doi", message="Si 结构")
        resp = agent.run(req)
        assert "source_doi" in resp.artifacts
        assert resp.artifacts["source_doi"].startswith("10.")
        assert "citation" in resp.artifacts
        assert "Gražulis" in resp.artifacts["citation"] or "Grazulis" in resp.artifacts["citation"]

    def test_artifacts_contain_source_platform(self):
        agent = MatCodAgent()
        req = AgentRequest(run_id="cod-platform", message="Si 结构")
        resp = agent.run(req)
        assert resp.artifacts["source_platform"] == "COD"


# ============================================================================
# Test 7: fetch_cif_inline 选项
# ============================================================================


class TestFetchCifInline:
    """fetch_cif_inline=True 时应尝试拉 CIF"""

    def test_cif_inline_off_by_default(self):
        agent = MatCodAgent()
        req = AgentRequest(run_id="cod-cif-off", message="Si 结构")
        resp = agent.run(req)
        assert "cif_text" not in resp.artifacts

    def test_cif_inline_requested(self):
        """即使 fetch_cif_inline=True,网络失败时不 crash"""
        agent = MatCodAgent()
        req = AgentRequest(
            run_id="cod-cif-on",
            message="Si 结构",
            context={"fetch_cif_inline": True},
        )
        resp = agent.run(req)
        # 不强制 cif_text 存在(可能网络失败)
        # 但若存在,必须是字符串
        if "cif_text" in resp.artifacts:
            assert isinstance(resp.artifacts["cif_text"], str)
            assert len(resp.artifacts["cif_text"]) <= 4000  # 4 KB 上限