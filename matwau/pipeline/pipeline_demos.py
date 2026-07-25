"""PipelineDemo — 3 个典型用例(锂电池正极 / 固态电解质 / 催化剂)

Stage 1 mock 用例,演示 4 段管线在真实场景下的表现
Stage 2 接真模型后,这些用例会跑出真 XRD 谱 + 真烧结参数

per MatWAU-开发计划 §5 W7 + W7 demo 收口
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

_PIPELINE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PIPELINE_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.pipeline.mat_pipeline import (  # noqa: E402
    MatPipeline,
    PipelineReport,
    create_default_pipeline,
)


# ============================================================================
# Demo 用例定义
# ============================================================================


@dataclass
class DemoCase:
    """1 个 demo 用例的定义"""

    case_id: str  # "DEMO-001"
    title: str  # "锂电池正极材料"
    user_intent: str  # "出 LiCoO2 实验方案"
    elements: List[str]  # ["Li", "Co", "O"]
    forbidden: List[str]  # [] (无)
    budget: Optional[float]  # 500.0
    expected_min_recipes: int  # 期望最少实验方案数
    description: str  # 用例描述


DEMO_CASES: List[DemoCase] = [
    DemoCase(
        case_id="DEMO-001",
        title="锂电池正极材料(LiCoO2)",
        user_intent="出 LiCoO2 锂电池正极材料实验方案,XRD + 烧结",
        elements=["Li", "Co", "O"],
        forbidden=[],
        budget=500.0,
        expected_min_recipes=2,
        description="经典锂电正极材料,Stage 1 mock 出 XRD 谱 + 烧结 850℃/air/12h",
    ),
    DemoCase(
        case_id="DEMO-002",
        title="固态电解质(LLZO)",
        user_intent="出 Li7La3Zr2O12 LLZO 固态电解质实验方案",
        elements=["Li", "La", "Zr", "O"],
        forbidden=["Pt", "Au", "Ag"],  # 无贵金属
        budget=800.0,
        expected_min_recipes=2,
        description="氧化物固态电解质,无贵金属约束,Stage 1 mock 出 1100℃/air/24h",
    ),
    DemoCase(
        case_id="DEMO-003",
        title="析氢催化剂(MoS2)",
        user_intent="出 MoS2 析氢催化剂实验方案",
        elements=["Mo", "S"],
        forbidden=["Pt"],  # 无 Pt(避免贵金属)
        budget=300.0,
        expected_min_recipes=2,
        description="HER 催化剂,无 Pt 约束,Stage 1 mock 出 500℃/air/6h",
    ),
]


# ============================================================================
# PipelineDemo
# ============================================================================


@dataclass
class DemoSummary:
    """1 个 demo 的执行摘要"""

    case: DemoCase
    report: PipelineReport
    success: bool
    elapsed_seconds: float


class PipelineDemo:
    """3 个 demo 用例的运行器

    用法:
        demo = PipelineDemo()
        summaries = demo.run_all()
        for s in summaries:
            print(s.report.to_report())
        demo.print_summary(summaries)
    """

    def __init__(self, pipeline: Optional[MatPipeline] = None) -> None:
        """构造

        Args:
            pipeline: 注入自定义 pipeline(测试用,默认 create_default_pipeline)
        """
        self.pipeline = pipeline or create_default_pipeline()
        self.cases: List[DemoCase] = DEMO_CASES

    def run_all(self) -> List[DemoSummary]:
        """跑全部 demo(按 case_id 顺序)

        Returns:
            List[DemoSummary]
        """
        summaries: List[DemoSummary] = []
        for case in self.cases:
            summary = self._run_one(case)
            summaries.append(summary)
        return summaries

    def run_one(self, case_id: str) -> Optional[DemoSummary]:
        """跑单个 demo

        Returns:
            DemoSummary 或 None(找不到 case_id)
        """
        for case in self.cases:
            if case.case_id == case_id:
                return self._run_one(case)
        return None

    def _run_one(self, case: DemoCase) -> DemoSummary:
        """跑 1 个 demo"""
        t0 = time.time()
        report = self.pipeline.run_full_pipeline(
            user_intent=case.user_intent,
            elements=case.elements,
            forbidden=case.forbidden,
            budget=case.budget,
            n_samples=5,
            run_id_prefix=f"demo-{case.case_id.lower()}",
        )
        elapsed = time.time() - t0

        # 成功判定:
        # 1. report.success == True
        # 2. final_recipes 数量 >= expected_min_recipes
        success = (
            report.success
            and len(report.final_recipes) >= case.expected_min_recipes
        )

        return DemoSummary(
            case=case,
            report=report,
            success=success,
            elapsed_seconds=elapsed,
        )

    def print_summary(self, summaries: List[DemoSummary]) -> None:
        """打印总览报告"""
        print("\n" + "=" * 70)
        print("🧪 MatWAU 3 个 Demo 总览报告")
        print("=" * 70)

        n_total = len(summaries)
        n_success = sum(1 for s in summaries if s.success)
        print(f"\n✅ 通过: {n_success}/{n_total}")
        print(f"⏱️  总耗时: {sum(s.elapsed_seconds for s in summaries):.2f}s")
        print(f"💵 总成本: ¥{sum(s.report.total_cost for s in summaries):.2f}")
        print()

        for s in summaries:
            status = "✅" if s.success else "❌"
            n_recipes = len(s.report.final_recipes)
            n_stages_ok = sum(1 for sr in s.report.stage_results if sr.success)
            n_stages = len(s.report.stage_results)
            print(
                f"{status} {s.case.case_id} {s.case.title} "
                f"({s.elapsed_seconds:.2f}s): "
                f"{n_stages_ok}/{n_stages} 段, "
                f"{n_recipes} 个实验方案, "
                f"¥{s.report.total_cost:.2f}"
            )

        print("=" * 70)

    def run_and_print_all(self) -> List[DemoSummary]:
        """跑全部 demo 并打印每份报告 + 总览

        Returns:
            List[DemoSummary]
        """
        summaries = self.run_all()

        # 打印每份详细报告
        for s in summaries:
            print(f"\n{'#' * 70}")
            print(f"# {s.case.case_id} — {s.case.title}")
            print(f"{'#' * 70}")
            print(f"📝 描述: {s.case.description}")
            print()
            print(s.report.to_report())

        # 打印总览
        self.print_summary(summaries)

        return summaries


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatWAU 3-Demo 端到端集成测试")
    print("=" * 70)

    demo = PipelineDemo()
    summaries = demo.run_and_print_all()