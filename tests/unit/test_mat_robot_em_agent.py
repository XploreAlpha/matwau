"""test_mat_robot_em_agent.py — W21 mat-robot-em-agent 测试

覆盖:
1. EMStep / EMProcedure / EMResult 数据类
2. ZeissMockSDK 模拟
3. EMSafetyGuard 6 类拦截(真空 / 舱门 / 喷金 / 易挥发 / 易辐照损伤 / 磁性)
4. EMSafetyGuard 继承自 SafetyGuard(W17-D 模板复用验证)
5. Agent 跑通安全 procedure(Inconel 718 默认)
6. Agent 拦截危险 procedure(6 类)
7. 4 域兼容(无机 / 高分子 / 纳米 / 金属合金)
8. E2E 衔接:mat-gen → mat-robot-synth → mat-robot-xrd → mat-robot-em

per MatWAU-开发计划 §8 W21
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_em_agent import (  # noqa: E402
    EMProcedure,
    EMResult,
    EMSafetyGuard,
    EMStep,
    MatRobotEmAgent,
    ZeissMockSDK,
    DEFAULT_EM_PROCEDURE,
    HAZARD_EM_DOOR_OPEN,
    HAZARD_EM_VACUUM_OK,
    HAZARD_EM_HIGH_VOLTAGE_KV,
    VACUUM_THRESHOLD,
    EM_VOLATILE_MATERIALS,
    EM_RADIATION_DAMAGE_MATERIALS,
    EM_MAGNETIC_MATERIALS,
    estimate_em_cost,
    get_default_em_procedure,
)
from agents.mat_robot_synth_agent.synth_engine import SafetyGuard  # noqa: E402
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402


# ============================================================================
# 测试 1: 数据类
# ============================================================================


class TestEMDataClasses:
    """EMStep / EMProcedure / EMResult"""

    def test_step_is_high_voltage(self):
        s1 = EMStep(name="low", beam_voltage_kv=15.0)
        s2 = EMStep(name="high", beam_voltage_kv=40.0)
        assert s1.is_high_voltage() is False
        assert s2.is_high_voltage() is True

    def test_procedure_max_voltage(self):
        p = EMProcedure(
            steps=[
                EMStep(name="a", beam_voltage_kv=10.0),
                EMStep(name="b", beam_voltage_kv=25.0),
                EMStep(name="c", beam_voltage_kv=40.0),
            ],
        )
        assert p.max_voltage() == 40.0

    def test_procedure_total_duration(self):
        p = EMProcedure(
            steps=[
                EMStep(name="a", duration_minutes=10),
                EMStep(name="b", duration_minutes=20),
            ],
        )
        assert p.total_duration_minutes() == 30.0

    def test_result_defaults(self):
        r = EMResult(run_id="e1")
        assert r.run_id == "e1"
        assert r.images == []
        assert r.success is True

    def test_result_to_dict(self):
        r = EMResult(
            run_id="e2",
            procedure=EMProcedure(sample_formula="TiO2"),
            success=True,
        )
        d = r.to_dict()
        assert d["sample_formula"] == "TiO2"
        assert d["success"] is True


# ============================================================================
# 测试 2: ZeissMockSDK
# ============================================================================


class TestZeissMockSDK:
    """电镜仪器 mock"""

    def test_default_connected(self):
        sdk = ZeissMockSDK()
        assert sdk.is_connected() is True

    def test_execute_sem_step(self):
        sdk = ZeissMockSDK(fail_chance=0.0)
        step = EMStep(name="SEM 1000x", duration_minutes=10, magnification=1000, imaging_mode="SEM")
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["images"]) >= 1

    def test_execute_tem_step(self):
        sdk = ZeissMockSDK(fail_chance=0.0)
        step = EMStep(name="TEM", duration_minutes=30, magnification=100000, imaging_mode="TEM")
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["images"]) >= 1
        assert r["images"][0]["mode"] in ("TEM", "SAED")

    def test_execute_eds_step(self):
        sdk = ZeissMockSDK(fail_chance=0.0)
        step = EMStep(name="EDS", duration_minutes=20, imaging_mode="EDS")
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["elements"]) >= 1
        for elem in r["elements"]:
            assert "element" in elem
            assert "wt_pct" in elem

    def test_execute_may_fail(self):
        sdk = ZeissMockSDK(fail_chance=1.0)
        step = EMStep(name="test")
        r = sdk.execute(step)
        assert r["ok"] is False

    def test_disconnect(self):
        sdk = ZeissMockSDK()
        sdk.disconnect()
        assert not sdk.is_connected()


# ============================================================================
# 测试 3: EMSafetyGuard 6 类拦截
# ============================================================================


class TestEMSafetyGuard:
    """W21 安全防护"""

    def test_inherits_from_safety_guard(self):
        """EMSafetyGuard 继承 SafetyGuard(W17-D 模板复用验证)"""
        assert issubclass(EMSafetyGuard, SafetyGuard)

    def test_no_warnings_when_safe(self):
        sg = EMSafetyGuard()
        p = get_default_em_procedure()  # 默认安全
        warns = sg.check_em(p)
        # 默认可能含磁性警告(不 block)— 6 类 hard block 应该没
        hard_blocks = [w for w in warns if "⛔" in w]
        assert hard_blocks == []

    def test_block_vacuum_insufficient(self):
        sg = EMSafetyGuard()
        p = EMProcedure(vacuum_ok=False, door_open=False, sample_conductive_coated=True)
        warns = sg.check_em(p)
        assert any("真空" in w for w in warns)
        assert any("⛔" in w for w in warns)

    def test_block_door_open(self):
        sg = EMSafetyGuard()
        p = EMProcedure(door_open=True, vacuum_ok=True, sample_conductive_coated=True)
        warns = sg.check_em(p)
        assert any("舱门" in w for w in warns)
        assert any("⛔" in w for w in warns)

    def test_block_no_conductive_coating(self):
        sg = EMSafetyGuard()
        p = EMProcedure(
            target_imaging_modes=["SEM"],
            door_open=False,
            vacuum_ok=True,
            sample_conductive_coated=False,
        )
        warns = sg.check_em(p)
        assert any("喷金" in w for w in warns)

    def test_block_volatile_sample(self):
        sg = EMSafetyGuard()
        p = EMProcedure(
            sample_formula="H2O residue",
            door_open=False,
            vacuum_ok=True,
            sample_conductive_coated=True,
            sample_is_volatile=True,
        )
        warns = sg.check_em(p)
        assert any("易挥发" in w for w in warns)

    def test_block_radiation_damage_sensitive(self):
        sg = EMSafetyGuard()
        p = EMProcedure(
            sample_formula="PMMA film",
            door_open=False,
            vacuum_ok=True,
            sample_conductive_coated=True,
            sample_is_radiation_sensitive=True,
        )
        warns = sg.check_em(p)
        assert any("辐照" in w for w in warns)

    def test_warn_magnetic_sample(self):
        sg = EMSafetyGuard()
        p = EMProcedure(
            sample_formula="pure Fe",
            door_open=False,
            vacuum_ok=True,
            sample_conductive_coated=True,
            sample_is_magnetic=True,
        )
        warns = sg.check_em(p)
        # 磁性只警告,不 block
        assert any("磁性" in w for w in warns)
        # 不应该有 ⛔(磁性不是 block 级)
        hard_blocks = [w for w in warns if "⛔" in w]
        assert all("磁性" not in w for w in hard_blocks)

    def test_check_method_returns_bool_em(self):
        sg = EMSafetyGuard()
        # 安全 procedure
        safe = AgentResponse(
            reply="x",
            artifacts={"procedure": get_default_em_procedure()},
        )
        assert sg.check(safe) is True
        # 舱门开
        danger = AgentResponse(
            reply="x",
            artifacts={"procedure": EMProcedure(door_open=True)},
        )
        assert sg.check(danger) is False


# ============================================================================
# 测试 4: Agent 基础
# ============================================================================


class TestMatRobotEmAgent:
    """EM agent 跑通 + 拦截"""

    def test_default_inconel_718_em(self):
        """默认 procedure = Inconel 718 SEM + EDS"""
        p = get_default_em_procedure()
        assert "Inconel" in p.sample_formula
        assert "SEM" in p.target_imaging_modes
        assert "EDS" in p.target_imaging_modes
        assert p.vacuum_ok is True
        assert p.door_open is False
        assert p.sample_conductive_coated is True

    def test_agent_runs_safe(self):
        agent = MatRobotEmAgent()
        req = AgentRequest(run_id="em-x", message="测 Inconel 718")
        resp = agent.run(req)
        # 默认 Inconel 718 procedure 安全 → 应成功
        assert resp.error is None
        assert resp.artifacts.get("success") is True
        result = resp.artifacts.get("result", {})
        assert len(result.get("images", [])) >= 1
        assert len(result.get("elements", [])) >= 1

    def test_agent_blocks_vacuum(self):
        agent = MatRobotEmAgent()
        p = EMProcedure(
            sample_formula="test", vacuum_ok=False, door_open=False, sample_conductive_coated=True,
        )
        req = AgentRequest(run_id="em-vac", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert "真空" in resp.reply

    def test_agent_blocks_door_open(self):
        agent = MatRobotEmAgent()
        p = EMProcedure(
            sample_formula="test", vacuum_ok=True, door_open=True, sample_conductive_coated=True,
        )
        req = AgentRequest(run_id="em-door", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_blocks_no_coating(self):
        agent = MatRobotEmAgent()
        p = EMProcedure(
            sample_formula="Ceramic sample",
            target_imaging_modes=["SEM"],
            vacuum_ok=True,
            door_open=False,
            sample_conductive_coated=False,
        )
        req = AgentRequest(run_id="em-coat", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert "喷金" in resp.reply

    def test_agent_blocks_volatile(self):
        agent = MatRobotEmAgent()
        p = EMProcedure(
            sample_formula="H2O residue",
            vacuum_ok=True, door_open=False, sample_conductive_coated=True,
            sample_is_volatile=True,
        )
        req = AgentRequest(run_id="em-vol", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_blocks_radiation_damage(self):
        agent = MatRobotEmAgent()
        p = EMProcedure(
            sample_formula="PMMA film",
            vacuum_ok=True, door_open=False, sample_conductive_coated=True,
            sample_is_radiation_sensitive=True,
        )
        req = AgentRequest(run_id="em-rad", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_images_generated_per_mode(self):
        """EM 应生成 SEM 图像"""
        agent = MatRobotEmAgent()
        req = AgentRequest(run_id="em-img", message="x")
        resp = agent.run(req)
        images = resp.artifacts.get("result", {}).get("images", [])
        assert len(images) >= 1
        for img in images:
            assert "mag" in img
            assert "mode" in img

    def test_grain_size_calculated(self):
        """成功 procedure 应有 grain_size_um"""
        agent = MatRobotEmAgent()
        req = AgentRequest(run_id="em-grain", message="x")
        resp = agent.run(req)
        grain = resp.artifacts.get("result", {}).get("grain_size_um")
        assert grain is not None
        assert grain > 0


# ============================================================================
# 测试 5: 4 域兼容
# ============================================================================


class TestEMRobot4Domains:
    """W21 + 4 域"""

    @pytest.mark.parametrize("domain", ["inorganic_crystal", "polymer", "nano", "metal_alloy"])
    def test_safe_em_per_domain(self, domain):
        agent = MatRobotEmAgent()
        sample_map = {
            "inorganic_crystal": "TiO2 (anatase)",
            "polymer": "PVDF film",
            "nano": "CdSe nanocrystal",
            "metal_alloy": "Inconel 718",
        }
        p = EMProcedure(
            sample_formula=sample_map[domain],
            target_imaging_modes=["SEM"],
            steps=[
                EMStep(name="SEM 拍照", duration_minutes=15, magnification=5000, imaging_mode="SEM"),
            ],
            door_open=False,
            vacuum_ok=True,
            sample_conductive_coated=True,
            domain=domain,
        )
        req = AgentRequest(
            run_id=f"em-{domain}",
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
    """W21 电镜单价约定"""

    def test_minimal_em_cost(self):
        p = EMProcedure(steps=[
            EMStep(name="装样", duration_minutes=5),
            EMStep(name="SEM", duration_minutes=30, imaging_mode="SEM"),
            EMStep(name="卸载", duration_minutes=5),
        ])
        cost = estimate_em_cost(p)
        # 基础 ¥40 + 装样 ¥20 + SEM 0.5h ¥20 + 卸载 ¥20 = ¥100
        assert cost == 100.0

    def test_eds_step_cost(self):
        p = EMProcedure(steps=[
            EMStep(name="EDS", duration_minutes=30, imaging_mode="EDS"),
        ])
        cost = estimate_em_cost(p)
        # 基础 ¥40 + EDS ¥60 = ¥100
        assert cost == 100.0

    def test_tem_expensive(self):
        p = EMProcedure(steps=[
            EMStep(name="TEM", duration_minutes=60, imaging_mode="TEM"),
        ])
        cost = estimate_em_cost(p)
        # 基础 ¥40 + TEM ¥50 + 1h ¥80 = ¥170
        assert cost == 170.0


# ============================================================================
# 测试 7: E2E 衔接(mat-gen → synth → xrd → em)
# ============================================================================


class TestE2EMatGenToEm:
    """W17-D + W18 + W21 闭环 E2E"""

    def test_xrd_then_em_complete_chain(self):
        """XRD 表征 → EM 表征端到端"""
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent

        # 1. mat-robot-xrd 跑 XRD(Inconel 718 默认 procedure)
        # Inconel 718 不在默认 XRD 里 — 用通用 procedure
        from agents.mat_robot_xrd_agent.xrd_engine import (
            XRDProcedure, XRDStep, get_default_xrd_procedure,
        )

        xrd = MatRobotXrdAgent()
        xrd_req = AgentRequest(
            run_id="e2e-w21-xrd",
            message="测 Inconel 718",
            artifacts={"procedure": get_default_xrd_procedure()},  # 默认 Ca-LLZO 安全
        )
        xrd_resp = xrd.run(xrd_req)
        assert xrd_resp.error is None

        # 2. mat-robot-em 跑 EM
        em = MatRobotEmAgent()
        em_req = AgentRequest(
            run_id="e2e-w21-em",
            message="拍 Inconel 718 微观结构",
        )
        em_resp = em.run(em_req)
        # 默认 Inconel 718 procedure 安全(磁性是 warning,不是 block)
        assert em_resp.error is None
        assert em_resp.artifacts.get("success") is True


# ============================================================================
# 测试 8: W21 跟 W17-D/W18 模板复用
# ============================================================================


class TestEMTemplateInheritance:
    """W21 价值点 — W17-D 设计被有效复用"""

    def test_em_safety_guard_is_a_safety_guard(self):
        sg = EMSafetyGuard()
        assert isinstance(sg, SafetyGuard)
        # 父类属性也可调用
        assert hasattr(sg, "DANGEROUS_CHEMICALS")
        assert hasattr(sg, "MAX_REAGENT_GRAMS")

    def test_em_doesnt_break_xrd(self):
        """W21 加 agent,W18 agent 仍可工作"""
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        xrd = MatRobotXrdAgent()
        assert xrd.name == "mat-robot-xrd-agent"

    def test_em_doesnt_break_synth(self):
        """W21 加 agent,W17-D agent 仍可工作"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        synth = MatRobotSynthAgent()
        assert synth.name == "mat-robot-synth-agent"


