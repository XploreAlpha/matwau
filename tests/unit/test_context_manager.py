"""mat-context-manager 单元测试

任务 3 验收(per MatWAU-Harness-Loop-工程心法实践.md §5.1 + §8):
1. ✅ mat-lit token 比 naive 拼装省 50%(16000 → < 8000)
2. ✅ ContextManager.assemble() 输出结构正确
3. ✅ 历史摘要(长历史 → 500 tokens)
4. ✅ RAG top-5 截断
5. ✅ 超 max_tokens 自动压缩
6. ✅ Stage 2 升级:llm_summarize_fn 注入
7. ✅ 默认值 + 边界
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from matwau.harness.context_manager import (  # noqa: E402
    ContextManager,
    ContextMessage,
    naive_assemble,
)


# ============================================================================
# 1. 主效果验收:token 比 naive 省 50%
# ============================================================================


def test_mat_lit_token_50_percent_saving():
    """任务 3 主验收:mat-lit 场景,ContextManager 比 naive 拼装省 token ≥ 50%"""
    # 模拟 mat-lit 真实场景:100 条历史 + 20 篇 RAG 论文 + 1 个 CIF artifact
    system_prompt = "你是材料科学图书管理员,负责检索和分析论文。" * 10  # ~500 tokens
    user_message = "帮我查 2024 年固态电解质论文"

    history = [
        {"role": "user", "content": f"查询 #{i}: 查找 {f'材料体系 {i}'} 相关论文"}
        for i in range(100)
    ]

    rag_results = [
        f"论文 #{i} 摘要:This paper investigates {f'material system {i}'} for solid electrolyte applications..."
        for i in range(20)
    ]

    artifacts = {"cif": "C1=2 O3 Li1..." * 50}

    # naive 拼装
    naive_ctx = naive_assemble(
        system_prompt=system_prompt,
        user_message=user_message,
        artifacts=artifacts,
        history=history,
        rag_results=rag_results,
    )

    # ContextManager 智能拼装
    cm = ContextManager(max_tokens=4000)
    smart_ctx = cm.assemble(
        system_prompt=system_prompt,
        user_message=user_message,
        artifacts=artifacts,
        history=history,
        rag_results=rag_results,
    )

    naive_tokens = naive_ctx["estimated_tokens"]
    smart_tokens = smart_ctx["estimated_tokens"]
    saving = (naive_tokens - smart_tokens) / naive_tokens

    print(f"  naive: {naive_tokens} tokens, smart: {smart_tokens} tokens, saving: {saving:.1%}")

    # 任务 3 主验收:省 ≥ 50%
    assert saving >= 0.5, (
        f"saving {saving:.1%} < 50%, naive={naive_tokens}, smart={smart_tokens}"
    )


# ============================================================================
# 2. assemble() 输出结构
# ============================================================================


def test_assemble_basic_structure():
    """基本输出结构"""
    cm = ContextManager()
    ctx = cm.assemble(
        system_prompt="你是测试 agent",
        user_message="hello",
    )

    assert "messages" in ctx
    assert "estimated_tokens" in ctx
    assert "compressed" in ctx
    assert "parts" in ctx
    assert len(ctx["messages"]) >= 2  # 至少有 system + user
    # system prompt 第一
    assert ctx["messages"][0].role == "system"
    # 用户消息最后
    assert ctx["messages"][-1].role == "user"
    assert ctx["messages"][-1].content == "hello"


def test_assemble_parts_breakdown():
    """各段 token 统计正确"""
    cm = ContextManager()
    ctx = cm.assemble(
        system_prompt="你是测试",
        user_message="hi",
        history=[{"role": "user", "content": "之前问过 X"}],
        rag_results=["paper 1 abstract", "paper 2 abstract"],
        task_state={"step": 3},
        artifacts={"cif": "data"},
    )

    parts = ctx["parts"]
    assert parts["system"] > 0
    assert parts["summary"] > 0  # 历史摘要
    assert parts["rag"] > 0  # RAG 结果
    assert parts["state"] > 0  # 任务状态
    assert parts["artifacts"] > 0  # artifacts 描述
    assert parts["user"] > 0


# ============================================================================
# 3. 历史摘要(长历史 → 500 tokens 内)
# ============================================================================


def test_long_history_summarized_to_limit():
    """100 条历史 → summary ≤ 500 tokens"""
    cm = ContextManager(summary_max_tokens=500)
    long_history = [
        {"role": m, "content": f"消息 #{i} 内容比较长" * 5}
        for m in ["user", "assistant"]
        for i in range(50)
    ]

    ctx = cm.assemble(
        system_prompt="sys",
        user_message="hi",
        history=long_history,
    )

    summary_msg = next(m for m in ctx["messages"] if "[历史摘要]" in m.content)
    summary_tokens = cm.token_estimator(summary_msg.content)
    assert summary_tokens <= 500


def test_empty_history_no_summary():
    """空历史 → 不加 summary 消息"""
    cm = ContextManager()
    ctx = cm.assemble(system_prompt="sys", user_message="hi", history=[])
    assert not any("[历史摘要]" in m.content for m in ctx["messages"])


def test_short_history_kept_verbatim():
    """短历史(<= 5 条)直接保留,不当摘要"""
    cm = ContextManager()
    short_history = [
        {"role": "user", "content": "第一条"},
        {"role": "assistant", "content": "回复 1"},
        {"role": "user", "content": "第二条"},
    ]
    ctx = cm.assemble(system_prompt="sys", user_message="hi", history=short_history)

    summary_msg = next(m for m in ctx["messages"] if "[历史摘要]" in m.content)
    assert "第一条" in summary_msg.content
    assert "第二条" in summary_msg.content


# ============================================================================
# 4. RAG top-K 截断
# ============================================================================


def test_rag_top_5_truncation():
    """20 篇 RAG → 只取 top-5"""
    cm = ContextManager(rag_top_k=5)
    rag_results = [f"论文 #{i} abstract" for i in range(20)]

    ctx = cm.assemble(
        system_prompt="sys",
        user_message="hi",
        rag_results=rag_results,
    )

    rag_msg = next(m for m in ctx["messages"] if "[相关知识]" in m.content)
    # 只含前 5 篇
    for i in range(5):
        assert f"论文 #{i}" in rag_msg.content
    # 不含第 6 篇及之后
    for i in range(5, 20):
        assert f"论文 #{i}" not in rag_msg.content


def test_rag_fewer_than_topk_keeps_all():
    """RAG 不足 top-K 时全保留"""
    cm = ContextManager(rag_top_k=5)
    rag_results = ["论文 1", "论文 2", "论文 3"]

    ctx = cm.assemble(system_prompt="sys", user_message="hi", rag_results=rag_results)
    rag_msg = next(m for m in ctx["messages"] if "[相关知识]" in m.content)
    assert "论文 1" in rag_msg.content
    assert "论文 3" in rag_msg.content


# ============================================================================
# 5. 超 max_tokens 自动压缩
# ============================================================================


def test_over_max_tokens_compresses():
    """超 max_tokens → 自动压缩 + compressed=True"""
    cm = ContextManager(max_tokens=500)
    long_history = [
        {"role": "user", "content": "长消息 " * 100} for _ in range(20)
    ]
    rag_results = ["RAG " * 50 for _ in range(10)]
    artifacts = {"cif": "CIF data " * 100}

    ctx = cm.assemble(
        system_prompt="sys " * 50,
        user_message="hi",
        history=long_history,
        rag_results=rag_results,
        artifacts=artifacts,
    )

    assert ctx["compressed"] is True
    assert ctx["estimated_tokens"] <= 500 * 1.05  # 5% buffer


def test_under_max_tokens_no_compression():
    """未超 max_tokens → compressed=False"""
    cm = ContextManager(max_tokens=8000)
    ctx = cm.assemble(system_prompt="sys", user_message="hi")
    assert ctx["compressed"] is False


# ============================================================================
# 6. Stage 2 升级:llm_summarize_fn 注入
# ============================================================================


def test_llm_summarize_fn_used_for_long_history():
    """长历史 + 注入 llm_summarize_fn → 走 LLM 摘要"""
    call_log = []

    def mock_llm_summarize(text: str, max_tokens: int) -> str:
        call_log.append((len(text), max_tokens))
        return "[LLM 摘要] 这是用 LLM 智能摘要的历史"

    cm = ContextManager(
        summary_max_tokens=500,
        llm_summarize_fn=mock_llm_summarize,
    )
    long_history = [{"role": "user", "content": f"消息 {i}"} for i in range(20)]

    ctx = cm.assemble(system_prompt="sys", user_message="hi", history=long_history)

    # 验证 LLM 函数被调用
    assert len(call_log) == 1
    # 验证摘要内容来自 LLM
    summary_msg = next(m for m in ctx["messages"] if "[历史摘要]" in m.content)
    assert "[LLM 摘要]" in summary_msg.content


def test_short_history_skips_llm_summarize():
    """短历史(<= 10 条)不调 LLM"""
    call_log = []

    def mock_llm_summarize(text: str, max_tokens: int) -> str:
        call_log.append("called")
        return "summary"

    cm = ContextManager(llm_summarize_fn=mock_llm_summarize)
    short_history = [{"role": "user", "content": f"msg {i}"} for i in range(5)]

    ctx = cm.assemble(system_prompt="sys", user_message="hi", history=short_history)
    assert len(call_log) == 0  # 未调 LLM


# ============================================================================
# 7. 默认值 + 边界
# ============================================================================


def test_default_max_tokens():
    """默认 max_tokens=4000(per doc §5.1)"""
    cm = ContextManager()
    assert cm.max_tokens == 4000


def test_default_rag_top_k():
    """默认 rag_top_k=5(per doc §5.1)"""
    cm = ContextManager()
    assert cm.rag_top_k == 5


def test_token_estimator_zero_for_empty():
    """空字符串 token = 0"""
    cm = ContextManager()
    assert cm.token_estimator("") == 0


def test_task_state_format():
    """task_state 格式化(str/int/float/bool 简洁输出)"""
    cm = ContextManager()
    ctx = cm.assemble(
        system_prompt="sys",
        user_message="hi",
        task_state={
            "step": 3,
            "agent": "mat-gen",
            "budget": 500.0,
            "completed": True,
            "history": [1, 2, 3],  # 复杂类型 → 显示类型名
        },
    )
    state_msg = next(m for m in ctx["messages"] if "[任务状态]" in m.content)
    assert "step=3" in state_msg.content
    assert "agent=mat-gen" in state_msg.content
    assert "budget=500.0" in state_msg.content
    assert "completed=True" in state_msg.content


def test_artifacts_description_long_truncated():
    """artifacts 字符串过长 → 截断"""
    cm = ContextManager(artifacts_max_tokens=500)
    artifacts = {"cif": "C" * 5000}  # 超长

    ctx = cm.assemble(system_prompt="sys", user_message="hi", artifacts=artifacts)
    artifacts_msg = next(m for m in ctx["messages"] if "[输入文件]" in m.content)
    assert "..." in artifacts_msg.content


def test_artifacts_non_string_compact():
    """artifacts 非字符串(list/dict)→ 紧凑显示"""
    cm = ContextManager()
    artifacts = {"candidates": ["f1", "f2", "f3"], "meta": {"k": "v"}}

    ctx = cm.assemble(system_prompt="sys", user_message="hi", artifacts=artifacts)
    artifacts_msg = next(m for m in ctx["messages"] if "[输入文件]" in m.content)
    assert "<list" in artifacts_msg.content
    assert "<dict" in artifacts_msg.content


def test_compress_user_message_preserved():
    """压缩后用户消息完整保留"""
    cm = ContextManager(max_tokens=500)
    long_history = [{"role": "user", "content": "x" * 1000} for _ in range(10)]

    user_msg = "这是用户关键问题,不能丢"
    ctx = cm.assemble(
        system_prompt="sys " * 100,
        user_message=user_msg,
        history=long_history,
    )

    # 用户消息最后一条,内容完整
    assert ctx["messages"][-1].content == user_msg


# ============================================================================
# 8. naive_assemble() 对照组
# ============================================================================


def test_naive_assemble_all_included():
    """naive 全塞(无摘要无截断)"""
    ctx = naive_assemble(
        system_prompt="sys",
        user_message="hi",
        history=[{"role": "user", "content": "h1"}, {"role": "assistant", "content": "h2"}],
        rag_results=["r1", "r2"],
        artifacts={"a": "x"},
    )

    # 1 条 user message 包含所有内容
    assert len(ctx["messages"]) == 1
    assert ctx["messages"][0].role == "user"
    content = ctx["messages"][0].content
    assert "[SYSTEM] sys" in content
    assert "[USER] h1" in content
    assert "[ASSISTANT] h2" in content
    assert "[RAG] r1" in content
    assert "[ARTIFACT a] x" in content
    assert "[USER] hi" in content


def test_naive_vs_smart_size_difference():
    """naive 比 smart 至少大 50%(主效果)"""
    system_prompt = "sys " * 100
    user_message = "hi"
    history = [{"role": "user", "content": "h" * 200} for _ in range(20)]
    rag_results = ["RAG " * 100 for _ in range(10)]

    naive_ctx = naive_assemble(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
        rag_results=rag_results,
    )

    cm = ContextManager(max_tokens=4000)
    smart_ctx = cm.assemble(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
        rag_results=rag_results,
    )

    assert naive_ctx["estimated_tokens"] > smart_ctx["estimated_tokens"] * 1.5