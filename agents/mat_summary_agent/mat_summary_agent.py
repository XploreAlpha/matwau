"""mat_summary_agent / mat_summary_agent.py — free-form Markdown 合成 agent

业务逻辑:
1. 解析 user_intent → LLM prompt(per _build_prompt)
2. 调 OpenAI 兼容 LLM(默认 DeepSeek)生成 Markdown 文本
3. 包成 AgentResponse(widgets=[matwau_markdown widget])
4. Fail-soft:无 API key / LLM 失败 → 返回空 widgets

设计:
- 与 mat_critic_agent.llm_reviewer 同样 OpenAI 兼容 SDK 模式
- v1.4.2-Academic 新增 widget type(matwau_markdown)
- 默认 cost_per_query=0.005(LLM 一次合成 < ¥0.01)
- Markdown 输出上限 4000 字符(LLM 端),FE 端 16K 兜底

per MatWAU-v1.4.2-Academic-dev-plan-20260811.md §Layer 2.3
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.widget_helpers import (
    attach_widget_protocol,
    make_markdown_widget,
)
from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard

logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================


@dataclass
class SummaryAgentConfig:
    """Markdown summary 配置(per AgentRequest.context)

    Attributes:
        max_chars: LLM 输出 Markdown 最大字符数(对齐 FE 16K 兜底,这里 4K 防止浪费 token)
        temperature: LLM temperature(0.3 偏向事实准确)
        system_prompt: 透传,可注入自定义 prompt
        enable_llm: False = 跳过 LLM 调用,返回空 widgets(per default fail-soft)
        locale: zh / en(影响 system prompt 语言)
    """

    max_chars: int = 4000
    temperature: float = 0.3
    system_prompt: str | None = None
    enable_llm: bool = False  # 默认 False,显式开启才调 LLM
    locale: str = "zh"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> SummaryAgentConfig:
        if not d:
            return cls()
        return cls(
            max_chars=int(d.get("max_chars", 4000)),
            temperature=float(d.get("temperature", 0.3)),
            system_prompt=d.get("system_prompt"),
            enable_llm=bool(d.get("enable_llm", False)),
            locale=str(d.get("locale", "zh")),
        )


# ============================================================================
# LLM client(OpenAI 兼容 + fail-soft)
# ============================================================================


class SummaryLLMClient(Protocol):
    """LLM 客户端协议(测试可注入 fake)"""

    def generate(self, *, system: str, user: str, max_chars: int) -> str:
        """调 LLM 生成 Markdown 文本。

        Returns:
            Markdown 字符串(可能为空字符串表示 LLM 跳过 / 失败)
        """


class LLMSkippedError(Exception):
    """LLM 跳过(无 API key / 包未装 / 显式 enable_llm=False)"""


@dataclass
class OpenAICompatibleSummaryLLMClient:
    """OpenAI 兼容 SDK 客户端(默认 DeepSeek)

    配置(per user-confirmed):
      - MATWAU_LLM_API_KEY=<key>      (必填,无则抛 LLMSkippedError)
      - MATWAU_LLM_BASE_URL=https://api.deepseek.com
      - MATWAU_LLM_MODEL=deepseek-v4-flash
      - MATWAU_LLM_ENABLED=1          (显式开关)

    Fail-soft:任何异常返回空字符串(act() 拿空串 → 返回空 widgets)
    """

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    enabled: bool = False
    _client: Any = field(default=None, init=False)
    _init_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        # 显式开关 + API key 都到位才尝试 init SDK
        if not self.enabled or not self.api_key:
            return
        try:
            import openai  # type: ignore[import-untyped]
            with self._init_lock:
                if self._client is None:
                    self._client = openai.OpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                    )
        except ImportError:
            logger.warning("openai package not installed; SummaryAgent will skip LLM calls")

    @classmethod
    def from_env(cls) -> "OpenAICompatibleSummaryLLMClient":
        """从环境变量构造(per MATWAU_LLM_* 命名约定)"""
        return cls(
            api_key=os.environ.get("MATWAU_LLM_API_KEY", ""),
            base_url=os.environ.get("MATWAU_LLM_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("MATWAU_LLM_MODEL", "deepseek-v4-flash"),
            enabled=os.environ.get("MATWAU_LLM_ENABLED", "").strip().lower() in ("1", "true", "yes"),
        )

    def generate(self, *, system: str, user: str, max_chars: int) -> str:
        if not self.enabled or not self.api_key or self._client is None:
            raise LLMSkippedError("LLM not enabled or not configured")
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=max_chars // 2,  # 粗估:1 token ≈ 2 chars
            )
            text = response.choices[0].message.content or ""
            return text.strip()
        except Exception as exc:  # noqa: BLE001 — fail-soft 兜底
            logger.warning("LLM call failed: %s", exc)
            return ""


# ============================================================================
# helper: prompt + markdown cleanup
# ============================================================================


def _default_system_prompt(locale: str) -> str:
    if locale == "zh":
        return (
            "你是 MatWAU 学院的科研助手,负责回答用户关于材料、化学、化合物、合成、"
            "物性、文献等领域的问题。\n\n"
            "回答要求:\n"
            "1. **必须用 Markdown 格式**(标题、列表、表格、引用都可)\n"
            "2. 信息准确,不确定就明说\n"
            "3. 结构清晰:先结论后细节\n"
            "4. 长度适中,不超过 4000 字符\n"
            "5. 不要写代码块或长公式\n"
        )
    return (
        "You are a MatWAU research assistant answering questions about materials, "
        "chemistry, compounds, synthesis, properties, and literature.\n\n"
        "Output requirements:\n"
        "1. **Markdown format** (headings, lists, tables, blockquotes allowed)\n"
        "2. Accurate — say 'uncertain' when unsure\n"
        "3. Structure: conclusion first, then details\n"
        "4. Keep under 4000 characters\n"
        "5. Avoid long code blocks or equations\n"
    )


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+\-]*\s*$", re.MULTILINE)


def _clean_markdown(text: str) -> str:
    """去 LLM 常见的 markdown 杂质

    - 去首尾 ```markdown ... ``` 包裹
    - 去尾部孤立 ``` 围栏
    """
    if not text:
        return ""
    text = text.strip()
    # 整体 ```markdown ... ``` 包裹
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline > 0:
            inner = text[first_newline + 1 :]
            last_fence = inner.rfind("```")
            if last_fence > 0:
                text = inner[:last_fence].strip()
                return text
    # 尾部孤立 ```
    text = _FENCE_RE.sub("", text)
    return text.strip()


