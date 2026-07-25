"""mat-context-manager — Context 组装器(per Harness-Loop doc §5.1)

Stage 1 简版,11 agent 各自实例化 1 个。

核心功能:
1. 拼装 LLM Context:system + history_summary + rag_top5 + task_state + artifacts + user
2. 估算 token,超 max_tokens 自动压缩
3. 历史摘要(走 LLM,Stage 2 接 wau-llm-router 选最便宜)
4. RAG top-K 截断
5. artifacts 描述生成

效果(per doc §5.1):
| 方案 | token 数 | LLM 成本/次 | 准确率 |
| Naive | ~16000 | ¥0.08 | 70% |
| ContextManager | ~4000 | ¥0.02 | 88% |
| (省 75% + 提升 18%) |

用法:
    cm = ContextManager(max_tokens=4000)
    ctx = cm.assemble(
        system_prompt="...",
        user_message="...",
        artifacts={"cif": "..."},
        history=[...],
        rag_results=["paper 1 abstract", "paper 2 abstract"],
        task_state={"step": 3},
    )
    # ctx = {"messages": [...], "estimated_tokens": 4000}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ContextMessage:
    """LLM Context 中的一条消息"""

    role: str  # "system" | "user" | "assistant"
    content: str


# 1 token ≈ 1.5 字符(中文),粗估用
CHARS_PER_TOKEN_CN = 1.5
CHARS_PER_TOKEN_EN = 4.0


class ContextManager:
    """Context 组装器 — 11 agent 各自实例化 1 个

    Args:
        max_tokens: 单次 LLM 调用最大 token(默认 4000,per doc §5.1)
        summary_max_tokens: 历史摘要最大 token(默认 500)
        rag_top_k: RAG 检索结果取 top-K(默认 5)
        artifacts_max_tokens: artifacts 描述最大 token(默认 500)
        llm_summarize_fn: 历史摘要用的 LLM 调用函数
            signature: (text: str, max_tokens: int) -> str
            Stage 1 默认 naive 截断,Stage 2 接 wau-llm-router
        token_estimator: token 估算函数(默认粗估)
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        summary_max_tokens: int = 500,
        rag_top_k: int = 5,
        artifacts_max_tokens: int = 500,
        llm_summarize_fn: Optional[Callable[[str, int], str]] = None,
        token_estimator: Optional[Callable[[str], int]] = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.summary_max_tokens = summary_max_tokens
        self.rag_top_k = rag_top_k
        self.artifacts_max_tokens = artifacts_max_tokens
        self.llm_summarize_fn = llm_summarize_fn
        self.token_estimator = token_estimator or self._default_token_estimate

    # ========================================================================
    # 主入口:assemble()
    # ========================================================================

    def assemble(
        self,
        system_prompt: str,
        user_message: str,
        artifacts: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        rag_results: Optional[List[str]] = None,
        task_state: Optional[Dict[str, Any]] = None,
        **kwargs: Any,  # W15: 兼容 mat-* agent 透传的额外字段(domain / workflow / ...)
    ) -> Dict[str, Any]:
        """拼装 1 个完整 LLM Context

        Args:
            system_prompt: agent 系统 prompt(~500 tokens)
            user_message: 用户原始消息(最优先,必填)
            artifacts: 输入文件 dict(mat-gen 给 CIF,mat-exp 给 XRD 等)
            history: 历史消息 list,每条 {"role": str, "content": str}
            rag_results: RAG 检索结果 list[str](论文摘要 / 相关知识)
            task_state: 任务状态(mat-orchestrator 注入的 DAG 状态)
            **kwargs: 其他透传字段(W15 域路由等);当前不消费,仅兼容

        Returns:
            {
                "messages": List[ContextMessage],
                "estimated_tokens": int,
                "compressed": bool,
                "parts": {"system": int, "summary": int, "rag": int, ...}
            }
        """
        messages: List[ContextMessage] = []

        # 1. 系统 prompt(必填)
        messages.append(ContextMessage(role="system", content=system_prompt))

        # 2. 历史摘要(可选,智能摘要)
        if history:
            summary_text = self._summarize_history(history)
            if summary_text:
                messages.append(
                    ContextMessage(role="system", content=f"[历史摘要] {summary_text}")
                )

        # 3. RAG 检索结果(可选,top-K 截断)
        if rag_results:
            rag_text = "\n".join(rag_results[: self.rag_top_k])
            messages.append(
                ContextMessage(role="system", content=f"[相关知识] {rag_text}")
            )

        # 4. 任务状态(可选)
        if task_state:
            state_text = self._format_task_state(task_state)
            messages.append(
                ContextMessage(role="system", content=f"[任务状态] {state_text}")
            )

        # 5. artifacts 描述(可选,粗描述)
        if artifacts:
            artifacts_text = self._describe_artifacts(artifacts)
            if artifacts_text:
                messages.append(
                    ContextMessage(role="system", content=f"[输入文件] {artifacts_text}")
                )

        # 6. 用户消息(原始,最优先)
        messages.append(ContextMessage(role="user", content=user_message))

        # 7. 估算 token + 必要时压缩
        parts_tokens = self._calc_parts_tokens(messages)
        total_tokens = sum(parts_tokens.values())
        compressed = False

        if total_tokens > self.max_tokens:
            messages = self._compress(messages, total_tokens)
            parts_tokens = self._calc_parts_tokens(messages)
            total_tokens = sum(parts_tokens.values())
            compressed = True

        return {
            "messages": messages,
            "estimated_tokens": total_tokens,
            "compressed": compressed,
            "parts": parts_tokens,
        }

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _summarize_history(self, history: List[Dict[str, Any]]) -> str:
        """智能摘要历史消息

        Stage 1:naive 截断(取最近 N 条)
        Stage 2:接 wau-llm-router 调 LLM 摘要
        """
        if not history:
            return ""

        # Stage 1 简版:取最近 5 条,每条截断到 100 字符
        recent = history[-5:]
        lines = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if len(content) > 100:
                content = content[:97] + "..."
            lines.append(f"{role}: {content}")
        summary = "\n".join(lines)

        # 截断到 summary_max_tokens
        max_chars = int(self.summary_max_tokens * CHARS_PER_TOKEN_CN)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3] + "..."

        # Stage 2 升级:若注入 llm_summarize_fn,走 LLM 摘要
        if self.llm_summarize_fn and len(history) > 10:
            history_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}"
                for m in history[-20:]
            )
            try:
                summary = self.llm_summarize_fn(history_text, self.summary_max_tokens)
            except Exception:
                pass  # fallback 到 naive 截断

        return summary

    def _format_task_state(self, task_state: Dict[str, Any]) -> str:
        """格式化任务状态(简洁版)"""
        lines = []
        for key, value in task_state.items():
            if isinstance(value, (str, int, float, bool)):
                lines.append(f"{key}={value}")
            else:
                lines.append(f"{key}={type(value).__name__}")
        return ", ".join(lines)

    def _describe_artifacts(self, artifacts: Dict[str, Any]) -> str:
        """描述 artifacts(粗描述,不全文加载)"""
        if not artifacts:
            return ""

        parts = []
        for key, value in artifacts.items():
            if isinstance(value, str):
                # 文件类:取前 200 字符
                desc = value[:200] + ("..." if len(value) > 200 else "")
                parts.append(f"{key}: {desc}")
            elif isinstance(value, (list, dict)):
                parts.append(f"{key}: <{type(value).__name__} len={len(value)}>")
            else:
                parts.append(f"{key}: {value}")

        text = "\n".join(parts)
        max_chars = int(self.artifacts_max_tokens * CHARS_PER_TOKEN_CN)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    def _compress(
        self, messages: List[ContextMessage], total_tokens: int
    ) -> List[ContextMessage]:
        """压缩 Context:超 max_tokens 时截断非关键部分

        优先级(从低到高):
        1. 历史摘要 → 截断到 200 tokens
        2. RAG 结果 → 截断到 top-2
        3. artifacts 描述 → 截断到 200 tokens
        系统 prompt + 用户消息不动
        """
        target = int(self.max_tokens * 0.95)  # 留 5% buffer

        # 简化版压缩:从后往前裁剪非核心消息
        # 实际 Stage 2 会用 LLM 重新摘要
        compressed: List[ContextMessage] = []
        for msg in messages:
            content = msg.content
            if "[历史摘要]" in content and len(content) > 200:
                content = content[:197] + "..."
            elif "[相关知识]" in content:
                # 截断 RAG top-5 → top-2
                lines = content.split("\n")
                if len(lines) > 3:
                    content = "\n".join(lines[:3]) + "\n[其他省略...]"
            elif "[输入文件]" in content and len(content) > 200:
                content = content[:197] + "..."
            compressed.append(ContextMessage(role=msg.role, content=content))

        # 校验
        new_tokens = sum(self.token_estimator(m.content) for m in compressed)
        if new_tokens > target:
            # 还超 → 暴力截断所有 system 消息
            for msg in compressed:
                if msg.role == "system" and len(msg.content) > 100:
                    msg.content = msg.content[:97] + "..."

        return compressed

    def _calc_parts_tokens(self, messages: List[ContextMessage]) -> Dict[str, int]:
        """按段统计 token(system / summary / rag / state / artifacts / user)"""
        parts = {
            "system": 0,
            "summary": 0,
            "rag": 0,
            "state": 0,
            "artifacts": 0,
            "user": 0,
        }
        for msg in messages:
            n = self.token_estimator(msg.content)
            if msg.role == "user":
                parts["user"] += n
            elif "[历史摘要]" in msg.content:
                parts["summary"] += n
            elif "[相关知识]" in msg.content:
                parts["rag"] += n
            elif "[任务状态]" in msg.content:
                parts["state"] += n
            elif "[输入文件]" in msg.content:
                parts["artifacts"] += n
            else:
                parts["system"] += n
        return parts

    def _default_token_estimate(self, text: str) -> int:
        """默认 token 估算(中英混合)

        中文 1 token ≈ 1.5 字符,英文 1 token ≈ 4 字符
        简化:全部按中文 1.5 字符/token 估
        """
        if not text:
            return 0
        return int(len(text) / CHARS_PER_TOKEN_CN)


# ============================================================================
# 便利函数:naive 对照组(per doc §5.1 效果对比表)
# ============================================================================


def naive_assemble(
    system_prompt: str,
    user_message: str,
    artifacts: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    rag_results: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Naive 对照组:全塞 prompt,不摘要不截断

    Returns: ~16000 tokens(per doc §5.1 对比)
    """
    parts = [f"[SYSTEM] {system_prompt}"]

    if history:
        for msg in history:
            parts.append(f"[{msg.get('role', 'user').upper()}] {msg.get('content', '')}")

    if rag_results:
        for r in rag_results:
            parts.append(f"[RAG] {r}")

    if artifacts:
        for k, v in artifacts.items():
            parts.append(f"[ARTIFACT {k}] {v}")

    parts.append(f"[USER] {user_message}")

    text = "\n\n".join(parts)
    tokens = int(len(text) / CHARS_PER_TOKEN_CN)

    return {
        "messages": [ContextMessage(role="user", content=text)],
        "estimated_tokens": tokens,
        "compressed": False,
    }


__all__ = ["ContextManager", "ContextMessage", "naive_assemble"]