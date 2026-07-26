"""llm_reviewer.py — W33 LLM 二次复核(DeepSeek + OpenAI 兼容 SDK)

职责:
1. **LLMReviewer class** — 吃 CriticOutput → 输出自然语言复核建议
2. **fail-soft 模式** — 无 API key / 无 openai 包 / API 失败 → 返回空串,不阻断
3. **OpenAI 兼容 SDK** — `openai` Python package + 自定义 base_url
4. **环境变量配置**(per user-confirmed):
   - MATWAU_LLM_API_KEY=<key>      (必填,无则跳过)
   - MATWAU_LLM_BASE_URL=https://api.deepseek.com   (默认 DeepSeek)
   - MATWAU_LLM_MODEL=deepseek-v4-flash              (默认 DeepSeek Flash)
   - MATWAU_LLM_ENABLED=1                            (显式开关)

设计原则(per MatWAU-Harness-Loop 心法):
- **失败吞掉**:任何异常返回空串
- **可选依赖**:openai 包未装 → LLMReviewer 仍可用,只 review() 返回空
- **不污染 act()**:MatCriticAgent 默认 enable_llm_review=False,显式开启

per W33 plan §B
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 默认 / 常量
# ============================================================================

# DeepSeek 默认 base_url(per user-confirmed 2026-07-26)
DEFAULT_BASE_URL = "https://api.deepseek.com"

# 默认 model(per user-confirmed 2026-07-26)
DEFAULT_MODEL = "deepseek-v4-flash"

# 默认 prompt(系统角色)
DEFAULT_SYSTEM_PROMPT = """你是材料科学实验室的资深裁决复核专家。

你的任务是基于 critic 的规则评分,给出**第二次独立判断**:
1. 评分是否合理?(1-2 句话)
2. 有没有规则漏掉的边界 case?
3. 是否同意最终 verdict?如果不同意,建议改为哪个?

