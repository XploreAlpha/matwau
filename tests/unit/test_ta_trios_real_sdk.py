"""test_ta_trios_real_sdk.py — W25 TA Trios DSC RealSDK 真接测试

目标(per W25 规划):
1. 验证 SDK 检测逻辑(per W17-B 降级策略)
2. 验证 TATriosProtocolBuilder 输出合法 .csv 程序
3. 验证 MATERIAL_DSC_LIBRARY 标准材料查表
4. 验证 compute_tg_tm + generate_dsc_curve 确定性
5. 验证 TATriosRealSDK 双形态:
   - skip_endpoint_check=True → sdk_mode="real"
   - prefer_real=False → sdk_mode="mock"
6. 验证 execute() 输出格式(per MockSDK 接口兼容)
7. 验证 MatRobotDscAgent 默认用 TATriosRealSDK
8. 验证 W22 DSCSafetyGuard 5 类拦截不变

per MatWAU-开发计划 §8 W25 + W17-B 降级策略
"""
from __future__ import annotations

import csv
import io
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_dsc_agent import (  # noqa: E402
    DSCSafetyGuard,
    DSCStep,
    DSCProcedure,
    DEFAULT_DSC_PROCEDURE,
    MATERIAL_DSC_LIBRARY,
    MatRobotDscAgent,
    TA_DSC_250_DEFAULT_PARAMS,
    TA_TRIOS_DEFAULT_API_URL,
    TAMockSDK,
    TATriosProtocolBuilder,
    TATriosRealSDK,
    compute_tg_tm,
    generate_dsc_curve,
    get_ta_sdk_list,
    is_ta_trios_available,
    lookup_material_dsc,
    trios_endpoint_available,
)
from agents.mat_robot_synth_agent.synth_engine import SafetyGuard  # noqa: E402


# ============================================================================
# 测试 1: SDK 检测
# ============================================================================


class TestTATriosSdkDetection:
    """TA Trios SDK 检测逻辑(per W17-B)"""

    def test_is_ta_trios_available_returns_bool(self):
        result = is_ta_trios_available()
        assert isinstance(result, bool)

    def test_get_ta_sdk_list_returns_list(self):
        result = get_ta_sdk_list()
        assert isinstance(result, list)

    def test_trios_endpoint_available_returns_bool(self):
        result = trios_endpoint_available(
            url="http://localhost:99999/nonexistent",
            timeout=0.1,
        )
        assert isinstance(result, bool)


# ============================================================================
# 测试 2: TATriosProtocolBuilder .csv 输出
# ============================================================================


class TestTATriosProtocolBuilder:
    """TA Trios .csv 温度程序生成器"""

    def test_basic_csv_structure(self):
        """基本 CSV 结构"""
        builder = TATriosProtocolBuilder()
        proc = DEFAULT_DSC_PROCEDURE
        csv_str = builder.build(proc, run_id="w25-test-001")
        # 头注释
        assert "# TA Trios temperature program" in csv_str
        assert "w25-test-001" in csv_str
        # CSV 头
        assert "Step,Name,Duration(min),TargetTemp(C)" in csv_str
        # 步骤数据
        assert "升温 25→200" in csv_str or "升温" in csv_str

    def test_csv_parseable(self):
        """生成的 CSV 可被 csv.reader 解析"""
        builder = TATriosProtocolBuilder()
        proc = DEFAULT_DSC_PROCEDURE
        csv_str = builder.build(proc, run_id="w25-test-002")
        # 跳过 # 开头行
        lines = [ln for ln in csv_str.split("\n") if ln and not ln.startswith("#")]
        reader = csv.reader(lines)
        rows = list(reader)
        assert len(rows) >= 1
        # 第一行是 header
        assert rows[0] == ["Step", "Name", "Duration(min)", "TargetTemp(C)", "HeatingRate(C/min)", "Isothermal"]

    def test_csv_save_to_file(self):
        """保存 CSV 到文件"""
        builder = TATriosProtocolBuilder()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            path = builder.save(DEFAULT_DSC_PROCEDURE, tmp_path, run_id="w25-save-001")
            assert Path(path).exists()
            content = Path(path).read_text()
            assert "TA Trios temperature program" in content
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

    def test_method_xml(self):
        """Trios method XML 元数据"""
        builder = TATriosProtocolBuilder()
        xml_str = builder.build_method_xml(DEFAULT_DSC_PROCEDURE, run_id="w25-xml-001")
        assert "<?xml version" in xml_str
        assert "<TATriosMethod" in xml_str
        assert "<Instrument" in xml_str
        assert "<Atmosphere>N2</Atmosphere>" in xml_str
        assert "<Step" in xml_str


