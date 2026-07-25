"""mat-exp-agent — 实验规划 agent(XRD + 烧结,per dev plan §5.5)

Stage 1 / Phase 1:本地 mock(Bragg 方程 + 经验数据库),不需真 XRD 仪器
Stage 2(WAU v1.0.0 GA + 真实验设备后)切真仪器 + 反馈学习

业务流程(per act() 实现):
1. 从 req.artifacts["jobs"] 拿 mat-hpc 的 HPCJobResult 列表(也兼容 SimCandidate / GenCandidate)
2. 对每个候选:
   - XRD:Bragg 方程 mock 计算理论谱(2θ + intensity)
   - 烧结:经验数据库查温度/压力/时间/气氛
3. 返回 List[ExpRecipe](每个有 formula + xrd + sintering)

用法:
    from agents.mat_exp_agent.mat_exp_agent import MatExpAgent
    from agents.mat_hpc_agent.mat_hpc_agent import HPCJobResult
    from matwau.core.agent_base import AgentRequest

    # 准备 HPCJobResult(mat-hpc 输出)
    hpc_jobs = [...]

    agent = MatExpAgent()
    req = AgentRequest(
        run_id="exp-001",
        message="出 XRD + 烧结方案",
        artifacts={"jobs": hpc_jobs},
    )
    response = agent.run(req)
    print(response.artifacts["recipes"])  # List[ExpRecipe]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager  # noqa: E402
from matwau.harness.safety_guard import SafetyGuard  # noqa: E402

from .xrd_sintering import (  # noqa: E402
    ExpRecipe,
    SinteringRecipe,
    XRDPattern,
    generate_exp_recipes,
)


def _extract_input_candidates(req: AgentRequest) -> List:
    """从 req.artifacts 抽取候选(支持 3 种格式)

    Returns:
        List of HPCJobResult / SimCandidate / GenCandidate / dict
    """
    artifacts = req.artifacts or {}

    # 优先 jobs(mat-hpc 输出)
    if "jobs" in artifacts:
        cands = artifacts["jobs"]
        if isinstance(cands, list):
            return cands

    # 备选 simulated(mat-sim 输出)
    if "simulated" in artifacts:
        cands = artifacts["simulated"]
        if isinstance(cands, list):
            return cands

    # 备选 candidates(mat-gen 输出)
    if "candidates" in artifacts:
        cands = artifacts["candidates"]
        if isinstance(cands, list):
            return cands

    return []


# ============================================================================
# MatExpAgent 主体
# ============================================================================


class MatExpAgent(MatWAUAgentBase):
    """mat-exp-agent — 材料科学实验规划 agent(实验老师)

    业务流程(per act() 实现):
    1. 抽取 HPCJobResult(mat-hpc) / SimCandidate(mat-sim) / GenCandidate(mat-gen)
    2. 对每个候选生成 XRD 理论谱 + 烧结参数方案
    3. 返回 List[ExpRecipe]
    """

    name = "mat-exp-agent"

    def __init__(
        self,
        *,
        cost_per_recipe: float = 50.0,  # ¥/实验方案(XRD + 烧结耗材估算)
        **kwargs,
    ) -> None:
        """构造

        Args:
            cost_per_recipe: 单个实验方案估算成本 ¥(XRD 测试 + 烧结耗材)
        """
        super().__init__(**kwargs)
        self.cost_per_recipe = cost_per_recipe

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            # 实验预算默认 ¥5000(50 个实验方案 × ¥100)
            self.safety_guard = SafetyGuard(budget_limit=5000.0)

    def system_prompt(self) -> str:
        return """你是材料科学实验规划 agent(mat-exp-agent,实验老师),给实验员出 pre-flight 实验方案。

能力:
1. 接收 mat-hpc-agent 的 List[HPCJobResult](或 mat-sim / mat-gen 输出)
2. 对每个候选生成 XRD 理论谱:
   - Bragg 方程:nλ = 2d sin(θ),λ=1.5406 Å Cu Kα
   - 输出 top-10 峰(2θ + intensity + (hkl) 标签)
3. 对每个候选推荐烧结参数(经验数据库):
   - 温度(℃)/ 压力(MPa)/ 时间(h)/ 气氛(air/N2/Ar/...)
   - 不同材料类别用不同条件(锂电正极 / 固态电解质 / 钙钛矿 / 催化剂 / ...)

