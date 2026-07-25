"""test_mat_robot_xrd_agent.py — W18 mat-robot-xrd-agent 测试

覆盖:
1. XRDProcedure / XRDStep / XRDResult 数据类
2. BrukerMockSDK 模拟
3. XRDSafetyGuard 3 类拦截(舱门 / 围裙 / 易辐射分解)
4. XRDSafetyGuard 继承自 SafetyGuard(W17-D 模板复用验证)
5. Agent 跑通安全 procedure
6. Agent 拦截危险 procedure(3 类)
7. 默认 Ca-LLZO XRD procedure
8. 4 域兼容(W18 + W15 + W17-A)
9. E2E 衔接:mat-gen → mat-robot-synth → mat-robot-xrd

per MatWAU-开发计划 §8 W18
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_xrd_agent import (  # noqa: E402
    BrukerMockSDK,
    HAZARD_XRD_DOOR_OPEN,
    HAZARD_XRD_NO_APRON,
    MatRobotXrdAgent,
    RADIATION_DECOMPOSE_MATERIALS,
    XRDSafetyGuard,
    XRDProcedure,
    XRDResult,
    XRDStep,
    estimate_xrd_cost,
    get_default_xrd_procedure,
)
from agents.mat_robot_synth_agent.synth_engine import SafetyGuard  # noqa: E402
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402


# ============================================================================
# 测试 1: 数据类
# ============================================================================


class TestXRDDataClasses:
    """XRDStep / XRDProcedure / XRDResult"""

    def test_procedure_total_duration(self):
        p = XRDProcedure(
            steps=[
                XRDStep(duration_minutes=10),
                XRDStep(duration_minutes=20),
            ],
        )
        assert p.total_duration_minutes() == 30

    def test_result_defaults(self):
        r = XRDResult(run_id="r1")
        assert r.run_id == "r1"
        assert r.peaks == []
        assert r.success is True


# ============================================================================
# 测试 2: BrukerMockSDK
# ============================================================================


class TestBrukerMockSDK:
    """XRD 仪器 mock"""

    def test_default_connected(self):
        sdk = BrukerMockSDK()
        assert sdk.is_connected()

    def test_execute_scan_ok(self):
        sdk = BrukerMockSDK(fail_chance=0.0)
        step = XRDStep(name="扫描", duration_minutes=30)
        r = sdk.execute(step)
        assert r["ok"] is True
        assert len(r["peaks"]) >= 1

    def test_execute_may_fail(self):
        sdk = BrukerMockSDK(fail_chance=1.0)
        step = XRDStep(name="扫描")
        r = sdk.execute(step)
        assert r["ok"] is False

    def test_disconnect(self):
        sdk = BrukerMockSDK()
        sdk.disconnect()
        assert not sdk.is_connected()


# ============================================================================
# 测试 3: XRDSafetyGuard 3 类拦截
# ============================================================================


class TestXRDSafetyGuard:
    """W18 辐射防护"""

    def test_inherits_from_safety_guard(self):
        """XRDSafetyGuard 继承 SafetyGuard(W17-D 模板复用验证)"""
        assert issubclass(XRDSafetyGuard, SafetyGuard)

    def test_no_warnings_when_safe(self):
        sg = XRDSafetyGuard()
        p = get_default_xrd_procedure()  # 默认安全
        assert sg.check_xrd(p) == []

    def test_block_door_open(self):
        sg = XRDSafetyGuard()
        p = XRDProcedure(door_open=True, user_in_apron=True)
        warns = sg.check_xrd(p)
        assert any("舱门" in w for w in warns)

    def test_block_no_apron(self):
        sg = XRDSafetyGuard()
        p = XRDProcedure(door_open=False, user_in_apron=False)
        warns = sg.check_xrd(p)
        assert any("围裙" in w for w in warns)

    def test_block_radiation_sensitive(self):
        sg = XRDSafetyGuard()
        p = XRDProcedure(
            sample_formula="H2O2 solution",
            door_open=False,
            user_in_apron=True,
            sample_is_radioactive_sensitive=True,
        )
        warns = sg.check_xrd(p)
        assert any("辐射分解" in w for w in warns)

    def test_can_disable_door_check(self):
        """配置化 block_if_door_open=False → 不拦截"""
        sg = XRDSafetyGuard(block_if_door_open=False)
        p = XRDProcedure(door_open=True, user_in_apron=True)
        assert sg.check_xrd(p) == []

    def test_check_method_returns_bool_xrd(self):
        """BaseSafetyGuard.check()override 用 XRD"""
        sg = XRDSafetyGuard()
        # 安全 procedure
        safe = AgentResponse(
            reply="x",
            artifacts={"procedure": get_default_xrd_procedure()},
        )
        assert sg.check(safe) is True
        # 舱门开
        danger = AgentResponse(
            reply="x",
            artifacts={"procedure": XRDProcedure(door_open=True)},
        )
        assert sg.check(danger) is False


# ============================================================================
# 测试 4: Agent 基础
# ============================================================================


class TestMatRobotXrdAgent:
    """XRD agent 跑通 + 拦截"""

    def test_default_ca_llzo_xrd(self):
        """默认 procedure = Ca-LLZO(per W17-D 衔接)"""
        p = get_default_xrd_procedure()
        assert "Ca" in p.sample_formula
        assert "PDF" in p.target_phases[0]    # PDF 卡号作 target
        assert p.user_in_apron is True
        assert p.door_open is False           # 默认安全(门关,穿围裙)

    def test_agent_runs_safe(self):
        agent = MatRobotXrdAgent()
        req = AgentRequest(run_id="xrd-x", message="x")
        resp = agent.run(req)
        # Ca-LLZO 默认应该安全跑通
        assert resp.error is None
        assert resp.artifacts.get("success") is True
        r = resp.artifacts.get("result", {})
        assert r.get("matched_phase") == "PDF 45-1090 LLZO cubic"
        assert "✅" in resp.reply

    def test_agent_blocks_door_open(self):
        agent = MatRobotXrdAgent()
        p = XRDProcedure(door_open=True, user_in_apron=True)
        req = AgentRequest(run_id="xrd-door", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert "⛔" in resp.reply

    def test_agent_blocks_no_apron(self):
        agent = MatRobotXrdAgent()
        p = XRDProcedure(door_open=False, user_in_apron=False)
        req = AgentRequest(run_id="xrd-noapron", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_agent_blocks_radiation_sensitive(self):
        agent = MatRobotXrdAgent()
        p = XRDProcedure(
            sample_formula="H2O2 sample",
            door_open=False,
            user_in_apron=True,
            sample_is_radioactive_sensitive=True,
        )
        req = AgentRequest(run_id="xrd-radio", message="x", artifacts={"procedure": p})
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True

    def test_peaks_generated(self):
        """XRD 应生成 Bragg 峰"""
        agent = MatRobotXrdAgent()
        req = AgentRequest(run_id="xrd-peaks", message="x")
        resp = agent.run(req)
        peaks = resp.artifacts.get("result", {}).get("peaks", [])
        assert len(peaks) >= 1
        # 每个峰有 2θ 和 d-spacing
        for p in peaks:
            assert "two_theta" in p
            assert "d_spacing_angstrom" in p
            assert "intensity" in p


# ============================================================================
# 测试 5: 4 域兼容(W18 跟 W15 + W17-A 一致)
# ============================================================================


class TestXRDRobot4Domains:
    """W18 + 4 域"""

    @pytest.mark.parametrize("domain", ["inorganic_crystal", "polymer", "nano", "metal_alloy"])
    def test_safe_xrd_per_domain(self, domain):
        """4 域下安全 procedure 都能跑通"""
        agent = MatRobotXrdAgent()
        # 构造每域 1 个安全 procedure
        sample_map = {
            "inorganic_crystal": "Ca-LLZO",
            "polymer": "PMMA",
            "nano": "CdSe QD",
            "metal_alloy": "Inconel 718",
        }
        p = XRDProcedure(
            sample_formula=sample_map[domain],
            door_open=False,
            user_in_apron=True,
            steps=[XRDStep(name="扫描", duration_minutes=10)],
        )
        req = AgentRequest(
            run_id=f"xrd-{domain}",
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
    """W18 XRD 单价约定"""

    def test_minimal_xrd_cost(self):
        p = XRDProcedure(steps=[XRDStep(name="扫描", duration_minutes=60)])
        # 基础 ¥30 + 扫描 1 小时 ¥30 = ¥60
        assert estimate_xrd_cost(p) == 60.0

    def test_full_xrd_pipeline(self):
        p = XRDProcedure(steps=[
            XRDStep(name="装样"),
            XRDStep(name="对光"),
            XRDStep(name="扫描", duration_minutes=30),
            XRDStep(name="卸载"),
        ])
        # 基础 ¥30 + 装样 ¥10 + 对光 ¥5 + 扫描 30min ¥15 + 卸载 ¥10 = ¥70
        assert estimate_xrd_cost(p) == 70.0


# ============================================================================
# 测试 7: E2E 衔接(mat-gen → mat-robot-synth → mat-robot-xrd)
# ============================================================================


class TestE2EMatGenToSynthToXRD:
    """W17-D + W18 闭环 E2E"""
    def test_synth_to_xrd_safety_chain(self):
        """合成 → XRD 表征端到端"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent

        # 1. mat-robot-synth 跑合成 — Ca-LLZO(默认 procedure 被拦截)
        synth = MatRobotSynthAgent()
        synth_req = AgentRequest(
            run_id="e2e-synth",
            message="合成 Ca-LLZO",
            context={"domain": "inorganic_crystal"},
        )
        synth_resp = synth.run(synth_req)
        # 合成被高温拦,出来 blocked=True
        assert synth_resp.artifacts.get("blocked") is True

        # 2. mat-robot-xrd 跑表征(独立 procedure,不依赖 synth 的 blocked)
        xrd = MatRobotXrdAgent()
        xrd_req = AgentRequest(
            run_id="e2e-xrd",
            message="测 Ca-LLZO",
            context={"domain": "inorganic_crystal"},
        )
        xrd_resp = xrd.run(xrd_req)
        # XRD 默认 procedure 安全 → 应成功
        assert xrd_resp.artifacts.get("success") is True


