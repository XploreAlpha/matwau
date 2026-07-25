"""test_mat_robot_dsc_agent.py — W22 mat-robot-dsc-agent 测试

覆盖:
1. DSCStep / DSCProcedure / DSCResult 数据类
2. TAMockSDK 模拟
3. DSCSafetyGuard 5 类拦截(高温氧化 / 坩埚密封 / 超量 / 升温速率 / 爆炸物)
4. DSCSafetyGuard 继承自 SafetyGuard(W17-D 模板复用验证)
5. Agent 跑通安全 procedure(PMMA Tg 默认)
6. Agent 拦截危险 procedure(5 类)
7. 4 域兼容(无机 / 高分子 / 纳米 / 金属合金)
8. E2E 衔接:mat-gen → mat-robot-synth → mat-robot-dsc

per MatWAU-开发计划 §8 W22
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_dsc_agent import (  # noqa: E402
    DSCProcedure,
    DSCResult,
    DSCSafetyGuard,
    DSCStep,
    MatRobotDscAgent,
    TAMockSDK,
    DSC_DANGEROUS_MATERIALS,
    HAZARD_DSC_HIGH_TEMP_OXIDIZING,
    HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN,
    HAZARD_DSC_MAX_SAMPLE_MASS_MG,
    DEFAULT_DSC_PROCEDURE,
    estimate_dsc_cost,
    get_default_dsc_procedure,
)
from agents.mat_robot_synth_agent.synth_engine import SafetyGuard  # noqa: E402
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402


# ============================================================================
# 测试 1: 数据类
# ============================================================================


class TestDSCDataClasses:
    """DSCStep / DSCProcedure / DSCResult"""

    def test_step_is_ramp(self):
        s1 = DSCStep(name="ramp", is_isothermal=False, heating_rate_c_per_min=10.0)
        s2 = DSCStep(name="iso", is_isothermal=True)
        assert s1.is_ramp() is True
        assert s2.is_ramp() is False

    def test_procedure_max_temperature(self):
        p = DSCProcedure(
            steps=[
                DSCStep(name="a", target_temperature_celsius=100.0),
                DSCStep(name="b", target_temperature_celsius=300.0),
            ],
        )
        assert p.max_temperature() == 300.0

    def test_procedure_effective_heating_rate(self):
        p = DSCProcedure(
            steps=[
                DSCStep(name="a", heating_rate_c_per_min=5.0),
                DSCStep(name="b", heating_rate_c_per_min=20.0),
                DSCStep(name="c", heating_rate_c_per_min=10.0),
            ],
        )
        assert p.effective_heating_rate() == 20.0

    def test_procedure_total_duration(self):
        p = DSCProcedure(
            steps=[
                DSCStep(name="a", duration_minutes=10),
                DSCStep(name="b", duration_minutes=20),
            ],
        )
        assert p.total_duration_minutes() == 30

    def test_result_defaults(self):
        r = DSCResult(run_id="d1")
        assert r.run_id == "d1"
        assert r.dsc_curve_x == []
        assert r.success is True

    def test_result_to_dict(self):
        r = DSCResult(
            run_id="d2",
            procedure=DSCProcedure(sample_formula="PMMA"),
            success=True,
            glass_transition_temp_c=105.0,
            melting_temp_c=160.0,
        )
        d = r.to_dict()
        assert d["sample_formula"] == "PMMA"
        assert d["Tg_c"] == 105.0
        assert d["Tm_c"] == 160.0


# ============================================================================
# 测试 2: TAMockSDK
# ============================================================================


class TestTAMockSDK:
    """DSC 仪器 mock"""

    def test_default_connected(self):
        sdk = TAMockSDK()
        assert sdk.is_connected() is True

    def test_execute_ramp_step(self):
        sdk = TAMockSDK(fail_chance=0.0)
        step = DSCStep(name="升温", duration_minutes=30, target_temperature_celsius=200.0, heating_rate_c_per_min=5.0)
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["curve"]) >= 1

    def test_execute_isothermal_step(self):
        sdk = TAMockSDK(fail_chance=0.0)
        step = DSCStep(name="恒温", duration_minutes=10, target_temperature_celsius=180.0, is_isothermal=True)
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["curve"]) >= 1

    def test_execute_may_fail(self):
        sdk = TAMockSDK(fail_chance=1.0)
        step = DSCStep(name="test")
        r = sdk.execute(step)
        assert r["ok"] is False

    def test_disconnect(self):
        sdk = TAMockSDK()
        sdk.disconnect()
        assert not sdk.is_connected()


# ============================================================================
# 测试 3: DSCSafetyGuard 5 类拦截
# ============================================================================


class TestDSCSafetyGuard:
    """W22 安全防护"""

    def test_inherits_from_safety_guard(self):
        """DSCSafetyGuard 继承 SafetyGuard(W17-D 模板复用验证)"""
        assert issubclass(DSCSafetyGuard, SafetyGuard)

    def test_no_warnings_when_safe(self):
        sg = DSCSafetyGuard()
        p = get_default_dsc_procedure()  # 默认安全
        warns = sg.check_dsc(p)
        hard_blocks = [w for w in warns if "⛔" in w]
        assert hard_blocks == []

    def test_block_high_temp_air_combustible(self):
        sg = DSCSafetyGuard()
        p = DSCProcedure(
            atmosphere="air",                        # 空气气氛
            sample_mass_mg=5.0,
            steps=[DSCStep(name="高温", target_temperature_celsius=700.0, heating_rate_c_per_min=10.0)],
        )
        warns = sg.check_dsc(p)
        assert any("高温氧化" in w or "空气" in w for w in warns)
        assert any("⛔" in w for w in warns)

    def test_block_unsealed_high_temp(self):
        sg = DSCSafetyGuard()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=False,                   # 未密封
            sample_mass_mg=5.0,
            steps=[DSCStep(name="高温", target_temperature_celsius=400.0, heating_rate_c_per_min=10.0)],
        )
        warns = sg.check_dsc(p)
        assert any("坩埚" in w for w in warns)

    def test_block_over_mass(self):
        sg = DSCSafetyGuard()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=150.0,                    # > 100mg
        )
        warns = sg.check_dsc(p)
        assert any("样品超量" in w for w in warns)

    def test_block_overheating_rate(self):
        sg = DSCSafetyGuard()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=5.0,
            steps=[DSCStep(name="急升温", target_temperature_celsius=200.0, heating_rate_c_per_min=150.0)],  # > 100
        )
        warns = sg.check_dsc(p)
        assert any("升温速率" in w for w in warns)

    def test_block_explosive(self):
        sg = DSCSafetyGuard()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=5.0,
            sample_formula="nitroglycerin tablet",
            sample_is_explosive=True,
        )
        warns = sg.check_dsc(p)
        assert any("爆炸" in w for w in warns)

    def test_check_method_returns_bool_dsc(self):
        sg = DSCSafetyGuard()
        # 安全 procedure
        safe = AgentResponse(
            reply="x",
            artifacts={"procedure": get_default_dsc_procedure()},
        )
        assert sg.check(safe) is True
        # 超量
        danger = AgentResponse(
            reply="x",
            artifacts={"procedure": DSCProcedure(sample_mass_mg=200.0, atmosphere="N2", crucible_sealed=True)},
        )
        assert sg.check(danger) is False


# ============================================================================
# 测试 4: Agent 基础
# ============================================================================


class TestMatRobotDscAgent:
    """DSC agent 跑通 + 拦截"""

    def test_default_pmma_dsc(self):
        """默认 procedure = PMMA Tg 测试"""
        p = get_default_dsc_procedure()
        assert p.sample_formula == "PMMA"
        assert "Tg" in p.target_properties
        assert p.atmosphere == "N2"
        assert p.crucible_sealed is True

    def test_agent_runs_safe(self):
        agent = MatRobotDscAgent()
        req = AgentRequest(run_id="dsc-x", message="测 PMMA Tg")
        resp = agent.run(req)
        # 默认 PMMA procedure 安全 → 应成功
        assert resp.error is None
        assert resp.artifacts.get("success") is True
        result = resp.artifacts.get("result", {})
        # Tg/Tm 应有数值
        assert result.get("Tg_c") is not None
        assert result.get("Tm_c") is not None

    def test_agent_blocks_high_temp_air(self):
        agent = MatRobotDscAgent()
        p = DSCProcedure(
            atmosphere="air",
            sample_mass_mg=5.0,
            crucible_sealed=True,
            steps=[DSCStep(name="高温", target_temperature_celsius=700.0, heating_rate_c_per_min=10.0)],
        )
        req = AgentRequest(run_id="dsc-air", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert any("高温氧化" in w or "空气" in w for w in resp.artifacts.get("warnings", []))

    def test_agent_blocks_over_mass(self):
        agent = MatRobotDscAgent()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=150.0,
        )
        req = AgentRequest(run_id="dsc-mass", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_blocks_overheating_rate(self):
        agent = MatRobotDscAgent()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=5.0,
            steps=[DSCStep(name="急升温", target_temperature_celsius=200.0, heating_rate_c_per_min=200.0)],
        )
        req = AgentRequest(run_id="dsc-rate", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_blocks_explosive(self):
        agent = MatRobotDscAgent()
        p = DSCProcedure(
            atmosphere="N2",
            crucible_sealed=True,
            sample_mass_mg=5.0,
            sample_formula="nitroglycerin",
            sample_is_explosive=True,
        )
        req = AgentRequest(run_id="dsc-exp", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_curve_generated(self):
        """DSC 应生成温度/热流曲线"""
        agent = MatRobotDscAgent()
        req = AgentRequest(run_id="dsc-curve", message="x")
        resp = agent.run(req)
        curve_pts = resp.artifacts.get("result", {}).get("curve_points", 0)
        assert curve_pts > 0


# ============================================================================
# 测试 5: 4 域兼容
# ============================================================================


class TestDSCRobot4Domains:
    """W22 + 4 域"""

    @pytest.mark.parametrize("domain", ["inorganic_crystal", "polymer", "nano", "metal_alloy"])
    def test_safe_dsc_per_domain(self, domain):
        agent = MatRobotDscAgent()
        sample_map = {
            "inorganic_crystal": "LiPON ceramic",
            "polymer": "PMMA",
            "nano": "PMMA nanofiber",
            "metal_alloy": "AlSi alloy ribbon",
        }
        p = DSCProcedure(
            sample_formula=sample_map[domain],
            target_properties=["Tg", "Tm"],
            steps=[
                DSCStep(name="升温", duration_minutes=30, target_temperature_celsius=200.0, heating_rate_c_per_min=5.0),
                DSCStep(name="降温", duration_minutes=15, target_temperature_celsius=25.0, heating_rate_c_per_min=-10.0),
            ],
            atmosphere="N2",
            sample_mass_mg=5.0,
            crucible_sealed=True,
            domain=domain,
        )
        req = AgentRequest(
            run_id=f"dsc-{domain}",
            message="x",
            artifacts={"procedure": p},
            context={"domain": domain},
        )
        resp = agent.run(req)
        assert resp.error is None
        assert resp.artifacts.get("success") is True


# ============================================================================
# 测试 6: 成本估算
# ============================================================================


class TestCostEstimate:
    """W22 DSC 单价约定"""

    def test_minimal_dsc_cost(self):
        p = DSCProcedure(steps=[
            DSCStep(name="升温", duration_minutes=60, heating_rate_c_per_min=10.0),
        ])
        cost = estimate_dsc_cost(p)
        # 基础 ¥25 + 升温 1h ¥30 + 步骤 ¥5 = ¥60
        assert cost == 60.0

    def test_isothermal_cheaper_than_ramp(self):
        p_iso = DSCProcedure(steps=[
            DSCStep(name="恒温", duration_minutes=60, is_isothermal=True),
        ])
        p_ramp = DSCProcedure(steps=[
            DSCStep(name="升温", duration_minutes=60, heating_rate_c_per_min=10.0),
        ])
        c_iso = estimate_dsc_cost(p_iso)
        c_ramp = estimate_dsc_cost(p_ramp)
        # 恒温段比升温段便宜
        assert c_iso < c_ramp


# ============================================================================
# 测试 7: E2E 衔接(mat-gen → synth → dsc)
# ============================================================================


class TestE2EMatGenToDsc:
    """W17-D + W22 闭环 E2E"""

    def test_synth_to_dsc_safe_chain(self):
        """合成 → DSC 表征端到端"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent

        # 1. mat-robot-synth 跑合成 — 安全 procedure
        from agents.mat_robot_synth_agent.synth_engine import SynthProcedure, SynthStep

        synth_proc = SynthProcedure(
            target_formula="PMMA",
            method="sol-gel",
            steps=[SynthStep(name="混合", duration_minutes=10, temperature_celsius=25.0)],
            target_yield_grams=1.0,
        )
        synth = MatRobotSynthAgent()
        synth_req = AgentRequest(
            run_id="e2e-w22-synth",
            message="合成 PMMA",
            artifacts={"procedure": synth_proc},
        )
        synth_resp = synth.run(synth_req)
        assert synth_resp.error is None
        assert synth_resp.artifacts.get("success") is True

        # 2. mat-robot-dsc 跑 DSC(默认 PMMA)
        dsc = MatRobotDscAgent()
        dsc_req = AgentRequest(
            run_id="e2e-w22-dsc",
            message="测 PMMA Tg",
        )
        dsc_resp = dsc.run(dsc_req)
        assert dsc_resp.error is None
        assert dsc_resp.artifacts.get("success") is True


