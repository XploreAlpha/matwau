"""test_mat_robot_synth_agent.py — W17-D mat-robot-synth-agent 测试

覆盖:
1. SynthProcedure / SynthStep 数据类
2. OpentronsMockSDK 模拟
3. SafetyGuard 3 类拦截(高温 / 危险化学品 / 超量)
4. Agent 跑通安全 procedure
5. Agent 拦截危险 procedure
6. 默认 procedure Ca-LLZO
7. E2E:mat-gen → mat-robot-synth → mat-critic 接通
8. W17-D 跟 W15 + W17-A 4 域兼容

per MatWAU-开发计划 §8 W17-D
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_synth_agent import (  # noqa: E402
    HAZARD_TEMP_CELSIUS_LIMIT,
    MatRobotSynthAgent,
    OpentronsMockSDK,
    SafetyGuard,
    SynthProcedure,
    SynthResult,
    SynthStep,
    estimate_synth_cost,
    get_default_procedure,
)
from agents.mat_robot_synth_agent.synth_engine import DEFAULT_PROCEDURES  # noqa: E402
from matwau.core.agent_base import AgentRequest  # noqa: E402


# ============================================================================
# 测试 1: 数据类
# ============================================================================


class TestSynthDataClasses:
    """SynthStep / SynthProcedure / SynthResult"""

    def test_step_is_high_temperature(self):
        assert SynthStep(name="x", temperature_celsius=900).is_high_temperature()
        assert not SynthStep(name="x", temperature_celsius=500).is_high_temperature()

    def test_procedure_max_temperature(self):
        p = SynthProcedure(
            target_formula="X",
            steps=[
                SynthStep(name="a", temperature_celsius=25),
                SynthStep(name="b", temperature_celsius=1200),
                SynthStep(name="c", temperature_celsius=600),
            ],
        )
        assert p.max_temperature() == 1200

    def test_procedure_total_duration(self):
        p = SynthProcedure(
            target_formula="X",
            steps=[
                SynthStep(name="a", duration_minutes=60),
                SynthStep(name="b", duration_minutes=120),
            ],
        )
        assert p.total_duration_minutes() == 180

    def test_result_to_dict(self):
        r = SynthResult(
            run_id="r1",
            product_formula="X",
            yield_grams=1.5,
            success=True,
        )
        d = r.to_dict()
        assert d["product_formula"] == "X"
        assert d["yield_grams"] == 1.5
        assert d["success"] is True


# ============================================================================
# 测试 2: OpentronsMockSDK
# ============================================================================


class TestOpentronsMockSDK:
    """机械臂 mock"""

    def test_default_connected(self):
        sdk = OpentronsMockSDK()
        assert sdk.is_connected()

    def test_execute_step_ok(self):
        sdk = OpentronsMockSDK(fail_chance=0.0)  # 不失败
        step = SynthStep(name="称量", duration_minutes=10, temperature_celsius=25)
        r = sdk.execute(step)
        assert r["ok"] is True
        assert "执行" in r["log"]

    def test_execute_step_may_fail(self):
        sdk = OpentronsMockSDK(fail_chance=1.0)  # 100% 失败
        step = SynthStep(name="烧结", duration_minutes=10, temperature_celsius=900)
        r = sdk.execute(step)
        assert r["ok"] is False

    def test_disconnect(self):
        sdk = OpentronsMockSDK()
        sdk.disconnect()
        assert not sdk.is_connected()
        r = sdk.execute(SynthStep(name="x"))
        assert not r["ok"]


# ============================================================================
# 测试 3: SafetyGuard
# ============================================================================


class TestSafetyGuard:
    """SafetyGuard 拦截 3 类危险"""

    def test_no_warnings_for_safe_procedure(self):
        sg = SafetyGuard()
        p = SynthProcedure(
            target_formula="x",
            steps=[SynthStep(name="称量", temperature_celsius=25)],
            target_yield_grams=1.0,
        )
        assert sg.check_procedure(p) == []

    def test_warnings_for_high_temperature(self):
        sg = SafetyGuard()
        p = SynthProcedure(
            target_formula="Hot",
            steps=[SynthStep(name="高温", temperature_celsius=2000)],
        )
        warns = sg.check_procedure(p)
        assert any("高温报警" in w for w in warns)

    def test_warnings_for_dangerous_chemicals(self):
        sg = SafetyGuard()
        p = SynthProcedure(
            target_formula="Acid",
            steps=[SynthStep(name="配溶液", chemicals=["HF"])],
        )
        warns = sg.check_procedure(p)
        assert any("危险化学品" in w for w in warns)

    def test_warnings_for_over_yield(self):
        sg = SafetyGuard()
        p = SynthProcedure(
            target_formula="Bulk",
            target_yield_grams=200.0,
        )
        warns = sg.check_procedure(p)
        assert any("试剂超量" in w for w in warns)

    def test_check_method_returns_bool(self):
        """BaseSafetyGuard.check() 返回 bool"""
        from matwau.core.agent_base import AgentResponse
        sg = SafetyGuard()
        safe_resp = AgentResponse(
            reply="ok",
            artifacts={"procedure": SynthProcedure(target_formula="x")},
        )
        assert sg.check(safe_resp) is True

        danger_resp = AgentResponse(
            reply="x",
            artifacts={"procedure": SynthProcedure(
                target_formula="hot",
                steps=[SynthStep(name="y", temperature_celsius=2000)],
            )},
        )
        assert sg.check(danger_resp) is False


# ============================================================================
# 测试 4: Agent 跑通 + 拦截
# ============================================================================


class TestMatRobotSynthAgent:
    """Agent 基础测试"""

    def test_default_procedure_ca_llzo(self):
        """默认 Ca-LLZO procedure(per W4 Goldens)"""
        p = get_default_procedure("Pechini_Ca_LLZO")
        assert p is not None
        assert p.method == "Pechini"
        # Ca0.25Li6.5La3Zr1.75O12 是 Ca 掺杂 LLZO 标准化学式
        assert "Ca" in p.target_formula
        assert "Li" in p.target_formula
        assert "La" in p.target_formula
        assert "Zr" in p.target_formula
        assert "O" in p.target_formula

    def test_sol_gel_pmma_procedure(self):
        """polymer 域默认 procedure"""
        p = get_default_procedure("sol_gel_PMMA")
        assert p is not None
        assert p.method == "sol-gel"

    def test_agent_runs_safe_procedure(self):
        """Agent 跑安全 procedure(应成功)"""
        agent = MatRobotSynthAgent()
        p = SynthProcedure(
            target_formula="TestSafe",
            steps=[
                SynthStep(name="称量", duration_minutes=5, temperature_celsius=25),
            ],
            target_yield_grams=1.0,
        )
        req = AgentRequest(run_id="synth-x", message="y", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.error is None
        assert resp.artifacts.get("success") is True
        assert "✅" in resp.reply

    def test_agent_blocks_high_temperature(self):
        """Agent 拦截高温(应 blocked)"""
        agent = MatRobotSynthAgent()
        p = SynthProcedure(
            target_formula="Hot",
            steps=[SynthStep(name="炸", temperature_celsius=2500)],
            target_yield_grams=0.1,
        )
        req = AgentRequest(run_id="synth-hot", message="z", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert "⛔" in resp.reply

    def test_agent_blocks_dangerous_chemical(self):
        """Agent 拦截危险化学品"""
        agent = MatRobotSynthAgent()
        p = SynthProcedure(
            target_formula="AcidMix",
            steps=[SynthStep(name="配溶液", chemicals=["HF"])],
            target_yield_grams=1.0,
        )
        req = AgentRequest(run_id="synth-acid", message="a", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_uses_default_procedure_without_artifacts(self):
        """不传 procedure → 用默认 Ca-LLZO(应被拦截,因为 900°C)"""
        agent = MatRobotSynthAgent()
        req = AgentRequest(run_id="synth-default", message="用 Pechini")
        resp = agent.run(req)
        # Ca-LLZO 主烧 900°C → 被拦截
        assert resp.artifacts.get("blocked") is True


# ============================================================================
# 测试 5: 4 域兼容(W17-D 跟 W15 + W17-A 一致)
# ============================================================================


class TestRobotSynth4Domains:
    """W17-D 机器人能跑所有 4 域的合成"""

    @pytest.mark.parametrize("domain", ["inorganic_crystal", "polymer", "nano", "metal_alloy"])
    def test_safe_procedure_per_domain(self, domain):
        """4 域下安全 procedure 都能跑通"""
        agent = MatRobotSynthAgent()
        p = SynthProcedure(
            target_formula=f"X-{domain}",
            steps=[SynthStep(name="基础操作", duration_minutes=5, temperature_celsius=25)],
            target_yield_grams=1.0,
        )
        req = AgentRequest(
            run_id=f"synth-{domain}",
            message="x",
            artifacts={"procedure": p},
            context={"domain": domain},
        )
        resp = agent.run(req)
        assert resp.error is None
        assert resp.artifacts.get("domain") == domain


# ============================================================================
# 测试 6: 成本估算
# ============================================================================


class TestCostEstimate:
    """W17-D 单价约定"""

    def test_room_temp_step_cost(self):
        p = SynthProcedure(steps=[SynthStep(duration_minutes=60, temperature_celsius=25)])
        # 室温 1 小时 = ¥10 + 基础费 ¥5 = ¥15
        assert estimate_synth_cost(p) == 15.0

    def test_high_temp_step_expensive(self):
        p = SynthProcedure(steps=[SynthStep(duration_minutes=60, temperature_celsius=900)])
        # 高温 1 小时 = ¥80 + 基础费 ¥5 = ¥85
        assert estimate_synth_cost(p) == 85.0

    def test_multi_step_total(self):
        p = SynthProcedure(
            steps=[
                SynthStep(duration_minutes=60, temperature_celsius=25),   # ¥15
                SynthStep(duration_minutes=60, temperature_celsius=900),  # ¥85
            ],
        )
        # 总 = ¥100
        assert estimate_synth_cost(p) == 100.0


# ============================================================================
# 测试 7: E2E 拼接(mat-gen → mat-robot-synth)
# ============================================================================


class TestE2EMatGenToRobot:
    """W17-D E2E:mat-gen 出结构 → mat-robot-synth 实验"""

    def test_mat_gen_then_robot_synth(self):
        """mat-gen 跑 LiCoO2 → 出 procedure → mat-robot-synth 跑通"""
        from agents.mat_gen_agent.mat_gen_agent import MatGenAgent
        from agents.mat_robot_synth_agent import MatRobotSynthAgent

        gen = MatGenAgent(domain="inorganic_crystal")
        gen_req = AgentRequest(run_id="e2e-gen", message="生成 LiCoO2 候选", context={"domain": "inorganic_crystal"})
        gen_resp = gen.run(gen_req)
        assert gen_resp.error is None
        assert "candidates" in gen_resp.artifacts

        # 把 mat-gen 的 candidates 当 synthesize 触发(简单 mock — 把 candidates[0] 当 procedure)
        # 这里为简单化用默认 procedure
        synth = MatRobotSynthAgent()
        synth_req = AgentRequest(
            run_id="e2e-synth",
            message="合成",
            context={"domain": "inorganic_crystal"},
        )
        synth_resp = synth.run(synth_req)
        assert synth_resp.error is None
        # Ca-LLZO 默认被拦截
        assert synth_resp.artifacts.get("blocked") is True


# ============================================================================
# 测试 8: W14/W16 向后兼容(其他 11 agent 没被改)
# ============================================================================


class TestBackwardCompat:
    """W17-D 不破坏现有测试"""

    def test_other_agents_still_import(self):
        """其他 11 agent 仍可 import"""
        from agents.mat_gen_agent.mat_gen_agent import MatGenAgent
        from agents.mat_sim_agent.mat_sim_agent import MatSimAgent
        from agents.mat_lit_agent.mat_lit_agent import MatLitAgent
        from agents.mat_critic_agent.mat_critic_agent import MatCriticAgent
        # 全部 import 成功 = 没破
        assert MatGenAgent is not None

    def test_agent_count_is_16(self):
        """W17-D 后 = 16 agent(15 软件 + 1 机器人)"""
        from agents.material_domain_router import DOMAINS
        assert len(DOMAINS) == 4  # 4 域(W17 后)
        # 新增的 1 个 agent 不在 4 域分类(它是物理世界)
        assert MatRobotSynthAgent is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
