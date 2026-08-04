"""mat-hpc-agent — 超算对接员(VASP + Slurm,per dev plan §5.4)

Stage 1 / Phase 1:本地 mock VASP + Slurm,不需真超算环境
Stage 2(WAU v1.0.0 GA + 服务器 GPU 后)切真 VASP + 真 Slurm

业务流程(per act() 实现):
1. 从 req.artifacts["simulated"] 拿 mat-sim 的 SimCandidate 列表
2. 默认过滤掉 unstable(只跑 stable + metastable,值得花 HPC 钱)
3. 对每个候选:估算资源 → 生成 VASP 4 件套 → 生成 Slurm 脚本 → 提交(Stage 1 mock)
4. 高 cost 拦截(> ¥1000 触发 supervisor 审批)
5. 返回 List[HPCJobResult]

用法:
    from agents.mat_hpc_agent.mat_hpc_agent import MatHpcAgent
    from agents.mat_sim_agent.mat_sim_agent import SimCandidate
    from matwau.core.agent_base import AgentRequest

    # 准备 SimCandidate(mat-sim 输出)
    sim_candidates = [...]

    agent = MatHpcAgent()
    req = AgentRequest(
        run_id="hpc-001",
        message="提交 VASP HPC 计算",
        artifacts={"simulated": sim_candidates},
    )
    response = agent.run(req)
    print(response.artifacts["jobs"])  # List[HPCJobResult]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard

from .vasp_slurm import (
    HPCJobResult,
    submit_batch,
)
from .vasp_slurm import (
    stats as hpc_stats,
)


def _extract_input_candidates(req: AgentRequest) -> list:
    """从 req.artifacts 抽取候选(支持 SimCandidate / GenCandidate / dict)

    Returns:
        List of SimCandidate / GenCandidate / dict
    """
    artifacts = req.artifacts or {}

    # 优先 simulated(mat-sim 输出)
    if "simulated" in artifacts:
        cands = artifacts["simulated"]
        if isinstance(cands, list):
            return cands

    # 备选 candidates(mat-gen 直传,跳过 mat-sim)
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


def _is_stable_or_metastable(candidate) -> bool:
    """判断候选是否 stable / metastable(unstable 不值得 HPC 钱)"""
    # SimCandidate 有 stability 字段
    if hasattr(candidate, "stability"):
        return candidate.stability in ("stable", "metastable")
    # dict 格式
    if isinstance(candidate, dict):
        st = candidate.get("stability", "stable")
        return st in ("stable", "metastable")
    # GenCandidate 无 stability 字段,默认全跑
    return True


# ============================================================================
# MatHpcAgent 主体
# ============================================================================


class MatHpcAgent(MatWAUAgentBase):
    """mat-hpc-agent — 材料科学超算对接员

    业务流程(per act() 实现):
    1. 抽取 SimCandidate 列表(mat-sim 直传)或 GenCandidate(mat-gen 直传)
    2. 过滤 unstable(默认)
    3. 估算 HPC 资源 + 生成 VASP 输入 + 提交 Slurm
    4. 高 cost 拦截(> ¥1000 → status=blocked,需审批)
    5. 返回 List[HPCJobResult]
    """

    name = "mat-hpc-agent"

    def __init__(
        self,
        *,
        filter_unstable: bool = True,
        calc_type: str = "relax",
        cost_per_node_hour: float = 10.0,
        cost_threshold: float = 1000.0,
        domain: str | None = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            filter_unstable: 是否过滤掉 unstable 候选(默认 True,unstable 不值得 HPC 钱)
            calc_type: VASP 计算类型(relax / static / dos / band)
                     (per W15:nano 域用 cp2k,polymer 域用 lammps — Stage 2 注入)
            cost_per_node_hour: per-node ¥/h(Stage 2 接真实计费)
            cost_threshold: 单 job cost 阈值,超过 → status=blocked
            domain: 材料域(W15)
        """
        super().__init__(**kwargs)
        self.filter_unstable = filter_unstable
        self.calc_type = calc_type
        self.cost_per_node_hour = cost_per_node_hour
        self.cost_threshold = cost_threshold
        # W15: 域路由
        from agents.material_domain_router import DEFAULT_DOMAIN
        self.domain = domain or DEFAULT_DOMAIN

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            # HPC 预算默认 ¥5000,比 mat-gen 大
            self.safety_guard = SafetyGuard(budget_limit=5000.0)

    def system_prompt(self) -> str:
        return f"""你是材料科学超算对接员 agent(mat-hpc-agent),对 mat-sim-agent 弛豫后的候选提交 VASP HPC 计算。

能力:
1. 接收 mat-sim-agent 输出的 List[SimCandidate](CIF + 弛豫后能量 + 稳定性)
2. 默认过滤掉 unstable(只跑 stable + metastable,unstable 不值得花 HPC 钱)
3. 对每个候选生成 VASP 4 件套(INCAR + KPOINTS + POSCAR + POTCAR)
4. 生成 Slurm 提交脚本(#SBATCH 指令)
5. 估算 HPC 资源(nodes × cores × walltime)+ 成本(¥)
6. 高 cost(> ¥{self.cost_threshold})→ 拦截,需 supervisor 审批

VASP 计算类型(calc_type):
- relax:结构弛豫(IBRION=2,NSW=100)
- static:静态自洽(IBRION=-1,NSW=0)
- dos:态密度计算(ICHARG=11,NEDOS=3001)
- band:能带计算(ICHARG=11,LORBIT=11)

输出格式:
- reply:自然语言总结(总候选数 + 已提交 + 已拦截 + 总成本 ¥)
- artifacts.jobs: List[HPCJobResult](每个有 job_id / formula / status / estimated_cost / walltime_hours / vasp_inputs / slurm_script)

约束:
- 0 行 UI 代码(无头架构,所有展示走 HomeRail / Claude Desktop / Cursor)
- 1 个 LLM 调用 = 1 次 Goldens 跑分(mat-hpc.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-hpc 特有业务逻辑

        1. 从 ctx 拿 candidates(由 perceive 预处理)
        2. 过滤 unstable
        3. 提交 Slurm(Stage 1 mock;Stage 2 按 hpc_engine 路由)
        4. 统计 + SafetyGuard 检查
        5. 返回 AgentResponse
        """
        # W15: 域路由
        from agents.material_domain_router import detect_domain, get_hpc_engine, get_profile
        ctx_domain = ctx.get("domain") or self.domain
        if not ctx_domain or ctx_domain == "auto":
            ctx_domain = detect_domain(ctx.get("user_message", ""))
        hpc_engine = get_hpc_engine(ctx_domain)

        # 1. 拿 candidates
        candidates = ctx.get("_input_candidates") or []
        if not candidates:
            artifacts = ctx.get("_input_artifacts") or {}
            candidates = artifacts.get("simulated") or artifacts.get("candidates") or []

        if not candidates:
            return self._empty_response("上游 mat-sim 未传 simulated,candidates 也为空")

        # 2. 过滤 unstable(可选)
        if self.filter_unstable:
            filtered = [c for c in candidates if _is_stable_or_metastable(c)]
        else:
            filtered = list(candidates)

        if not filtered:
            return self._empty_response("过滤 unstable 后无候选可提交")

        # 3. 提交 Slurm(Stage 1 mock;Stage 2 按 hpc_engine 切真)
        try:
            jobs = submit_batch(
                candidates=filtered,
                calc_type=self.calc_type,
                cost_per_node_hour=self.cost_per_node_hour,
                cost_threshold=self.cost_threshold,
            )
        except Exception as e:
            return self._error_response(f"{hpc_engine} 提交失败: {e}")

        # 4. 统计
        stats = hpc_stats(jobs)
        budget = ctx.get("budget")
        total_cost = stats["total_cost"]

        # 5. 构造响应(W15: domain + engine 标签)
        domain_label = get_profile(ctx_domain).get("display_name_zh", ctx_domain)
        if not jobs:
            reply = f"❌ [{domain_label}/{hpc_engine}] 未能提交任何 HPC job"
            confidence = 0.2
        else:
            top_3 = [j.formula for j in jobs[:3] if j.status == "submitted"]
            reply = (
                f"✅ [{domain_label}/{hpc_engine}] 提交 {stats['submitted']} 个 HPC job "
                f"(总候选 {len(candidates)},过滤后 {len(filtered)})\n"
                f"状态分布:submitted={stats['submitted']}, "
                f"completed={stats['completed']}, "
                f"failed={stats['failed']}, "
                f"blocked={stats['blocked']}\n"
                f"总成本:¥{stats['total_cost']}, "
                f"总 walltime:{stats['total_walltime']}h\n"
                f"top-3 已提交:{top_3}"
            )
            # confidence 基于成功率
            if stats["failed"] == 0 and stats["blocked"] == 0:
                confidence = 0.9
            elif stats["failed"] + stats["blocked"] < len(jobs) * 0.2:
                confidence = 0.75
            else:
                confidence = 0.5

        # 6. 预算警告
        if budget is not None and total_cost > budget:
            reply = f"[WARN 超预算] 总成本 ¥{total_cost} > 预算 ¥{budget}\n" + reply

        response = AgentResponse(
            reply=reply,
            artifacts={
                "jobs": jobs,
                "stats": stats,
                "input_count": len(candidates),
                "filtered_count": len(filtered),
                "domain": ctx_domain,         # W15
                "hpc_engine": hpc_engine,     # W15
            },
            confidence=confidence,
            cost=total_cost,
        )

        # 7. SafetyGuard 检查(Stage 1 简版)
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1 重写:预处理 candidates(mat-sim → mat-hpc 数据流)

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
            artifacts={
                "jobs": [],
                "stats": {},
                "input_count": 0,
                "filtered_count": 0,
            },
            confidence=0.1,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应(Slurm 失败)"""
        return AgentResponse(
            reply=f"❌ mat-hpc 错误: {error}",
            artifacts={
                "jobs": [],
                "stats": {},
                "input_count": 0,
                "filtered_count": 0,
            },
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatHpcAgent:
    """便利函数:创建带默认 Harness 的 MatHpcAgent"""
    return MatHpcAgent(
        filter_unstable=True,
        calc_type="relax",
        cost_per_node_hour=10.0,
        cost_threshold=1000.0,
    )


# ============================================================================
# CLI 入口
# ============================================================================

if __name__ == "__main__":
    print("🚀 MatHpcAgent Demo")
    print("=" * 60)

    # 跑 1 个 demo:mat-gen → mat-sim → mat-hpc 三段链路
    from agents.mat_gen_agent.mattergen import GenConstraints
    from agents.mat_gen_agent.mattergen import generate as mattergen_generate
    from agents.mat_sim_agent.mat_sim_agent import create_default_agent as create_sim

    # Stage 1: mat-gen
    print("\n📦 Stage 1: mat-gen 生成候选")
    gen_constraints = GenConstraints(elements=["Li", "Co", "O"], n_samples=8)
    gen_candidates = mattergen_generate(gen_constraints)
    print(f"   生成 {len(gen_candidates)} 个候选")

    # Stage 2: mat-sim
    print("\n🔬 Stage 2: mat-sim 跑 CHGNet 弛豫")
    sim_agent = create_sim()
    sim_req = AgentRequest(
        run_id="demo-sim",
        message="弛豫",
        artifacts={"candidates": gen_candidates},
    )
    sim_response = sim_agent.run(sim_req)
    sim_candidates = sim_response.artifacts["simulated"]
    print(f"   弛豫后 {len(sim_candidates)} 个候选")
    for s in sim_candidates[:3]:
        print(f"   - {s.formula}: stability={s.stability}, energy={s.relaxed_energy:.2f}")

    # Stage 3: mat-hpc
    print("\n🖥️ Stage 3: mat-hpc 提交 VASP HPC")
    agent = create_default_agent()
    req = AgentRequest(
        run_id="demo-hpc",
        message="提交 VASP 计算",
        artifacts={"simulated": sim_candidates},
    )
    response = agent.run(req)

    print(f"\n📨 reply: {response.reply[:300]}")
    print(f"📊 confidence: {response.confidence:.0%}, cost: ¥{response.cost:.2f}")
    print("\n🖥️ HPC 作业:")
    for i, job in enumerate(response.artifacts.get("jobs", [])[:5]):
        print(
            f"   #{i+1} {job.job_id}: {job.formula}, "
            f"status={job.status}, "
            f"¥{job.estimated_cost}, {job.walltime_hours}h, "
            f"{job.n_nodes}×{job.n_cores_per_node} cores"
        )


__all__ = [
    "HPCJobResult",
    "MatHpcAgent",
    "create_default_agent",
]