"""test_llm_critic_e2e.py — W33 critic 接 LLM 复核端到端集成测试

测试覆盖(5 类 × 2-3 件 = ~12 件):
1. TestCriticWithLLMReview       3 — act() 跑完自动接 LLM,字段填充
2. TestCriticLLMDisabled         2 — 默认/显式 False → 不调 LLM
3. TestCriticLLMFailureFailsSoft 2 — LLM 异常 → verdict 仍正常,error 字段填
4. TestCriticWithChemistReport   2 — W30 + W33 集成(ChemistReport 路径)
5. TestCriticInOrchestrator      2 — orchestrator.run_batch() 内嵌 critic + LLM

per W33 plan §G
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================================
# helpers
# ============================================================================


def _mock_response(content: str, prompt_tokens: int = 200, completion_tokens: int = 100):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


def _mock_client(content: str = "同意", should_raise: bool = False):
    client = MagicMock()
    if should_raise:
        client.chat.completions.create.side_effect = RuntimeError("API down")
    else:
        client.chat.completions.create.return_value = _mock_response(content)
    return client


def _make_critic_with_mock_llm(content="同意 verdict", should_raise=False):
    """造 1 个 enable_llm_review=True + mock client 的 MatCriticAgent"""
    from agents.mat_critic_agent import MatCriticAgent, LLMReviewer
    client = _mock_client(content=content, should_raise=should_raise)
    reviewer = LLMReviewer(api_key="k", enabled=True, client=client)
    return MatCriticAgent(enable_llm_review=True, llm_reviewer=reviewer), client


# ============================================================================
# TestCriticWithLLMReview — act() 自动接 LLM
# ============================================================================


class TestCriticWithLLMReview:
    """act() 跑完自动接 LLM,字段填充"""

    def test_critic_with_llm_review_end_to_end(self):
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        agent, _ = _make_critic_with_mock_llm(content="同意 verdict,综合分合理")
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-e2e-1", message="评估",
                           artifacts={"candidates": candidates})
        resp = agent.run(req)

        # verdict 字段
        assert resp.artifacts["verdict"].verdict == "pass"
        assert resp.artifacts["verdict"].overall_score > 0.7
        # LLM 字段
        assert resp.artifacts["llm_review"] == "同意 verdict,综合分合理"
        assert resp.artifacts["llm_review_model"] == "deepseek-v4-flash"
        assert resp.artifacts["llm_review_error"] == ""

    def test_critic_llm_review_message_format(self):
        """prompt 应含 system + user messages"""
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        agent, client = _make_critic_with_mock_llm(content="OK")
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-e2e-2", message="评估候选",
                           artifacts={"candidates": candidates})
        agent.run(req)

        # 验证 chat.completions.create 被调
        assert client.chat.completions.create.called
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-v4-flash"
        assert "messages" in call_kwargs
        assert len(call_kwargs["messages"]) == 2  # system + user
        assert call_kwargs["messages"][0]["role"] == "system"
        assert call_kwargs["messages"][1]["role"] == "user"
        # user 消息含 critic 评分
        user_msg = call_kwargs["messages"][1]["content"]
        assert "Verdict:" in user_msg
        assert "L1 (物理):" in user_msg

    def test_critic_llm_review_does_not_break_verdict(self):
        """LLM 成功 → verdict 仍由规则打分决定(LLM 不修改 verdict)"""
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        # LLM 即使说 "建议改为 warn",verdict 仍是 pass(规则打分)
        agent, _ = _make_critic_with_mock_llm(content="建议改为 warn,理由:L4 一致性偏低")
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-e2e-3", message="评估",
                           artifacts={"candidates": candidates})
        resp = agent.run(req)
        # verdict 仍 pass(规则说了算)
        assert resp.artifacts["verdict"].verdict == "pass"
        # 但 llm_review 含 LLM 建议
        assert "warn" in resp.artifacts["llm_review"]


# ============================================================================
# TestCriticLLMDisabled — 默认/显式 False
# ============================================================================


class TestCriticLLMDisabled:
    """默认/显式 False → 不调 LLM"""

    def test_default_no_llm(self):
        from agents.mat_critic_agent import MatCriticAgent
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        agent = MatCriticAgent()  # 默认 False
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-d-1", message="评估",
                           artifacts={"candidates": candidates})
        resp = agent.run(req)
        assert resp.artifacts["llm_review"] == ""

    def test_explicit_false_no_llm(self):
        from agents.mat_critic_agent import MatCriticAgent, LLMReviewer
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        client = _mock_client(content="OK")
        reviewer = LLMReviewer(api_key="k", enabled=True, client=client)
        agent = MatCriticAgent(enable_llm_review=False, llm_reviewer=reviewer)
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-d-2", message="评估",
                           artifacts={"candidates": candidates})
        agent.run(req)
        # client 完全没被调
        assert not client.chat.completions.create.called


# ============================================================================
# TestCriticLLMFailureFailsSoft — LLM 异常 → verdict 仍正常
# ============================================================================


class TestCriticLLMFailureFailsSoft:
    """LLM 异常 → verdict 仍正常,error 字段填"""

    def test_llm_api_failure_keeps_verdict(self):
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        agent, _ = _make_critic_with_mock_llm(should_raise=True)
        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-f-1", message="评估",
                           artifacts={"candidates": candidates})
        resp = agent.run(req)
        # verdict 仍是 pass(规则打分)
        assert resp.artifacts["verdict"].verdict == "pass"
        # llm_review 空
        assert resp.artifacts["llm_review"] == ""
        # error 有值
        assert "API down" in resp.artifacts["llm_review_error"]

    def test_llm_empty_response_keeps_verdict(self):
        """LLM 返回空 choices → 不影响 verdict"""
        from matwau.core.agent_base import AgentRequest
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate
        from agents.mat_critic_agent import MatCriticAgent, LLMReviewer

        resp_empty = MagicMock()
        resp_empty.choices = []
        resp_empty.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = resp_empty
        reviewer = LLMReviewer(api_key="k", enabled=True, client=client)
        agent = MatCriticAgent(enable_llm_review=True, llm_reviewer=reviewer)

        candidates = [
            SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                         relaxed_energy=-3.5, forces_max=0.01,
                         relaxation_converged=True, stability="stable", confidence=0.9),
        ]
        req = AgentRequest(run_id="t-f-2", message="评估",
                           artifacts={"candidates": candidates})
        resp = agent.run(req)
        assert resp.artifacts["verdict"].verdict == "pass"
        assert resp.artifacts["llm_review"] == ""


# ============================================================================
# TestCriticWithChemistReport — W30 + W33 集成
# ============================================================================


class TestCriticWithChemistReport:
    """W30 ChemistReport 路径 + W33 LLM review"""

    def test_chemist_report_with_llm_review(self):
        """ChemistReport 路径走 L4 + LLM review"""
        from matwau.core.agent_base import AgentRequest
        from agents.mat_chemist_agent.chemist_engine import (
            ChemistReport,
            RobotStepResult,
        )
        from agents.mat_chemist_agent.chemist_engine import RobotStep as CRS

        # mock ChemistReport
        class MockReport:
            target_sample = "Inconel 718"
            domain = "metal_alloy"
            summary = "OK"
            warnings = []
            robot_results = [
                RobotStepResult(robot_type="synth", success=True, blocked=False,
                                reply="OK", cost_cny=100.0),
            ]

        agent, _ = _make_critic_with_mock_llm(content="同意 verdict")
        req = AgentRequest(
            run_id="t-cr-1",
            message="评估 Inconel 718",
            artifacts={"report": MockReport()},
        )
        resp = agent.run(req)
        # LLM review 应填
        assert resp.artifacts["llm_review"] == "同意 verdict"
        assert resp.artifacts["llm_review_model"] == "deepseek-v4-flash"
        # critic verdict 应是 pass 或 warn
        assert resp.artifacts["verdict"].verdict in ("pass", "warn")

    def test_chemist_report_llm_failure_keeps_l4_score(self):
        """LLM 失败 → L4 cross_robot 仍正常"""
        from matwau.core.agent_base import AgentRequest
        from agents.mat_chemist_agent.chemist_engine import RobotStepResult

        class MockReport:
            target_sample = "Inconel 718"
            domain = "metal_alloy"
            summary = "OK"
            warnings = []
            robot_results = [
                RobotStepResult(robot_type="synth", success=True, blocked=False,
                                reply="OK", cost_cny=100.0),
            ]

        agent, _ = _make_critic_with_mock_llm(should_raise=True)
        req = AgentRequest(
            run_id="t-cr-2",
            message="评估 Inconel 718",
            artifacts={"report": MockReport()},
        )
        resp = agent.run(req)
        # verdict 仍由规则
        assert resp.artifacts["verdict"] is not None
        # LLM 失败
        assert resp.artifacts["llm_review"] == ""
        assert "API down" in resp.artifacts["llm_review_error"]


# ============================================================================
# TestCriticInOrchestrator — orchestrator.run_batch() 内嵌 critic + LLM
# ============================================================================


class TestCriticInOrchestrator:
    """orchestrator.run_batch() 内嵌 critic + LLM review"""

    def test_orchestrator_critic_uses_llm_review(self):
        """orchestrator.run_batch() 默认 critic 应被 enable_llm_review 影响"""
        from agents.mat_orchestrator import MatOrchestrator
        from agents.mat_orchestrator.mat_orchestrator import MatOrchestrator as MO

        # Monkey-patch MatCriticAgent.create_default_agent → 用 mock
        from agents.mat_critic_agent import MatCriticAgent, LLMReviewer

        # 这里较复杂 — orchestrator 内嵌 critic 实例,我们 patch critic_agent
        client = _mock_client(content="同意 L4 一致性")
        reviewer = LLMReviewer(api_key="k", enabled=True, client=client)

        # 显式 critic_agent 实例
        custom_critic = MatCriticAgent(enable_llm_review=True, llm_reviewer=reviewer)
        orch = MatOrchestrator(critic_agent=custom_critic)

        # 跑 1 个 PMMA 实验
        from agents.mat_orchestrator import get_multi_experiment_default_batch
        batch = orch.run_batch(get_multi_experiment_default_batch()[:1],
                               parallel=False, max_workers=1)

        # 每 experiment 的 critic_verdict 应有 llm_review
        for r in batch.experiment_results:
            if r.critic_verdict is not None:
                # CriticOutput.llm_review 应填
                # critic_verdict.cross_robot 来自 critic_engine,不是 CriticOutput
                # CriticOutput 在 artifacts 里 — 通过 _run_one 内 critic_resp.artifacts["verdict"]
                pass  # orchestrator 返回的 batch 不直接暴露 CriticOutput.llm_review
        # 至少 batch 跑通
        assert batch.n_total == 1
        # mock client 至少被调过一次
        assert client.chat.completions.create.called

    def test_orchestrator_critic_disabled_no_llm(self):
        """默认 critic(enable_llm_review=False)→ 不调 LLM"""
        from agents.mat_orchestrator import MatOrchestrator
        from agents.mat_critic_agent import MatCriticAgent, LLMReviewer

        client = _mock_client(content="OK")
        reviewer = LLMReviewer(api_key="k", enabled=True, client=client)
        # 显式 critic 但 enable_llm_review=False
        custom_critic = MatCriticAgent(enable_llm_review=False, llm_reviewer=reviewer)
        orch = MatOrchestrator(critic_agent=custom_critic)

        from agents.mat_orchestrator import get_multi_experiment_default_batch
        batch = orch.run_batch(get_multi_experiment_default_batch()[:1],
                               parallel=False, max_workers=1)
        # client 没被调
        assert not client.chat.completions.create.called
        assert batch.n_total == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])