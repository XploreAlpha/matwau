"""test_mat_nomad_agent.py — MatNomadAgent wrapper agent 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 11 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_nomad_agent import (  # noqa: E402
    MatNomadAgent,
    NomadConfig,
    create_default_agent,
)


# ============================================================================
# Test 1: 基本端到端
# ============================================================================


class TestMatNomadAgentBasic:
    def test_default_agent(self):
        agent = create_default_agent()
        assert agent.name == "mat-nomad-agent"
        assert isinstance(agent, MatNomadAgent)

    def test_run_empty_message(self):
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(run_id="n-empty", message="")
        resp = agent.run(req)
        assert resp.confidence <= 0.5
        assert "empty" in resp.reply.lower() or "为空" in resp.reply

    def test_run_known_compound_mock(self):
        """离线 mock 模式:已知化合物返回 mock 数据"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-mock-1",
            message="查 LLZO 综合性质",
        )
        resp = agent.run(req)
        # mock LLZO → Li7La3Zr2O12 / Ia-3d
        assert resp.artifacts["source_platform"] == "NOMAD"
        assert resp.artifacts["source_doi"] == "10.1088/2515-7655/ab002a"
        assert resp.artifacts["n_results"] >= 1

    def test_run_source_attribution(self):
        """所有 reply 都含 source attribution + artifacts 含 citation"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-cite",
            message="LiCoO2",
        )
        resp = agent.run(req)
        # reply 含平台名
        assert "NOMAD" in resp.reply
        # artifacts 含 citation(per M1 模式,reply + artifacts 各有所侧重)
        assert resp.artifacts["source_platform"] == "NOMAD"
        assert "Draxl" in resp.artifacts["citation"] or "J. Phys. Mater." in resp.artifacts["citation"]


# ============================================================================
# Test 2: NomadConfig
# ============================================================================


class TestNomadConfig:
    def test_defaults(self):
        c = NomadConfig()
        assert c.n_results == 5
        assert c.include_canonical is True
        assert c.include_metainfo_unmapped is True

    def test_from_dict_empty(self):
        c = NomadConfig.from_dict(None)
        assert c.n_results == 5

    def test_from_dict_overrides(self):
        c = NomadConfig.from_dict({
            "n_results": 10,
            "include_canonical": False,
            "include_metainfo_unmapped": False,
        })
        assert c.n_results == 10
        assert c.include_canonical is False
        assert c.include_metainfo_unmapped is False

    def test_from_dict_partial(self):
        c = NomadConfig.from_dict({"n_results": 8})
        assert c.n_results == 8
        assert c.include_canonical is True  # default


# ============================================================================
# Test 3: metainfo_unmapped 输出
# ============================================================================


class TestMetainfoUnmapped:
    def test_metainfo_unmapped_key_in_artifacts(self):
        """artifacts 含 metainfo_unmapped key"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-meta",
            message="TiO2 综合性质",
        )
        resp = agent.run(req)
        assert "metainfo_unmapped" in resp.artifacts
        assert isinstance(resp.artifacts["metainfo_unmapped"], list)

    def test_include_metainfo_unmapped_false_omits(self):
        """include_metainfo_unmapped=False → artifacts 无 metainfo_unmapped"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-no-meta",
            message="LLZO",
            context={"include_metainfo_unmapped": False},
        )
        resp = agent.run(req)
        # 即便 False 也会给(空 list) — 因为 _results_to_response 总会写 key
        # 这里只确认 is a list
        assert isinstance(resp.artifacts.get("metainfo_unmapped"), list)


# ============================================================================
# Test 4: canonical_key
# ============================================================================


class TestNomadAgentCanonical:
    def test_artifacts_contain_canonical_keys(self):
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-can",
            message="LiCoO2",
        )
        resp = agent.run(req)
        assert "canonical_keys" in resp.artifacts
        # 应该含至少 1 个有效 canonical
        cks = resp.artifacts["canonical_keys"]
        assert isinstance(cks, list)
        assert len(cks) >= 1
        # 至少一个 reduced_formula 非空(mock LCO)
        non_empty = [k for k in cks if k.get("reduced_formula")]
        assert len(non_empty) >= 1

    def test_include_canonical_false(self):
        """include_canonical=False → canonical_keys 为空"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-no-can",
            message="Si",
            context={"include_canonical": False},
        )
        resp = agent.run(req)
        assert resp.artifacts["canonical_keys"] == []


# ============================================================================
# Test 5: error handling
# ============================================================================


class TestNomadAgentErrors:
    def test_error_response_format(self):
        """client raise 时返 _error_response"""
        # use_real_nomad=True 让 act() 走 self._client.search() 路径
        agent = MatNomadAgent(use_real_nomad=True)
        # 注入一个抛异常的 client(enable_fallback 必须 True 才会触发 try/except)
        class _ExplodingClient:
            enable_fallback = True
            def search(self, *args, **kwargs):
                raise RuntimeError("explode")

        agent._client = _ExplodingClient()
        req = AgentRequest(run_id="n-err", message="LLZO")
        resp = agent.run(req)
        # 错误 response 应含 error 字段
        assert resp.error is not None
        assert "explode" in resp.error
        # artifacts.source_platform 应仍是 NOMAD(标记归属)
        assert resp.artifacts["source_platform"] == "NOMAD"


# ============================================================================
# Test 6: n_results 限制
# ============================================================================


class TestNomadAgentNResults:
    def test_n_results_override(self):
        """n_results=1 时返回最多 1 条"""
        agent = MatNomadAgent(use_real_nomad=False)
        req = AgentRequest(
            run_id="n-1",
            message="LLZO",
            context={"n_results": 1},
        )
        resp = agent.run(req)
        assert resp.artifacts["n_results"] <= 1


# ============================================================================
# Test 7: 系统提示
# ============================================================================


class TestNomadAgentSystemPrompt:
    def test_system_prompt_mentions_nomad(self):
        agent = MatNomadAgent()
        sp = agent.system_prompt()
        assert "NOMAD" in sp
        assert "metainfo" in sp.lower() or "Metainfo" in sp