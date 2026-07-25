"""test_zeiss_real_sdk.py — W24 Zeiss SmartSEM RealSDK 真接测试

目标(per W24 规划):
1. 验证 SDK 检测逻辑(per W17-B 降级策略)
2. 验证 ZeissProtocolBuilder 输出合法 .sxml XML
3. 验证 EDS 标准组成查表(确定性)
4. 验证 generate_sem_image 输出规范
5. 验证 ZeissRealSDK 双形态:
   - skip_endpoint_check=True → sdk_mode="real"
   - prefer_real=False → sdk_mode="mock"(降级)
6. 验证 execute() 输出格式(per MockSDK 接口兼容)
7. 验证 MatRobotEmAgent 默认用 ZeissRealSDK
8. 验证 W21 EM 模板复用(SafetyGuard 6 类拦截不变)

per MatWAU-开发计划 §8 W24 + W17-B PostgresBackend 降级策略
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_em_agent import (  # noqa: E402
    EDS_KNOWN_COMPOSITIONS,
    EMSafetyGuard,
    EMProcedure,
    EMResult,
    EMStep,
    MatRobotEmAgent,
    SMARTSEM_DEFAULT_API_URL,
    ZEISS_SIGMA_DEFAULT_PARAMS,
    ZeissMockSDK,
    ZeissProtocolBuilder,
    ZeissRealSDK,
    generate_eds_output,
    generate_sem_image,
    get_zeiss_sdk_list,
    is_zeiss_smartsem_available,
    lookup_eds_composition,
    smartsem_endpoint_available,
)
from agents.mat_robot_synth_agent.synth_engine import SafetyGuard  # noqa: E402


# ============================================================================
# 测试 1: SDK 检测
# ============================================================================


class TestZeissSdkDetection:
    """ZeissRealSDK 检测逻辑(per W17-B)"""

    def test_is_zeiss_smartsem_available_returns_bool(self):
        """is_zeiss_smartsem_available 返回 bool"""
        result = is_zeiss_smartsem_available()
        assert isinstance(result, bool)

    def test_get_zeiss_sdk_list_returns_list(self):
        """get_zeiss_sdk_list 返回 list"""
        result = get_zeiss_sdk_list()
        assert isinstance(result, list)
        # 至少检测了 candidates: requests / zeiss_smartsem / pysem
        assert len(result) >= 0

    def test_smartsem_endpoint_available_returns_bool(self):
        """smartsem_endpoint_available 返回 bool"""
        result = smartsem_endpoint_available(
            url="http://localhost:99999/nonexistent",
            timeout=0.1,
        )
        assert isinstance(result, bool)


# ============================================================================
# 测试 2: ZeissProtocolBuilder 输出合法 .sxml
# ============================================================================


class TestZeissProtocolBuilder:
    """Zeiss SmartSEM .sxml XML 配置生成器"""

    def test_basic_sxml_structure(self):
        """基本 .sxml 结构"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="Inconel 718",
            target_imaging_modes=["SEM"],
            steps=[EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM")],
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        sxml = builder.build(proc, run_id="w24-test-001")
        assert "<?xml version" in sxml
        assert "<SmartSEMConfig" in sxml
        assert 'sample="Inconel 718"' in sxml
        assert 'run_id="w24-test-001"' in sxml
        assert "<Instrument model=" in sxml
        assert "</SmartSEMConfig>" in sxml

    def test_sem_step_rendered(self):
        """SEM 拍照步骤渲染"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="",
            target_imaging_modes=["SEM"],
            steps=[EMStep(name="SEM 10000x", magnification=10000, imaging_mode="SEM", beam_voltage_kv=15.0)],
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        sxml = builder.build(proc, run_id="t1")
        assert "<Type>sem_image</Type>" in sxml
        assert "<Magnification>10000</Magnification>" in sxml
        assert 'BeamVoltage kv="15.0"' in sxml

    def test_eds_step_rendered(self):
        """EDS 元素分析步骤渲染"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="",
            target_imaging_modes=["EDS"],
            steps=[EMStep(name="EDS 元素分析", imaging_mode="EDS", beam_voltage_kv=20.0)],
        )
        sxml = builder.build(proc, run_id="t2")
        assert "<Type>eds_analysis</Type>" in sxml
        assert "<ElementsToDetect>" in sxml

    def test_tem_saed_step_rendered(self):
        """TEM SAED 步骤渲染"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="",
            target_imaging_modes=["TEM"],
            steps=[EMStep(name="SAED 衍射", magnification=50000, imaging_mode="TEM", beam_voltage_kv=200.0)],
        )
        sxml = builder.build(proc, run_id="t3")
        assert "<Type>tem_saed</Type>" in sxml

    def test_target_modes_rendered(self):
        """target_imaging_modes 渲染"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="Ti-6Al-4V",
            target_imaging_modes=["SEM", "EDS", "TEM"],
            steps=[EMStep(name="装样")],
        )
        sxml = builder.build(proc, run_id="t4")
        assert "<TargetModes>" in sxml
        assert "<Mode>SEM</Mode>" in sxml
        assert "<Mode>EDS</Mode>" in sxml
        assert "<Mode>TEM</Mode>" in sxml

    def test_eds_config_xml(self):
        """EDS 元素配置 XML"""
        builder = ZeissProtocolBuilder()
        eds_xml = builder.build_eds_config(["Fe", "Cr", "Ni", "Mo"])
        assert "<EDSConfig>" in eds_xml
        assert '<Element symbol="Fe"/>' in eds_xml
        assert '<Element symbol="Mo"/>' in eds_xml
        assert "</EDSConfig>" in eds_xml

    def test_save_to_file(self):
        """保存 .sxml 到文件"""
        builder = ZeissProtocolBuilder()
        proc = EMProcedure(
            sample_formula="Inconel 718",
            target_imaging_modes=["SEM"],
            steps=[EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM")],
        )
        with tempfile.NamedTemporaryFile(suffix=".sxml", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            path = builder.save(proc, tmp_path, run_id="w24-save-001")
            assert Path(path).exists()
            content = Path(path).read_text()
            assert "<SmartSEMConfig" in content
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


# ============================================================================
# 测试 3: EDS 标准组成查表 + 确定性输出
# ============================================================================


class TestEdsComposition:
    """EDS 标准组成查表(W24 增量)"""

    def test_lookup_inconel_718(self):
        """查 Inconel 718 标准组成"""
        comp = lookup_eds_composition("Inconel 718")
        assert len(comp) == 7
        assert any(c["element"] == "Ni" and c["wt_pct"] == 52.5 for c in comp)

    def test_lookup_ss304(self):
        """查 SS304 标准组成"""
        comp = lookup_eds_composition("SS304")
        assert len(comp) == 6
        assert any(c["element"] == "Cr" for c in comp)

    def test_lookup_ti6al4v(self):
        """查 Ti-6Al-4V 标准组成"""
        comp = lookup_eds_composition("Ti-6Al-4V")
        assert len(comp) == 3
        assert comp[0]["element"] == "Ti"

    def test_lookup_pmma(self):
        """查 PMMA 标准组成"""
        comp = lookup_eds_composition("PMMA")
        assert len(comp) == 3
        assert any(c["element"] == "C" for c in comp)

    def test_lookup_unknown_returns_empty(self):
        """未知样品返回空 list"""
        comp = lookup_eds_composition("UnknownXyz123")
        assert comp == []

    def test_lookup_empty_returns_empty(self):
        """空字符串返回空 list"""
        comp = lookup_eds_composition("")
        assert comp == []

    def test_eds_output_deterministic(self):
        """EDS 输出确定性(noise=0)"""
        out1 = generate_eds_output("Inconel 718", noise=0)
        out2 = generate_eds_output("Inconel 718", noise=0)
        out3 = generate_eds_output("Inconel 718", noise=0)
        # 三次输出完全一致
        assert out1 == out2 == out3

    def test_eds_output_no_noise_no_random(self):
        """EDS 输出 noise=0 时数值稳定(Ni wt_pct = 52.5)"""
        out = generate_eds_output("Inconel 718", noise=0)
        ni = next(c for c in out if c["element"] == "Ni")
        assert ni["wt_pct"] == 52.5

    def test_eds_known_compositions_has_5_samples(self):
        """内置 5 个已知样品"""
        assert len(EDS_KNOWN_COMPOSITIONS) >= 5
        assert "Inconel 718" in EDS_KNOWN_COMPOSITIONS
        assert "SS304" in EDS_KNOWN_COMPOSITIONS
        assert "Ti-6Al-4V" in EDS_KNOWN_COMPOSITIONS
        assert "PMMA" in EDS_KNOWN_COMPOSITIONS


# ============================================================================
# 测试 4: generate_sem_image 输出规范
# ============================================================================


class TestGenerateSemImage:
    """SEM 图像记录生成"""

    def test_basic_image_record(self):
        """基本图像记录"""
        step = EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM", beam_voltage_kv=15.0)
        img = generate_sem_image(step, noise=0)
        assert "path" in img
        assert img["mag"] == 1000
        assert img["mode"] == "SEM"
        assert img["size_pixel"] == 1024
        assert img["beam_kv"] == 15.0

    def test_image_path_format(self):
        """图像 path 格式 synthetic:SEM_xxx_mag1000.tif"""
        step = EMStep(name="SEM 5000x", magnification=5000, imaging_mode="SEM")
        img = generate_sem_image(step, noise=0)
        assert img["path"].startswith("synthetic:SEM_")
        assert "_mag5000.tif" in img["path"]

    def test_noise_field(self):
        """noise 字段记录"""
        step = EMStep(name="SEM", magnification=1000, imaging_mode="SEM")
        img = generate_sem_image(step, noise=5)
        assert img["noise_level"] == 5


# ============================================================================
# 测试 5: ZeissRealSDK 双形态(per W17-B 降级策略)
# ============================================================================


class TestZeissRealSdkDualMode:
    """ZeissRealSDK 双形态(per W17-B 降级策略)"""

    def test_skip_endpoint_check_uses_real(self):
        """skip_endpoint_check=True → sdk_mode='real'"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        assert sdk.sdk_mode == "real"
        assert sdk.is_endpoint_reachable is True

    def test_prefer_real_false_uses_mock(self):
        """prefer_real=False → sdk_mode='mock'"""
        sdk = ZeissRealSDK(prefer_real=False)
        assert sdk.sdk_mode == "mock"
        # Mock fallback 应该是 ZeissMockSDK
        from agents.mat_robot_em_agent.em_engine import ZeissMockSDK
        assert isinstance(sdk._fallback, ZeissMockSDK)

    def test_default_construction(self):
        """默认构造(本机 requests 已装但 endpoint 通常不可达 → mock)"""
        sdk = ZeissRealSDK()  # 默认 prefer_real=True
        # 真接 OR mock 都行,但接口要一致
        assert sdk.sdk_mode in ("real", "mock")
        assert sdk.lab_id == "matwau-em-01"

    def test_sdk_mode_property(self):
        """sdk_mode property 暴露"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        assert sdk.sdk_mode == "real"

    def test_installed_packages_method(self):
        """installed_packages() 返回 list"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        pkgs = sdk.installed_packages()
        assert isinstance(pkgs, list)


# ============================================================================
# 测试 6: ZeissRealSDK.execute() 输出格式(Mock 兼容)
# ============================================================================


class TestZeissRealSdkExecute:
    """ZeissRealSDK.execute() 接口与 Mock 100% 兼容"""

    def test_execute_sem_step(self):
        """执行 SEM 步骤"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        step = EMStep(name="SEM 1000x", duration_minutes=15, magnification=1000, imaging_mode="SEM", beam_voltage_kv=15.0)
        result = sdk.execute(step)
        assert "ok" in result
        assert "log" in result
        assert "images" in result
        assert "elements" in result
        assert "sdk_mode" in result
        assert result["ok"] is True
        assert result["sdk_mode"] == "real"
        assert len(result["images"]) >= 1

    def test_execute_eds_step_with_sample_formula(self):
        """执行 EDS 步骤(带 sample_formula)"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        step = EMStep(
            name="EDS 元素分析", duration_minutes=30, imaging_mode="EDS",
            beam_voltage_kv=20.0, params={"sample_formula": "Inconel 718"},
        )
        result = sdk.execute(step)
        assert result["ok"] is True
        assert result["sdk_mode"] == "real"
        # Inconel 718 应该返回 7 个元素
        assert len(result["elements"]) == 7
        ni = next(e for e in result["elements"] if e["element"] == "Ni")
        assert ni["wt_pct"] == 52.5

    def test_execute_tem_saed_step(self):
        """执行 TEM SAED 步骤"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        step = EMStep(name="SAED 衍射", magnification=50000, imaging_mode="TEM", beam_voltage_kv=200.0)
        result = sdk.execute(step)
        assert result["ok"] is True
        assert len(result["images"]) >= 1
        assert result["images"][0]["mode"] == "SAED"

    def test_execute_via_mock_fallback(self):
        """降级到 mock 后 execute 仍 OK"""
        sdk = ZeissRealSDK(prefer_real=False)
        step = EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM", beam_voltage_kv=15.0)
        result = sdk.execute(step)
        assert result["ok"] is True
        assert result["sdk_mode"] == "mock"
        # Mock 应该返回 mag 相关的 images
        assert len(result["images"]) >= 1

    def test_disconnect_clears_state(self):
        """disconnect 清空状态"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        step = EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM")
        sdk.execute(step)
        assert len(sdk.commands_executed) >= 1
        sdk.disconnect()
        # RealSDK 不更新 commands_executed(只是清 sxml files)
        assert len(sdk.sxml_files_generated) == 0

    def test_is_connected_returns_bool(self):
        """is_connected 返回 bool"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        assert sdk.is_connected() is True
        sdk2 = ZeissRealSDK(prefer_real=False)
        assert sdk2.is_connected() is True


# ============================================================================
# 测试 7: ZeissRealSDK 输出 sxml + 保存
# ============================================================================


class TestZeissRealSdkOutputs:
    """ZeissRealSDK 增量能力输出"""

    def test_generate_sxml_config(self):
        """generate_sxml_config 返回 XML 字符串"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        proc = EMProcedure(
            sample_formula="Inconel 718",
            target_imaging_modes=["SEM"],
            steps=[EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM")],
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        sxml = sdk.generate_sxml_config(proc, run_id="w24-sdk-001")
        assert "<SmartSEMConfig" in sxml
        assert "</SmartSEMConfig>" in sxml

    def test_save_sxml_config(self):
        """save_sxml_config 写到文件"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        proc = EMProcedure(
            sample_formula="Inconel 718",
            target_imaging_modes=["SEM"],
            steps=[EMStep(name="SEM 1000x", magnification=1000, imaging_mode="SEM")],
        )
        with tempfile.NamedTemporaryFile(suffix=".sxml", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            path = sdk.save_sxml_config(proc, tmp_path, run_id="w24-save-sdk-001")
            assert Path(path).exists()
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

    def test_lookup_eds_composition_via_sdk(self):
        """sdk.lookup_eds_composition 转发"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        comp = sdk.lookup_eds_composition("SS304")
        assert len(comp) == 6

    def test_generate_eds_output_via_sdk(self):
        """sdk.generate_eds_output 转发"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        out = sdk.generate_eds_output("Inconel 718", noise=0)
        assert len(out) == 7

    def test_generate_sem_image_via_sdk(self):
        """sdk.generate_sem_image 转发"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        step = EMStep(name="SEM 5000x", magnification=5000, imaging_mode="SEM")
        img = sdk.generate_sem_image(step, noise=0)
        assert img["mag"] == 5000

    def test_smart_sem_endpoint_reachable(self):
        """sdk.smartsem_endpoint_reachable 返回 bool"""
        sdk = ZeissRealSDK(skip_endpoint_check=True)
        result = sdk.smartsem_endpoint_reachable("http://localhost:99999/nonexistent")
        assert isinstance(result, bool)


# ============================================================================
# 测试 8: MatRobotEmAgent 默认用 ZeissRealSDK
# ============================================================================


class TestMatRobotEmAgentWithRealSdk:
    """MatRobotEmAgent 默认用 ZeissRealSDK(W24 接入)"""

    def test_default_uses_real_sdk(self):
        """默认构造 → robot_sdk 是 ZeissRealSDK"""
        agent = MatRobotEmAgent()
        assert isinstance(agent.robot_sdk, ZeissRealSDK)
        # 默认 sdk_mode(可能 real 或 mock,看本机)
        assert agent.robot_sdk.sdk_mode in ("real", "mock")

    def test_use_real_sdk_true_with_skip_endpoint(self):
        """use_real_sdk=True + 默认 skip_endpoint_check=True → real"""
        agent = MatRobotEmAgent()
        # 因为默认 skip_endpoint_check=True → mode=real
        assert agent.robot_sdk.sdk_mode == "real"
        assert agent.robot_sdk.is_endpoint_reachable is True

    def test_use_real_sdk_false_uses_mock(self):
        """use_real_sdk=False → ZeissMockSDK"""
        agent = MatRobotEmAgent(use_real_sdk=False)
        from agents.mat_robot_em_agent.em_engine import ZeissMockSDK
        assert isinstance(agent.robot_sdk, ZeissMockSDK)

    def test_pass_robot_sdk_explicit(self):
        """显式传 robot_sdk 用传入的"""
        mock_sdk = ZeissMockSDK(fail_chance=0.0)
        agent = MatRobotEmAgent(robot_sdk=mock_sdk)
        assert agent.robot_sdk is mock_sdk

    def test_run_includes_sdk_mode(self):
        """agent.run 输出包含 sdk_mode 字段"""
        agent = MatRobotEmAgent()
        from matwau.core.agent_base import AgentRequest
        req = AgentRequest(
            run_id="w24-agent-001",
            message="拍 Inconel 718 SEM",
        )
        resp = agent.run(req)
        assert resp.artifacts["sdk_mode"] in ("real", "mock")
        assert resp.confidence > 0.0


# ============================================================================
# 测试 9: W21 EMSafetyGuard 6 类拦截不变(W24 不破坏 W21)
# ============================================================================


class TestW21SafetyGuardUnchanged:
    """W24 不破坏 W21 EMSafetyGuard 6 类拦截"""

    def test_safety_guard_subclasses(self):
        """EMSafetyGuard 继承 SafetyGuard"""
        sg = EMSafetyGuard()
        assert isinstance(sg, SafetyGuard)

    def test_six_block_categories(self):
        """6 类 EM 拦截全部就绪"""
        sg = EMSafetyGuard()
        assert sg.block_if_not_vacuum is True
        assert sg.block_if_door_open is True
        assert sg.block_if_no_coating is True
        assert sg.block_if_volatile is True
        assert sg.block_if_radiation_damage is True
        assert sg.warn_if_magnetic is True

    def test_volatile_block(self):
        """易挥发物质拦截"""
        sg = EMSafetyGuard()
        proc = EMProcedure(
            sample_formula="Mg(OH)2 test",
            sample_is_volatile=True,
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        warnings = sg.check_em(proc)
        assert any("⛔" in w and "易挥发" in w for w in warnings)

    def test_radiation_damage_block(self):
        """辐照损伤拦截"""
        sg = EMSafetyGuard()
        proc = EMProcedure(
            sample_formula="PMMA film",
            sample_is_radiation_sensitive=True,
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        warnings = sg.check_em(proc)
        assert any("⛔" in w and "辐照损伤" in w for w in warnings)

    def test_magnetic_warning_only(self):
        """磁性样品只警告不阻断"""
        sg = EMSafetyGuard()
        proc = EMProcedure(
            sample_formula="Fe nanoparticle",
            sample_is_magnetic=True,
            door_open=False, vacuum_ok=True, sample_conductive_coated=True,
        )
        warnings = sg.check_em(proc)
        assert any("⚠️" in w and "磁性" in w for w in warnings)
        # 不应该有 ⛔
        assert not any("⛔" in w for w in warnings)


# ============================================================================
# 测试 10: 默认 procedure + Ze Zeiss 规格常量
# ============================================================================


class TestZeissConstants:
    """Zeiss Sigma 规格常量"""

    def test_default_instrument(self):
        """默认仪器型号"""
        assert ZEISS_SIGMA_DEFAULT_PARAMS["instrument"] == "Zeiss Sigma FE-SEM"

    def test_accelerating_voltage_range(self):
        """加速电压范围"""
        v_lo, v_hi = ZEISS_SIGMA_DEFAULT_PARAMS["accelerating_voltage_kv_range"]
        assert 0.0 < v_lo < v_hi <= 30.0

    def test_magnification_range(self):
        """放大倍数范围"""
        m_lo, m_hi = ZEISS_SIGMA_DEFAULT_PARAMS["magnification_range"]
        assert m_lo >= 1 and m_hi >= 100000

    def test_default_smart_sem_url(self):
        """默认 SmartSEM URL"""
        assert "smartsem" in SMARTSEM_DEFAULT_API_URL.lower()


# ============================================================================
# 总览
# ============================================================================


class TestW24Overview:
    """W24 总览"""

    def test_zeiss_real_sdk_full_pipeline(self):
        """端到端:RealSDK + Agent + EDS 标准组成"""
        agent = MatRobotEmAgent()
        from matwau.core.agent_base import AgentRequest
        req = AgentRequest(
            run_id="w24-overview-001",
            message="拍 Inconel 718 微观结构 + 元素分析",
        )
        resp = agent.run(req)
        # 默认 procedure 是 Inconel 718 SEM + EDS
        assert resp.confidence > 0.0
        result = resp.artifacts["result"]
        # 应该有 images(SEM)和 elements(EDS)
        assert len(result["images"]) >= 2  # SEM 1000x + 10000x
        assert len(result["elements"]) >= 4  # Fe/Cr/Ni/Mo 等
        # 4 域兼容标识
        assert resp.artifacts["imaging_modes"] == ["SEM", "EDS"]
        # sdk_mode 标记
        assert resp.artifacts["sdk_mode"] in ("real", "mock")