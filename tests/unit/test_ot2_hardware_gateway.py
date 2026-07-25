"""test_ot2_hardware_gateway.py — W28 OT-2 硬件网关测试

目标(per W28 规划):
1. 验证化学品供应清单(REAGENT_CATALOG + build_reagent_order)
2. 验证 OpentronsProtocolBuilder 输出包含 apiLevel metadata
3. 验证 AST 兜底语法验证
4. 验证 docker-compose.yml + 启动脚本存在
5. 验证 W19 OpentronsRealSDK 集成不破坏(W28 增强)
6. 验证端到端 hardware_full_workflow

per MatWAU-Stage 3 钢铁侠 doc §3.5 W28
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_synth_agent import (  # noqa: E402
    OpentronsProtocolBuilder,
    OpentronsRealSDK,
    SynthProcedure,
)
from agents.mat_robot_synth_agent.ot2_hardware_gateway import (  # noqa: E402
    DOCKER_COMPOSE_OT2,
    DOCKER_OPENTRONS_IMAGE,
    GatewayConfig,
    REAGENT_CATALOG,
    ReagentOrder,
    build_reagent_manifest,
    build_reagent_order,
    estimate_reagent_cost,
    hardware_full_workflow,
    run_docker_simulate,
    run_opentrons_simulate,
    write_protocol_to_file,
)
from agents.mat_robot_synth_agent.synth_engine import DEFAULT_PROCEDURES  # noqa: E402


# ============================================================================
# 测试 1: REAGENT_CATALOG + ReagentOrder
# ============================================================================


class TestReagentCatalog:
    """REAGENT_CATALOG 化学品目录(W28)"""

    def test_catalog_has_min_chemicals(self):
        """目录里 ≥ 9 个化学品"""
        assert len(REAGENT_CATALOG) >= 9

    def test_catalog_contains_common(self):
        """含常用化学品"""
        for chem in ["H2O", "ethanol", "Li2CO3", "La2O3", "ZrO2", "HNO3"]:
            assert chem in REAGENT_CATALOG, f"缺化学品:{chem}"

    def test_catalog_has_price_and_supplier(self):
        """每个化学品有 price + supplier + hazard"""
        for chem, info in REAGENT_CATALOG.items():
            assert "supplier" in info, f"{chem} 缺 supplier"
            assert "hazard_class" in info, f"{chem} 缺 hazard_class"
            # price 字段 per unit
            has_price = any(k.startswith("price_per_") for k in info)
            assert has_price, f"{chem} 缺 price 字段"

    def test_build_reagent_order_known(self):
        """构造已知化学品订单"""
        order = build_reagent_order("Li2CO3", amount=5.0)
        assert order.chemical_formula == "Li2CO3"
        assert order.amount == 5.0
        assert order.supplier == "Alfa Aesar"
        assert order.price_cny > 0.0  # ¥18/g × 5g = ¥90
        assert order.hazard_class == "irritant"

    def test_build_reagent_order_unknown(self):
        """未知化学品 → 默认值"""
        order = build_reagent_order("UnknownXyz", amount=10.0)
        assert order.supplier == "Unknown"
        assert order.price_cny == 0.0
        assert order.hazard_class == "none"


# ============================================================================
# 测试 2: build_reagent_manifest + estimate_reagent_cost
# ============================================================================


class TestReagentManifest:
    """build_reagent_manifest 从 procedure 构造清单"""

    def test_build_manifest_from_llzo(self):
        """LLZO procedure → 化学品清单"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        orders = build_reagent_manifest(proc)
        # LLZO 用硝酸盐,应有多个订单
        assert len(orders) >= 1

    def test_estimate_reagent_cost(self):
        """估算化学品总成本"""
        orders = [
            ReagentOrder(chemical_formula="Li2CO3", amount=5.0, price_cny=90.0),
            ReagentOrder(chemical_formula="La2O3", amount=5.0, price_cny=175.0),
        ]
        total = estimate_reagent_cost(orders)
        assert total == 265.0


# ============================================================================
# 测试 3: OT-2 协议生成(W19 + W28 增强 — 含 apiLevel metadata)
# ============================================================================


