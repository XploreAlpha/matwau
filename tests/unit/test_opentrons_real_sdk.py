"""test_opentrons_real_sdk.py — W19 OpentronsRealSDK 测试

覆盖:
1. SDK 检测 is_opentrons_available()
2. OpentronsProtocolBuilder 协议生成
3. OpentronsRealSDK 双形态(real + mock)
4. 与 OpentronsMockSDK 100% 接口兼容
5. 真协议保存到文件
6. Stage 2 增量能力(sdk_mode property + generate_protocol)
7. E2E 衔接:mat-gen → MatRobotSynthAgent(用真 SDK)

per MatWAU-开发计划 W19
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_synth_agent.opentrons_real_sdk import (  # noqa: E402
    OpentronsProtocolBuilder,
    OpentronsRealSDK,
    is_opentrons_available,
)
from agents.mat_robot_synth_agent.synth_engine import (  # noqa: E402
    HAZARD_TEMP_CELSIUS_LIMIT,
    OpentronsMockSDK,
    SafetyGuard,
    SynthProcedure,
    SynthStep,
    get_default_procedure,
)
from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402


# ============================================================================
# 测试 1: SDK 检测
# ============================================================================


class TestSDKDetection:
    """opentrons 探测"""

    def test_opentrons_availability_returns_bool(self):
        """返回 True 或 False(永远不抛异常)"""
        result = is_opentrons_available()
        assert isinstance(result, bool)

    def test_sdk_constructor_never_crashes(self):
        """没装 opentrons 也应该能 new 出 SDK(降级)"""
        sdk = OpentronsRealSDK(lab_id="mat-test-01")
        assert sdk.is_connected() is True

    def test_sdk_mode_attribute_present(self):
        """sdk_mode 恒为 'real' 或 'mock'"""
        sdk = OpentronsRealSDK(lab_id="mat-test-02")
        assert sdk.sdk_mode in ("real", "mock")


# ============================================================================
# 测试 2: OpentronsProtocolBuilder 协议生成
# ============================================================================


class TestProtocolBuilder:
    """协议字符串生成(不依赖 opentrons pip)"""

    def test_build_returns_string(self):
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-001")
        assert isinstance(protocol_str, str)
        assert "def run(protocol):" in protocol_str

    def test_protocol_contains_target_formula(self):
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-002")
        assert proc.target_formula in protocol_str or "PMMA" in protocol_str

    def test_protocol_contains_steps(self):
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-003")
        for step in proc.steps:
            assert step.name in protocol_str

    def test_protocol_contains_pipette_load(self):
        builder = OpentronsProtocolBuilder(pipette_type="p20_single_gen2")
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-004")
        assert "p20_single_gen2" in protocol_str
        assert "load_instrument" in protocol_str

    def test_protocol_contains_labware_load(self):
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-005")
        assert "load_labware" in protocol_str

    def test_protocol_save_writes_file(self):
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
        ) as f:
            output_path = f.name
        try:
            returned_path = builder.save(proc, output_path, run_id="test-006")
            assert returned_path == output_path
            content = Path(output_path).read_text(encoding="utf-8")
            assert "def run(protocol):" in content
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_protocol_syntax_valid_python(self):
        """生成的 .py 应该是合法 Python(可 ast.parse)"""
        import ast
        builder = OpentronsProtocolBuilder()
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = builder.build(proc, run_id="test-007")
        try:
            ast.parse(protocol_str)
        except SyntaxError as e:
            pytest.fail(
                f"协议不是合法 Python! SyntaxError: {e}\n--- 协议 ---\n{protocol_str[:500]}"
            )

    def test_translate_transfer_step(self):
        """配液步骤应该翻译成 pipette.transfer()"""
        builder = OpentronsProtocolBuilder()
        proc = SynthProcedure(
            target_formula="test",
            steps=[SynthStep(name="配液", duration_minutes=10, chemicals=["water", "salt"])],
            target_yield_grams=1.0,
        )
        protocol_str = builder.build(proc, run_id="test-008")
        assert "pipette.transfer(" in protocol_str
        assert "water" in protocol_str or "salt" in protocol_str

    def test_translate_non_ot2_step(self):
        """球磨步骤应该走 protocol.comment + delay"""
        builder = OpentronsProtocolBuilder()
        proc = SynthProcedure(
            target_formula="test",
            steps=[SynthStep(name="球磨", duration_minutes=30, temperature_celsius=25.0)],
            target_yield_grams=1.0,
        )
        protocol_str = builder.build(proc, run_id="test-009")
        # 球磨不在 OT-2 操作范围 → 应该有 comment + delay
        assert "OT-2" in protocol_str or "protocol.comment" in protocol_str


# ============================================================================
# 测试 3: OpentronsRealSDK 双形态
# ============================================================================


class TestOpentronsRealSDK:
    """真接 SDK(优先真 opentrons;降级 mock)"""

    def test_sdk_has_execute_method(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-10")
        assert hasattr(sdk, "execute")
        assert callable(sdk.execute)

    def test_sdk_has_disconnect(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-11")
        sdk.disconnect()  # 不应抛异常

    def test_sdk_execute_returns_dict(self):
        """execute() 返回 dict(per Mock 接口)"""
        sdk = OpentronsRealSDK(lab_id="mat-test-12")
        step = SynthStep(name="称量", duration_minutes=5)
        result = sdk.execute(step)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "log" in result
        assert "yield" in result

    def test_sdk_records_command(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-13")
        step = SynthStep(name="烧结")
        sdk.execute(step)
        assert step.name in sdk.commands_executed

    def test_sdk_records_protocol(self):
        """真形态应该把生成的协议记录到 protocols_generated"""
        sdk = OpentronsRealSDK(lab_id="mat-test-14")
        step = SynthStep(name="烧结", duration_minutes=10, temperature_celsius=200)
        sdk.execute(step)
        # 真形态应有 protocols_generated >= 1,Mock 形态为 0
        if sdk.sdk_mode == "real":
            assert len(sdk.protocols_generated) >= 1
        else:
            assert len(sdk.protocols_generated) == 0

    def test_sdk_mode_reflects_opentrons_availability(self):
        """sdk_mode 应该跟 is_opentrons_available() 一致"""
        sdk = OpentronsRealSDK(lab_id="mat-test-15")
        if is_opentrons_available():
            assert sdk.sdk_mode == "real"
        else:
            assert sdk.sdk_mode == "mock"

    def test_prefer_real_false_always_mock(self):
        """prefer_real=False 应该强制 mock 模式"""
        sdk = OpentronsRealSDK(lab_id="mat-test-16", prefer_real=False)
        assert sdk.sdk_mode == "mock"
        assert len(sdk.protocols_generated) == 0

    def test_prefer_real_false_still_works(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-17", prefer_real=False)
        step = SynthStep(name="测温", duration_minutes=1)
        result = sdk.execute(step)
        assert result["ok"] is True

    def test_save_protocol_to_file(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-18")
        proc = get_default_procedure("sol_gel_PMMA")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
        ) as f:
            output_path = f.name
        try:
            returned = sdk.save_protocol(proc, output_path, run_id="real-test-18")
            assert returned == output_path
            content = Path(output_path).read_text(encoding="utf-8")
            assert "def run(protocol):" in content
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_generate_protocol_returns_str(self):
        sdk = OpentronsRealSDK(lab_id="mat-test-19")
        proc = get_default_procedure("sol_gel_PMMA")
        protocol_str = sdk.generate_protocol(proc, run_id="gen-test-19")
        assert isinstance(protocol_str, str)
        assert "def run(protocol):" in protocol_str


# ============================================================================
# 测试 4: 真协议应输出合法 Python(可以 ast.parse 走通)
# ============================================================================


class TestGeneratedProtocolIsValidPython:
    """多 procedure 生成的协议都得能 ast.parse"""

    @pytest.mark.parametrize("proc_name", ["sol_gel_PMMA"])
    def test_procedure_protocol_valid_python(self, proc_name):
        import ast

        sdk = OpentronsRealSDK(lab_id=f"valid-py-{proc_name}")
        proc = get_default_procedure(proc_name)
        protocol_str = sdk.generate_protocol(proc, run_id=f"valid-{proc_name}")
        try:
            ast.parse(protocol_str)
        except SyntaxError as e:
            pytest.fail(f"{proc_name} 协议不是合法 Python! {e}")


# ============================================================================
# 测试 5: 与 Mock 接口兼容(W17-D 接口不变)
# ============================================================================


class TestMockInterfaceCompatibility:
    """W19 SDK 必须跟 W17-D Mock 接口一致"""

    def test_real_sdk_substitutes_for_mock(self):
        """OpentronsRealSDK 可以替换 OpentronsMockSDK 用(MatRobotSynthAgent 默认切换 0 改)"""
        mock = OpentronsMockSDK(fail_chance=0.0)
        real = OpentronsRealSDK(prefer_real=False)  # 强制 mock 模式

        # 同接口 = execute / disconnect / is_connected
        for sdk in (mock, real):
            assert callable(sdk.execute)
            assert callable(sdk.disconnect)
            assert callable(sdk.is_connected)

        step = SynthStep(name="测试步骤", duration_minutes=10)
        r_mock = mock.execute(step)
        r_real = real.execute(step)
        # 都该有 ok / log / yield key
        assert set(r_mock.keys()) >= {"ok", "log", "yield"}
        assert set(r_real.keys()) >= {"ok", "log", "yield"}


# ============================================================================
# 测试 6: E2E 衔接(MatRobotSynthAgent 用真 SDK)
# ============================================================================


class TestE2EMatRobotSynthWithRealSDK:
    """W17-D agent 接 W19 SDK"""

    def test_agent_with_real_sdk_default(self):
        """默认 SDK 应能切到真 OpentronsRealSDK(不破坏 W17-D 测试)"""
        from agents.mat_robot_synth_agent.mat_robot_synth_agent import MatRobotSynthAgent
        from agents.mat_robot_synth_agent.synth_engine import SafetyGuard

        # 安全 procedure:30°C,无危险化学品,少量(< 100g)
        safe_proc = SynthProcedure(
            target_formula="safe-test",
            steps=[SynthStep(name="室温混合", duration_minutes=10, temperature_celsius=30.0)],
            target_yield_grams=1.0,
        )
        # agent 默认 robot_sdk 已经是 OpentronsMockSDK(W17-D)— 验证两个都能跑
        agent_mock = MatRobotSynthAgent(
            safety_guard=SafetyGuard(),
            robot_sdk=OpentronsMockSDK(fail_chance=0.0),
        )
        agent_real = MatRobotSynthAgent(
            safety_guard=SafetyGuard(),
            robot_sdk=OpentronsRealSDK(prefer_real=False),
        )
        req = AgentRequest(
            run_id="e2e-w19",
            message="测",
            artifacts={"procedure": safe_proc},
        )
        r_mock = agent_mock.run(req)
        r_real = agent_real.run(req)
        assert r_mock.error is None
        assert r_real.error is None
        assert r_mock.artifacts.get("success") is True
        assert r_real.artifacts.get("success") is True

    def test_agent_high_temp_still_blocks_with_real_sdk(self):
        """高温 procedure 用真 SDK 也会被 SafetyGuard 拦"""
        from agents.mat_robot_synth_agent.mat_robot_synth_agent import MatRobotSynthAgent

        high_temp_proc = SynthProcedure(
            target_formula="unsafe",
            steps=[SynthStep(name="烧结", duration_minutes=60, temperature_celsius=950.0)],  # > 800
            target_yield_grams=1.0,
        )
        agent = MatRobotSynthAgent(
            robot_sdk=OpentronsRealSDK(prefer_real=False),
        )
        req = AgentRequest(
            run_id="e2e-block",
            message="x",
            artifacts={"procedure": high_temp_proc},
        )
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert any("高温" in w for w in resp.artifacts.get("warnings", []))


# ============================================================================
# 测试 7: OpentronsRealSDK 协议能 bot 调试
# ============================================================================


class TestProtocolGenerationObservability:
    """sdk.protocols_generated 应当可调试"""

    def test_protocols_generated_is_list(self):
        sdk = OpentronsRealSDK(lab_id="obs-01")
        assert isinstance(sdk.protocols_generated, list)

    def test_disconnect_clears_protocols(self):
        sdk = OpentronsRealSDK(lab_id="obs-02")
        sdk.execute(SynthStep(name="step", duration_minutes=1))
        sdk.disconnect()
        assert sdk.protocols_generated == []


# ============================================================================
# 测试 8: 默认+向后兼容(SDK 提供无 lab_id 也能 new)
# ============================================================================


class TestDefaults:
    """默认参数稳定性"""

    def test_default_constructor(self):
        sdk = OpentronsRealSDK()
        assert sdk.lab_id == "matwau-lab-01"  # 默认值
        assert sdk.sdk_mode in ("real", "mock")
        assert sdk.is_connected() is True

    def test_protocol_builder_default_constructor(self):
        builder = OpentronsProtocolBuilder()
        proc = SynthProcedure(
            target_formula="def",
            steps=[SynthStep(name="室温", duration_minutes=5)],
            target_yield_grams=0.1,
        )
        protocol_str = builder.build(proc, run_id="def-001")
        assert "def run(protocol):" in protocol_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