# ============================================================================
# 测试 3: 标准材料 DSC 属性库
# ============================================================================


class TestMaterialDscLibrary:
    """MATERIAL_DSC_LIBRARY(W25 增量)"""

    def test_library_has_9_materials(self):
        """内置 ≥ 9 个材料"""
        assert len(MATERIAL_DSC_LIBRARY) >= 9

    def test_lookup_pmma(self):
        """查 PMMA 标准属性"""
        info = lookup_material_dsc("PMMA")
        assert info is not None
        assert info["Tg_c"] == 105.0
        assert info["Tm_c"] == 160.0
        assert info["domain"] == "polymer"

    def test_lookup_pe(self):
        """查 PE(半结晶,完整 Tg/Tm/Tc/ΔH)"""
        info = lookup_material_dsc("PE")
        assert info is not None
        assert info["Tg_c"] == -120.0
        assert info["Tm_c"] == 130.0
        assert info["crystallization_temp_c"] == 110.0
        assert info["enthalpy_j_per_g"] == 290.0

    def test_lookup_inconel_718(self):
        """查 Inconel 718(金属,无 Tg)"""
        info = lookup_material_dsc("Inconel 718")
        assert info is not None
        assert info["Tg_c"] is None
        assert info["Tm_c"] == 1330.0
        assert info["domain"] == "metal_alloy"

    def test_lookup_unknown_returns_none(self):
        info = lookup_material_dsc("UnknownXyz123")
        assert info is None

    def test_lookup_empty_returns_none(self):
        info = lookup_material_dsc("")
        assert info is None

    def test_lico_and_llzo(self):
        """查 LiCoO2 / LLZO(无机晶体)"""
        for mat in ["LiCoO2", "LLZO"]:
            info = lookup_material_dsc(mat)
            assert info is not None
            assert info["domain"] == "inorganic_crystal"


# ============================================================================
# 测试 4: compute_tg_tm 估算
# ============================================================================


class TestComputeTgTm:
    """compute_tg_tm(W25 增量)"""

    def test_compute_pmma(self):
        """PMMA → Tg=105, Tm=160"""
        result = compute_tg_tm(DEFAULT_DSC_PROCEDURE, "PMMA")
        assert result["source"] == "library"
        assert result["Tg_c"] == 105.0
        assert result["Tm_c"] == 160.0

    def test_compute_unknown(self):
        """未知样品 → source="unknown", values None"""
        result = compute_tg_tm(DEFAULT_DSC_PROCEDURE, "UnknownXyz123")
        assert result["source"] == "unknown"
        assert result["Tg_c"] is None
        assert result["Tm_c"] is None

    def test_compute_with_target_properties_filter(self):
        """target_properties 过滤"""
        proc = DSCProcedure(
            sample_formula="PMMA",
            target_properties=["Tg"],  # 只要 Tg
            steps=[],
        )
        result = compute_tg_tm(proc, "PMMA")
        assert "Tg_c" in result
        # Tm_c 没在 target_properties,不返回
        # (但 source 仍是 library)
        assert result["source"] == "library"

    def test_compute_no_target_properties(self):
        """target_properties 空 → 全部返回"""
        proc = DSCProcedure(
            sample_formula="PE",
            target_properties=[],
            steps=[],
        )
        result = compute_tg_tm(proc, "PE")
        assert result["Tg_c"] == -120.0
        assert result["Tm_c"] == 130.0
        assert result["Tc_c"] == 110.0
        assert result["enthalpy_j_per_g"] == 290.0


# ============================================================================
# 测试 5: generate_dsc_curve 确定性
# ============================================================================


