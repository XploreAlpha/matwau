"""mat-critic-agent — 材料科学 3 路交叉验证员(per dev plan §5.7 + §七 W12)

Stage 1 / Phase 1:纯规则引擎(关键词 + 数值比较)
Stage 2(WAU v1.0.0 GA 后):接 LLM 复核 — **W33 已实现**

业务流程(per act() 实现):
1. 从 req.artifacts 抽 candidates(支持 GenCandidate / SimCandidate / HPCJobResult / ExpRecipe / dict)
2. 跑 critic_engine.evaluate_candidates 3 路打分(W30 加 L4 跨机器人)
3. 识别失败类型 + 生成 top 建议
4. W33 可选:接 LLMReviewer 做自然语言复核
5. 返回 CriticVerdict + llm_review

用法:
    from agents.mat_critic_agent import MatCriticAgent, evaluate_candidates
    from agents.mat_sim_agent.mat_sim_agent import SimCandidate

    # 准备 candidates(从 mat-sim 输出的 SimCandidate)
    simulated = [...]

    # 默认(纯规则,W33 llm review 关)— 测试/CI 默认
    agent = MatCriticAgent()

    # W33 — 显式开 LLM 复核(需要 MATWAU_LLM_API_KEY + MATWAU_LLM_ENABLED=1)
    agent = MatCriticAgent(enable_llm_review=True)
    req = AgentRequest(
        run_id="critic-001",
        message="为什么 XRD 谱不对",
        artifacts={"candidates": simulated},
    )
    response = agent.run(req)
    print(response.artifacts["verdict"].verdict)  # pass / warn / fail
    print(response.artifacts["llm_review"])       # W33 NEW - LLM 自然语言复核
    print(response.artifacts["failures"])         # List[FailureType]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
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

from .critic_engine import (
    CriticVerdict,
    FailureType,
    evaluate_candidates,
    evaluate_chemist_report,  # W30
    explain_failure,
)
from .llm_reviewer import (
    LLMReviewer,
)
from .llm_reviewer import (
    get_default_reviewer as _get_default_reviewer,
)

# v1.4-Academic M3 — cross-source summary widget
from agents.widget_helpers import (
    assert_spoken_text_safe,
    attach_widget_protocol,
    make_cross_source_summary_widget,
    summarize_for_voice,
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
    l4_cross_robot_score: float = 0.0            # W30 NEW - 跨机器人一致性
    l5_cross_source_score: float = 0.0           # M3 NEW - 跨数据源一致率
    l5_cross_source_consensus_rate: float = 0.0  # M3 NEW
    l5_cross_source_n_clusters: int = 0          # M3 NEW
    failures: list[FailureType] = None            # type: ignore
    top_suggestions: list[str] = None             # type: ignore
    confidence: float = 0.85
    # W33 NEW — LLM 二次复核
    llm_review: str = ""                         # 自然语言复核文本(空串 = 未跑 / 失败)
    llm_review_model: str = ""                   # 实际用的 model
    llm_review_cost: float = 0.0                 # LLM 调用成本 ¥
    llm_review_error: str = ""                   # 失败时的错误信息(成功时为空)

    def __post_init__(self):
        if self.failures is None:
            self.failures = []
        if self.top_suggestions is None:
            self.top_suggestions = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "overall_score": round(self.overall_score, 3),
            "l1_score": round(self.l1_score, 3),
            "l2_score": round(self.l2_score, 3),
            "l3_score": round(self.l3_score, 3),
            "l4_cross_robot_score": round(self.l4_cross_robot_score, 3),  # W30
            "l5_cross_source_score": round(self.l5_cross_source_score, 3),  # M3 NEW
            "l5_cross_source_consensus_rate": round(self.l5_cross_source_consensus_rate, 3),
            "l5_cross_source_n_clusters": self.l5_cross_source_n_clusters,
            "failures": [
                {"code": f.code, "severity": f.severity, "confidence": f.confidence}
                for f in self.failures
            ],
            "top_suggestions": self.top_suggestions,
            # W33 NEW
            "llm_review": self.llm_review,
            "llm_review_model": self.llm_review_model,
            "llm_review_cost": round(self.llm_review_cost, 6),
            "llm_review_error": self.llm_review_error,
        }


def _verdict_to_output(verdict: CriticVerdict) -> CriticOutput:
    """CriticVerdict → CriticOutput(对外稳定格式)"""
    # M3 — cross_source(L5) 可能为 None(没启用 L5 时)
    cs = getattr(verdict, "cross_source", None)
    cs_score = cs.score if cs is not None else 0.0
    cs_consensus_rate = cs.consensus_rate if cs is not None else 0.0
    cs_n_clusters = cs.n_clusters if cs is not None else 0

    return CriticOutput(
        verdict=verdict.verdict,
        overall_score=verdict.overall_score,
        l1_score=verdict.l1.score,
        l2_score=verdict.l2.score,
        l3_score=verdict.l3.score,
        l4_cross_robot_score=verdict.cross_robot.score,  # W30
        # M3 NEW
        l5_cross_source_score=cs_score,
        l5_cross_source_consensus_rate=cs_consensus_rate,
        l5_cross_source_n_clusters=cs_n_clusters,
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
        enable_llm_review: bool = False,    # W33 — 默认 False,保持测试确定性
        llm_reviewer: LLMReviewer | None = None,  # W33 — 显式注入(测试用)
        **kwargs,
    ) -> None:
        """构造

        Args:
            cost_per_eval: 单次评估估算成本 ¥(规则引擎几乎免费,Stage 2 接 LLM 后会涨)
            enable_llm_review: W33 — 是否启用 LLM 二次复核(默认 False)
                True → 跑完规则打分后,自动调 LLMReviewer 出自然语言复核
                需 MATWAU_LLM_API_KEY + MATWAU_LLM_ENABLED=1 才会真跑
                否则 fail-soft 跳过
            llm_reviewer: W33 — 显式注入 LLMReviewer 实例(测试用 mock client)
        """
        super().__init__(**kwargs)
        self.cost_per_eval = cost_per_eval
        self.enable_llm_review = enable_llm_review
        self._llm_reviewer = llm_reviewer  # None → 懒加载 get_default_reviewer()

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def _get_llm_reviewer(self) -> LLMReviewer | None:
        """获取 LLMReviewer(懒加载)"""
        if self._llm_reviewer is None:
            self._llm_reviewer = _get_default_reviewer()
        return self._llm_reviewer

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

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-critic 特有业务逻辑

        1. 从 ctx 抽 user_message + candidates
        2. W30 4-mode auto-detect:
           - report / robot_results → evaluate_chemist_report(L1-L4 4 路)
           - 普通 candidates → evaluate_candidates(L1-L3 3 路)
           - explain_failure workflow → explain_failure
        3. 构造 CriticOutput + 自然语言 reply
        4. SafetyGuard 检查
        5. 返回 AgentResponse
        """
        user_message = ctx.get("user_message") or ""
        candidates = ctx.get("_input_candidates") or []
        artifacts_ctx = ctx.get("_input_artifacts") or {}

        # fallback: 从 artifacts 抽
        if not candidates:
            candidates = (
                artifacts_ctx.get("candidates")
                or artifacts_ctx.get("simulated")
                or artifacts_ctx.get("jobs")
                or artifacts_ctx.get("recipes")
                or []
            )

        # fallback: 从 ctx 直接抽
        if not candidates:
            candidates = ctx.get("candidates") or []

        # M3 NEW - Mode 5 优先:cross_source_records 在前(L5 不需要 candidates)
        use_cross_source = ctx.get("use_cross_source") or artifacts_ctx.get("use_cross_source")
        records_by_platform = ctx.get("records_by_platform") or artifacts_ctx.get("records_by_platform")
        cross_source_priority = (
            (use_cross_source or str(use_cross_source).lower() == "true")
            and records_by_platform
        )

        # 1. 跑打分(W30 - 4 mode auto-detect, M3 加 Mode 5)
        if not cross_source_priority and not candidates:
            return self._empty_response("上游未传 candidates / report")

        try:
            # M3 NEW - Mode 5: cross_source_records(L5 跨数据源一致率)
            if cross_source_priority:
                from agents.mat_critic_agent.critic_engine import evaluate_with_cross_source
                # L5 入口(candidates 仍然传,fallback 用)
                verdict = evaluate_with_cross_source(
                    candidates if candidates else [{"formula": user_message}],
                    records_by_platform,
                    user_intent=user_message,
                )
            # W30 - Mode 1: ChemistReport dataclass / dict
            elif candidates == ["__chemist_report__"]:
                report = artifacts_ctx.get("report")
                verdict = evaluate_chemist_report(report, user_intent=user_message)

            # W30 - Mode 2: 4 robot results 列表(包装成 dict-form report)
            elif candidates == ["__robot_results__"]:
                robot_results = artifacts_ctx.get("robot_results", []) or []
                fake_report = {
                    "robot_results": robot_results,
                    "target_sample": "",
                }
                verdict = evaluate_chemist_report(fake_report, user_intent=user_message)

            # 原 3 路 - explain_failure workflow
            elif self._is_failure_query(user_message):
                verdict = explain_failure(user_message, candidates=candidates)

            # 原 3 路 - 普通评估
            else:
                verdict = evaluate_candidates(candidates, user_intent=user_message)
        except Exception as e:
            return self._error_response(f"mat-critic 评估失败: {e}")

        # 2. 转 CriticOutput
        output = _verdict_to_output(verdict)

        # 2.5 W33 — LLM 二次复核(可选,默认关)
        if self.enable_llm_review:
            self._run_llm_review(output, verdict, user_message=user_message, artifacts_ctx=artifacts_ctx)

        # 3. 自然语言 reply
        reply = self._format_reply(output, verdict)

        # 4. 置信度
        confidence = 0.9 if verdict.verdict == "pass" else (0.7 if verdict.verdict == "warn" else 0.5)

        # 5. cost
        cost = self.cost_per_eval + output.llm_review_cost  # W33 — 加 LLM cost

        response = AgentResponse(
            reply=reply,
            artifacts={
                "verdict": output,
                "critic_verdict": verdict,    # 完整结构(给下游用)
                "failures": [f for f in verdict.failures],
                "suggestions": output.top_suggestions,
                "input_count": len(candidates),
                # W33 NEW
                "llm_review": output.llm_review,
                "llm_review_model": output.llm_review_model,
                "llm_review_cost": output.llm_review_cost,
                "llm_review_error": output.llm_review_error,
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

        # v1.4-Academic M3 — attach matwau_cross_source_summary widget(Mode 5 路径)
        if cross_source_priority and records_by_platform:
            cs = getattr(verdict, "cross_source", None)
            if cs is not None:
                _attach_cross_source_widget(response, verdict, records_by_platform, user_message)

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1 重写:抽取 user_message + candidates"""
        ctx = super().perceive(req)

        ctx["user_message"] = req.message
        ctx["_input_candidates"] = self._extract_candidates(req)
        ctx["_input_artifacts"] = req.artifacts or {}

        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _extract_candidates(self, req: AgentRequest) -> list:
        """从 req.artifacts 抽 candidates(支持 7 种格式 — W30 加 2 种 ChemistReport)

        优先级(W30):
        1. report - ChemistReport dataclass / dict(走 evaluate_chemist_report)
        2. robot_results - 4 robot results 列表(走 evaluate_chemist_report 包装)
        3. candidates / simulated / jobs / recipes(原 5 种 fallback)
        """
        artifacts = req.artifacts or {}

        # W30 - 优先 ChemistReport 模式
        if "report" in artifacts and artifacts["report"] is not None:
            return ["__chemist_report__"]  # sentinel

        if "robot_results" in artifacts and isinstance(artifacts["robot_results"], list):
            return ["__robot_results__"]  # sentinel,act() 会包装成 report

        # 兼容 5 种原 fallback
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

    def _run_llm_review(
        self,
        output: CriticOutput,
        verdict: CriticVerdict,
        *,
        user_message: str,
        artifacts_ctx: dict[str, Any],
    ) -> None:
        """W33 — 跑 LLM 二次复核,结果写进 output(失败吞掉)

        设计原则:
        - LLM 失败 / 不可用 → output.llm_review 留空,不影响 verdict
        - target_sample 从 artifacts_ctx["report"].target_sample 抽
        - 不抛异常
        """
        reviewer = self._get_llm_reviewer()
        if reviewer is None or not reviewer.is_available():
            return

        # 抽 target_sample
        target_sample = ""
        report = artifacts_ctx.get("report")
        if report is not None and hasattr(report, "target_sample"):
            target_sample = str(getattr(report, "target_sample", "") or "")

        # 调 LLM(失败吞掉)
        try:
            result = reviewer.review(
                critic_output=output,
                target_sample=target_sample,
                user_intent=user_message,
            )
        except Exception as e:
            output.llm_review_error = f"{type(e).__name__}: {e}"
            return

        if result is None:
            return

        # 写回 output
        output.llm_review = result.review or ""
        output.llm_review_model = result.model or ""
        output.llm_review_cost = float(result.cost_cny or 0.0)
        if result.error:
            output.llm_review_error = result.error

    def _format_reply(self, output: CriticOutput, verdict: CriticVerdict) -> str:
        """生成自然语言 reply"""
        lines = [
            f"📊 mat-critic verdict: {output.verdict.upper()}(综合 {output.overall_score:.2f})",
            f"   L1 物理一致性: {output.l1_score:.2f}",
            f"   L2 实验可行性: {output.l2_score:.2f}",
            f"   L3 安全规则:   {output.l3_score:.2f}",
        ]

        # W30 - L4 跨机器人一致性(只在 cross_robot 有数据时显示)
        if output.l4_cross_robot_score > 0 or getattr(verdict.cross_robot, "rules_passed", None):
            lines.append(f"   L4 跨机器人一致性: {output.l4_cross_robot_score:.2f}")
            cross = verdict.cross_robot
            if cross.rules_passed:
                lines.append(f"     ✅ 通过规则: {', '.join(cross.rules_passed)}")
            if cross.rules_failed:
                lines.append(f"     ❌ 失败规则: {', '.join(cross.rules_failed)}")

        if verdict.failures:
            lines.append(f"\n⚠️ 发现 {len(verdict.failures)} 个问题:")
            for f in verdict.failures[:3]:
                lines.append(f"   [{f.severity.upper()}] {f.code}(置信 {f.confidence:.2f})")
                if f.evidence:
                    lines.append(f"     证据: {f.evidence[0][:80]}")

        if output.top_suggestions:
            lines.append("\n💡 修复建议:")
            for sug in output.top_suggestions[:3]:
                lines.append(f"   - {sug}")

        # W33 NEW — LLM 复核
        if output.llm_review:
            lines.append(f"\n🤖 LLM 复核({output.llm_review_model}):")
            lines.append(f"   {output.llm_review}")
            if output.llm_review_cost > 0:
                lines.append(f"   (LLM cost: ¥{output.llm_review_cost:.4f})")
        elif output.llm_review_error:
            lines.append(f"\n🤖 LLM 复核跳过: {output.llm_review_error[:100]}")

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


# ============================================================================
# v1.4-Academic M3 — cross-source widget attach helper(module-level)
# ============================================================================


def _attach_cross_source_widget(
    response: AgentResponse,
    verdict: CriticVerdict,
    records_by_platform: dict[str, list[dict]],
    user_message: str,
) -> None:
    """attach matwau_cross_source_summary widget 到 critic AgentResponse

    wire 字段(per homerail FE VoiceDynamicWidget union):
    - data["query"] = user_message
    - data["consensus"] = {text, confidence, consensus_rate}
    - data["sources"] = [{name, label, hit_count, agreed, error}]
    """
    cross_source = getattr(verdict, "cross_source", None)

    # 抽 4 platform sources — 调 module-level helpers(MatCriticAgent 实例方法用 __new__ copy 调用)
    sources = _extract_sources_for_widget(records_by_platform, cross_source)
    consensus_text, confidence = _cross_source_consensus_text(cross_source)
    consensus_rate = cross_source.consensus_rate if cross_source else 0.0

    widget = make_cross_source_summary_widget(
        consensus_text=consensus_text,
        confidence=confidence,
        consensus_rate=consensus_rate,
        sources=sources,
        query=user_message,
    )

    # TTS — 用 sources 当 records(简化)
    spoken_records = [{"name": s["name"], "agreed": s["agreed"], "hit_count": s["hit_count"]}
                      for s in sources]
    spoken = summarize_for_voice(spoken_records, user_message, locale="zh", kind="cross_source")
    attach_widget_protocol(
        response,
        widgets=[widget],
        spoken_text=spoken,
        structured_data={
            "query": user_message,
            "consensus": {"text": consensus_text, "confidence": confidence,
                          "consensus_rate": consensus_rate},
            "sources": sources,
            "records_by_platform": records_by_platform,
        },
    )
    assert_spoken_text_safe(spoken)


# module-level helpers(供 _attach_cross_source_widget)
PLATFORM_LABELS = {
    "OQMD": "OQMD(DFT)",
    "COD": "COD(实验晶体)",
    "NOMAD": "NOMAD(archive)",
    "JARVIS": "JARVIS(综合)",
}


def _extract_sources_for_widget(
    records_by_platform: dict[str, list[dict]],
    cross_source,  # CrossSourceStats | None
) -> list[dict]:
    """从 records_by_platform 抽 4 platform source entries"""
    n_consensus = cross_source.n_clusters if cross_source else 0
    sources = []
    for platform_name, label in PLATFORM_LABELS.items():
        records = records_by_platform.get(platform_name, [])
        hit_count = len(records)
        error = "" if hit_count > 0 else "no_hits"
        agreed = hit_count > 0 and n_consensus > 0
        sources.append({
            "name": platform_name,
            "label": label,
            "hit_count": hit_count,
            "agreed": agreed,
            "error": error,
        })
    return sources


def _cross_source_consensus_text(cross_source) -> tuple[str, float]:
    """生成 consensus.text + confidence"""
    if cross_source is None:
        return ("未跑跨源评估", 0.0)
    rate = cross_source.consensus_rate
    n_clusters = cross_source.n_clusters
    confidence = cross_source.score
    if rate >= 0.7:
        tone = "高度一致"
    elif rate >= 0.4:
        tone = "中等一致"
    else:
        tone = "低一致性"
    text = f"L5 跨源{tone}(consensus_rate={rate:.0%},达成 {n_clusters} 个 cluster)"
    return (text, confidence)


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
    "CriticOutput",
    "MatCriticAgent",
    "create_default_agent",
]