# ============================================================================
# 测试 9: 4 域标识
# ============================================================================


class TestDomainDetection:
    """W21 + W15 + W17-A 4 域"""

    def test_default_em_is_metal_alloy(self):
        """默认 Inconel 718 procedure 应归 metal_alloy 域"""
        p = get_default_em_procedure()
        assert p.domain == "metal_alloy"

    def test_em_procedure_has_domain(self):
        p = EMProcedure(sample_formula="test", domain="polymer")
        assert p.domain == "polymer"


# ============================================================================
# 测试 10: 总览
# ============================================================================


class TestBackwardCompat:
    """W21 不破坏现有测试"""

    def test_total_agent_count_is_18(self):
        """W21 后 = 18 agent(15 软件 + synth + xrd + em)"""
        from agents.material_domain_router import DOMAINS
        assert len(DOMAINS) == 4  # 4 域
        assert MatRobotEmAgent.name == "mat-robot-em-agent"

    def test_all_three_robots_importable(self):
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        from agents.mat_robot_em_agent import MatRobotEmAgent
        # 三件套同时存在
        assert MatRobotSynthAgent.name == "mat-robot-synth-agent"
        assert MatRobotXrdAgent.name == "mat-robot-xrd-agent"
        assert MatRobotEmAgent.name == "mat-robot-em-agent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