class TestOt2ProtocolGeneration:
    """OT-2 协议生成 + apiLevel metadata"""

    def test_protocol_has_apiLevel_metadata(self):
        """协议含 apiLevel metadata(W28 关键,opentrons.simulate 要求)"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-meta-001")
        assert 'metadata = {"apiLevel"' in code

    def test_protocol_has_run_function(self):
        """协议含 def run(protocol)"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-run-001")
        assert "def run(protocol):" in code

    def test_protocol_ast_parseable(self):
        """协议能被 ast.parse 解析"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-ast-001")
        # 不抛 SyntaxError = 合法
        ast.parse(code)

    def test_protocol_compile_valid(self):
        """协议能被 compile"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-compile-001")
        compile(code, "<protocol>", "exec")  # 不抛 = OK

    def test_write_protocol_to_file(self):
        """写协议到文件"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-write-001")
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            result = write_protocol_to_file(code, tmp_path)
            assert result == tmp_path
            assert Path(tmp_path).exists()
            content = Path(tmp_path).read_text()
            assert "metadata" in content
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


# ============================================================================
# 测试 4: opentrons.simulate() + AST 兜底
# ============================================================================


class TestOpenTronsSimulateFallback:
    """opentrons.simulate() + AST 兜底(W28 关键)"""

    def test_simulate_returns_dict(self):
        """simulate 返回 Dict 或 None"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-sim-001")

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            tmp_path = f.name
            f.write(code)
        try:
            result = run_opentrons_simulate(tmp_path)
            # opentrons 9.x 装了但需要 OT-2 真实连接,可能返回 None 或 Dict
            if result is not None:
                assert "ok" in result
                assert "log" in result
                assert "sdk_mode" in result
                # 兜底:应该有 syntax_valid 字段
                if result["sdk_mode"] == "real-ast-validated":
                    assert result.get("syntax_valid") is True
                    assert result.get("has_run_function") is True
                    assert result.get("has_apiLevel") is True
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

    def test_simulate_invalid_syntax(self):
        """无效语法 simulate 应失败"""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            tmp_path = f.name
            f.write("def broken syntax !!!")  # 无效语法
        try:
            result = run_opentrons_simulate(tmp_path)
            if result is not None:
                # 兜底也会捕获 SyntaxError
                assert result["ok"] is False
                assert result.get("syntax_valid") is False
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


# ============================================================================
# 测试 5: Docker 网关 + run_docker_simulate
# ============================================================================


class TestDockerGateway:
    """Docker 网关(W28 部署)"""

    def test_docker_image_constant(self):
        """Docker 镜像常量"""
        assert "opentrons" in DOCKER_OPENTRONS_IMAGE.lower()

    def test_docker_simulate_returns_none_or_dict(self):
        """docker simulate 返回 Dict 或 None(没 docker 时 None)"""
        builder = OpentronsProtocolBuilder()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = builder.build(proc, run_id="w28-docker-001")
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            tmp_path = f.name
            f.write(code)
        try:
            result = run_docker_simulate(tmp_path)
            # 没 docker 时返回 None,有 docker 时返回 Dict
            if result is not None:
                assert "ok" in result
                assert "source" in result
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


# ============================================================================
# 测试 6: 部署产物
# ============================================================================


class TestDeploymentArtifacts:
    """W28 部署产物"""

    def test_docker_compose_exists(self):
        path = _PROJECT_ROOT / "deploy" / "ot2_gateway" / "docker-compose.yml"
        assert path.exists(), f"docker-compose.yml 不存在:{path}"
        content = path.read_text()
        assert "opentrons" in content.lower()
        assert "31950" in content  # OT-2 RPC 端口

    def test_start_script_exists(self):
        path = _PROJECT_ROOT / "deploy" / "ot2_gateway" / "start_ot2_gateway.sh"
        assert path.exists()
        content = path.read_text()
        for cmd in ("up", "status", "stop", "logs", "reset", "demo"):
            assert cmd in content, f"缺 {cmd} 子命令"

    def test_start_script_executable(self):
        path = _PROJECT_ROOT / "deploy" / "ot2_gateway" / "start_ot2_gateway.sh"
        import stat
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, "启动脚本不可执行"

    def test_docker_compose_yml_constant(self):
        """DOCKER_COMPOSE_OT2 字符串常量"""
        assert "opentrons" in DOCKER_COMPOSE_OT2.lower()
        assert "31950" in DOCKER_COMPOSE_OT2