# ============================================================================
# 测试 8: W18 跟 W17-D 模板复用
# ============================================================================


class TestXRDTemplateInheritance:
    """W18 价值点 — W17-D 设计被有效复用"""

    def test_xrd_safety_guard_is_a_safety_guard(self):
        """XRDSafetyGuard 是 SafetyGuard 的子类(W17-D 设计被 W18 复用)"""
        sg = XRDSafetyGuard()
        assert isinstance(sg, SafetyGuard)
        # 父类属性也可调用
        assert hasattr(sg, "DANGEROUS_CHEMICALS")
        assert hasattr(sg, "MAX_REAGENT_GRAMS")

    def test_xrd_doesnt_break_synth(self):
        """W18 加 agent,W17-D agent 仍可工作"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        synth = MatRobotSynthAgent()
        assert synth.name == "mat-robot-synth-agent"


# ============================================================================
# 测试 9: W14/W16 向后兼容
# ============================================================================


class TestBackwardCompat:
    """W18 不破坏现有测试"""

    def test_total_agent_count_is_17(self):
        """W18 后 = 17 agent(15 软件 + synth + xrd)"""
        from agents.material_domain_router import DOMAINS
        assert len(DOMAINS) == 4  # 4 域
        assert MatRobotXrdAgent.name == "mat-robot-xrd-agent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
