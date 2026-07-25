"""mat-intent-agent — 材料科学意图翻译官(per WauProject 拍板)

业务层意图解析(区别于平台层 wau-intent):
- wau-intent(平台层):用户想干啥 → 路由到哪个 WAU 能力
- mat-intent(业务层):材料任务具体干啥 → 调 mat-lit/gen/sim/exp

业务流程(per act() 实现):
1. 从 req.message 拿用户意图
2. parse_mat_intent() → MatIntent(子类 + material_system + target_props + constraints)
3. 包装成 AgentResponse(artifacts.mat_intent + downstream_agent + reply)

Stage 1 mock 用关键词 + 规则,Stage 2 接真 LLM

用法:
    from agents.mat_intent_agent.mat_intent_agent import MatIntentAgent
    from matwau.core.agent_base import AgentRequest

    agent = MatIntentAgent()
    req = AgentRequest(
        run_id="intent-001",
        message="设计新型无钴锂电池正极材料,能量密度 > 500 Wh/kg",
    )
    response = agent.run(req)
    print(response.artifacts["mat_intent"])
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

# 允许直接 python3 -m 运行
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

from .intent_classifier import (  # noqa: E402
    MatIntent,
    parse_mat_intent,
)


# ============================================================================
# MatIntentAgent 主体
# ============================================================================


class MatIntentAgent(MatWAUAgentBase):
    """mat-intent-agent — 材料科学意图翻译官

    业务流程:
    1. 接收用户 1 句话意图(中英文都支持)
    2. 解析 5 子类 + 11 material_system + 8 target_props + constraints
    3. 输出 MatIntent(供下游 mat-orchestrator 或 mat-pipeline 使用)
    """

    name = "mat-intent-agent"

    def __init__(
        self,
        *,
        default_downstream: str = "mat-pipeline",
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_downstream: 默认下游 agent(mat-pipeline / mat-orchestrator)
        """
        super().__init__(**kwargs)
        self.default_downstream = default_downstream

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=10.0)

    def system_prompt(self) -> str:
        return """你是材料科学意图翻译官(mat-intent-agent,业务层意图解析)。

**注意**:你的工作跟 wau-intent(平台层)不同:
- wau-intent:平台层,路由用户请求到哪个 WAU 能力
- mat-intent:业务层,把 material_task 拆解成具体的 mat 子任务

能力:
1. 接收用户 1 句话意图(中文 / 英文 / 混合)
2. 解析 5 子类:design_new_material / optimize_existing / explain_failure / literature_review / experiment_planning
3. 识别 11 material_system:li_ion_cathode / solid_electrolyte / catalyst_her / ...
4. 提取 8 target_props:energy_density / ionic_conductivity / voltage / ...
5. 提取 constraints:elements / forbidden / n_samples
6. 输出 MatIntent(供下游 mat-orchestrator 或 mat-pipeline 使用)

输出格式:
- reply:自然语言总结(子类 + material_system + target_props + 约束)
- artifacts.mat_intent: MatIntent 对象
- artifacts.downstream_agent: 默认 "mat-pipeline"

约束:
- 0 行 UI 代码(无头架构)
- 1 次 LLM 调用 = 1 次 Goldens 跑分(mat-intent.yaml)
"""

    def act(self, ctx: Dict[str, Any], tools: list) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-intent 特有业务逻辑

        1. 从 ctx 拿 user_message
        2. parse_mat_intent() → MatIntent
        3. 包装成 AgentResponse
        """
        user_message = ctx.get("user_message", "")
        if not user_message:
            messages = ctx.get("messages", [])
            if messages and hasattr(messages[-1], "content"):
                user_message = messages[-1].content

        if not user_message:
            return self._empty_response("用户消息为空")

        # 解析
        try:
            mat_intent = parse_mat_intent(user_message)
        except Exception as e:
            return self._error_response(f"意图解析失败: {e}")

        # 设置下游 agent
        mat_intent.downstream_agent = self.default_downstream

        # 构造响应
        reply = self._format_reply(mat_intent)

        # confidence 衰减(若 confidence 过低)
        confidence = mat_intent.confidence

        response = AgentResponse(
            reply=reply,
            artifacts={
                "mat_intent": mat_intent,
                "mat_intent_dict": mat_intent.to_dict(),
                "subclass": mat_intent.subclass,
                "material_system": mat_intent.material_system,
                "target_props": mat_intent.target_props,
                "elements": mat_intent.elements,
                "forbidden": mat_intent.forbidden,
                "n_samples": mat_intent.n_samples,
                "downstream_agent": mat_intent.downstream_agent,
            },
            confidence=confidence,
            cost=0.01,  # Stage 1 mock 几乎免费
        )

        # SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:把 user_message 放进 ctx"""
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _format_reply(self, intent: MatIntent) -> str:
        """格式化自然语言回复"""
        parts = []
        parts.append(f"🎯 子类: {intent.subclass}")
        if intent.material_system:
            parts.append(f"🧬 材料体系: {intent.material_system}")
        if intent.target_props:
            parts.append(f"📊 目标属性: {', '.join(intent.target_props)}")
        if intent.elements:
            parts.append(f"✅ 必含元素: {', '.join(intent.elements)}")
        if intent.forbidden:
            parts.append(f"🚫 禁止元素: {', '.join(intent.forbidden)}")
        parts.append(f"🔢 生成候选数: {intent.n_samples}")
        parts.append(f"📊 解析置信度: {intent.confidence:.0%}")
        parts.append(f"➡️  下游: {intent.downstream_agent}")
        return "\n".join(parts)

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ {reason}",
            artifacts={"mat_intent": None, "downstream_agent": self.default_downstream},
            confidence=0.1,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-intent 错误: {error}",
            artifacts={"mat_intent": None, "downstream_agent": self.default_downstream},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatIntentAgent:
    """便利函数:创建默认 MatIntentAgent"""
    return MatIntentAgent(default_downstream="mat-pipeline")


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatIntentAgent Demo")
    print("=" * 60)

    agent = create_default_agent()

    test_intents = [
        "设计新型无钴锂电池正极材料,能量密度 > 500 Wh/kg",
        "出 LLZO 固态电解质实验方案,无贵金属",
        "为什么这个 MoS2 的 XRD 谱不对?",
        "优化 LiCoO2 配方,提高循环寿命",
        "Review 一下 LLZO 最新进展",
        "出 Bi2Te3 热电材料实验方案",
    ]

    for intent_text in test_intents:
        print(f"\n📝 用户: {intent_text}")
        req = AgentRequest(run_id=f"demo-{hash(intent_text) % 10000}", message=intent_text)
        response = agent.run(req)
        print(response.reply)
        print("-" * 60)


__all__ = ["MatIntentAgent", "create_default_agent", "MatIntent"]