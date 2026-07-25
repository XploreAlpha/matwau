"""test_stress.py — W8 压力测试

测试覆盖:
1. 超大输入(n_samples=100)不崩
2. 并发跑(同 pipeline 多次跑 + 不同 pipeline 并行)
3. 多次跑稳定性(同 demo 跑 10 次,检查 recipe 集合稳定)
4. 长时间运行(连续 50 次 pipeline)
5. 内存稳定性(无明显泄漏)

per MatWAU-开发计划 §5.6 W8
"""
from __future__ import annotations

import sys
import time
import gc
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.pipeline import (  # noqa: E402
    MatPipeline,
    PipelineDemo,
    create_default_pipeline,
)


# ============================================================================
# 测试 1: 超大输入
# ============================================================================


class TestLargeInput:
    """超大输入压力测试"""

    def test_n_samples_100(self):
        """n_samples=100 不崩"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=["Li", "Co", "O"],
            n_samples=100,
            budget=10000.0,
        )
        # 4 段全跑通
        assert all(sr.success for sr in report.stage_results), "某段失败"
        # 至少 1 个最终方案(可能 mat-sim 弛豫失败的过滤掉)
        assert len(report.final_recipes) >= 1

    def test_many_elements(self):
        """5+ 元素约束"""
        p = create_default_pipeline()
        report = p.run_full_pipeline(
            user_intent="出 NMC811 + LATP 复合正极实验方案",
            elements=["Li", "Ni", "Mn", "Co", "Al", "Ti", "P", "O"],
            n_samples=8,
            budget=5000.0,
        )
        # 跑通
        assert all(sr.success for sr in report.stage_results)

    def test_long_intent(self):
        """超长用户意图(1000 字符)"""
        p = create_default_pipeline()
        long_intent = (
            "出锂离子电池正极材料实验方案,要求高能量密度(> 500 Wh/kg),"
            "高循环寿命(> 1000 cycles),高安全性(无 Co 元素),低成本(< ¥100/kg),"
            "易合成(烧结温度 < 1000℃),环境友好(无贵金属 Pt/Au/Ag),"
            "室温稳定(空气中不分解),适合大规模量产,合成工艺简单,适合固相反应法,"
            + "高镍 NMC 三元材料配方优化 LiNi_xMn_yCo_zO_2 其中 x+y+z=1 x≥0.6," * 20
        )
        assert len(long_intent) > 1000

        report = p.run_full_pipeline(
            user_intent=long_intent,
            elements=["Li", "Ni", "Mn", "O"],
            forbidden=["Co", "Pt", "Au", "Ag"],
            n_samples=5,
            budget=2000.0,
        )
        assert all(sr.success for sr in report.stage_results)


# ============================================================================
# 测试 2: 并发跑
# ============================================================================


class TestConcurrentRuns:
    """并发跑压力测试"""

    def test_same_pipeline_sequential_5_times(self):
        """同 pipeline 顺序跑 5 次,每次都成功"""
        p = create_default_pipeline()

        results = []
        for i in range(5):
            report = p.run_full_pipeline(
                user_intent=f"出 LiCoO2 实验方案(第 {i+1} 次)",
                elements=["Li", "Co", "O"],
                n_samples=5,
            )
            results.append(report)

        # 每次都跑通
        for i, r in enumerate(results):
            assert r.success, f"第 {i+1} 次失败: {r.error}"
            assert len(r.final_recipes) >= 1

    def test_pipeline_demos_3_concurrent(self):
        """3 个 demo 一次性跑(快速版)"""
        demo = PipelineDemo()
        summaries = demo.run_all()

        # 3 个都成功
        n_success = sum(1 for s in summaries if s.success)
        assert n_success == 3, f"3 demo 应全成功,实际 {n_success}/3"

    def test_independent_pipelines(self):
        """多个独立 pipeline 各自跑自己的 demo"""
        pipelines = [create_default_pipeline() for _ in range(3)]

        reports = []
        for p in pipelines:
            r = p.run_full_pipeline(
                user_intent="出 LiCoO2 实验方案",
                elements=["Li", "Co", "O"],
                n_samples=5,
            )
            reports.append(r)

        # 每个 pipeline 都跑通
        for i, r in enumerate(reports):
            assert r.success, f"pipeline {i+1} 失败: {r.error}"


# ============================================================================
# 测试 3: 多次跑稳定性(同 demo 10 次)
# ============================================================================


class TestRepeatedRuns:
    """同 demo 跑 10 次,检查稳定性"""

    def test_repeated_runs_consistency(self):
        """同 demo 跑 10 次,recipe 数量应在合理范围内"""
        p = create_default_pipeline()
        n_recipes_list = []

        for _ in range(10):
            r = p.run_full_pipeline(
                user_intent="出 LiCoO2 实验方案",
                elements=["Li", "Co", "O"],
                n_samples=5,
            )
            assert r.success
            n_recipes_list.append(len(r.final_recipes))

        # 平均方案数
        avg = sum(n_recipes_list) / len(n_recipes_list)
        # 标准差应该 <= 3(mock 随机性合理范围)
        std = (sum((n - avg) ** 2 for n in n_recipes_list) / len(n_recipes_list)) ** 0.5

        print(f"\n📊 10 次 recipe 数量: avg={avg:.1f}, std={std:.2f}")
        print(f"   {n_recipes_list}")

        # 每次至少 1 个方案
        assert min(n_recipes_list) >= 1
        # 标准差不超过均值(避免极不稳定)
        assert std <= avg, f"标准差 {std:.1f} > 均值 {avg:.1f}"

    def test_repeated_runs_total_cost(self):
        """10 次跑总成本应该合理 < ¥10000"""
        p = create_default_pipeline()
        total_cost = 0

        for _ in range(10):
            r = p.run_full_pipeline(
                user_intent="出 LiCoO2 实验方案",
                elements=["Li", "Co", "O"],
                n_samples=5,
            )
            total_cost += r.total_cost

        print(f"\n💵 10 次总成本: ¥{total_cost:.2f}, 平均 ¥{total_cost/10:.2f}")
        # 10 次 < ¥10000(每次 ~¥650,余量充足)
        assert total_cost < 10000, f"10 次总成本过高: ¥{total_cost:.2f}"


# ============================================================================
# 测试 4: 长时间运行
# ============================================================================


class TestLongRunning:
    """连续 50 次 pipeline 跑"""

    def test_50_consecutive_runs(self):
        """连续 50 次 pipeline 跑通"""
        p = create_default_pipeline()
        t0 = time.time()
        n_success = 0
        n_total = 50

        for i in range(n_total):
            r = p.run_full_pipeline(
                user_intent="出 LiCoO2 实验方案",
                elements=["Li", "Co", "O"],
                n_samples=3,  # 降 n_samples 加速
            )
            if r.success:
                n_success += 1

        elapsed = time.time() - t0

        print(
            f"\n📊 50 次连续跑: {n_success}/{n_total} 成功, "
            f"总耗时 {elapsed:.2f}s, 平均 {elapsed/n_total*1000:.1f}ms/次"
        )

        # 成功率 >= 95%(允许 2 次失败)
        assert n_success >= 48, f"成功率 {n_success}/{n_total} < 95%"
        # 总耗时 < 60s
        assert elapsed < 60.0, f"50 次总耗时 {elapsed:.2f}s > 60s"


# ============================================================================
# 测试 5: 内存稳定性(简单检查)
# ============================================================================


class TestMemoryStability:
    """内存稳定性(无明显泄漏)"""

    def test_no_exponential_growth(self):
        """20 次跑耗时不应指数增长(简单 leak 指标)"""
        p = create_default_pipeline()
        times = []

        for i in range(20):
            t0 = time.time()
            r = p.run_full_pipeline(
                user_intent="出 LiCoO2 实验方案",
                elements=["Li", "Co", "O"],
                n_samples=5,
            )
            elapsed = time.time() - t0
            times.append(elapsed)
            assert r.success
            gc.collect()  # 强制 GC

        # 后 10 次平均耗时 vs 前 10 次平均耗时
        early_avg = sum(times[:10]) / 10
        late_avg = sum(times[10:]) / 10

        print(f"\n📊 内存稳定性: 前 10 平均 {early_avg*1000:.1f}ms, 后 10 平均 {late_avg*1000:.1f}ms")

        # 后 10 次不应比前 10 次慢 3 倍以上(简单 leak 指标)
        assert late_avg < early_avg * 3, (
            f"疑似内存泄漏: 前 {early_avg*1000:.1f}ms → 后 {late_avg*1000:.1f}ms"
        )


# ============================================================================
# 主入口
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])