# ============================================================================
# MatSummaryAgent
# ============================================================================


class MatSummaryAgent(MatWAUAgentBase):
    """MatWAU v1.4.2-Academic 新增 — free-form Markdown 合成 agent

    用于"无外部结构化数据可查 / 概念解释"类查询,通过 OpenAI 兼容 LLM
    生成 Markdown 回答,包成 matwau_markdown widget。

    与 mat_arxiv_agent / mat_pubchem_agent 等"查询外部 API"agent 的区别:
    - 不查外部数据库,只调 LLM
    - 不需要 cache(LLM 自身有服务端 cache 或可加)
    - 默认 enable_llm=False(必须显式开 + 配 API key 才真调)

    Example:
        agent = MatSummaryAgent(enable_llm=True)
        agent.llm_client = OpenAICompatibleSummaryLLMClient.from_env()
        response = agent.act({"user_message": "介绍阿司匹林"}, [])
    """

    name: str = "mat-summary-agent"  # per MatWAUAgentBase 必须定义

    def __init__(
        self,
        *,
        default_max_chars: int = 4000,
        cost_per_query: float = 0.005,
        llm_client: SummaryLLMClient | None = None,
        context_manager: ContextManager | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_max_chars: 默认 Markdown 最大字符数
            cost_per_query: 单次 LLM 调用估算成本 ¥(DeepSeek Flash 实际 ~¥0.001)
            llm_client: 可选注入 SummaryLLMClient(测试用)
            context_manager / safety_guard: harness 组件
        """
        # enable_llm 不传 base,只用在 self 上做默认 config 标记
        enable_llm_default = bool(kwargs.pop("enable_llm", False))

        super().__init__(
            context_manager=context_manager,
            safety_guard=safety_guard,
            **kwargs,
        )
        self.default_max_chars = default_max_chars
        self.cost_per_query = cost_per_query
        self.enable_llm_default = enable_llm_default
        self.llm_client: SummaryLLMClient = llm_client or OpenAICompatibleSummaryLLMClient.from_env()

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return (
            "你是 mat-summary-agent — MatWAU v1.4.2-Academic 新增的 free-form Markdown "
            "合成 agent。\n\n"
            "职责:\n"
            "1. 接收 user_intent(用户自然语言 query)\n"
            "2. 通过 OpenAI 兼容 LLM(默认 DeepSeek)生成 Markdown 回答\n"
            "3. 包成 matwau_markdown widget 返回\n"
            "4. 无外部 API 查询,无 cache(LLM 服务端自己 cache)\n\n"
            "适用场景:\n"
            "- '介绍阿司匹林' / '什么是钙钛矿' 等概念解释类 query\n"
            "- 无 arxiv / pubchem / crossref 等结构化数据可查时\n"
            "- LLM 自由组织内容(heading + list + table + blockquote)\n\n"
            "约束:\n"
            "- 默认 enable_llm=False,显式开启 + 配 MATWAU_LLM_API_KEY 才真调\n"
            "- 输出 Markdown 字符上限 4000(可配)\n"
            "- 失败 → 空 widgets,不阻断 orchestrator\n"
            "- 0 行 UI 代码\n"
        )

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:LLM Markdown 合成

        v1.4.2-Academic FIX:即使 LLM 关闭 / 调用失败 / 用户 query 为空,
        也要返回 1 个 matwau_markdown widget(空 markdown + fallback_text),
        这样 FE 始终有内容渲染,不会出现 "widgets=[]" 静默失败。

        Fail-soft 分档:
          - LLM 成功    → markdown=原文, confidence=0.85
          - LLM 跳过/失败 → markdown="", fallback_text="...", confidence=0.0
          - query 空    → markdown="", fallback_text="请提供更具体的问题", confidence=0.3
        """
        user_message = (ctx.get("user_message") or ctx.get("message") or "").strip()
        config: SummaryAgentConfig = ctx.get("_input_config") or SummaryAgentConfig()

        markdown_text = ""
        skip_reason: str | None = None
        title = _guess_title(user_message) if user_message else "MatWAU 内容卡片"

        if not user_message:
            skip_reason = "用户 query 为空"
            fallback_text = "请提供更具体的问题,我会尽力解释。"
            confidence = 0.3
            cost = 0.0
            reply = "请提供更具体的问题,我会尽力解释。"
        else:
            if not config.enable_llm:
                skip_reason = (
                    "LLM 未启用(enable_llm=False)。"
                    "学院服务器请在 .env 配 MATWAU_LLM_ENABLED=1 + MATWAU_LLM_API_KEY=<key>。"
                )
                fallback_text = (
                    "Markdown 内容暂不可用:mat-summary-agent 默认 fail-soft 模式未启用 LLM。"
                    "学院服务器运维可在 .env 配 MATWAU_LLM_ENABLED=1 + MATWAU_LLM_API_KEY=<key> 后重启服务启用。"
                )
                confidence = 0.0
                cost = 0.0
                reply = (
                    "⚠️ mat-summary-agent: LLM 未启用(enable_llm=False)。"
                    "已返回空 Markdown 卡片占位。"
                )
            else:
                # 尝试调 LLM
                try:
                    system = config.system_prompt or _default_system_prompt(config.locale)
                    markdown_text = self.llm_client.generate(
                        system=system,
                        user=user_message,
                        max_chars=config.max_chars or self.default_max_chars,
                    )
                    markdown_text = _clean_markdown(markdown_text)
                except LLMSkippedError as exc:
                    skip_reason = f"LLM 跳过:{exc}"
                except Exception as exc:  # noqa: BLE001 — fail-soft 兜底
                    logger.warning("MatSummaryAgent.act 异常: %s", exc)
                    skip_reason = f"LLM 失败:{exc}"

                if markdown_text:
                    # 截到 config.max_chars
                    max_chars = config.max_chars or self.default_max_chars
                    if len(markdown_text) > max_chars:
                        markdown_text = markdown_text[: max_chars - 1].rstrip() + "…"
                    fallback_text = None
                    confidence = 0.85
                    cost = self.cost_per_query
                    reply = f"已生成 Markdown 总结(长度 {len(markdown_text)} 字符)。"
                else:
                    # LLM 启用但返回空 / 失败
                    fallback_text = (
                        f"Markdown 内容生成失败:{skip_reason or 'LLM 返回空'}"
                    )
                    confidence = 0.0
                    cost = 0.0
                    reply = (
                        f"⚠️ mat-summary-agent: {skip_reason or 'LLM 返回空 Markdown'}。"
                        "已返回空 Markdown 卡片占位。"
                    )

        # ===== 永远构造 1 个 widget =====
        widget = make_markdown_widget(
            markdown=markdown_text,
            title=title,
            source="mat_summary_agent",
            generated_at=_now_iso(),
            data_ref="matwau_markdown:concept",
            fallback_text=fallback_text,
        )

        response = AgentResponse(
            reply=reply,
            confidence=confidence,
            cost=cost,
            artifacts={"skip_reason": skip_reason} if skip_reason else {},
        )
        attach_widget_protocol(response, widgets=[widget])
        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """解析 AgentRequest → act() 输入 ctx"""
        user_message = (req.message or "").strip()
        ctx = req.context if isinstance(req.context, dict) else None
        # 允许 AgentRequest.context 不显式带 enable_llm 时,fallback 到 agent 默认
        if ctx is not None and "enable_llm" not in ctx and self.enable_llm_default:
            ctx = {**ctx, "enable_llm": True}
        config = SummaryAgentConfig.from_dict(ctx)
        return {
            "user_message": user_message,
            "_input_config": config,
        }

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-summary-agent: {reason}",
            confidence=0.0,
            cost=0.0,
            artifacts={"skip_reason": reason},
        )