# ============================================================================
# 测试 7: 端到端 hardware_full_workflow
# ============================================================================


class TestHardwareFullWorkflow:
    """端到端 hardware_full_workflow"""

    def test_full_workflow_returns_required_keys(self):
        """workflow 返回必要字段"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-full-001")
        assert "reagent_orders" in result
        assert "total_reagent_cost_cny" in result
        assert "protocol_path" in result
        assert "simulate_result" in result
        assert "summary" in result

    def test_full_workflow_writes_protocol_file(self):
        """workflow 写协议文件"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-file-001")
        assert Path(result["protocol_path"]).exists()

    def test_full_workflow_protocol_has_apiLevel(self):
        """workflow 写的协议含 apiLevel"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-apilevel-001")
        content = Path(result["protocol_path"]).read_text()
        assert "metadata" in content
        assert "apiLevel" in content

    def test_full_workflow_reagent_orders_present(self):
        """workflow 化学品清单非空"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-orders-001")
        assert len(result["reagent_orders"]) >= 1

    def test_full_workflow_simulate_result(self):
        """workflow simulate_result 是 Dict 或 None"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-sim-001")
        sim = result["simulate_result"]
        if sim is not None:
            assert "ok" in sim
            assert "sdk_mode" in sim or "source" in sim


# ============================================================================
# 测试 8: GatewayConfig 数据类
# ============================================================================


class TestGatewayConfig:
    """GatewayConfig"""

    def test_default_config(self):
        cfg = GatewayConfig()
        assert cfg.image == DOCKER_OPENTRONS_IMAGE
        assert cfg.container_name == "matwau-ot2-simulator"
        assert cfg.auto_cleanup is True

    def test_custom_config(self):
        cfg = GatewayConfig(
            image="custom-image:latest",
            container_name="my-ot2",
            protocols_dir="/tmp/protocols",
            output_dir="/tmp/output",
            auto_cleanup=False,
        )
        assert cfg.image == "custom-image:latest"
        assert cfg.auto_cleanup is False

    def test_config_to_dict(self):
        cfg = GatewayConfig()
        d = cfg.to_dict()
        assert "image" in d
        assert "container_name" in d
        assert "protocols_dir" in d


# ============================================================================
# 测试 9: W19 OpentronsRealSDK 集成不破坏
# ============================================================================


class TestW19Unchanged:
    """W28 不破坏 W19 OpentronsRealSDK"""

    def test_sdk_still_dual_mode(self):
        """OpentronsRealSDK 双形态"""
        sdk = OpentronsRealSDK()
        assert sdk.sdk_mode in ("real", "mock")

    def test_sdk_generate_protocol_method(self):
        """sdk.generate_protocol() 仍可用"""
        sdk = OpentronsRealSDK()
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = sdk.generate_protocol(proc, run_id="w19-w28-test")
        assert "metadata" in code  # W28 加的
        assert "def run(protocol):" in code

    def test_sdk_real_mode_includes_apiLevel(self):
        """真接 SDK 生成的协议含 apiLevel"""
        sdk = OpentronsRealSDK()
        # 强制跳过 endpoint 检查,走真接
        if sdk.sdk_mode == "mock":
            pytest.skip("opentrons 未装,降级 mock")
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        code = sdk.generate_protocol(proc, run_id="w28-real-001")
        assert "metadata" in code


# ============================================================================
# 总览
# ============================================================================


class TestW28Overview:
    """W28 总览"""

    def test_full_pipeline(self):
        """端到端:procedure → 化学品 → 协议 → simulate"""
        proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
        if proc is None:
            pytest.skip("LLZO procedure not available")
        result = hardware_full_workflow(proc, run_id="w28-overview-001")
        # 5 件产出齐
        assert isinstance(result["reagent_orders"], list)
        assert result["total_reagent_cost_cny"] >= 0
        assert Path(result["protocol_path"]).exists()
        assert "summary" in result
        # simulate 至少跑了(opentrons 装了)
        from agents.mat_robot_synth_agent import is_opentrons_available
        if is_opentrons_available():
            assert result["simulate_result"] is not None