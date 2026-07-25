"""mat-sim-agent — 快速试菜员(MLIP 秒级预筛,per dev plan §5.3)

Stage 1 / Phase 1:用 mock MLIP(本机不需 GPU)
Stage 2(WAU v1.0.0 GA + 服务器 GPU 后)切真模型

W15 多域支持:
- inorganic_crystal: CHGNet(默认)
- polymer: ani1x
- nano: OrbNet-DFT

业务流程(per act() 实现):
1. 从 req.artifacts["candidates"] 拿 mat-gen 的候选(List[GenCandidate])
2. 对每个候选跑 CHGNet relax()(Stage 1 mock / Stage 2 真模型)
3. 按 relaxed_energy 升序排序
4. 可选过滤掉 unstable
5. 统计收敛率 + 稳定性分布
6. 返回 List[SimResult]

用法:
    from agents.mat_sim_agent.mat_sim_agent import MatSimAgent
    from agents.mat_gen_agent.mattergen import generate, GenConstraints
    from matwau.core.agent_base import AgentRequest

    # Step 1: mat-gen 生成
    constraints = GenConstraints(elements=["Li", "Co", "O"], n_samples=10)
    candidates = generate(constraints)

    # Step 2: mat-sim 弛豫
    agent = MatSimAgent()
    req = AgentRequest(
        run_id="run-001",
        message="对候选做 CHGNet 弛豫",
        artifacts={"candidates": candidates},
    )
    response = agent.run(req)
    print(response.reply)
    print(response.artifacts["simulated"])  # List[SimResult]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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

from .chgnet import (  # noqa: E402
    SimResult,
    parse_constraints as parse_sim_constraints,
    relax_batch,
    stats as sim_stats,
)


# 复用 mat-gen 的 GenCandidate(避免重新定义)
@dataclass
class SimCandidate:
    """mat-sim 输出的 1 个弛豫候选(对外稳定格式,跟 SimResult 同义)

    注:这里跟 SimResult 字段一致,但单独定义让外部 import 更稳定
    """

    formula: str
    cif: str
    relaxed_energy: float  # eV/atom
    forces_max: float  # eV/Å
    relaxation_converged: bool
    stability: str  # stable / metastable / unstable
    confidence: float = 0.5


def _sim_result_to_candidate(r: SimResult) -> SimCandidate:
    """SimResult → SimCandidate(对外暴露)"""
    return SimCandidate(
        formula=r.formula,
        cif=r.cif,
        relaxed_energy=r.relaxed_energy,
        forces_max=r.forces_max,
        relaxation_converged=r.relaxation_converged,
        stability=r.stability,
        confidence=r.confidence,
    )


def _extract_candidates(req: AgentRequest) -> List:
    """从 req.artifacts 抽取候选(支持 GenCandidate 列表 / dict 列表 / 空)

    Returns:
        List of GenCandidate / dict
    """
    artifacts = req.artifacts or {}

    # 优先 candidates(List[GenCandidate] 或 List[dict])
    if "candidates" in artifacts:
        cands = artifacts["candidates"]
        if isinstance(cands, list):
            return cands

    # 备选 candidates_dict
    if "candidates_dict" in artifacts:
        cands = artifacts["candidates_dict"]
        if isinstance(cands, list):
            return cands

    return []


# ============================================================================
# MatSimAgent 主体
# ============================================================================


class MatSimAgent(MatWAUAgentBase):
    """mat-sim-agent — 材料科学快速试菜员

    业务流程(per act() 实现):
    1. 抽取 mat-gen 的候选(List[GenCandidate] 或 dict)
    2. 跑 CHGNet mock 弛豫
    3. 按 relaxed_energy 排序(最稳定在前)
    4. 可选过滤 unstable
    5. 返回 List[SimCandidate](包装 SimResult)
    """

    name = "mat-sim-agent"

    def __init__(
        self,
        *,
        filter_unstable: bool = False,
        stability_threshold: str = "metastable",  # "stable" / "metastable" / "unstable"
        force_threshold: float = 0.05,  # eV/Å,CHGNet 默认收敛阈值
        cost_per_candidate: float = 0.5,  # ¥/候选(MLIP 推理,无机晶体默认值)
        domain: Optional[str] = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            filter_unstable: 是否过滤掉 unstable 候选
            stability_threshold: 过滤阈值,保留 <= 此档的
                - "stable": 只保留 stable
                - "metastable": 保留 stable + metastable
                - "unstable": 全部保留
            force_threshold: 收敛阈值(eV/Å),forces_max < 此值算收敛
            cost_per_candidate: 单候选估算成本 ¥
        """
        super().__init__(**kwargs)
        self.filter_unstable = filter_unstable
        self.stability_threshold = stability_threshold
        self.force_threshold = force_threshold
        self.cost_per_candidate = cost_per_candidate
        # W15: 域路由
        from agents.material_domain_router import DEFAULT_DOMAIN
        self.domain = domain or DEFAULT_DOMAIN

        # 默认注入 harness 部件(跟 mat-gen 风格一致)
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学快速试菜员 agent(mat-sim-agent),用 CHGNet MLIP 对候选结构做秒级预筛。