# ============================================================================
# helper: title + timestamp
# ============================================================================


_TITLE_STOPWORDS = {
    "zh": {"的", "是", "什么", "什么是", "怎么", "如何", "请", "给我",
           "介绍", "解释", "说明", "讲讲", "说说", "简述", "概括"},
    "en": {"the", "a", "an", "is", "what", "what is", "how",
           "explain", "describe", "tell", "me", "about",
           "summarize", "overview", "introduction"},
}


def _guess_title(user_message: str, max_len: int = 24) -> str:
    """从 user_message 粗略猜标题(给 widget title 字段用)

    截前 max_len 字符,去 leading 停用词。
    注:停用词按"长度降序"匹配,确保 "什么是" 先于 "什么" 命中(避免残 "是")。
    中英文边界处理:
      - 英文 stop 后接空格 / 字符串末尾
      - 中文 stop 后直接接汉字 / 字符串末尾(无空格)
    """
    msg = user_message.strip()
    if not msg:
        return "MatWAU 内容卡片"
    # 去 leading 停用词(zh + en 都试),按 token 长度降序优先(让长 token 先匹配)
    all_stops = sorted(
        (s for lang_stops in _TITLE_STOPWORDS.values() for s in lang_stops),
        key=lambda x: -len(x),
    )
    msg_lower = msg.lower()
    for stop in all_stops:
        # 3 种匹配:
        # 1) 英文 stop 后接空格(标准英语)
        # 2) 字符串完全等于 stop
        # 3) 中文 stop 后直接接 CJK 字符(无空格)
        if msg_lower.startswith(stop + " "):
            msg = msg[len(stop):].lstrip()
            break
        if msg_lower == stop:
            msg = ""
            break
        # 中文 stop 后接汉字
        if (
            len(stop) <= 4  # 中文 stop 通常 ≤ 4 字符
            and msg_lower.startswith(stop)
            and len(msg_lower) > len(stop)
            # 下一字符是 CJK(0x4E00-0x9FFF)或其他非 ASCII 字符
            and ord(msg_lower[len(stop)]) > 127
        ):
            msg = msg[len(stop):]
            break
    if not msg:
        msg = user_message.strip()
    return msg[:max_len]


def _now_iso() -> str:
    """返回当前 UTC ISO 8601 时间(秒精度)"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================================
# 便利工厂:create_default_agent()(对齐其他 agent 模块)
# ============================================================================


def create_default_agent(**kwargs: Any) -> MatSummaryAgent:
    """构造默认 MatSummaryAgent 实例(对齐 mat_intent_agent / mat_pubchem_agent 模式)

    Args:
        **kwargs: 透传到 MatSummaryAgent.__init__()
            - enable_llm: bool — 显式开启 LLM 调用(默认 False,fail-soft)
            - llm_client: SummaryLLMClient — 注入 fake / 真 client(测试用)

    Returns:
        MatSummaryAgent(默认无 LLM,act() 走空 widgets 兜底)
    """
    return MatSummaryAgent(**kwargs)
