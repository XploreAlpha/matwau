"""mat-critic-agent — 材料科学 3 路交叉验证员(per dev plan §5.7 + §七 W12)

Stage 1 / Phase 1:纯规则引擎(关键词 + 数值比较)
Stage 2(WAU v1.0.0 GA 后):接 LLM 复核

业务流程(per act() 实现):
1. 从 req.artifacts 抽 candidates(支持 GenCandidate / SimCandidate / HPCJobResult / ExpRecipe / dict)
2. 跑 critic_engine.evaluate_candidates 3 路打分
3. 识别失败类型 + 生成 top 建议
4. 返回 CriticVerdict

用法:
    from agents.mat_critic_agent import MatCriticAgent, evaluate_candidates
    from agents.mat_sim_agent.mat_sim_agent import SimCandidate

    # 准备 candidates(从 mat-sim 输出的 SimCandidate)
    simulated = [...]

    agent = MatCriticAgent()
    req = AgentRequest(
        run_id="critic-001",
        message="为什么 XRD 谱不对",
        artifacts={"candidates": simulated},
    )
    response = agent.run(req)
    print(response.artifacts["verdict"].verdict)  # pass / warn / fail
    print(response.artifacts["failures"])         # List[FailureType]
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

from .critic_engine import (  # noqa: E402
    CriticScore,
    CriticVerdict,
    FailureType,
    evaluate_candidates,
    explain_failure,
)


# ============================================================================
# 数据结构(对外暴露)
# ============================================================================


@dataclass
class CriticOutput:
    """mat-critic 对外暴露的输出(兼容 SimCandidate / ExpRecipe 风格)"""

    verdict: str                                 # pass / warn / fail
    overall_score: float                          # 0-1
    l1_score: float                              # 物理一致性
    l2_score: float                              # 实验可行性
    l3_score: float                              # 安全规则
    failures: List[FailureType]
    top_suggestions: List[str]
    confidence: float = 0.85

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "overall_score": round(self.overall_score, 3),
            "l1_score": round(self.l1_score, 3),
            "l2_score": round(self.l2_score, 3),
            "l3_score": round(self.l3_score, 3),
            "failures": [
                {"code": f.code, "severity": f.severity, "confidence": f.confidence}
                for f in self.failures
            ],
            "top_suggestions": self.top_suggestions,
        }


def _verdict_to_output(verdict: CriticVerdict) -> CriticOutput:
    """CriticVerdict → CriticOutput(对外稳定格式)"""
    return CriticOutput(
        verdict=verdict.verdict,
        overall_score=verdict.overall_score,
        l1_score=verdict.l1.score,
        l2_score=verdict.l2.score,
        l3_score=verdict.l3.score,
        failures=verdict.failures,
        top_suggestions=verdict.top_suggestions,
    )


# ============================================================================
# MatCriticAgent 主体
# ============================================================================


class MatCriticAgent(MatWAUAgentBase):
    """mat-critic-agent — 材料科学 3 路交叉验证员

    业务流程:
    1. 抽取上游候选(支持 5 种格式:GenCandidate / SimCandidate / HPCJobResult / ExpRecipe / dict)
    2. 跑 critic_engine.evaluate_candidates 3 路打分
    3. 识别失败类型 + 生成 top 建议
    4. 返回 CriticOutput + 自然语言总结
    """

    name = "mat-critic-agent"

    def __init__(
        self,
        *,
        cost_per_eval: float = 0.05,        # ¥/次(规则引擎几乎免费)
        **kwargs,
    ) -> None:
        """构造

        Args:
            cost_per_eval: 单次评估估算成本 ¥(规则引擎几乎免费,Stage 2 接 LLM 后会涨)
        """
        super().__init__(**kwargs)
        self.cost_per_eval = cost_per_eval

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 3 路交叉验证员 agent(mat-critic-agent),用 3 路打分验证候选是否可信。

3 路打分:
- L1 物理一致性(0.4 权重):形成能 + 弛豫能 + 收敛性
- L2 实验可行性(0.4 权重):元素可得性 + 合成温度
- L3 安全规则(0.2 权重):禁元素 + 放射性 + 高毒

verdict 阈值:
- 综合分 >= 0.7 → pass(可信)
- 0.5-0.7 → warn(有疑,需复核)
- < 0.5 → fail(不可信)

主要场景:
- 解释失败(explain_failure workflow):为什么 XRD 谱不对 / 合成失败
- 评估候选可信度:对 mat-gen/sim/hpc/exp 任意输出打分
- 输出 CriticOutput(verdict + 3 路分 + failures + top_suggestions)

约束:
- 0 行 UI 代码(无头架构)
- 1 个 LLM 调用 = 1 次 Goldens 跑分(mat-critic.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-critic 特有业务逻辑

        1. 从 ctx 抽 user_message + candidates
        2. 用 evaluate_candidates 或 explain_failure(per scenario)
        3. 构造 CriticOutput + 自然语言 reply
        4. SafetyGuard 检查
        5. 返回 AgentResponse
        """
        user_message = ctx.get("user_message") or ""
        candidates = ctx.get("_input_candidates") or []

        # fallback: 从 artifacts 抽
        if not candidates:
            artifacts = ctx.get("_input_artifacts") or {}
            candidates = artifacts.get("candidates") or artifacts.get("simulated") or artifacts.get("jobs") or artifacts.get("recipes") or []

        # fallback: 从 ctx 直接抽
        if not candidates:
            candidates = ctx.get("candidates") or []

        if not candidates:
            return self._empty_response("上游未传 candidates")

        # 1. 跑 3 路打分
        try:
            # scenario 1: explain_failure workflow(用户问"为什么失败")
            if self._is_failure_query(user_message):
                verdict = explain_failure(user_message, candidates=candidates)
            else:
                # scenario 2: 普通评估
                verdict = evaluate_candidates(candidates, user_intent=user_message)
        except Exception as e:
            return self._error_response(f"mat-critic 评估失败: {e}")

        # 2. 转 CriticOutput
        output = _verdict_to_output(verdict)

        # 3. 自然语言 reply
        reply = self._format_reply(output, verdict)

        # 4. 置信度
        confidence = 0.9 if verdict.verdict == "pass" else (0.7 if verdict.verdict == "warn" else 0.5)

        # 5. cost
        cost = self.cost_per_eval

        response = AgentResponse(
            reply=reply,
            artifacts={
                "verdict": output,
                "critic_verdict": verdict,    # 完整结构(给下游用)
                "failures": [f for f in verdict.failures],
                "suggestions": output.top_suggestions,
                "input_count": len(candidates),
            },
            confidence=confidence,
            cost=cost,
        )

        # 6. SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:抽取 user_message + candidates"""
        ctx = super().perceive(req)

        ctx["user_message"] = req.message
        ctx["_input_candidates"] = self._extract_candidates(req)
        ctx["_input_artifacts"] = req.artifacts or {}

        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _extract_candidates(self, req: AgentRequest) -> List:
        """从 req.artifacts 抽 candidates(支持 5 种格式)"""
        artifacts = req.artifacts or {}

        # 优先 candidates
        if "candidates" in artifacts and isinstance(artifacts["candidates"], list):
            return artifacts["candidates"]
        # simulated(mat-sim)
        if "simulated" in artifacts and isinstance(artifacts["simulated"], list):
            return artifacts["simulated"]
        # jobs(mat-hpc)
        if "jobs" in artifacts and isinstance(artifacts["jobs"], list):
            return artifacts["jobs"]
        # recipes(mat-exp)
        if "recipes" in artifacts and isinstance(artifacts["recipes"], list):
            return artifacts["recipes"]
        return []

    def _is_failure_query(self, user_message: str) -> bool:
        """判断是否为失败解释 query"""
        msg_lower = user_message.lower()
        failure_keywords = [
            "为什么", "失败", "不对", "异常", "错了", "wrong", "fail", "error",
            "xrd", "谱", "synthesis", "合成", "energy", "能量异常",
        ]
        return any(kw in user_message or kw in msg_lower for kw in failure_keywords)

    def _format_reply(self, output: CriticOutput, verdict: CriticVerdict) -> str:
        """生成自然语言 reply"""
        lines = [
            f"📊 mat-critic verdict: {output.verdict.upper()}(综合 {output.overall_score:.2f})",
            f"   L1 物理一致性: {output.l1_score:.2f}",
            f"   L2 实验可行性: {output.l2_score:.2f}",
            f"   L3 安全规则:   {output.l3_score:.2f}",
        ]

        if verdict.failures:
            lines.append(f"\n⚠️ 发现 {len(verdict.failures)} 个问题:")
            for f in verdict.failures[:3]:
                lines.append(f"   [{f.severity.upper()}] {f.code}(置信 {f.confidence:.2f})")
                if f.evidence:
                    lines.append(f"     证据: {f.evidence[0][:80]}")

        if output.top_suggestions:
            lines.append(f"\n💡 修复建议:")
            for sug in output.top_suggestions[:3]:
                lines.append(f"   - {sug}")

        return "\n".join(lines)

    def _empty_response(self, reason: str) -> AgentResponse:
        """空响应"""
        empty_verdict = CriticOutput(
            verdict="warn",
            overall_score=0.5,
            l1_score=0.5,
            l2_score=0.5,
            l3_score=0.7,
            failures=[],
            top_suggestions=[reason],
            confidence=0.3,
        )
        return AgentResponse(
            reply=f"⚠️ mat-critic: {reason}",
            artifacts={"verdict": empty_verdict, "input_count": 0},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应"""
        error_verdict = CriticOutput(
            verdict="fail",
            overall_score=0.0,
            l1_score=0.0,
            l2_score=0.0,
            l3_score=0.0,
            failures=[],
            top_suggestions=[error],
            confidence=0.0,
        )
        return AgentResponse(
            reply=f"❌ mat-critic 错误: {error}",
            artifacts={"verdict": error_verdict, "input_count": 0},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatCriticAgent:
    """便利函数:创建带默认 Harness 的 MatCriticAgent"""
    return MatCriticAgent(cost_per_eval=0.05)


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatCriticAgent Demo")
    print("=" * 60)

    agent = create_default_agent()

    # Demo 1: 评估稳定候选
    print("\n📊 Demo 1: 评估 LiCoO2 等稳定候选")
    from agents.mat_sim_agent.mat_sim_agent import SimCandidate

    stable_candidates = [
        SimCandidate(
            formula="LiCoO2",
            cif="data_LiCoO2\n_cell_length_a 4.5\n",
            relaxed_energy=-3.5,
            forces_max=0.01,
            relaxation_converged=True,
            stability="stable",
            confidence=0.9,
        ),
        SimCandidate(
            formula="LiFePO4",
            cif="data_LiFePO4\n_cell_length_a 5.0\n",
            relaxed_energy=-3.2,
            forces_max=0.02,
            relaxation_converged=True,
            stability="stable",
            confidence=0.85,
        ),
    ]

    req1 = AgentRequest(
        run_id="critic-demo-1",
        message="评估这些候选",
        artifacts={"candidates": stable_candidates},
    )
    r1 = agent.run(req1)
    print(r1.reply)
    print(f"   artifacts keys: {list(r1.artifacts.keys())}")

    # Demo 2: 解释 XRD 失败
    print("\n\n📊 Demo 2: 解释 XRD 谱不对")
    bad_candidates = [
        SimCandidate(
            formula="WrongPhase",
            cif="data_X\n",
            relaxed_energy=-0.3,         # 异常高
            forces_max=0.8,              # 未收敛
            relaxation_converged=False,
            stability="unstable",
            confidence=0.4,
        ),
    ]

    req2 = AgentRequest(
        run_id="critic-demo-2",
        message="为什么 XRD 谱不对",
        artifacts={"candidates": bad_candidates},
    )
    r2 = agent.run(req2)
    print(r2.reply)

    # Demo 3: 安全规则(无 Co)
    print("\n\n📊 Demo 3: 用户说 '无 Co' 但候选含 Co")
    cobalt_candidates = [
        SimCandidate(
            formula="LiCoO2",
            cif="data_LiCoO2\n",
            relaxed_energy=-3.5,
            forces_max=0.01,
            relaxation_converged=True,
            stability="stable",
            confidence=0.9,
        ),
    ]

    req3 = AgentRequest(
        run_id="critic-demo-3",
        message="出无 Co 锂电池正极",
        artifacts={"candidates": cobalt_candidates},
    )
    r3 = agent.run(req3)
    print(r3.reply)


__all__ = [
    "MatCriticAgent",
    "CriticOutput",
    "create_default_agent",
]