输出要求:
- 中文
- 不超过 200 字
- 如同意,直接说"同意";如不同意,说"建议改为 <verdict>,理由: <reason>"
- 不要 markdown / 代码块 / 列表,纯文字
"""

# 默认 token 上限
DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.2


# ============================================================================
# dataclass — LLM 复核结果
# ============================================================================


@dataclass
class LLMReviewResult:
    """W33 — 1 次 LLM 复核的结果

    字段:
    - review: 自然语言复核文本(空串 = LLM 未跑 / 失败)
    - model: 实际用的 model
    - input_tokens / output_tokens: token 用量
    - cost_cny: 估算成本(¥)
    - duration_seconds: 耗时
    - error: 错误信息(成功时 None)
    - available: LLM 是否启用(API key + openai 包 + 显式 enabled)
    """

    review: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review": self.review,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_cny": self.cost_cny,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "available": self.available,
        }


# ============================================================================
# helper — 序列化 CriticOutput 给 LLM 看
# ============================================================================


def _summarize_critic_for_llm(critic_output: Any) -> str:
    """把 CriticOutput 序列化成 LLM-friendly 文本

    输出格式:
    ```
    Verdict: <verdict>
    Overall Score: <overall_score>
    L1 (物理): <l1_score>
    L2 (合成): <l2_score>
    L3 (安全): <l3_score>
    L4 (跨机器人): <l4_cross_robot_score>
    L4 Consistent: <bool>
    Rules Passed: <list>
    Rules Failed: <list>
    Failures: <list of {code, severity}>
    Top Suggestions: <list>
    ```
    """
    if critic_output is None:
        return "(no critic output)"

    lines = []
    if hasattr(critic_output, "verdict"):
        lines.append(f"Verdict: {critic_output.verdict}")
    if hasattr(critic_output, "overall_score"):
        lines.append(f"Overall Score: {critic_output.overall_score:.4f}")
    if hasattr(critic_output, "l1_score"):
        lines.append(f"L1 (物理): {critic_output.l1_score:.4f}")
    if hasattr(critic_output, "l2_score"):
        lines.append(f"L2 (合成): {critic_output.l2_score:.4f}")
    if hasattr(critic_output, "l3_score"):
        lines.append(f"L3 (安全): {critic_output.l3_score:.4f}")
    if hasattr(critic_output, "l4_cross_robot_score"):
        lines.append(f"L4 (跨机器人): {critic_output.l4_cross_robot_score:.4f}")

    # cross_robot 规则
    if hasattr(critic_output, "cross_robot") and critic_output.cross_robot is not None:
        cr = critic_output.cross_robot
        if hasattr(cr, "consistent"):
            lines.append(f"L4 Consistent: {cr.consistent}")
        if hasattr(cr, "rules_passed") and isinstance(cr.rules_passed, list):
            lines.append(f"Rules Passed: {', '.join(cr.rules_passed) if cr.rules_passed else '(none)'}")
        if hasattr(cr, "rules_failed") and isinstance(cr.rules_failed, list):
            lines.append(f"Rules Failed: {', '.join(cr.rules_failed) if cr.rules_failed else '(none)'}")

    # failures
    if hasattr(critic_output, "failures") and isinstance(critic_output.failures, list):
        if critic_output.failures:
            for f in critic_output.failures[:5]:
                code = getattr(f, "code", "?")
                severity = getattr(f, "severity", "?")
                lines.append(f"  Failure: {code} [{severity}]")

    # top_suggestions
    if hasattr(critic_output, "top_suggestions") and isinstance(critic_output.top_suggestions, list):
        if critic_output.top_suggestions:
            lines.append(f"Top Suggestions: {'; '.join(critic_output.top_suggestions[:3])}")

    return "\n".join(lines)


# ============================================================================
# LLMReviewer
# ============================================================================


class LLMReviewer:
    """W33 — LLM 二次复核 client(OpenAI 兼容 SDK + DeepSeek)

    用法:
        reviewer = LLMReviewer()  # 自动从 env var 读配置

        # 检查是否可用
        if reviewer.is_available():
            result = reviewer.review(critic_output, target_sample="Inconel 718")
            if result.review:
                print(f"LLM 复核: {result.review}")
            if result.error:
                logger.warning("LLM 复核失败: %s", result.error)

    env vars:
    - MATWAU_LLM_API_KEY   — API key(无则不可用)
    - MATWAU_LLM_BASE_URL  — base URL(默认 https://api.deepseek.com)
    - MATWAU_LLM_MODEL     — model 名(默认 deepseek-v4-flash)
    - MATWAU_LLM_ENABLED   — "1" 显式启用(None / "0" / "false" → 默认 False)
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        enabled: Optional[bool] = None,
        client: Any = None,  # 显式注入(测试用 mock OpenAI client)
    ) -> None:
        """构造

        Args:
            api_key: 显式 API key(None → 读 env)
            base_url: 显式 base URL(None → 读 env 或默认 DeepSeek)
            model: 显式 model 名(None → 读 env 或默认 deepseek-v4-flash)
            enabled: 显式启用开关(None → 读 env)
            client: 显式注入 OpenAI client(测试用)
        """
        self._api_key = api_key if api_key is not None else os.environ.get("MATWAU_LLM_API_KEY", "").strip()
        self._base_url = (
            base_url if base_url is not None
            else os.environ.get("MATWAU_LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL
        )
        self._model = (
            model if model is not None
            else os.environ.get("MATWAU_LLM_MODEL", "").strip() or DEFAULT_MODEL
        )
        self._enabled_explicit = enabled
        self._client = client  # 测试用显式注入
        self._client_lock = threading.Lock()
        self._client_initialized = client is not None

    # ----------------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------------
    def is_available(self) -> bool:
        """LLM 复核是否可用(API key + 显式 enabled + openai 包 / mock client)

        关键:
        - 显式 client(测试用 mock)→ 不检查 openai 包,因为 mock 不需要真实包
        - 否则需要 openai 包可用
        """
        if self._enabled_explicit is False:
            return False
        env_enabled = os.environ.get("MATWAU_LLM_ENABLED", "").strip().lower()
        if env_enabled in ("1", "true", "yes") and self._enabled_explicit is None:
            pass  # 显式 env 启用
        elif self._enabled_explicit is None and not env_enabled:
            return False  # 默认禁用

        if not self._api_key:
            return False

        # 显式 mock client → 跳过 openai pkg 检查
        if self._client is not None:
            return True

        # 否则需要 openai 包可用
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def get_model(self) -> str:
        """当前 model"""
        return self._model

    # ----------------------------------------------------------------
    # 核心 review
    # ----------------------------------------------------------------
    def review(
        self,
        critic_output: Any,
        *,
        target_sample: str = "",
        user_intent: str = "",
        timeout: float = 30.0,
    ) -> LLMReviewResult:
        """对 critic_output 做 1 次 LLM 复核

        Args:
            critic_output: CriticOutput 对象(dataclass with verdict/scores/...)
            target_sample: 样品名(可选,放进 prompt 帮 LLM 理解上下文)
            user_intent: 用户意图(可选)
            timeout: API 超时(秒)

        Returns:
            LLMReviewResult(review 字段空串 = 失败 / 不可用)
        """
        import time

        result = LLMReviewResult(model=self._model)

        if not self.is_available():
            result.error = "LLMReviewer not available (no API key / no openai pkg / not enabled)"
            return result

        # 拼 prompt
        critic_text = _summarize_critic_for_llm(critic_output)
        context_parts = []
        if target_sample:
            context_parts.append(f"样品: {target_sample}")
        if user_intent:
            context_parts.append(f"用户意图: {user_intent[:200]}")
        context_text = "\n".join(context_parts)

        user_prompt = (
            f"以下是 critic 对实验样品的规则评分结果:\n\n"
            f"```\n{critic_text}\n```\n\n"
            + (f"上下文:\n{context_text}\n\n" if context_text else "")
            + "请基于以上评分,给出你的复核意见。"
        )

        # 调 LLM
        client = self._get_client()
        if client is None:
            result.error = "Failed to initialize OpenAI client"
            return result

        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                timeout=timeout,
            )
            result.duration_seconds = time.time() - t0

            # 提取回复
            if resp.choices and len(resp.choices) > 0:
                content = resp.choices[0].message.content or ""
                result.review = content.strip()
            else:
                result.error = "Empty response from LLM"

            # token 统计
            if hasattr(resp, "usage") and resp.usage is not None:
                result.input_tokens = int(getattr(resp.usage, "prompt_tokens", 0) or 0)
                result.output_tokens = int(getattr(resp.usage, "completion_tokens", 0) or 0)
                # DeepSeek 价格(2026-07-26 估算):input ¥1/M,output ¥2/M
                result.cost_cny = (
                    result.input_tokens * 0.000001
                    + result.output_tokens * 0.000002
                )

            result.available = True
            return result

        except Exception as e:
            result.duration_seconds = time.time() - t0
            result.error = f"{type(e).__name__}: {e}"
            logger.warning("[LLMReviewer] API 调用失败: %s", e)
            return result

    # ----------------------------------------------------------------
    # 内部 helper — lazy init OpenAI client
    # ----------------------------------------------------------------
    def _get_client(self) -> Any:
        """获取 OpenAI client(单例,线程安全)"""
        if self._client is not None:
            return self._client
        if self._client_initialized:
            return None  # 之前试过失败,不再试

        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                )
                self._client_initialized = True
                return self._client
            except Exception as e:
                logger.warning("[LLMReviewer] init client 失败: %s", e)
                self._client_initialized = True  # 标记已尝试,不再重试
                return None


# ============================================================================
# 工厂函数
# ============================================================================


_global_reviewer: Optional[LLMReviewer] = None
_global_reviewer_lock = threading.Lock()


def get_default_reviewer() -> LLMReviewer:
    """获取全局 LLMReviewer(单例,懒加载)"""
    global _global_reviewer
    if _global_reviewer is None:
        with _global_reviewer_lock:
            if _global_reviewer is None:
                _global_reviewer = LLMReviewer()
    return _global_reviewer


def reset_global_reviewer() -> None:
    """重置全局 reviewer(测试用)"""
    global _global_reviewer
    with _global_reviewer_lock:
        _global_reviewer = None


__all__ = [
    "LLMReviewer",
    "LLMReviewResult",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "get_default_reviewer",
    "reset_global_reviewer",
    "_summarize_critic_for_llm",
]