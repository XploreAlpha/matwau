"""MatWAU-AgentBase 基类 — 所有 11 个 MatWAU agent 的根

设计哲学(per MatWAU-Harness-Loop-工程心法实践.md §4):
- 每个 agent 独立 Harness,不强制统一实现
- Inner Loop 4 步固定:perceive → plan → act → reflect
- Harness 部件(Context/Tools/State/Safety/Eval)通过构造器注入
- 不依赖 WAU 自动注入,跟 WAU 中间件是显式调用
- 11 agent 仍然保持独立,不合并成超级 agent

用法:
    class MyAgent(MatWAUAgentBase):
        name = "my-agent"
        def system_prompt(self): return "你是材料科学 X agent,..."
        def act(self, ctx, tools):
            return AgentResponse(reply="ok", ...)

    agent = MyAgent(context_manager=..., tool_registry=..., ...)
    req = AgentRequest(run_id="run-001", message="...", artifacts={}, context={})
    response = agent.run(req)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 数据类:统一 agent 请求 / 响应格式(per wau-python-sdk v1.3.3)
# ============================================================================


@dataclass
class AgentRequest:
    """统一 agent 请求格式

    Attributes:
        run_id: 全局唯一运行 ID,跨 agent 透传(per WAU workflow 约定)
        message: 用户原始消息(per W3.2 wau-edge 协议)
        artifacts: 输入文件 dict(mat-gen 给 CIF,mat-exp 给 XRD 数据等)
        context: 跨 agent 上下文(mat-orchestrator 注入的 DAG 状态)
        budget: 本任务预算 ¥(None = 不限)
        metadata: 自由扩展字段(trace_id / user_id / tenant_id 等)
    """

    run_id: str
    message: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    budget: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """统一 agent 响应格式

    Attributes:
        reply: 自然语言回复(给用户看)
        artifacts: 输出文件 dict(mat-gen 给 CIF 列表,mat-exp 给 XRD peaks)
        confidence: 置信度 0-1(mat-critic 用)
        cost: 实际花费 ¥(per MatWAU-AgentBase 跑完后统计)
        lineage_id: 回放 ID(W32 — LineageRecorder 自动回填)
        error: 错误信息(失败时填充)
    """

    reply: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    cost: float = 0.0
    lineage_id: str | None = None
    error: str | None = None

    # ─── v1.4-Academic widget 协议层新增字段(全 optional,默认值不破老调用方) ───
    # homerail voice cockpit 通过这 3 字段读 widget protocol + TTS 友好摘要
    # 老 agent 不填这 3 字段也兼容(hore 端 has 读 → None / [] fallback)
    spoken_text: str | None = None       # ≤200 字语音摘要(per widget_helpers)
    structured_data: dict[str, Any] | None = None  # raw records / recipes 备份
    widgets: list[Any] = field(default_factory=list)  # list[Widget] — 避免循环 import


# ============================================================================
# Harness 部件(类型提示,W2 后续实现)
# ============================================================================
# 注:这里是 Protocol/类型占位,W2 才会具体实现 ContextManager / ToolRegistry / etc.
# 这样 AgentBase 不强制依赖具体 Harness 实现,11 agent 可注入不同版本


class ContextManager(ABC):  # type: ignore[misc]
    """占位:5 大 Harness 职责 #1 — Context 组装器(per doc §5.1)

    W2 待实现:matwau/harness/context_manager.py
    """

    @abstractmethod
    def assemble(
        self,
        system_prompt: str,
        user_message: str,
        artifacts: dict[str, Any],
        history: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """拼装 LLM Context,返回 {messages: [...], estimated_tokens: int}"""
        ...


class ToolRegistry(ABC):  # type: ignore[misc]
    """占位:5 大 Harness 职责 #2 — 工具注册表(per doc §5.2)

    W2 待实现:matwau/harness/tool_registry.py
    """

    @abstractmethod
    def select_tools(self, ctx: dict[str, Any]) -> list[str]:
        """根据 ctx 选 1 组工具"""
        ...


class StateStore(ABC):  # type: ignore[misc]
    """占位:5 大 Harness 职责 #3 — 状态持久化(per doc §5.3)

    W2 待实现:matwau/harness/state_store.py
    """

    @abstractmethod
    def persist(self, run_id: str, response: AgentResponse) -> None:
        """写 1 步 lineage"""

    @abstractmethod
    def load_history(self, run_id: str) -> list[dict[str, Any]]:
        """读历史消息"""


class SafetyGuard(ABC):  # type: ignore[misc]
    """占位:5 大 Harness 职责 #4 — 安全护栏(per doc §5.4)

    W2 待实现:matwau/harness/safety_guard.py
    """

    @abstractmethod
    def check(self, response: AgentResponse) -> bool:
        """检查 response 是否安全,True = 通过,False = 拦截"""
        ...


class EvalHarness(ABC):  # type: ignore[misc]
    """占位:5 大 Harness 职责 #5 — 评估 harness(per doc §5.5)

    W2 待实现:matwau/harness/eval_harness.py
    """

    @abstractmethod
    def self_eval(self, response: AgentResponse) -> float:
        """单次响应自评,返回 0-1 置信度"""
        ...


# ============================================================================
# MatWAU-AgentBase 基类 — Inner Loop 4 步模板
# ============================================================================


class MatWAUAgentBase(ABC):
    """所有 11 个 MatWAU agent 的基类

    Inner Loop 4 步:
        1. perceive → 2. plan → 3. act → 4. reflect → 循环

    每个 MatWAU agent 必须实现:
        - name (类属性,agent 名)
        - system_prompt() (返回本 agent 角色描述)
        - act() (业务逻辑,Inner Loop 第 3 步)

    可选重写:
        - perceive() (默认走 ContextManager)
        - plan() (默认走 ToolRegistry)
        - reflect() (默认走 SafetyGuard + EvalHarness + StateStore)

    Harness 部件可注入(W2 完整,W1 可 None):
        - context_manager (Context 组装)
        - tool_registry (工具/MCP)
        - state_store (状态持久化)
        - safety_guard (安全护栏)
        - eval_harness (自评)
    """

    # === 必填:子类定义 ===
    name: str = ""  # agent 名(mat-lit / mat-gen / mat-sim / ...)

    # === Harness 部件(子类注入,W2 完整) ===
    context_manager: ContextManager | None = None
    tool_registry: ToolRegistry | None = None
    state_store: StateStore | None = None
    safety_guard: SafetyGuard | None = None
    eval_harness: EvalHarness | None = None

    # === 可选:Outer Loop 钩子(per doc §6)===
    failure_callback: Callable[[AgentRequest, AgentResponse], None] | None = None

    # === Inner Loop 配置 ===
    max_iterations: int = 5  # 防止无限循环(可子类重写)
    confidence_threshold: float = 0.85  # 置信度达此值跳出循环

    def __init__(
        self,
        *,
        context_manager: ContextManager | None = None,
        tool_registry: ToolRegistry | None = None,
        state_store: StateStore | None = None,
        safety_guard: SafetyGuard | None = None,
        eval_harness: EvalHarness | None = None,
        failure_callback: Callable[[AgentRequest, AgentResponse], None] | None = None,
        max_iterations: int = 5,
        confidence_threshold: float = 0.85,
    ) -> None:
        """构造:注入 Harness 部件(全部 optional,W1 可 None)"""
        self.context_manager = context_manager
        self.tool_registry = tool_registry
        self.state_store = state_store
        self.safety_guard = safety_guard
        self.eval_harness = eval_harness
        self.failure_callback = failure_callback
        self.max_iterations = max_iterations
        self.confidence_threshold = confidence_threshold

        if not self.name:
            raise ValueError(
                f"{type(self).__name__} 必须定义类属性 name(agent 名)"
            )

    # === Inner Loop 4 步 ===

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1:感知输入 — 拼装 LLM 需要的 Context

        默认走 ContextManager;若未注入,返回最简 ctx(只有 user_message)

        W15 关键修正:把 req.context["domain"] 透传到 act() 的 ctx 里
        (ContextManager 不消费,但 act() 需要 domain 路由)
        """
        history: list[dict[str, Any]] = []
        if self.state_store:
            try:
                history = self.state_store.load_history(req.run_id)
            except Exception as e:
                logger.warning("[%s] load_history 失败: %s", self.name, e)

        if self.context_manager:
            try:
                ctx = self.context_manager.assemble(
                    system_prompt=self.system_prompt(),
                    user_message=req.message,
                    artifacts=req.artifacts,
                    history=history,
                    **req.context,  # 透传 mat-orchestrator 注入的 DAG 状态等
                )
            except Exception as e:
                logger.warning("[%s] context_manager.assemble 失败: %s", self.name, e)
                ctx = None
            if ctx is not None:
                # W15: 透传 req.context 顶层字段(domain / workflow / subclass / ...)
                # 让 act() 能读到(per domain router)
                for k, v in req.context.items():
                    if k not in ctx:
                        ctx[k] = v
                return ctx

        # W1 fallback:无 ContextManager 时返回最简 ctx
        fallback_ctx = {
            "messages": [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": req.message},
            ],
            "estimated_tokens": len(req.message) // 2,
            "_history_loaded": len(history),
        }
        # W15: fallback 也要透传 req.context
        fallback_ctx.update(req.context)
        return fallback_ctx

    def plan(self, ctx: dict[str, Any]) -> list[str]:
        """步骤 2:规划 — 决定调哪些 tools

        默认走 ToolRegistry;若未注入,返回 ["__default__"](sentinel 让 act() 仍能跑)
        若 ToolRegistry.select_tools() 显式返回 [] → 真无工具,触发终止条件 2
        """
        if self.tool_registry:
            try:
                return self.tool_registry.select_tools(ctx)
            except Exception as e:
                logger.warning("[%s] select_tools 失败: %s", self.name, e)
                return ["__default__"]  # fallback
        return ["__default__"]  # 未注入 → 给 sentinel,让 act() 仍能跑

    @abstractmethod
    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """步骤 3:执行 — 子类必须实现(每个 agent 业务不同)

        Args:
            ctx: perceive() 的输出
            tools: plan() 选出的工具列表

        Returns:
            AgentResponse 子类实例
        """
        ...

    def reflect(self, req: AgentRequest, response: AgentResponse) -> AgentResponse:
        """步骤 4:反思 — 自评 + 安全检查 + 持久化 + 失败回调

        顺序:
        1. 跑 Eval Harness 自评(若注入)→ 填 response.confidence
        2. Safety Guard 拦截(若注入)→ 失败时改 reply 为 [BLOCKED]
        3. 写 State Store(若注入)→ 持久化 lineage
        4. 失败 → 触发 Outer Loop 回调(若注入)
        """
        # 1. Eval Harness 自评
        if self.eval_harness:
            try:
                response.confidence = self.eval_harness.self_eval(response)
            except Exception as e:
                logger.warning("[%s] self_eval 失败: %s", self.name, e)
                response.confidence = 0.5  # 未知 → 中等置信
        elif response.confidence == 0.0:
            # 无 EvalHarness 时,默认 confidence=0.5(未知 → 中等)
            response.confidence = 0.5

        # 2. Safety Guard 拦截
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
                    response.confidence = 0.0
                    logger.warning("[%s] SafetyGuard 拦截", self.name)
            except Exception as e:
                logger.warning("[%s] safety_guard.check 失败: %s", self.name, e)

        # 3. State Store 持久化
        if self.state_store:
            try:
                self.state_store.persist(req.run_id, response)
            except Exception as e:
                logger.warning("[%s] persist 失败: %s", self.name, e)

        # 4. Outer Loop 失败回调
        if response.confidence < 0.5 and self.failure_callback:
            try:
                self.failure_callback(req, response)
            except Exception as e:
                logger.warning("[%s] failure_callback 失败: %s", self.name, e)

        return response

    def run(self, req: AgentRequest) -> AgentResponse:
        """Inner Loop 完整循环 — 通用骨架,所有 agent 都跑这个

        Args:
            req: AgentRequest

        Returns:
            最终 AgentResponse(最高置信度版本)

        终止条件(任一):
        - confidence > confidence_threshold(0.85)
        - tools 为空(plan() 没选出工具)
        - 达 max_iterations 上限(默认 5)
        """
        if not self.name:
            raise ValueError(f"{type(self).__name__}.name 未设置")

        logger.info(
            "[%s] run start: run_id=%s, message=%s",
            self.name,
            req.run_id,
            req.message[:80],
        )

        best_response: AgentResponse | None = None

        for i in range(self.max_iterations):
            # Inner Loop 4 步
            ctx = self.perceive(req)
            tools = self.plan(ctx)

            # 终止条件 2:tool_registry 显式注入 + 返回空 → 真无工具,跳过 act
            # (若 tool_registry 未注入,plan() 返回 ["__default__"],仍会跑 act)
            if not tools and self.tool_registry is not None:
                logger.info("[%s] iter %d 终止: 无工具", self.name, i)
                # 用占位 response 收口(若 best_response 已存在,保留)
                if best_response is None:
                    best_response = AgentResponse(
                        reply="(no tools selected)", confidence=0.0
                    )
                break

            response = self.act(ctx, tools)
            response = self.reflect(req, response)

            # 跟踪最佳
            if best_response is None or response.confidence > best_response.confidence:
                best_response = response
            elif self.eval_harness is not None and best_response is not None and i > 0:
                # 有 EvalHarness(量化打分)+ 本轮 confidence 没比上一轮高 → 没进步,停止
                # (无 EvalHarness 时跑满 5 轮是合理默认,避免假性终止)
                logger.info(
                    "[%s] iter %d 终止: 无进步 (%.2f → %.2f)",
                    self.name,
                    i,
                    best_response.confidence,
                    response.confidence,
                )
                break

            # 终止条件 1:置信度高
            if response.confidence > self.confidence_threshold:
                logger.info(
                    "[%s] iter %d 终止: confidence=%.2f", self.name, i, response.confidence
                )
                break

            # 终止条件 3:最后 1 轮
            if i == self.max_iterations - 1:
                logger.warning(
                    "[%s] 达 max_iterations=%d 上限,confidence=%.2f",
                    self.name,
                    self.max_iterations,
                    response.confidence,
                )
        # type: ignore[return-value]
        return best_response

    @abstractmethod
    def system_prompt(self) -> str:
        """子类必须定义:本 agent 的角色 + 能力描述"""
        ...

    def __repr__(self) -> str:
        parts = [f"name={self.name!r}"]
        if self.context_manager:
            parts.append("context_manager=✓")
        if self.tool_registry:
            parts.append("tool_registry=✓")
        if self.state_store:
            parts.append("state_store=✓")
        if self.safety_guard:
            parts.append("safety_guard=✓")
        if self.eval_harness:
            parts.append("eval_harness=✓")
        return f"<{type(self).__name__}({', '.join(parts)})>"


__all__ = [
    "AgentRequest",
    "AgentResponse",
    "ContextManager",
    "EvalHarness",
    "MatWAUAgentBase",
    "SafetyGuard",
    "StateStore",
    "ToolRegistry",
]