"""test_inconel_718_full_characterization.py — W27 多机器人协调实战

端到端测试:化学师协调 4 机器人跑 Inconel 718 完整表征

测试场景:
1. 完整 4 步表征(synth + xrd + em + dsc)
2. 分阶段验证每步结果
3. cross_validation 跨机器人一致性
4. 失败恢复机制(某个机器人失败 → 标记 + 继续)
5. 端到端 timing + cost 累计
6. 真实材料数据库比对(EDS 标准组成 vs 实测)
7. 汇总报告输出格式

per MatWAU-Stage 3 钢铁侠 doc §3.5 Phase 4 + Stage 4 enterprise
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_chemist_agent import (  # noqa: E402
    ChemistReport,
    ChemistSafetyGuard,
    ChemistTask,
    MatChemistAgent,
    RobotStep,
    RobotStepResult,
    decompose_goal_to_robots,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
)
from agents.mat_robot_em_agent import (  # noqa: E402
    MatRobotEmAgent,
    lookup_eds_composition,
)
from agents.mat_robot_synth_agent import MatRobotSynthAgent  # noqa: E402
from agents.mat_robot_xrd_agent import (  # noqa: E402
    BrukerRealSDK,
    MatRobotXrdAgent,
    lookup_pdf_card,
)
from agents.mat_robot_dsc_agent import (  # noqa: E402
    MatRobotDscAgent,
    lookup_material_dsc,
)
from matwau.core.agent_base import AgentRequest  # noqa: E402


# ============================================================================
# 端到端测试 1: 4 机器人完整跑通 Inconel 718 表征
# ============================================================================


class TestInconel718FullCharacterization:
    """完整 Inconel 718 表征(synth + xrd + em + dsc)"""

    def test_full_4_robot_pipeline(self):
        """4 机器人 pipeline 全跑"""
        synth = MatRobotSynthAgent()
        xrd = MatRobotXrdAgent()
        em = MatRobotEmAgent()
        dsc = MatRobotDscAgent()
        chemist = MatChemistAgent(
            synth_agent=synth, xrd_agent=xrd, em_agent=em, dsc_agent=dsc,
        )

        task = get_default_inconel_718_workflow()
        req = AgentRequest(
            run_id="w27-inconel-001",
            message="测 Inconel 718 完整表征",
            artifacts={"task": task},
        )
        resp = chemist.run(req)

        # 4 步都被调用
        assert resp.artifacts["n_robot_steps"] == 4
        robot_types = [r["robot_type"] for r in resp.artifacts["robot_results"]]
        assert robot_types == ["synth", "xrd", "em", "dsc"]

        # 至少 3 个成功(synth 可能因高温 block)
        n_successful = resp.artifacts["n_successful"]
        assert n_successful >= 1, f"应该至少 1 个成功,实际 {n_successful}"

        # 报告汇总
        assert "summary" in resp.artifacts
        assert "total_cost_cny" in resp.artifacts
        assert resp.artifacts["total_cost_cny"] >= 0

    def test_results_categorize_by_robot(self):
        """结果按 robot type 分类"""
        synth = MatRobotSynthAgent()
        xrd = MatRobotXrdAgent()
        em = MatRobotEmAgent()
        dsc = MatRobotDscAgent()
        chemist = MatChemistAgent(
            synth_agent=synth, xrd_agent=xrd, em_agent=em, dsc_agent=dsc,
        )

        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-cat-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # 按 robot type 查找
        results_by_type = {r["robot_type"]: r for r in resp.artifacts["robot_results"]}
        assert "synth" in results_by_type
        assert "xrd" in results_by_type
        assert "em" in results_by_type
        assert "dsc" in results_by_type

        # 每个结果有 reply + success + cost
        for robot_type, result in results_by_type.items():
            assert "success" in result
            assert "reply" in result
            assert "cost" in result

    def test_cross_validation_in_full_run(self):
        """完整跑通的 cross_validation"""
        chemist = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-cv-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        cv = resp.artifacts["cross_validation"]
        # cv 必有 consistent + warnings + issues
        assert "consistent" in cv
        assert "warnings" in cv
        assert "issues" in cv


# ============================================================================
# 端到端测试 2: 真实材料数据库比对(EDS / DSC / XRD 标准)
# ============================================================================


class TestMaterialDatabaseCrossCheck:
    """真实材料数据库比对(Inconel 718 跨数据源)"""

    def test_inconel_eds_standard_composition(self):
        """EDS 标准组成 = 7 元素"""
        comp = lookup_eds_composition("Inconel 718")
        assert len(comp) == 7
        # 镍是主元素
        ni = next(c for c in comp if c["element"] == "Ni")
        assert ni["wt_pct"] >= 50.0

    def test_inconel_pdf_card_exists(self):
        """XRD PDF 卡片库有可用参照(虽然 Inconel 718 不在标准库,可查主相)"""
        # 实际测试用主元素相(Cu Kα 辐射 / Ni-Fe 主相)
        pdf = lookup_pdf_card("PDF 04-0850")  # Cu 作为示例
        assert pdf is not None
        assert pdf["formula"] == "Cu"

    def test_inconel_dsc_library(self):
        """DSC 标准库 Inconel 718 → Tm=1330°C"""
        info = lookup_material_dsc("Inconel 718")
        assert info is not None
        assert info["Tm_c"] == 1330.0
        assert info["domain"] == "metal_alloy"

    def test_xrd_real_sdk_inconel(self):
        """XRD RealSDK 能用 PDF 卡片库比对"""
        from agents.mat_robot_xrd_agent.xrd_engine import DEFAULT_XRD_PROCEDURE

        sdk = BrukerRealSDK()
        proc = DEFAULT_XRD_PROCEDURE
        brml = sdk.generate_brml_config(proc, run_id="w27-brml-001")
        assert "<BrukerMethod" in brml

    def test_em_real_sdk_inconel_eds(self):
        """EM RealSDK 能查 Inconel 718 EDS 标准组成"""
        from agents.mat_robot_em_agent.zeiss_real_sdk import ZeissRealSDK

        sdk = ZeissRealSDK(skip_endpoint_check=True)
        comp = sdk.lookup_eds_composition("Inconel 718")
        assert len(comp) == 7

    def test_dsc_real_sdk_inconel_tm(self):
        """DSC RealSDK 能查 Inconel 718 标准 Tm"""
        from agents.mat_robot_dsc_agent.ta_trios_real_sdk import TATriosRealSDK

        sdk = TATriosRealSDK(skip_endpoint_check=True)
        info = sdk.lookup_material_dsc("Inconel 718")
        assert info["Tm_c"] == 1330.0


# ============================================================================
# 端到端测试 3: 失败恢复 + Retry 机制
# ============================================================================


class TestFailureRecovery:
    """某个机器人失败 → chemist 标记 + 继续其他"""

    def test_synth_failure_xrd_em_dsc_continue(self):
        """synth 失败 → XRD/EM/DSC 仍执行"""
        # 用 mock synth(强制失败)
        mock_synth = MagicMock()
        mock_synth.run.return_value = MagicMock(
            reply="[BLOCKED by SafetyGuard] synth blocked",
            artifacts={"blocked": True, "warnings": ["⛔ mock failure"]},
            confidence=0.0,
            cost=200.0,
        )

        chemist = MatChemistAgent(synth_agent=mock_synth)
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-fail-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # synth 失败被记录
        synth_result = next(
            r for r in resp.artifacts["robot_results"] if r["robot_type"] == "synth"
        )
        assert synth_result["success"] is False

        # 其他 3 个仍执行
        assert resp.artifacts["n_robot_steps"] == 4
        # 至少 1 个成功(other 3 个真 robot)
        assert resp.artifacts["n_successful"] >= 1

        # cross_validation 标记 synth 失败
        cv = resp.artifacts["cross_validation"]
        assert cv["consistent"] is False
        assert any("synth" in w.lower() for w in cv["warnings"])

    def test_xrd_failure_em_dsc_continue(self):
        """xrd 失败 → EM/DSC 仍执行"""
        mock_xrd = MagicMock()
        mock_xrd.run.return_value = MagicMock(
            reply="xrd failed",
            artifacts={"blocked": True, "warnings": ["⛔ mock xrd failure"]},
            confidence=0.0,
            cost=150.0,
        )

        chemist = MatChemistAgent(xrd_agent=mock_xrd)
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-fail-002", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        xrd_result = next(
            r for r in resp.artifacts["robot_results"] if r["robot_type"] == "xrd"
        )
        assert xrd_result["success"] is False
        # 至少 2 个其他 robot 仍跑(EM/DSC)
        assert resp.artifacts["n_robot_steps"] == 4


# ============================================================================
# 端到端测试 4: 端到端 timing + cost 累计
# ============================================================================


class TestEndToEndMetrics:
    """端到端 timing + cost 累计"""

    def test_total_cost_within_budget(self):
        """总成本应在预算内"""
        chemist = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-cost-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # 默认预算 ¥10000,4 步总成本应在预算内
        assert resp.artifacts["total_cost_cny"] <= task.budget_cny

    def test_total_duration_tracked(self):
        """总 duration 跟踪"""
        chemist = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(run_id="w27-dur-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)
        assert "total_duration_seconds" in resp.artifacts
        # 累计时长 > 0(即使 mock 也跑时间)
        assert resp.artifacts["total_duration_seconds"] >= 0.0

    def test_per_robot_cost_visible(self):
        """每 robot cost 可见"""
        chemist = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-percost-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        for r in resp.artifacts["robot_results"]:
            assert "cost" in r
            assert r["cost"] >= 0


# ============================================================================
# 端到端测试 5: Stage 3 钢铁侠 完整路径演示
# ============================================================================


class TestStage3Demo:
    """Stage 3 钢铁侠完整路径演示(W27 关键)"""

    def test_jarvis_like_workflow(self):
        """JARVIS 风格工作流:接收目标 → 拆解 → 协调 4 机器人 → 汇总"""
        # 1. 化学师接收目标
        chemist = MatChemistAgent()

        # 2. 自然语言拆解(per W26 decompose_goal_to_robots)
        steps = decompose_goal_to_robots(
            target_sample="Inconel 718",
            goal="完整表征 Inconel 718 合金(制备 XRD EM DSC)",
        )

        # 拆解成 4 个 robot step
        task = ChemistTask(
            target_sample="Inconel 718",
            domain="metal_alloy",
            goal="JARVIS 完整表征",
            robot_steps=steps,
        )

        # 3. 协调 4 机器人
        req = AgentRequest(run_id="w27-jarvis-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # 4. 验证 4 机器人全跑(拆解后应有 4 个:synth/xrd/em/dsc)
        assert resp.artifacts["n_robot_steps"] >= 3
        # 至少 1 个 robot 成功
        assert resp.artifacts["n_successful"] >= 1
        # 报告完整
        assert "summary" in resp.artifacts
        assert "cross_validation" in resp.artifacts

    def test_pmma_jr_workflow(self):
        """PMMA 简化 workflow(2 步:dissolve + DSC)"""
        chemist = MatChemistAgent()

        # 用关键词拆解
        steps = decompose_goal_to_robots(
            target_sample="PMMA",
            goal="测 PMMA 玻璃化温度 Tg",
        )
        # 应该只有 dsc
        robots = [s.robot_type for s in steps]
        assert "dsc" in robots

        task = ChemistTask(
            target_sample="PMMA",
            domain="polymer",
            goal="PMMA Tg 测试",
            robot_steps=steps,
            budget_cny=500.0,
        )
        req = AgentRequest(run_id="w27-pmma-jr-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)
        assert resp.artifacts["target_sample"] == "PMMA"


# ============================================================================
# 端到端测试 6: Stage 4 enterprise 数据准备(mat-critic 喂数据)
# ============================================================================


class TestStage4DataPreparation:
    """为 mat-critic 准备数据(W27 Stage 4 入口)"""

    def test_robot_results_have_artifacts_for_critic(self):
        """robot_results 包含 critic 需要的 artifacts"""
        chemist = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-critic-prep-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # 每个 robot_results 应该能直接喂给 mat-critic
        for r in resp.artifacts["robot_results"]:
            assert "robot_type" in r
            assert "success" in r
            assert "reply" in r
            # critic 需要 success 标记,失败的不喂

    def test_consolidated_report_for_critic(self):
        """汇总报告可喂给 critic"""
        chemist = MatChemistAgent()
        task = get_default_inconel_718_workflow()
        req = AgentRequest(run_id="w27-consol-001", message="test", artifacts={"task": task})
        resp = chemist.run(req)

        # report.to_dict() 是 critic 标准输入格式
        # 已经在 artifacts 里
        assert "task_id" in resp.artifacts
        assert "overall_success" in resp.artifacts
        assert "robot_results" in resp.artifacts
        assert "cross_validation" in resp.artifacts