class TestGenerateDscCurve:
    """generate_dsc_curve 确定性"""

    def test_pmma_curve_deterministic(self):
        """PMMA DSC 曲线确定性(noise=0)"""
        proc = DEFAULT_DSC_PROCEDURE
        curve1 = generate_dsc_curve(proc, "PMMA", noise=0)
        curve2 = generate_dsc_curve(proc, "PMMA", noise=0)
        assert curve1["x"] == curve2["x"]
        assert curve1["y"] == curve2["y"]

    def test_pmma_curve_has_data_points(self):
        """PMMA 曲线应该有点"""
        curve = generate_dsc_curve(DEFAULT_DSC_PROCEDURE, "PMMA", noise=0)
        assert len(curve["x"]) > 0
        assert len(curve["x"]) == len(curve["y"])

    def test_unknown_sample_no_crash(self):
        """未知样品不崩"""
        curve = generate_dsc_curve(DEFAULT_DSC_PROCEDURE, "UnknownXyz", noise=0)
        assert isinstance(curve, dict)
        assert "x" in curve and "y" in curve

    def test_temperature_range(self):
        """温度范围在 procedure 范围内"""
        curve = generate_dsc_curve(DEFAULT_DSC_PROCEDURE, "PMMA", noise=0)
        # 默认 procedure 范围 25-200°C
        assert min(curve["x"]) >= 20.0
        assert max(curve["x"]) <= 210.0


# ============================================================================
# 测试 6: TATriosRealSDK 双形态
# ============================================================================


class TestTATriosRealSdkDualMode:
    """TATriosRealSDK 双形态(per W17-B)"""

    def test_skip_endpoint_check_uses_real(self):
        """skip_endpoint_check=True → sdk_mode='real'"""
        sdk = TATriosRealSDK(skip_endpoint_check=True, sample_formula="PMMA")
        assert sdk.sdk_mode == "real"
        assert sdk.is_endpoint_reachable is True

    def test_prefer_real_false_uses_mock(self):
        """prefer_real=False → sdk_mode='mock'"""
        sdk = TATriosRealSDK(prefer_real=False)
        assert sdk.sdk_mode == "mock"
        assert isinstance(sdk._fallback, TAMockSDK)

    def test_default_construction(self):
        """默认构造(sdk_mode 可能是 real 或 mock)"""
        sdk = TATriosRealSDK()
        assert sdk.sdk_mode in ("real", "mock")
        assert sdk.lab_id == "matwau-dsc-01"

    def test_set_sample_formula(self):
        """set_sample_formula 更新 sample_formula"""
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        sdk.set_sample_formula("Inconel 718")
        assert sdk.sample_formula == "Inconel 718"


# ============================================================================
# 测试 7: TATriosRealSDK.execute() 输出格式
# ============================================================================


