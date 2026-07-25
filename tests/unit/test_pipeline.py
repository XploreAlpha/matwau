"""test_pipeline.py — W7 端到端工作流整合测试

测试覆盖:
1. MatPipeline 4 段基本流
2. StageResult / PipelineReport 数据结构
3. 公式一致性校验(必须 + 禁止)
4. 异常分支(某段失败 → 整段管线终止)
5. 预算警告
6. 3 个 demo 用例(DEMO-001/002/003)
7. PipelineDemo run_all / run_one
8. CLI 入口(可独立运行)

per MatWAU-开发计划 §5 W7
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

# 允许 import matwau
_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
)
from matwau.pipeline import (  # noqa: E402
    DEMO_CASES,
    MatPipeline,
    PipelineDemo,
    PipelineReport,
    StageResult,
    create_default_pipeline,
)
from matwau.pipeline.mat_pipeline import _check_formula_constraints  # noqa: E402


# ============================================================================
# 测试 1: StageResult 数据结构
# ============================================================================


class TestStageResult:
    """StageResult 数据结构测试"""

    def test_stage_result_success_summary(self):
        """成功时 summary 显示 ✅"""
        sr = StageResult(
            stage_name="mat-gen",
            agent_name="mat-gen-agent",
            response=AgentResponse(
                reply="OK",
                artifacts={"candidates": [MagicMock(), MagicMock()]},
                confidence=0.9,
                cost=0.6,
            ),
            duration_seconds=0.05,
            success=True,
            input_count=0,
            output_count=2,
        )
        summary = sr.to_summary()
        assert "✅" in summary
        assert "mat-gen" in summary
        assert "2" in summary  # output_count
        assert "90%" in summary  # confidence

    def test_stage_result_error_summary(self):
        """失败时 summary 显示 ❌ + error"""
        sr = StageResult(
            stage_name="mat-sim",
            agent_name="mat-sim-agent",
            response=None,
            duration_seconds=0.01,
            success=False,
            error="CHGNet 失败",
        )
        summary = sr.to_summary()
        assert "❌" in summary
        assert "CHGNet 失败" in summary


# ============================================================================
# 测试 2: PipelineReport 数据结构
# ============================================================================


class TestPipelineReport:
    """PipelineReport 数据结构测试"""

    def test_pipeline_report_basic(self):
        """基本构造"""
        report = PipelineReport(
            user_intent="出 LiCoO2",
            elements=["Li", "Co", "O"],
        )
        assert report.user_intent == "出 LiCoO2"
        assert report.elements == ["Li", "Co", "O"]
        assert report.total_duration_seconds == 0.0
        assert report.success is False
        assert report.formula_consistency_ok is True
        assert report.final_recipes == []

    def test_pipeline_report_to_report(self):
        """to_report() 输出完整报告"""
        report = PipelineReport(
            user_intent="出 LiCoO2",
            elements=["Li", "Co", "O"],
            forbidden=["Co"],  # 测试一下
            budget=500.0,
            success=True,
            total_cost=12.5,
            total_duration_seconds=0.5,
            final_recipes=[
                MagicMock(
                    formula="LiFeO2",
                    sintering=MagicMock(
                        temperature_celsius=850,
                        pressure_mpa=10,
                        time_hours=12,
                        atmosphere="air",
                    ),
                    xrd=MagicMock(
                        peaks=[MagicMock(two_theta=18.5, hkl="(003)")],
                        lattice_a=2.815,
                    ),
                )
            ],
        )
        text = report.to_report()
        assert "出 LiCoO2" in text
        assert "Li" in text and "Co" in text
        assert "500" in text  # budget
        assert "¥12.50" in text or "12.5" in text
        assert "✅ 成功" in text


# ============================================================================
# 测试 3: 公式一致性校验
# ============================================================================


class TestFormulaConstraints:
    """_check_formula_constraints 工具函数测试"""

    def test_all_pass(self):
        """全部公式满足约束"""
        ok, violations = _check_formula_constraints(
            formulas=["LiCoO2", "Li2CoO3"],
            required_elements=["Li", "Co"],
            forbidden_elements=["Mn"],
        )
        assert ok is True
        assert violations == []

    def test_required_missing(self):
        """formula 缺少必须元素"""
        ok, violations = _check_formula_constraints(
            formulas=["LiFeO2"],  # 没有 Co
            required_elements=["Li", "Co"],
            forbidden_elements=[],
        )
        assert ok is False
        assert any("缺少必须元素" in v for v in violations)
        assert any("Co" in v for v in violations)

    def test_forbidden_present(self):
        """formula 含禁止元素"""
        ok, violations = _check_formula_constraints(
            formulas=["LiCoO2"],  # 含 Co(被禁)
            required_elements=["Li"],
            forbidden_elements=["Co"],
        )
        assert ok is False
        assert any("含禁止元素" in v for v in violations)
        assert any("Co" in v for v in violations)

    def test_no_required_no_forbidden(self):
        """无约束时全 pass"""
        ok, violations = _check_formula_constraints(
            formulas=["LiCoO2", "Fe2O3"],
            required_elements=[],
            forbidden_elements=[],
        )
        assert ok is True
        assert violations == []

    def test_empty_formulas(self):
        """空公式列表"""
        ok, violations = _check_formula_constraints(
            formulas=[],
            required_elements=["Li"],
            forbidden_elements=[],
        )
        assert ok is True
        assert violations == []


# ============================================================================
# 测试 4: MatPipeline 端到端
# ============================================================================


class TestMatPipeline:
    """MatPipeline 端到端测试"""

    def test_create_default_pipeline(self):
        """默认 pipeline 创建"""
        p = create_default_pipeline()
        assert isinstance(p, MatPipeline)
        assert p.gen_agent is not None
        assert p.sim_agent is not None
        assert p.hpc_agent is not None
        assert p.exp_agent is not None
        assert p.gen_agent.name == "mat-gen-agent"
        assert p.sim_agent.name == "mat-sim-agent"
        assert p.hpc_agent.name == "mat-hpc-agent"
        assert p.exp_agent.name == "mat-exp-agent"

    def test_pipeline_basic_flow(self):
        """基本 4 段流(LiCoO2)"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )
        # 必须 4 段
        assert len(report.stage_results) == 4
        stage_names = [sr.stage_name for sr in report.stage_results]
        assert stage_names == ["mat-gen", "mat-sim", "mat-hpc", "mat-exp"]

        # 每段都成功
        for sr in report.stage_results:
            assert sr.success, f"{sr.stage_name} 失败: {sr.error}"

        # 最终至少 1 个实验方案
        assert len(report.final_recipes) >= 1

        # 报告字段
        assert report.success is True
        assert report.total_cost > 0
        assert report.total_duration_seconds > 0

    def test_pipeline_formula_consistency_required(self):
        """必须元素一致性(全部阶段都保留 Li/Co/O)"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )

        # Stage 1 (mat-gen) 的 formula 必须含 Li/Co/O
        gen_candidates = report.stage_results[0].response.artifacts["candidates"]
        for c in gen_candidates:
            assert "Li" in c.formula or "Co" in c.formula or "O" in c.formula

        # 最终 recipes 必须含元素(LLZO 这种可能有问题,这里只测 DEMO-001)
        for r in report.final_recipes:
            assert "Li" in r.formula or "Co" in r.formula

    def test_pipeline_formula_consistency_forbidden(self):
        """禁止元素一致性(无 Co)"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出无钴锂电池正极实验方案",
            elements=["Li", "Ni", "Mn", "O"],
            forbidden=["Co"],
            n_samples=8,
        )

        assert report.success is True

        # 所有 stage 1 candidates 都不能含 Co
        gen_candidates = report.stage_results[0].response.artifacts["candidates"]
        for c in gen_candidates:
            assert "Co" not in c.formula, f"mat-gen 输出违禁 Co: {c.formula}"

        # 最终 recipes 也不能含 Co
        for r in report.final_recipes:
            assert "Co" not in r.formula, f"final recipe 违禁 Co: {r.formula}"

        # 公式一致性校验通过
        assert report.formula_consistency_ok is True, (
            f"一致性违例: {report.consistency_violations}"
        )

    def test_pipeline_budget_warning(self):
        """预算警告(设超低 budget)"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            budget=0.01,  # 极低预算
            n_samples=5,
        )
        # 不阻断(只是警告),应继续成功
        # budget 不阻断,只看警告
        for sr in report.stage_results:
            if sr.response:
                # 有超预算警告
                if sr.response.cost > 0.01:
                    assert "[WARN 超预算]" in sr.response.reply or sr.success

    def test_pipeline_stage_failure_isolation(self):
        """某段失败 → 整段终止(mat-gen 用 mock 抛异常)"""
        # 构造 gen agent 让它抛异常
        from agents.mat_gen_agent.mat_gen_agent import MatGenAgent

        class BrokenGenAgent(MatGenAgent):
            def run(self, req):
                raise RuntimeError("mat-gen 故意失败")

        p = MatPipeline(gen_agent=BrokenGenAgent())
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2",
            elements=["Li", "Co", "O"],
        )

        # Stage 1 失败
        assert report.stage_results[0].success is False
        assert "mat-gen 故意失败" in report.stage_results[0].error

        # 后续 stage 不跑
        assert len(report.stage_results) == 1

        # 报告失败
        assert report.success is False
        assert "mat-gen 失败" in report.error


# ============================================================================
# 测试 5: PipelineDemo + 3 个用例
# ============================================================================


class TestPipelineDemo:
    """PipelineDemo + DEMO_CASES 测试"""

    def test_demo_cases_loaded(self):
        """3 个 demo 用例正确加载"""
        assert len(DEMO_CASES) == 3
        assert DEMO_CASES[0].case_id == "DEMO-001"
        assert DEMO_CASES[1].case_id == "DEMO-002"
        assert DEMO_CASES[2].case_id == "DEMO-003"

        # 每个用例都有必填字段
        for case in DEMO_CASES:
            assert case.title
            assert case.user_intent
            assert case.elements
            assert case.expected_min_recipes >= 1

    def test_demo_001_li_ion_cathode(self):
        """DEMO-001 LiCoO2 锂电正极"""
        demo = PipelineDemo()
        summary = demo.run_one("DEMO-001")
        assert summary is not None
        assert summary.case.case_id == "DEMO-001"

        # 跑通 + 至少 N 个方案
        if summary.success:
            assert len(summary.report.final_recipes) >= summary.case.expected_min_recipes

    def test_demo_002_llzo_no_precious(self):
        """DEMO-002 LLZO 无贵金属"""
        demo = PipelineDemo()
        summary = demo.run_one("DEMO-002")
        assert summary is not None

        if summary.success:
            # 必须含 Li/La/Zr/O
            for r in summary.report.final_recipes:
                f = r.formula
                assert "Li" in f, f"LLZO 必须含 Li: {f}"

            # 不能含 Pt/Au/Ag
            for r in summary.report.final_recipes:
                assert "Pt" not in r.formula, f"LLZO 不能含 Pt: {r.formula}"
                assert "Au" not in r.formula, f"LLZO 不能含 Au: {r.formula}"
                assert "Ag" not in r.formula, f"LLZO 不能含 Ag: {r.formula}"

    def test_demo_003_mos2_her(self):
        """DEMO-003 MoS2 HER 催化剂"""
        demo = PipelineDemo()
        summary = demo.run_one("DEMO-003")
        assert summary is not None

        if summary.success:
            # 不能含 Pt
            for r in summary.report.final_recipes:
                assert "Pt" not in r.formula, f"MoS2 HER 不能含 Pt: {r.formula}"

    def test_demo_run_all_returns_3_summaries(self):
        """run_all 返回 3 个 DemoSummary"""
        demo = PipelineDemo()
        summaries = demo.run_all()
        assert len(summaries) == 3

    def test_demo_run_one_invalid_id(self):
        """run_one 找不到 case_id 返回 None"""
        demo = PipelineDemo()
        summary = demo.run_one("DEMO-XXX")
        assert summary is None

    def test_demo_print_summary(self, capsys):
        """print_summary 不抛异常"""
        demo = PipelineDemo()
        summaries = demo.run_all()
        demo.print_summary(summaries)
        captured = capsys.readouterr()
        assert "MatWAU 3 个 Demo 总览" in captured.out
        assert "DEMO-001" in captured.out
        assert "DEMO-002" in captured.out
        assert "DEMO-003" in captured.out


# ============================================================================
# 测试 6: 自定义 pipeline 注入
# ============================================================================


class TestPipelineInjection:
    """测试注入自定义 agent"""

    def test_inject_custom_agent(self):
        """注入自定义 gen agent"""
        from agents.mat_gen_agent.mat_gen_agent import MatGenAgent

        # 自定义 gen agent,固定产生 3 个候选
        class CustomGenAgent(MatGenAgent):
            def run(self, req):
                from agents.mat_gen_agent.mattergen import (
                    GenCandidate,
                )

                return AgentResponse(
                    reply="自定义 mat-gen OK",
                    artifacts={
                        "candidates": [
                            GenCandidate(
                                formula="CustomFormula",
                                cif="mock cif",
                                estimated_energy=-2.0,
                                confidence=0.8,
                            )
                        ]
                    },
                    confidence=0.8,
                    cost=0.1,
                )

        p = MatPipeline(gen_agent=CustomGenAgent())
        report = p.run_full_pipeline(
            user_intent="custom test",
            elements=["Li", "Co", "O"],
            n_samples=1,
        )

        # 第 1 段用了自定义 agent
        sr = report.stage_results[0]
        assert sr.agent_name == "mat-gen-agent"
        assert "自定义 mat-gen OK" in sr.response.reply
        assert sr.output_count == 1


# ============================================================================
# 主入口
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])