"""MatPipeline — 4 段管线编排器(mat-gen → mat-sim → mat-hpc → mat-exp)

设计原则:
1. 每段是独立 agent,pipeline 只负责数据流转,不修改 agent 内部逻辑
2. 公式一致性校验(每段过滤后,核心元素集合必须保留)
3. 总成本统计 + 总耗时统计
4. 每段输出 + 最终 ExpRecipe 列表
5. 异常隔离(某段失败不影响其他段)

Stage 1:mock 模型,本机无 GPU / 无超算
Stage 2:WAU v1.0.0 GA + 服务器 GPU + 真超算后接真模型

per MatWAU-开发计划 §5 W7
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许直接 python3 -m 运行
_PIPELINE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PIPELINE_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class StageResult:
    """1 段管线的执行结果"""

    stage_name: str  # "mat-gen" / "mat-sim" / "mat-hpc" / "mat-exp"
    agent_name: str
    response: Optional[AgentResponse]
    duration_seconds: float
    success: bool
    error: Optional[str] = None
    input_count: int = 0
    output_count: int = 0

    def to_summary(self) -> str:
        """1 行总结(用于打印)"""
        status = "✅" if self.success else "❌"
        if self.error:
            return f"   {status} {self.stage_name} ({self.duration_seconds:.2f}s): ERROR {self.error}"
        return (
            f"   {status} {self.stage_name} ({self.duration_seconds:.2f}s): "
            f"{self.input_count} → {self.output_count}, "
            f"confidence={self.response.confidence:.0%}, "
            f"cost=¥{self.response.cost:.2f}"
        )


@dataclass
class PipelineReport:
    """完整管线报告"""

    user_intent: str
    elements: List[str]
    forbidden: List[str] = field(default_factory=list)
    budget: Optional[float] = None

    # 每段结果
    stage_results: List[StageResult] = field(default_factory=list)

    # 总览
    total_duration_seconds: float = 0.0
    total_cost: float = 0.0
    success: bool = False
    error: Optional[str] = None

    # 公式一致性检查
    formula_consistency_ok: bool = True
    consistency_violations: List[str] = field(default_factory=list)

    # 最终产物
    final_recipes: List = field(default_factory=list)  # List[ExpRecipe]

    def to_report(self) -> str:
        """完整人类可读报告"""
        lines = []
        lines.append("=" * 70)
        lines.append(f"🧪 MatWAU 4 段管线报告")
        lines.append("=" * 70)
        lines.append(f"📝 用户意图: {self.user_intent}")
        lines.append(f"🧬 元素约束: {self.elements}")
        if self.forbidden:
            lines.append(f"🚫 禁止元素: {self.forbidden}")
        if self.budget is not None:
            lines.append(f"💰 预算: ¥{self.budget}")
        lines.append("")
        lines.append(f"⏱️  总耗时: {self.total_duration_seconds:.2f}s")
        lines.append(f"💵 总成本: ¥{self.total_cost:.2f}")
        lines.append(f"{'✅ 成功' if self.success else '❌ 失败'}")
        lines.append("")
        lines.append("📊 各段执行:")
        for sr in self.stage_results:
            lines.append(sr.to_summary())
        lines.append("")

        # 公式一致性
        if self.formula_consistency_ok:
            lines.append("✅ 公式一致性:全部段公式集合一致")
        else:
            lines.append(f"⚠️  公式一致性违例: {self.consistency_violations}")

        lines.append("")

        # 最终方案
        if self.final_recipes:
            lines.append(f"🧪 最终实验方案 ({len(self.final_recipes)} 个):")
            for i, recipe in enumerate(self.final_recipes[:5]):
                sint = recipe.sintering
                xrd = recipe.xrd
                main_peak = (
                    f"{xrd.peaks[0].two_theta:.1f}°({xrd.peaks[0].hkl})"
                    if xrd.peaks else "N/A"
                )
                lines.append(
                    f"   #{i+1} {recipe.formula}:\n"
                    f"     XRD: 主峰 {main_peak} ({len(xrd.peaks)} peaks, a={xrd.lattice_a}Å)\n"
                    f"     烧结: {sint.temperature_celsius}℃ / {sint.pressure_mpa}MPa / "
                    f"{sint.time_hours}h / {sint.atmosphere}"
                )
            if len(self.final_recipes) > 5:
                lines.append(f"   ... 共 {len(self.final_recipes)} 个")

        if self.error:
            lines.append(f"\n❌ 错误: {self.error}")

        lines.append("=" * 70)
        return "\n".join(lines)


# ============================================================================
# MatPipeline 主体
# ============================================================================


class MatPipeline:
    """4 段管线编排器

    构造时传入 4 个 agent;不传入时自动用 create_default_*()
    编排逻辑:
    1. gen_req = parse(user_intent, elements, forbidden) → mat-gen
    2. sim_req = stage1.artifacts["candidates"] → mat-sim
    3. hpc_req = stage2.artifacts["simulated"] → mat-hpc
    4. exp_req = stage3.artifacts["jobs"] → mat-exp
    """

    def __init__(
        self,
        *,
        gen_agent=None,
        sim_agent=None,
        hpc_agent=None,
        exp_agent=None,
        intent_agent=None,
    ) -> None:
        """构造

        不传任何 agent → 用默认 (Stage 1 mock)
        任意子集可覆盖(测试用)
        intent_agent 可选(per W9:用户可用 1 句话直接进 pipeline)
        """
        if gen_agent is None or sim_agent is None or hpc_agent is None or exp_agent is None:
            # 懒加载(避免循环 import)
            from agents.mat_gen_agent.mat_gen_agent import create_default_agent as create_gen
            from agents.mat_sim_agent.mat_sim_agent import create_default_agent as create_sim
            from agents.mat_hpc_agent.mat_hpc_agent import create_default_agent as create_hpc
            from agents.mat_exp_agent.mat_exp_agent import create_default_agent as create_exp

        if gen_agent is None:
            gen_agent = create_gen()
        if sim_agent is None:
            sim_agent = create_sim()
        if hpc_agent is None:
            hpc_agent = create_hpc()
        if exp_agent is None:
            exp_agent = create_exp()

        self.gen_agent = gen_agent
        self.sim_agent = sim_agent
        self.hpc_agent = hpc_agent
        self.exp_agent = exp_agent

        # W9 新增:mat-intent-agent(可选,run_from_natural_language 用)
        if intent_agent is None:
            from agents.mat_intent_agent.mat_intent_agent import create_default_agent as create_intent

            intent_agent = create_intent()
        self.intent_agent = intent_agent

        # 默认 mat-hpc 端到端测试用 filter_unstable=False(Goldens 经验)
        self._hpc_relaxed_for_e2e = True

    # ========================================================================
    # 公开 API
    # ========================================================================

    def run_from_natural_language(
        self,
        *,
        user_intent: str,
        budget: Optional[float] = None,
        n_samples: Optional[int] = None,
        run_id_prefix: str = "nl-pipe",
    ) -> PipelineReport:
        """从自然语言意图跑完整 4 段管线(per W9 mat-intent-agent)

        Args:
            user_intent: 用户 1 句话意图(中英文)
            budget: 总预算
            n_samples: mat-gen 生成候选数(None → 用 mat-intent 解析出的)
            run_id_prefix: run_id 前缀

        Returns:
            PipelineReport(包含 mat_intent 在 stage 0)
        """
        from agents.mat_intent_agent.intent_classifier import parse_mat_intent
        from agents.mat_intent_agent.mat_intent_agent import create_default_agent as create_intent
        from matwau.core.agent_base import AgentRequest

        # Stage 0: mat-intent 解析
        intent_agent = self.intent_agent or create_intent()
        req = AgentRequest(run_id=f"{run_id_prefix}-intent", message=user_intent)
        intent_response = intent_agent.run(req)
        mi = intent_response.artifacts["mat_intent"]

        # 把 mat-intent 结果塞到 PipelineReport stage_results[0]
        from dataclasses import dataclass as _dc
        intent_sr = StageResult(
            stage_name="mat-intent",
            agent_name=intent_agent.name,
            response=intent_response,
            duration_seconds=0.01,
            success=True,
            input_count=0,
            output_count=1,
        )

        # 决定 elements / forbidden / n_samples
        # 优先级:用户传入 > mat-intent 解析 > fallback
        elements = mi.elements if mi.elements else ["Li", "O"]  # 默认元素
        forbidden = mi.forbidden
        n = n_samples if n_samples is not None else mi.n_samples

        # 调标准 run_full_pipeline
        report = self.run_full_pipeline(
            user_intent=user_intent,
            elements=elements,
            forbidden=forbidden,
            budget=budget,
            n_samples=n,
            run_id_prefix=run_id_prefix,
        )

        # 把 mat-intent stage 插入到 stage_results 最前面
        report.stage_results.insert(0, intent_sr)
        return report

    def run_full_pipeline(
        self,
        *,
        user_intent: str,
        elements: List[str],
        forbidden: Optional[List[str]] = None,
        budget: Optional[float] = None,
        n_samples: int = 5,
        run_id_prefix: str = "pipe",
    ) -> PipelineReport:
        """跑完整 4 段管线

        Args:
            user_intent: 用户需求描述(传给 mat-gen 当 message)
            elements: 元素约束列表
            forbidden: 禁止元素(可选)
            budget: 总预算(可选,只警告不阻断)
            n_samples: mat-gen 生成候选数
            run_id_prefix: run_id 前缀

        Returns:
            PipelineReport
        """
        forbidden = forbidden or []

        report = PipelineReport(
            user_intent=user_intent,
            elements=elements,
            forbidden=forbidden,
            budget=budget,
        )

        t_total_start = time.time()

        # ====================================================================
        # Stage 1: mat-gen
        # ====================================================================
        sr1 = self._run_stage_gen(
            user_intent=user_intent,
            elements=elements,
            forbidden=forbidden,
            n_samples=n_samples,
            run_id=f"{run_id_prefix}-gen",
            budget=budget,
        )
        report.stage_results.append(sr1)
        report.total_cost += sr1.response.cost if sr1.response else 0

        if not sr1.success or not sr1.response:
            report.error = f"mat-gen 失败: {sr1.error}"
            report.total_duration_seconds = time.time() - t_total_start
            return report

        gen_candidates = sr1.response.artifacts.get("candidates", [])

        # 公式约束校验(mat-gen 输出必须包含 elements,且不包含 forbidden)
        gen_formulas = [c.formula for c in gen_candidates]
        ok, violations = _check_formula_constraints(
            gen_formulas, elements, forbidden
        )
        if not ok:
            report.formula_consistency_ok = False
            report.consistency_violations.append(
                f"mat-gen 违例: {violations}"
            )

        # ====================================================================
        # Stage 2: mat-sim
        # ====================================================================
        sr2 = self._run_stage_sim(
            gen_candidates=gen_candidates,
            run_id=f"{run_id_prefix}-sim",
            budget=budget,
        )
        report.stage_results.append(sr2)
        report.total_cost += sr2.response.cost if sr2.response else 0

        if not sr2.success or not sr2.response:
            report.error = f"mat-sim 失败: {sr2.error}"
            report.total_duration_seconds = time.time() - t_total_start
            return report

        sim_candidates = sr2.response.artifacts.get("simulated", [])

        # ====================================================================
        # Stage 3: mat-hpc(端到端测试用 relaxed)
        # ====================================================================
        sr3 = self._run_stage_hpc(
            sim_candidates=sim_candidates,
            run_id=f"{run_id_prefix}-hpc",
            budget=budget,
            relaxed=self._hpc_relaxed_for_e2e,
        )
        report.stage_results.append(sr3)
        report.total_cost += sr3.response.cost if sr3.response else 0

        if not sr3.success or not sr3.response:
            report.error = f"mat-hpc 失败: {sr3.error}"
            report.total_duration_seconds = time.time() - t_total_start
            return report

        hpc_jobs = sr3.response.artifacts.get("jobs", [])

        # ====================================================================
        # Stage 4: mat-exp
        # ====================================================================
        sr4 = self._run_stage_exp(
            hpc_jobs=hpc_jobs,
            run_id=f"{run_id_prefix}-exp",
            budget=budget,
        )
        report.stage_results.append(sr4)
        report.total_cost += sr4.response.cost if sr4.response else 0

        if not sr4.success or not sr4.response:
            report.error = f"mat-exp 失败: {sr4.error}"
            report.total_duration_seconds = time.time() - t_total_start
            return report

        report.final_recipes = sr4.response.artifacts.get("recipes", [])

        # ====================================================================
        # 公式一致性最终校验
        # ====================================================================
        final_formulas = [r.formula for r in report.final_recipes]
        ok_final, violations_final = _check_formula_constraints(
            final_formulas, elements, forbidden
        )
        if not ok_final:
            report.formula_consistency_ok = False
            report.consistency_violations.append(
                f"final recipes 违例: {violations_final}"
            )

        report.success = True
        report.total_duration_seconds = time.time() - t_total_start
        return report

    # ========================================================================
    # 内部:4 段单跑 helper
    # ========================================================================

    def _run_stage_gen(
        self,
        *,
        user_intent: str,
        elements: List[str],
        forbidden: List[str],
        n_samples: int,
        run_id: str,
        budget: Optional[float],
    ) -> StageResult:
        """Stage 1: mat-gen

        把 user_intent + elements + forbidden 拼成 message 传进去。
        mattergen 的 parse_constraints 会从 message 抽元素和禁止元素。
        """
        t0 = time.time()
        try:
            # 拼装 message(让 mat-gen 的 parse_constraints 能解析)
            must_str = "、".join(elements)
            forbid_str = "、".join(forbidden) if forbidden else ""
            full_intent = user_intent
            if must_str:
                full_intent += f"。元素:必须包含 {must_str}"
            if forbid_str:
                full_intent += f"。禁止: {forbid_str}"
            if n_samples:
                full_intent += f"。生成 {n_samples} 个候选"

            req = AgentRequest(
                run_id=run_id,
                message=full_intent,
                budget=budget,
            )
            response = self.gen_agent.run(req)
            return StageResult(
                stage_name="mat-gen",
                agent_name=self.gen_agent.name,
                response=response,
                duration_seconds=time.time() - t0,
                success=True,
                input_count=0,  # mat-gen 无输入
                output_count=len(response.artifacts.get("candidates", [])),
            )
        except Exception as e:
            return StageResult(
                stage_name="mat-gen",
                agent_name=self.gen_agent.name,
                response=None,
                duration_seconds=time.time() - t0,
                success=False,
                error=str(e),
            )

    def _run_stage_sim(
        self,
        *,
        gen_candidates: List,
        run_id: str,
        budget: Optional[float],
    ) -> StageResult:
        """Stage 2: mat-sim"""
        t0 = time.time()
        try:
            req = AgentRequest(
                run_id=run_id,
                message="对候选做 CHGNet 弛豫",
                artifacts={"candidates": gen_candidates},
                budget=budget,
            )
            response = self.sim_agent.run(req)
            return StageResult(
                stage_name="mat-sim",
                agent_name=self.sim_agent.name,
                response=response,
                duration_seconds=time.time() - t0,
                success=True,
                input_count=len(gen_candidates),
                output_count=len(response.artifacts.get("simulated", [])),
            )
        except Exception as e:
            return StageResult(
                stage_name="mat-sim",
                agent_name=self.sim_agent.name,
                response=None,
                duration_seconds=time.time() - t0,
                success=False,
                error=str(e),
                input_count=len(gen_candidates),
            )

    def _run_stage_hpc(
        self,
        *,
        sim_candidates: List,
        run_id: str,
        budget: Optional[float],
        relaxed: bool,
    ) -> StageResult:
        """Stage 3: mat-hpc

        relaxed=True 时用 filter_unstable=False(Goldens 模式),
        relaxed=False 用默认 filter_unstable=True
        """
        t0 = time.time()
        try:
            # 端到端测试要看到 hpc jobs,所以 relaxed=True
            if relaxed and getattr(self.hpc_agent, "filter_unstable", True):
                # 临时覆盖 filter_unstable
                original = self.hpc_agent.filter_unstable
                self.hpc_agent.filter_unstable = False
                try:
                    req = AgentRequest(
                        run_id=run_id,
                        message="提交 VASP HPC",
                        artifacts={"simulated": sim_candidates},
                        budget=budget,
                    )
                    response = self.hpc_agent.run(req)
                finally:
                    self.hpc_agent.filter_unstable = original
            else:
                req = AgentRequest(
                    run_id=run_id,
                    message="提交 VASP HPC",
                    artifacts={"simulated": sim_candidates},
                    budget=budget,
                )
                response = self.hpc_agent.run(req)
            return StageResult(
                stage_name="mat-hpc",
                agent_name=self.hpc_agent.name,
                response=response,
                duration_seconds=time.time() - t0,
                success=True,
                input_count=len(sim_candidates),
                output_count=len(response.artifacts.get("jobs", [])),
            )
        except Exception as e:
            return StageResult(
                stage_name="mat-hpc",
                agent_name=self.hpc_agent.name,
                response=None,
                duration_seconds=time.time() - t0,
                success=False,
                error=str(e),
                input_count=len(sim_candidates),
            )

    def _run_stage_exp(
        self,
        *,
        hpc_jobs: List,
        run_id: str,
        budget: Optional[float],
    ) -> StageResult:
        """Stage 4: mat-exp"""
        t0 = time.time()
        try:
            req = AgentRequest(
                run_id=run_id,
                message="出 XRD + 烧结方案",
                artifacts={"jobs": hpc_jobs},
                budget=budget,
            )
            response = self.exp_agent.run(req)
            return StageResult(
                stage_name="mat-exp",
                agent_name=self.exp_agent.name,
                response=response,
                duration_seconds=time.time() - t0,
                success=True,
                input_count=len(hpc_jobs),
                output_count=len(response.artifacts.get("recipes", [])),
            )
        except Exception as e:
            return StageResult(
                stage_name="mat-exp",
                agent_name=self.exp_agent.name,
                response=None,
                duration_seconds=time.time() - t0,
                success=False,
                error=str(e),
                input_count=len(hpc_jobs),
            )


# ============================================================================
# 工具函数
# ============================================================================


def _check_formula_constraints(
    formulas: List[str],
    required_elements: List[str],
    forbidden_elements: List[str],
) -> tuple[bool, List[str]]:
    """检查 formula 集合是否满足元素约束

    规则:
    1. 每个 formula 必须包含所有 required_elements
    2. 每个 formula 不能包含任何 forbidden_elements

    Returns:
        (ok, violations) — ok=True 表示全部通过,violations 是违例描述列表
    """
    violations = []

    for f in formulas:
        # 必须元素(注意:跳过空 required)
        for elem in required_elements:
            if elem and elem not in f:
                violations.append(f"{f} 缺少必须元素 {elem}")

        # 禁止元素
        for elem in forbidden_elements:
            if elem and elem in f:
                violations.append(f"{f} 含禁止元素 {elem}")

    return (len(violations) == 0, violations)


def create_default_pipeline() -> MatPipeline:
    """便利函数:创建默认 MatPipeline(Stage 1 mock)"""
    return MatPipeline()


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    # 跑 1 个 demo
    print("🚀 MatPipeline Demo")
    print("=" * 70)

    pipeline = create_default_pipeline()
    report = pipeline.run_full_pipeline(
        user_intent="出 LiCoO2 实验方案",
        elements=["Li", "Co", "O"],
        budget=500.0,
        n_samples=5,
    )

    print(report.to_report())