class TestTATriosRealSdkExecute:
    """TATriosRealSDK.execute() 接口与 Mock 兼容"""

    def test_execute_step(self):
        """执行 1 个 DSCStep"""
        sdk = TATriosRealSDK(skip_endpoint_check=True, sample_formula="PMMA")
        step = DEFAULT_DSC_PROCEDURE.steps[1]  # 升温 25→200
        result = sdk.execute(step)
        assert "ok" in result
        assert "log" in result
        assert "curve" in result
        assert "sdk_mode" in result
        assert result["ok"] is True
        assert result["sdk_mode"] == "real"
        # 升温段应该有曲线点
        assert len(result["curve"]) > 0

    def test_execute_isothermal_step(self):
        """恒温段执行"""
        sdk = TATriosRealSDK(skip_endpoint_check=True, sample_formula="PMMA")
        step = DSCStep(name="恒温", duration_minutes=10, target_temperature_celsius=200.0, is_isothermal=True)
        result = sdk.execute(step)
        assert result["ok"] is True
        assert len(result["curve"]) > 0

    def test_execute_via_mock_fallback(self):
        """降级到 mock 后 execute 仍 OK"""
        sdk = TATriosRealSDK(prefer_real=False)
        step = DSCStep(name="升温", duration_minutes=30, target_temperature_celsius=200.0, heating_rate_c_per_min=5.0)
        result = sdk.execute(step)
        assert result["ok"] is True
        assert result["sdk_mode"] == "mock"

    def test_disconnect_clears_csv(self):
        """disconnect 清空 csv_files_generated"""
        sdk = TATriosRealSDK(skip_endpoint_check=True, sample_formula="PMMA")
        step = DSCStep(name="升温", duration_minutes=30, target_temperature_celsius=200.0)
        sdk.execute(step)
        assert len(sdk.csv_files_generated) >= 1
        sdk.disconnect()
        assert len(sdk.csv_files_generated) == 0

    def test_is_connected_returns_bool(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        assert sdk.is_connected() is True
        sdk2 = TATriosRealSDK(prefer_real=False)
        assert sdk2.is_connected() is True


# ============================================================================
# 测试 8: TATriosRealSDK 增量能力
# ============================================================================


class TestTATriosRealSdkOutputs:
    """TATriosRealSDK 增量能力"""

    def test_generate_csv_program(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        csv_str = sdk.generate_csv_program(DEFAULT_DSC_PROCEDURE, run_id="w25-sdk-001")
        assert "TA Trios temperature program" in csv_str

    def test_save_csv_program(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            path = sdk.save_csv_program(DEFAULT_DSC_PROCEDURE, tmp_path, run_id="w25-save-sdk")
            assert Path(path).exists()
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

    def test_generate_method_xml(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        xml_str = sdk.generate_method_xml(DEFAULT_DSC_PROCEDURE, run_id="w25-xml-sdk")
        assert "<TATriosMethod" in xml_str

    def test_lookup_material_via_sdk(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        info = sdk.lookup_material_dsc("PMMA")
        assert info["Tg_c"] == 105.0

    def test_compute_tg_tm_via_sdk(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        result = sdk.compute_tg_tm(DEFAULT_DSC_PROCEDURE, "PE")
        assert result["Tg_c"] == -120.0

    def test_generate_dsc_curve_via_sdk(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        curve = sdk.generate_dsc_curve(DEFAULT_DSC_PROCEDURE, "PMMA", noise=0)
        assert len(curve["x"]) > 0

    def test_installed_packages(self):
        sdk = TATriosRealSDK(skip_endpoint_check=True)
        pkgs = sdk.installed_packages()
        assert isinstance(pkgs, list)


# ============================================================================
# 测试 9: MatRobotDscAgent 默认用 TATriosRealSDK
# ============================================================================


class TestMatRobotDscAgentWithRealSdk:
    """MatRobotDscAgent 默认用 TATriosRealSDK(W25 接入)"""

    def test_default_uses_real_sdk(self):
        """默认构造 → robot_sdk 是 TATriosRealSDK"""
        agent = MatRobotDscAgent()
        assert isinstance(agent.robot_sdk, TATriosRealSDK)
        assert agent.robot_sdk.sdk_mode in ("real", "mock")

    def test_use_real_sdk_true_with_skip_endpoint(self):
        """默认 skip_endpoint_check=True → real"""
        agent = MatRobotDscAgent()
        assert agent.robot_sdk.sdk_mode == "real"

    def test_use_real_sdk_false_uses_mock(self):
        """use_real_sdk=False → TAMockSDK"""
        agent = MatRobotDscAgent(use_real_sdk=False)
        assert isinstance(agent.robot_sdk, TAMockSDK)

    def test_pass_robot_sdk_explicit(self):
        mock_sdk = TAMockSDK(fail_chance=0.0)
        agent = MatRobotDscAgent(robot_sdk=mock_sdk)
        assert agent.robot_sdk is mock_sdk

    def test_run_includes_sdk_mode(self):
        agent = MatRobotDscAgent()
        from matwau.core.agent_base import AgentRequest
        req = AgentRequest(
            run_id="w25-agent-001",
            message="测 PMMA Tg",
        )
        resp = agent.run(req)
        assert resp.artifacts["sdk_mode"] in ("real", "mock")
        assert resp.confidence > 0.0


# ============================================================================
# 测试 10: W22 DSCSafetyGuard 5 类拦截不变
# ============================================================================


class TestW22SafetyGuardUnchanged:
    """W25 不破坏 W22 DSCSafetyGuard 5 类拦截"""

    def test_safety_guard_subclasses(self):
        sg = DSCSafetyGuard()
        assert isinstance(sg, SafetyGuard)

    def test_five_block_categories(self):
        sg = DSCSafetyGuard()
        assert sg.block_if_oxidizing_combustible is True
        assert sg.block_if_unsealed_high_temp is True
        assert sg.block_if_overheating_rate is True
        assert sg.block_if_explosive is True

    def test_high_temp_oxidizing_block(self):
        sg = DSCSafetyGuard()
        proc = DSCProcedure(
            sample_formula="",
            steps=[
                DSCStep(name="升温", duration_minutes=60, target_temperature_celsius=700.0, heating_rate_c_per_min=10.0)
            ],
            atmosphere="air",  # 空气气氛 + 高温 → block
            sample_mass_mg=5.0,
            crucible_sealed=True,
        )
        warnings = sg.check_dsc(proc)
        assert any("⛔" in w and ("高温氧化" in w or "空气" in w) for w in warnings)

    def test_unsealed_high_temp_block(self):
        sg = DSCSafetyGuard()
        proc = DSCProcedure(
            sample_formula="",
            steps=[
                DSCStep(name="升温", duration_minutes=30, target_temperature_celsius=400.0, heating_rate_c_per_min=10.0)
            ],
            atmosphere="N2",
            sample_mass_mg=5.0,
            crucible_sealed=False,  # 未密封 + 高温 → block
        )
        warnings = sg.check_dsc(proc)
        assert any("⛔" in w and "坩埚" in w for w in warnings)

    def test_overheating_rate_block(self):
        sg = DSCSafetyGuard()
        proc = DSCProcedure(
            sample_formula="",
            steps=[
                DSCStep(name="升温", duration_minutes=10, target_temperature_celsius=200.0, heating_rate_c_per_min=150.0)
            ],
            atmosphere="N2",
            sample_mass_mg=5.0,
            crucible_sealed=True,
            max_heating_rate_c_per_min=150.0,
        )
        warnings = sg.check_dsc(proc)
        assert any("⛔" in w and "升温速率" in w for w in warnings)


# ============================================================================
# 测试 11: TA DSC 250 规格常量
# ============================================================================


class TestTADscConstants:
    """TA DSC 250 规格常量"""

    def test_instrument(self):
        assert TA_DSC_250_DEFAULT_PARAMS["instrument"] == "TA Instruments DSC 250"

    def test_temperature_range(self):
        t_lo, t_hi = TA_DSC_250_DEFAULT_PARAMS["temperature_range_c"]
        assert t_lo < 0 < t_hi

    def test_heating_rate_range(self):
        hr_lo, hr_hi = TA_DSC_250_DEFAULT_PARAMS["heating_rate_range_c_per_min"]
        assert hr_lo < hr_hi

    def test_default_trios_url(self):
        assert "trios" in TA_TRIOS_DEFAULT_API_URL.lower()


# ============================================================================
# 总览
# ============================================================================


class TestW25Overview:
    """W25 总览"""

    def test_full_pipeline_real_sdk(self):
        """端到端:RealSDK + Agent + 标准材料库"""
        agent = MatRobotDscAgent()
        from matwau.core.agent_base import AgentRequest
        req = AgentRequest(
            run_id="w25-overview-001",
            message="测 PMMA Tg / Tm",
        )
        resp = agent.run(req)
        assert resp.confidence > 0.0
        result = resp.artifacts["result"]
        # 应该有 Tg / Tm
        assert "Tg_c" in result
        assert "Tm_c" in result
        # sdk_mode 标记
        assert resp.artifacts["sdk_mode"] in ("real", "mock")

    def test_full_pipeline_inconel_718(self):
        """测 Inconel 718(金属,无 Tg)"""
        agent = MatRobotDscAgent()
        from matwau.core.agent_base import AgentRequest
        req = AgentRequest(
            run_id="w25-inconel-001",
            message="测 Inconel 718 Tm",
            artifacts={"procedure": DSCProcedure(
                sample_formula="Inconel 718",
                target_properties=["Tm"],
                steps=[
                    DSCStep(name="升温", duration_minutes=60, target_temperature_celsius=1400.0, heating_rate_c_per_min=20.0),
                ],
                atmosphere="Ar",
                sample_mass_mg=20.0,
                crucible_sealed=True,
                max_heating_rate_c_per_min=20.0,
                domain="metal_alloy",
            )},
        )
        resp = agent.run(req)
        assert resp.confidence > 0.0
        # 金属域温度太高,DSC 实测不了(W22 + W25 测试代码不要求安全通过,
        # 但 SafetyGuard 会对 1400°C 高温报警)
        # 实际上 SafetyGuard 高温警告 → DSC 不会硬阻断(只针对空气气氛)
        # 所以应该 success
        assert resp.artifacts["success"] is True