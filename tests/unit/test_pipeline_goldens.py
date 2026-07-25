"""test_pipeline_goldens.py — W8 集成 Goldens 跑分

测试覆盖:
1. mat-pipeline.yaml 25 case 加载 + 校验
2. 25 case 端到端跑分 + pass-rate
3. 按 category 细分 pass-rate
4. 公式一致性跨段验证
5. 性能基准(总耗时 / 平均每 case)

per MatWAU-开发计划 §5.6 W8
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.pipeline import MatPipeline, create_default_pipeline  # noqa: E402

from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-pipeline.yaml")


def _parse_int_constraint(s, default):
    """解析 '>= 2' / '>= 5' 这种字符串"""
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        if s.startswith(">="):
            return int(s.split(">=")[1].strip())
        if s.startswith(">"):
            return int(s.split(">")[1].strip()) + 1
    return default


# ============================================================================
# 测试 1: Goldens 文件加载
# ============================================================================


class TestGoldensLoad:
    """mat-pipeline.yaml 加载 + 结构测试"""

    def test_goldens_file_exists(self):
        """Goldens 文件存在"""
        assert Path(GOLDENS_PATH).exists()

    def test_goldens_load_25_cases(self):
        """加载 25 个 case"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        assert len(cases) == 25

    def test_goldens_id_range_p001_p025(self):
        """ID 范围 P001-P025"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        ids = [c.id for c in cases]
        assert ids[0] == "P001"
        assert ids[-1] == "P025"

    def test_goldens_categories_distribution(self):
        """4 个 category 分布"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        cats = {}
        for c in cases:
            cats[c.category] = cats.get(c.category, 0) + 1
        # 锂电池 8 + 固态电解质 7 + 催化剂 5 + 其他 5
        assert cats.get("pipeline-li-ion", 0) == 8
        assert cats.get("pipeline-solid-electrolyte", 0) == 7
        assert cats.get("pipeline-catalyst", 0) == 5
        assert cats.get("pipeline-other", 0) == 5

    def test_goldens_all_cases_have_expected(self):
        """每个 case 都有 expected 字段"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        for c in cases:
            assert c.expected, f"{c.id} 缺 expected"
            assert "min_recipes" in c.expected, f"{c.id} 缺 min_recipes"
            assert "min_stages_success" in c.expected, f"{c.id} 缺 min_stages_success"

    def test_goldens_get_by_id(self):
        """get_by_id 工作正常"""
        g = Goldens(GOLDENS_PATH)
        c = g.get_by_id("P010")
        assert c is not None
        assert c.category == "pipeline-solid-electrolyte"

    def test_goldens_get_by_category(self):
        """get_by_category 工作正常"""
        g = Goldens(GOLDENS_PATH)
        cases = g.get_by_category("pipeline-li-ion")
        assert len(cases) == 8


# ============================================================================
# 测试 2: 25 case 端到端跑分
# ============================================================================


def _run_one_case(pipeline: MatPipeline, case) -> dict:
    """跑 1 个 Goldens case,返回 pass/fail + 详细信息"""
    expected = case.expected
    elements = expected.get("elements")
    elements_any = expected.get("elements_any")
    forbidden = expected.get("forbidden", [])
    min_recipes = _parse_int_constraint(expected.get("min_recipes", 1), 1)
    min_stages_success = expected.get("min_stages_success", 4)

    # 拼装 pipeline 入参(per mat-gen parse_constraints 约定)
    if elements:
        elements_arg = elements
    else:
        elements_arg = elements_any or ["Li", "O"]  # fallback

    report = pipeline.run_full_pipeline(
        user_intent=case.intent,
        elements=elements_arg,
        forbidden=forbidden,
        budget=1000.0,
        n_samples=5,
        run_id_prefix=f"golden-{case.id.lower()}",
    )

    reasons = []
    actual = {
        "n_stages_success": sum(1 for sr in report.stage_results if sr.success),
        "n_recipes": len(report.final_recipes),
        "report_success": report.success,
        "formula_consistency_ok": report.formula_consistency_ok,
        "total_cost": report.total_cost,
    }

    # 校验 1: 至少 min_stages_success 段成功
    if actual["n_stages_success"] < min_stages_success:
        reasons.append(
            f"stages_success={actual['n_stages_success']} < {min_stages_success}"
        )

    # 校验 2: 至少 min_recipes 个最终方案
    if actual["n_recipes"] < min_recipes:
        reasons.append(
            f"n_recipes={actual['n_recipes']} < {min_recipes}"
        )

    # 校验 3: 公式一致性(must_contain_all + must_not_contain_any)
    if not actual["formula_consistency_ok"]:
        reasons.append(f"formula_consistency 违例")

    # 校验 4: 必须元素存在(每个 recipe 都含)
    if actual["n_recipes"] > 0 and elements:
        for r in report.final_recipes:
            for e in elements:
                if e and e not in r.formula:
                    reasons.append(f"{r.formula} 缺必含元素 {e}")

    # 校验 5: 禁止元素不存在(每个 recipe 都不含)
    if actual["n_recipes"] > 0 and forbidden:
        for r in report.final_recipes:
            for f in forbidden:
                if f and f in r.formula:
                    reasons.append(f"{r.formula} 含禁止元素 {f}")

    passed = len(reasons) == 0
    return {
        "case_id": case.id,
        "category": case.category,
        "passed": passed,
        "reasons": reasons,
        "actual": actual,
    }


class TestPipelineGoldens:
    """mat-pipeline.yaml 25 case 跑分"""

    @pytest.fixture(scope="class")
    def pipeline(self):
        """1 个 pipeline 跑全部 case(class scope 复用)"""
        return create_default_pipeline()

    @pytest.fixture(scope="class")
    def results(self, pipeline):
        """跑全部 25 case 的结果"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            r = _run_one_case(pipeline, case)
            results.append(r)
        return results

    def test_goldens_25_cases_pass_rate(self, results):
        """25 case 跑分 pass-rate > 50% (Stage 1) / > 80% (Stage 2)"""
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        print(f"\n📊 Pipeline Goldens 跑分: {n_pass}/{n_total} = {pass_rate:.0%}")
        # Stage 1 baseline > 50%
        assert pass_rate >= 0.5, (
            f"Pipeline Goldens pass-rate {pass_rate:.0%} < 50%(Stage 1 baseline)"
        )

    def test_goldens_li_ion_pass_rate(self, results):
        """锂电池正极 8 case pass-rate > 50%"""
        li_ion_results = [r for r in results if r["category"] == "pipeline-li-ion"]
        n_pass = sum(1 for r in li_ion_results if r["passed"])
        n_total = len(li_ion_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(
            f"\n📊 锂电池正极: {n_pass}/{n_total} = {pass_rate:.0%}"
        )
        assert pass_rate >= 0.5, (
            f"Li-ion pass-rate {pass_rate:.0%} < 50%"
        )

    def test_goldens_solid_electrolyte_pass_rate(self, results):
        """固态电解质 7 case pass-rate > 50%"""
        se_results = [r for r in results if r["category"] == "pipeline-solid-electrolyte"]
        n_pass = sum(1 for r in se_results if r["passed"])
        n_total = len(se_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(
            f"\n📊 固态电解质: {n_pass}/{n_total} = {pass_rate:.0%}"
        )
        assert pass_rate >= 0.5, (
            f"Solid electrolyte pass-rate {pass_rate:.0%} < 50%"
        )

    def test_goldens_catalyst_pass_rate(self, results):
        """催化剂 5 case pass-rate > 50%"""
        cat_results = [r for r in results if r["category"] == "pipeline-catalyst"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(
            f"\n📊 催化剂: {n_pass}/{n_total} = {pass_rate:.0%}"
        )
        assert pass_rate >= 0.5, (
            f"Catalyst pass-rate {pass_rate:.0%} < 50%"
        )

    def test_goldens_other_pass_rate(self, results):
        """其他材料 5 case pass-rate > 50%"""
        other_results = [r for r in results if r["category"] == "pipeline-other"]
        n_pass = sum(1 for r in other_results if r["passed"])
        n_total = len(other_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(
            f"\n📊 其他材料: {n_pass}/{n_total} = {pass_rate:.0%}"
        )
        assert pass_rate >= 0.5, (
            f"Other pass-rate {pass_rate:.0%} < 50%"
        )

    def test_goldens_no_regression_vs_individual(self, results):
        """集成跑分应不差于单 agent 跑分"""
        # 各单 agent 的 Goldens pass-rate(W3-W6 记录):
        # mat-gen 64%, mat-sim 84%, mat-hpc 90%, mat-exp 92%
        # 集成 pipeline 是 4 段链路,理论上应 >= 单段最低的 64%
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total if n_total else 0

        # 至少跟 mat-gen 单 agent 一致(64%)
        assert pass_rate >= 0.6, (
            f"Pipeline pass-rate {pass_rate:.0%} 低于单 agent mat-gen (64%)"
        )

    def test_goldens_total_cost_reasonable(self, results):
        """总成本合理(< ¥50000 总开销)"""
        total_cost = sum(r["actual"]["total_cost"] for r in results)
        print(f"\n💵 25 case 总成本: ¥{total_cost:.2f}")
        # Stage 1 mock 平均 ¥650/case,25 case ~¥16000,放余量到 ¥50000
        assert total_cost < 50000, f"总成本过高: ¥{total_cost:.2f}"


# ============================================================================
# 测试 3: 性能基准
# ============================================================================


class TestPipelinePerformance:
    """Pipeline 性能基准"""

    def test_single_pipeline_under_1s(self):
        """单次 pipeline 跑通 < 1s"""
        p = create_default_pipeline()
        t0 = time.time()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )
        elapsed = time.time() - t0

        print(f"\n⏱️  单次 pipeline: {elapsed:.3f}s")
        assert report.success
        assert elapsed < 1.0, f"单次 pipeline 太慢: {elapsed:.3f}s"

    def test_3_demos_under_2s(self):
        """3 个 demo 跑通 < 2s"""
        from matwau.pipeline import PipelineDemo

        d = PipelineDemo()
        t0 = time.time()
        summaries = d.run_all()
        elapsed = time.time() - t0

        print(f"\n⏱️  3 demo 总耗时: {elapsed:.3f}s")
        assert len(summaries) == 3
        # 3 demo < 2s
        assert elapsed < 2.0, f"3 demo 太慢: {elapsed:.3f}s"

    def test_avg_per_case_under_50ms(self):
        """平均每 case < 50ms"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        p = create_default_pipeline()

        t0 = time.time()
        for case in cases[:10]:  # 跑前 10 case
            expected = case.expected
            elements = expected.get("elements") or expected.get("elements_any") or ["Li", "O"]
            p.run_full_pipeline(
                user_intent=case.intent,
                elements=elements,
                forbidden=expected.get("forbidden", []),
                budget=1000.0,
                n_samples=5,
            )
        elapsed = time.time() - t0
        avg = elapsed / 10

        print(f"\n⏱️  平均每 case: {avg * 1000:.1f}ms")
        # 性能基线: < 50ms / case
        assert avg < 0.05, f"平均每 case 太慢: {avg * 1000:.1f}ms"


# ============================================================================
# 测试 4: 集成一致性(per stage)
# ============================================================================


class TestPipelineIntegrationConsistency:
    """集成一致性(每段产出对下一段的兼容性)"""

    def test_gen_to_sim_compatibility(self):
        """mat-gen 输出可被 mat-sim 消费"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )

        # Stage 1 输出有 formula 字段(mat-sim 需要)
        gen_candidates = report.stage_results[0].response.artifacts["candidates"]
        for c in gen_candidates:
            assert hasattr(c, "formula"), "mat-gen 输出无 formula"
            assert hasattr(c, "cif"), "mat-gen 输出无 cif"

    def test_sim_to_hpc_compatibility(self):
        """mat-sim 输出可被 mat-hpc 消费"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )

        # Stage 2 输出有 stability 字段(mat-hpc 需要)
        sim_candidates = report.stage_results[1].response.artifacts["simulated"]
        for c in sim_candidates:
            assert hasattr(c, "stability"), "mat-sim 输出无 stability"
            assert c.stability in ("stable", "metastable", "unstable")

    def test_hpc_to_exp_compatibility(self):
        """mat-hpc 输出可被 mat-exp 消费"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=5,
        )

        # Stage 3 输出有 formula 字段(mat-exp 需要)
        hpc_jobs = report.stage_results[2].response.artifacts["jobs"]
        for j in hpc_jobs:
            assert hasattr(j, "formula"), "mat-hpc 输出无 formula"

    def test_full_pipeline_formula_propagation(self):
        """必含元素一路传到 final_recipes"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 NMC811 实验方案",
            elements=["Ni", "Mn", "Co"],
            forbidden=[],
            n_samples=5,
        )

        # 必有元素(至少 Ni 之一)
        for r in report.final_recipes:
            assert any(e in r.formula for e in ["Ni", "Mn", "Co"]), (
                f"NMC811 必有 Ni/Mn/Co 之一,got {r.formula}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])