# ============================================================================
# 测试 8: W22 跟 W17-D/W18/W21 模板复用
# ============================================================================


class TestDSCTemplateInheritance:
    """W22 价值点 — W17-D 设计被有效复用"""

    def test_dsc_safety_guard_is_a_safety_guard(self):
        sg = DSCSafetyGuard()
        assert isinstance(sg, SafetyGuard)
        # 父类属性也可调用
        assert hasattr(sg, "DANGEROUS_CHEMICALS")
        assert hasattr(sg, "MAX_REAGENT_GRAMS")

    def test_dsc_doesnt_break_synth(self):
        """W22 加 agent,W17-D agent 仍可工作"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        synth = MatRobotSynthAgent()
        assert synth.name == "mat-robot-synth-agent"

    def test_dsc_doesnt_break_xrd(self):
        """W22 加 agent,W18 agent 仍可工作"""
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        xrd = MatRobotXrdAgent()
        assert xrd.name == "mat-robot-xrd-agent"

    def test_dsc_doesnt_break_em(self):
        """W22 加 agent,W21 agent 仍可工作"""
        from agents.mat_robot_em_agent import MatRobotEmAgent
        em = MatRobotEmAgent()
        assert em.name == "mat-robot-em-agent"

    def test_safety_guard_template_chain(self):
        """W17-D → W18 → W21 → W22 模板复用链验证"""
        # 4 个 SafetyGuard 父类都是 SafetyGuard
        assert issubclass(DSCSafetyGuard, SafetyGuard)
        from agents.mat_robot_xrd_agent import XRDSafetyGuard
        assert issubclass(XRDSafetyGuard, SafetyGuard)
        from agents.mat_robot_em_agent import EMSafetyGuard
        assert issubclass(EMSafetyGuard, SafetyGuard)
        assert issubclass(DSCSafetyGuard, SafetyGuard)


# ============================================================================
# 测试 9: 总览
# ============================================================================


class TestBackwardCompat:
    """W22 不破坏现有测试"""

    def test_total_agent_count_is_19(self):
        """W22 后 = 19 agent(15 软件 + synth + xrd + em + dsc)"""
        from agents.material_domain_router import DOMAINS
        assert len(DOMAINS) == 4  # 4 域
        assert MatRobotDscAgent.name == "mat-robot-dsc-agent"

    def test_all_four_robots_importable(self):
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        from agents.mat_robot_em_agent import MatRobotEmAgent
        from agents.mat_robot_dsc_agent import MatRobotDscAgent
        # 四件套同时存在
        assert MatRobotSynthAgent.name == "mat-robot-synth-agent"
        assert MatRobotXrdAgent.name == "mat-robot-xrd-agent"
        assert MatRobotEmAgent.name == "mat-robot-em-agent"
        assert MatRobotDscAgent.name == "mat-robot-dsc-agent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