实验方案 4 段管线位置:
mat-gen(造物主)→ mat-sim(快速试菜)→ mat-hpc(超算对接员)→ mat-exp(实验规划/分析)

输出格式:
- reply:自然语言总结(总方案数 + 烧结温度范围 + top-3 主峰位置)
- artifacts.recipes: List[ExpRecipe](每个有 formula / xrd / sintering)
  - xrd:XRDPattern(formula / wavelength / lattice_a / peaks)
  - sintering:SinteringRecipe(formula / temperature_celsius / pressure_mpa / time_hours / atmosphere / reference)

约束:
- 0 行 UI 代码(无头架构,所有展示走 HomeRail / Claude Desktop / Cursor)
- 1 个 LLM 调用 = 1 次 Goldens 跑分(mat-exp.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-exp 特有业务逻辑

        1. 从 ctx 拿 candidates(由 perceive 预处理)
        2. 生成 ExpRecipe(XRD + 烧结)
        3. 统计 + SafetyGuard 检查
        4. 返回 AgentResponse
        """
        # 1. 拿 candidates
        candidates = ctx.get("_input_candidates") or []
        if not candidates:
            artifacts = ctx.get("_input_artifacts") or {}
            candidates = artifacts.get("jobs") or artifacts.get("simulated") or artifacts.get("candidates") or []

        if not candidates:
            return self._empty_response("上游 mat-hpc 未传 jobs,mat-sim 未传 simulated,mat-gen 未传 candidates")

        # 2. 生成 ExpRecipe
        try:
            recipes = generate_exp_recipes(candidates)
        except Exception as e:
            return self._error_response(f"XRD/烧结生成失败: {e}")

        # 3. 统计
        budget = ctx.get("budget")
        total_cost = round(len(recipes) * self.cost_per_recipe, 2)
        sint_temps = [r.sintering.temperature_celsius for r in recipes] if recipes else []
        avg_temp = sum(sint_temps) / len(sint_temps) if sint_temps else 0

        # 4. 构造响应
        if not recipes:
            reply = "❌ 未能生成任何实验方案"
            confidence = 0.2
        else:
            top_3_formulas = [r.formula for r in recipes[:3]]
            top_3_peaks = [
                f"{r.formula}@{r.xrd.main_peak_hkl}={r.xrd.peaks[0].two_theta:.1f}°"
                if r.xrd.peaks else f"{r.formula}@N/A"
                for r in recipes[:3]
            ]
            reply = (
                f"✅ 生成 {len(recipes)} 个实验方案\n"
                f"烧结温度范围:{min(sint_temps):.0f} - {max(sint_temps):.0f}℃(平均 {avg_temp:.0f}℃)\n"
                f"top-3 实验方案:\n"
                + "\n".join(f"  - {r.formula}: 烧结 {r.sintering.temperature_celsius}℃/{r.sintering.atmosphere}/{r.sintering.time_hours}h, XRD 主峰 {r.xrd.peaks[0].two_theta:.1f}°" if r.xrd.peaks else f"  - {r.formula}: (无 XRD 数据)" for r in recipes[:3])
            )
            confidence = 0.85

        # 5. 预算警告
        if budget is not None and total_cost > budget:
            reply = f"[WARN 超预算] 总成本 ¥{total_cost} > 预算 ¥{budget}\n" + reply

        response = AgentResponse(
            reply=reply,
            artifacts={
                "recipes": recipes,
                "input_count": len(candidates),
                "sint_temp_range": (min(sint_temps), max(sint_temps)) if sint_temps else None,
            },
            confidence=confidence,
            cost=total_cost,
        )

        # 6. SafetyGuard 检查(Stage 1 简版)
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:预处理 candidates(mat-hpc → mat-exp 数据流)

        因为 act() 只能拿到 ctx,所以在 perceive 阶段
        把 candidates 提前抽好放 ctx["_input_candidates"]。
        """
        ctx = super().perceive(req)

        # 预处理 candidates → 放 ctx
        candidates = _extract_input_candidates(req)
        ctx["_input_candidates"] = candidates
        ctx["_input_artifacts"] = req.artifacts or {}
        ctx["user_message"] = req.message

        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _empty_response(self, reason: str) -> AgentResponse:
        """空响应(无候选)"""
        return AgentResponse(
            reply=f"⚠️ {reason}",
            artifacts={"recipes": [], "input_count": 0, "sint_temp_range": None},
            confidence=0.1,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应(XRD / 烧结生成失败)"""
        return AgentResponse(
            reply=f"❌ mat-exp 错误: {error}",
            artifacts={"recipes": [], "input_count": 0, "sint_temp_range": None},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatExpAgent:
    """便利函数:创建带默认 Harness 的 MatExpAgent"""
    return MatExpAgent(cost_per_recipe=50.0)


# ============================================================================
# CLI 入口
# ============================================================================

if __name__ == "__main__":
    print("🚀 MatExpAgent Demo")
    print("=" * 60)

    # 跑 1 个 demo:mat-gen → mat-sim → mat-hpc → mat-exp 4 段链路
    from agents.mat_gen_agent.mat_gen_agent import create_default_agent as create_gen
    from agents.mat_gen_agent.mattergen import generate as mattergen_generate
    from agents.mat_gen_agent.mattergen import GenConstraints
    from agents.mat_sim_agent.mat_sim_agent import create_default_agent as create_sim
    from agents.mat_hpc_agent.mat_hpc_agent import create_default_agent as create_hpc
    from agents.mat_hpc_agent.mat_hpc_agent import HPCJobResult

    # Stage 1: mat-gen
    print("\n📦 Stage 1: mat-gen 生成候选")
    gen_constraints = GenConstraints(elements=["Li", "Co", "O"], n_samples=5)
    gen_candidates = mattergen_generate(gen_constraints)
    print(f"   生成 {len(gen_candidates)} 个候选")

    # Stage 2: mat-sim
    print("\n🔬 Stage 2: mat-sim 弛豫")
    sim_agent = create_sim()
    sim_req = AgentRequest(
        run_id="demo-sim", message="弛豫",
        artifacts={"candidates": gen_candidates},
    )
    sim_response = sim_agent.run(sim_req)
    sim_candidates = sim_response.artifacts["simulated"]
    print(f"   弛豫后 {len(sim_candidates)} 个候选")

    # Stage 3: mat-hpc(简化:直接转 HPCJobResult)
    print("\n🖥️ Stage 3: mat-hpc 提交 HPC")
    hpc_agent = create_hpc()
    hpc_req = AgentRequest(
        run_id="demo-hpc", message="VASP",
        artifacts={"simulated": sim_candidates},
    )
    hpc_response = hpc_agent.run(hpc_req)
    hpc_jobs = hpc_response.artifacts["jobs"]
    print(f"   提交 {len(hpc_jobs)} 个 HPC job")

    # Stage 4: mat-exp
    print("\n🧪 Stage 4: mat-exp 出实验方案")
    agent = create_default_agent()
    req = AgentRequest(
        run_id="demo-exp", message="实验方案",
        artifacts={"jobs": hpc_jobs},
    )
    response = agent.run(req)

    print(f"\n📨 reply: {response.reply[:400]}")
    print(f"📊 confidence: {response.confidence:.0%}, cost: ¥{response.cost:.2f}")
    print(f"\n🧪 实验方案 (top-5):")
    for i, recipe in enumerate(response.artifacts.get("recipes", [])[:5]):
        sint = recipe.sintering
        xrd = recipe.xrd
        main_peak = f"{xrd.peaks[0].two_theta:.1f}°({xrd.peaks[0].hkl})" if xrd.peaks else "N/A"
        print(
            f"   #{i+1} {recipe.formula}:\n"
            f"     XRD: 主峰 {main_peak} ({len(xrd.peaks)} peaks, a={xrd.lattice_a}Å)\n"
            f"     烧结: {sint.temperature_celsius}℃ / {sint.pressure_mpa}MPa / "
            f"{sint.time_hours}h / {sint.atmosphere}\n"
            f"     参考: {sint.reference}"
        )


__all__ = [
    "MatExpAgent",
    "ExpRecipe",
    "XRDPattern",
    "SinteringRecipe",
    "create_default_agent",
]