能力:
1. 接收 mat-gen-agent 产出的 List[GenCandidate](CIF + 化学式 + 估算形成能)
2. 对每个候选跑 CHGNet relax()(Stage 1 mock / Stage 2 真模型)
3. 输出:弛豫后总能(eV/atom)+ 收敛标志 + 最大原子受力 + 稳定性分类
4. 按稳定性排序,返回 top-N

稳定性 3 档:
- stable: relaxed_energy < -3.5 eV/atom(典型稳定结构,如 NaCl/Li2O)
- metastable: -3.5 <= energy < -2.5(亚稳,需 HPC 验证)
- unstable: energy >= -2.5(可能分解,建议丢弃)

输出格式:
- reply:自然语言总结(总候选数 + 收敛率 + 稳定性分布 + top-3 化学式)
- artifacts.simulated: List[SimCandidate](每个有 formula / relaxed_energy / stability / relaxation_converged / forces_max)

约束:
- 0 行 UI 代码(无头架构,所有展示走 HomeRail / Claude Desktop / Cursor)
- 1 个 LLM 调用 = 1 次 Goldens 跑分(mat-sim.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-sim 特有业务逻辑

        1. 从 ctx["_input_candidates"] 拿 mat-gen 的候选(由 perceive 预处理)
        2. fallback 到 req.artifacts
        3. 跑 MLIP mock relax_batch(per W15 sim_backend 路由)
        4. 可选过滤 unstable
        5. 统计 + 排序
        6. 安全检查(SafetyGuard)
        7. 返回 AgentResponse
        """
        # W15: 域路由
        from agents.material_domain_router import detect_domain, get_sim_backend
        ctx_domain = ctx.get("domain") or self.domain
        if not ctx_domain or ctx_domain == "auto":
            ctx_domain = detect_domain(ctx.get("user_message", ""))
        sim_backend = get_sim_backend(ctx_domain)

        # 1. 拿 candidates(从 perceive 预处理 or 兜底)
        candidates = ctx.get("_input_candidates") or []
        if not candidates:
            # 兜底:从 ctx["_input_artifacts"] 直接拿
            artifacts = ctx.get("_input_artifacts") or {}
            candidates = artifacts.get("candidates") or []

        if not candidates:
            # 真的没候选 → 空响应
            return self._empty_response("上游 mat-gen 未传 candidates,或 artifacts 为空")

        # 2. 跑 MLIP mock 弛豫(Stage 1 同一 mock,Stage 2 按 sim_backend 切真模型)
        try:
            sim_results = relax_batch(candidates)
        except Exception as e:
            return self._error_response(f"{sim_backend} 弛豫失败: {e}")

        # 3. 可选过滤 unstable
        if self.filter_unstable:
            sim_results = self._filter_by_stability(sim_results)

        # 4. 转 SimCandidate
        simulated = [_sim_result_to_candidate(r) for r in sim_results]

        # 5. 统计
        stats = sim_stats(sim_results)
        budget = ctx.get("budget")
        total_cost = self._estimate_cost(len(sim_results), domain=ctx_domain)

        # 6. 构造响应(W15: domain 标签 + backend 标识)
        from agents.material_domain_router import get_profile
        domain_label = get_profile(ctx_domain).get("display_name_zh", ctx_domain)
        if not simulated:
            reply = f"❌ [{domain_label}/{sim_backend}] 弛豫后无候选(输入 {len(candidates)} 个全失败)"
            confidence = 0.2
        else:
            top_3 = [s.formula for s in simulated[:3]]
            converged_rate = stats["converged"] / max(stats["total"], 1)
            stable_count = stats["stable"]
            reply = (
                f"✅ [{domain_label}/{sim_backend}] 弛豫 {len(simulated)} 个候选 "
                f"(输入 {len(candidates)} 个)\n"
                f"收敛率 {converged_rate:.0%}\n"
                f"稳定性分布:stable={stable_count}, "
                f"metastable={stats['metastable']}, "
                f"unstable={stats['unstable']}\n"
                f"top-3 化学式:{top_3}"
            )
            confidence = 0.85 if converged_rate > 0.7 else 0.6

        # 7. 预算警告
        if budget is not None and total_cost > budget:
            reply = f"[WARN 超预算] 总成本 ¥{total_cost} > 预算 ¥{budget}\n" + reply

        response = AgentResponse(
            reply=reply,
            artifacts={
                "simulated": simulated,
                "stats": stats,
                "input_count": len(candidates),
                "domain": ctx_domain,         # W15: 透传
                "sim_backend": sim_backend,   # W15: 记录
            },
            confidence=confidence,
            cost=total_cost,
        )

        # 8. SafetyGuard 检查(Stage 1 简版)
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass  # SafetyGuard 异常不阻断

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:除了 ContextManager.assemble(),还要预处理 candidates

        因为 Inner Loop 4 步里 act() 只能拿到 ctx,所以在 perceive 阶段
        把 candidates 提前抽好放 ctx["_input_candidates"]。
        """
        ctx = super().perceive(req)

        # 预处理 candidates → 放 ctx
        candidates = _extract_candidates(req)
        ctx["_input_candidates"] = candidates
        ctx["_input_artifacts"] = req.artifacts or {}
        ctx["user_message"] = req.message

        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _filter_by_stability(self, sim_results: List[SimResult]) -> List[SimResult]:
        """按稳定性阈值过滤"""
        threshold_order = {"unstable": 0, "metastable": 1, "stable": 2}
        threshold_idx = threshold_order.get(self.stability_threshold, 1)

        filtered = []
        for r in sim_results:
            r_idx = threshold_order.get(r.stability, 0)
            if r_idx >= threshold_idx:
                filtered.append(r)

        return filtered

    def _empty_response(self, reason: str) -> AgentResponse:
        """空响应(无候选)"""
        return AgentResponse(
            reply=f"⚠️ {reason}",
            artifacts={"simulated": [], "stats": {}, "input_count": 0},
            confidence=0.1,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应(CHGNet 失败)"""
        return AgentResponse(
            reply=f"❌ mat-sim 错误: {error}",
            artifacts={"simulated": [], "stats": {}, "input_count": 0},
            confidence=0.0,
            error=error,
        )

    def _estimate_cost(self, n_candidates: int, domain: Optional[str] = None) -> float:
        """估算成本(per W15 domain 单价)

        Args:
            n_candidates: 候选数
            domain: 材料域(None → 用 self.domain)
        """
        from agents.material_domain_router import DEFAULT_DOMAIN, get_unit_cost_table

        d = domain or self.domain or DEFAULT_DOMAIN
        cost_table = get_unit_cost_table(d)
        per_candidate = cost_table.get("mat-sim-agent", self.cost_per_candidate)
        return round(n_candidates * per_candidate, 4)


def create_default_agent() -> MatSimAgent:
    """便利函数:创建带默认 Harness 的 MatSimAgent"""
    return MatSimAgent(
        filter_unstable=False,
        stability_threshold="metastable",
        force_threshold=0.05,
        cost_per_candidate=0.5,
    )


# ============================================================================
# CLI 入口
# ============================================================================

if __name__ == "__main__":
    # 跑 1 个 demo(mat-gen → mat-sim)
    from agents.mat_gen_agent.mat_gen_agent import create_default_agent as create_gen
    from agents.mat_gen_agent.mattergen import generate as mattergen_generate
    from agents.mat_gen_agent.mattergen import GenConstraints

    print("🚀 MatSimAgent Demo")
    print("=" * 60)

    # Step 1: mat-gen 生成候选
    print("\n📦 Step 1: mat-gen 生成候选")
    gen_constraints = GenConstraints(elements=["Li", "Co", "O"], n_samples=10)
    gen_candidates = mattergen_generate(gen_constraints)
    print(f"   生成 {len(gen_candidates)} 个候选")
    for c in gen_candidates[:3]:
        print(f"   - {c.formula}: 形成能 {c.estimated_energy:.2f} eV/atom")

    # Step 2: mat-sim 弛豫
    print("\n🔬 Step 2: mat-sim 跑 CHGNet 弛豫")
    agent = create_default_agent()
    req = AgentRequest(
        run_id="demo-001",
        message="对候选做 CHGNet 弛豫",
        artifacts={"candidates": gen_candidates},
    )
    response = agent.run(req)

    print(f"\n📨 reply: {response.reply}")
    print(f"📊 confidence: {response.confidence:.0%}, cost: ¥{response.cost:.2f}")
    print(f"\n🔬 Top-5 弛豫结果:")
    for i, s in enumerate(response.artifacts.get("simulated", [])[:5]):
        print(
            f"   #{i+1} {s.formula}: "
            f"弛豫能 {s.relaxed_energy:.2f} eV/atom, "
            f"converged={s.relaxation_converged}, "
            f"stability={s.stability}"
        )


__all__ = [
    "MatSimAgent",
    "SimCandidate",
    "create_default_agent",
]