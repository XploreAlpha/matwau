"""test_bruker_real_sdk.py — W20 BrukerRealSDK 测试

覆盖:
1. SDK 检测 is_bruker_raw_available() / get_bruker_sdk_list()
2. BrukerProtocolBuilder .brml XML 生成
3. PDF 卡片查询 + 峰比对
4. BrukerRealSDK 双形态(real + mock)
5. 与 BrukerMockSDK 100% 接口兼容
6. 真接路径默认选 PDF 卡片数据库(LLZO/LiCoO2/PMMA/Cu)
7. .brml 文件保存
8. E2E 衔接:mat-gen → MatRobotXrdAgent(用真 SDK)

per MatWAU-开发计划 W20
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

from agents.mat_robot_xrd_agent.bruker_real_sdk import (  # noqa: E402
    BrukerProtocolBuilder,
    BrukerRealSDK,
    PDF_CARDS_DB,
    compare_to_pdf_card,
    is_bruker_raw_available,
    lookup_pdf_card,
    scan_to_peaks,
)
from agents.mat_robot_xrd_agent.xrd_engine import (  # noqa: E402
    BrukerMockSDK,
    XRDProcedure,
    XRDStep,
    get_default_xrd_procedure,
)
from matwau.core.agent_base import AgentRequest  # noqa: E402


# ============================================================================
# 测试 1: SDK 检测
# ============================================================================


class TestSDKDetection:
    """bruker 库探测"""

    def test_bruker_availability_returns_bool(self):
        result = is_bruker_raw_available()
        assert isinstance(result, bool)

    def test_sdk_constructor_never_crashes(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-01")
        assert sdk.is_connected() is True

    def test_sdk_mode_attribute_present(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-02")
        assert sdk.sdk_mode in ("real", "mock")

    def test_installed_packages_returns_list(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-03")
        pkgs = sdk.installed_packages()
        assert isinstance(pkgs, list)


# ============================================================================
# 测试 2: BrukerProtocolBuilder .brml XML 生成
# ============================================================================


class TestProtocolBuilder:
    """Bruker .brml XML 生成(不依赖 brukerraw)"""

    def test_build_returns_string(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-001")
        assert isinstance(xml_str, str)
        assert "<?xml" in xml_str
        assert "<BrukerMethod" in xml_str

    def test_brml_contains_instrument(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-002")
        assert "D8 Advance" in xml_str

    def test_brml_contains_target_phases(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-003")
        assert "PDF 45-1090" in xml_str

    def test_brml_contains_steps(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-004")
        for step in proc.steps:
            assert step.name in xml_str

    def test_brml_scan_step_has_tube_voltage(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-005")
        # 默认 40 kV
        assert "TubeVoltage" in xml_str or "kv=" in xml_str

    def test_brml_save_writes_file(self):
        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".brml", delete=False,
        ) as f:
            output_path = f.name
        try:
            returned_path = builder.save(proc, output_path, run_id="xrd-test-006")
            assert returned_path == output_path
            content = Path(output_path).read_text(encoding="utf-8")
            assert "<BrukerMethod" in content
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_brml_is_valid_xml(self):
        """生成的 .brml 应该是合法 XML(可 ElementTree 解析)"""
        import xml.etree.ElementTree as ET

        builder = BrukerProtocolBuilder()
        proc = get_default_xrd_procedure()
        xml_str = builder.build(proc, run_id="xrd-test-007")
        try:
            root = ET.fromstring(xml_str)
            assert root.tag == "BrukerMethod"
        except ET.ParseError as e:
            pytest.fail(f".brml 不是合法 XML! {e}\n--- 协议 ---\n{xml_str[:500]}")

    def test_brml_translate_scan_step(self):
        builder = BrukerProtocolBuilder()
        proc = XRDProcedure(
            sample_formula="test",
            steps=[XRDStep(name="扫描", duration_minutes=30, two_theta_range=(10.0, 80.0))],
            target_phases=[],
        )
        xml_str = builder.build(proc, run_id="xrd-test-008")
        assert "<Type>scan</Type>" in xml_str
        assert 'start="10.0"' in xml_str or "10.0" in xml_str
        assert 'end="80.0"' in xml_str or "80.0" in xml_str

    def test_brml_translate_load_step(self):
        builder = BrukerProtocolBuilder()
        proc = XRDProcedure(
            sample_formula="test",
            steps=[XRDStep(name="装样", duration_minutes=10)],
            target_phases=[],
        )
        xml_str = builder.build(proc, run_id="xrd-test-009")
        assert "load_unload" in xml_str


# ============================================================================
# 测试 3: PDF 卡片数据库
# ============================================================================


class TestPDFCardDatabase:
    """内置 PDF 卡片数据库"""

    def test_pdf_cards_db_is_dict(self):
        assert isinstance(PDF_CARDS_DB, dict)
        assert len(PDF_CARDS_DB) >= 4

    def test_lookup_llzo_card(self):
        card = lookup_pdf_card("PDF 45-1090")
        assert card is not None
        assert "LLZO" in card["name"]
        assert len(card["bragg_peaks_2theta"]) >= 10

    def test_lookup_unknown_returns_none(self):
        card = lookup_pdf_card("PDF 99-9999")
        assert card is None

    def test_compare_to_pdf_card_matched(self):
        """LLZO peak list 跟 PDF 45-1090 比对应 match"""
        card = lookup_pdf_card("PDF 45-1090")
        measured = [
            {"two_theta": t, "intensity": i}
            for t, d, i in card["bragg_peaks_2theta"]
        ]
        result = compare_to_pdf_card(measured, "PDF 45-1090")
        assert result["matched"] is True
        assert result["score"] >= 0.5

    def test_compare_unknown_card_returns_zero(self):
        result = compare_to_pdf_card([], "PDF 99-9999")
        assert result["matched"] is False
        assert result["score"] == 0.0

    def test_scan_to_peaks_returns_list(self):
        step = XRDStep(name="扫描", duration_minutes=30)
        peaks = scan_to_peaks(sample_formula="LLZO", scan_step=step)
        assert isinstance(peaks, list)
        assert len(peaks) >= 1
        for peak in peaks:
            assert "two_theta" in peak
            assert "d_spacing_angstrom" in peak
            assert "intensity" in peak

    def test_scan_to_peaks_llzo_uses_card(self):
        """LLZO 应触发 PDF 45-1090 卡片"""
        step = XRDStep(name="扫描", duration_minutes=30)
        peaks = scan_to_peaks(sample_formula="LLZO", scan_step=step)
        # LLZO PDF 45-1090 有 12 个峰
        assert len(peaks) >= 10

    def test_scan_to_peaks_lico_uses_card(self):
        """LiCoO2 应触发 PDF 47-1743 卡片"""
        step = XRDStep(name="扫描", duration_minutes=30)
        peaks = scan_to_peaks(sample_formula="LiCoO2", scan_step=step)
        assert len(peaks) >= 3


# ============================================================================
# 测试 4: BrukerRealSDK 双形态
# ============================================================================


class TestBrukerRealSDK:
    """真接 SDK(优先真 brukerraw / 降级 mock)"""

    def test_sdk_has_execute_method(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-10")
        assert hasattr(sdk, "execute")
        assert callable(sdk.execute)

    def test_sdk_has_disconnect(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-11")
        sdk.disconnect()

    def test_sdk_execute_returns_dict_with_peaks(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-12")
        step = XRDStep(name="扫描", duration_minutes=30)
        result = sdk.execute(step)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "log" in result
        assert "peaks" in result

    def test_sdk_records_command(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-13")
        step = XRDStep(name="扫描")
        sdk.execute(step)
        assert "扫描" in sdk.commands_executed

    def test_sdk_records_brml(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-14")
        step = XRDStep(name="扫描")
        sdk.execute(step)
        if sdk.sdk_mode == "real":
            assert len(sdk.brml_files_generated) >= 1
        else:
            assert sdk.brml_files_generated == []

    def test_sdk_mode_reflects_availability(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-15")
        if is_bruker_raw_available():
            assert sdk.sdk_mode == "real"
        else:
            assert sdk.sdk_mode == "mock"

    def test_prefer_real_false_always_mock(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-16", prefer_real=False)
        assert sdk.sdk_mode == "mock"

    def test_save_brml_writes_file(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-17")
        proc = get_default_xrd_procedure()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".brml", delete=False,
        ) as f:
            output_path = f.name
        try:
            returned = sdk.save_brml_config(proc, output_path, run_id="real-test-17")
            assert returned == output_path
            content = Path(output_path).read_text(encoding="utf-8")
            assert "<BrukerMethod" in content
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_generate_brml_returns_str(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-18")
        proc = get_default_xrd_procedure()
        xml_str = sdk.generate_brml_config(proc, run_id="gen-test-18")
        assert isinstance(xml_str, str)
        assert "<BrukerMethod" in xml_str

    def test_lookup_pdf_via_sdk(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-19")
        card = sdk.lookup_pdf_card("PDF 45-1090")
        assert card is not None
        assert "LLZO" in card["name"]

    def test_compare_to_pdf_via_sdk(self):
        sdk = BrukerRealSDK(lab_id="xrd-test-20")
        card = lookup_pdf_card("PDF 45-1090")
        measured = [
            {"two_theta": t, "intensity": i}
            for t, d, i in card["bragg_peaks_2theta"]
        ]
        result = sdk.compare_to_pdf_card(measured, "PDF 45-1090")
        assert result["matched"] is True


# ============================================================================
# 测试 5: 与 Mock 接口兼容
# ============================================================================


class TestMockInterfaceCompatibility:
    """W20 SDK 必须跟 W18 Mock 接口一致"""

    def test_real_sdk_substitutes_for_mock(self):
        mock = BrukerMockSDK(fail_chance=0.0)
        real = BrukerRealSDK(prefer_real=False)
        for sdk in (mock, real):
            assert callable(sdk.execute)
            assert callable(sdk.disconnect)
            assert callable(sdk.is_connected)

        step = XRDStep(name="扫描", duration_minutes=10)
        r_mock = mock.execute(step)
        r_real = real.execute(step)
        assert set(r_mock.keys()) >= {"ok", "log", "peaks"}
        assert set(r_real.keys()) >= {"ok", "log", "peaks"}


# ============================================================================
# 测试 6: E2E 衔接(MatRobotXrdAgent 用真 SDK)
# ============================================================================


class TestE2EMatRobotXrdWithRealSDK:
    """W18 agent 接 W20 SDK"""

    def test_agent_with_real_sdk_runs_safe_procedure(self):
        """默认 SDK 应能切到真 BrukerRealSDK(不破坏 W18 测试)"""
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        from agents.mat_robot_xrd_agent.xrd_engine import XRDSafetyGuard

        # 默认 Ca-LLZO procedure 已经安全
        proc = get_default_xrd_procedure()
        agent_real = MatRobotXrdAgent(
            safety_guard=XRDSafetyGuard(),
            robot_sdk=BrukerRealSDK(prefer_real=False),
        )
        req = AgentRequest(
            run_id="e2e-w20",
            message="测",
            artifacts={"procedure": proc},
        )
        resp = agent_real.run(req)
        assert resp.error is None
        assert resp.artifacts.get("success") is True

    def test_agent_safety_guard_still_blocks_with_real_sdk(self):
        """舱门开 procedure 用真 SDK 也被 XRDSafetyGuard 拦"""
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent

        danger_proc = XRDProcedure(
            sample_formula="test",
            door_open=True,    # 舱门开
            user_in_apron=True,
            target_phases=[],
        )
        agent = MatRobotXrdAgent(
            robot_sdk=BrukerRealSDK(prefer_real=False),
        )
        req = AgentRequest(
            run_id="e2e-block",
            message="x",
            artifacts={"procedure": danger_proc},
        )
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True
        assert any("舱门" in w for w in resp.artifacts.get("warnings", []))


# ============================================================================
# 测试 7: 默认+向后兼容
# ============================================================================


class TestDefaults:
    """默认参数稳定性"""

    def test_default_constructor(self):
        sdk = BrukerRealSDK()
        assert sdk.lab_id == "matwau-xrd-01"
        assert sdk.sdk_mode in ("real", "mock")
        assert sdk.is_connected() is True

    def test_protocol_builder_default(self):
        builder = BrukerProtocolBuilder()
        proc = XRDProcedure(
            sample_formula="default",
            steps=[XRDStep(name="扫描", duration_minutes=30)],
            target_phases=["PDF 45-1090"],
        )
        xml_str = builder.build(proc, run_id="def-001")
        assert "<BrukerMethod" in xml_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
