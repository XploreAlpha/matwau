"""widget_helpers.py — MatWAU v1.4-Academic widget 协议层 helper

3 类函数:
1. summarize_for_voice() — TTS 专用短摘要(严禁含列表 / URL / DOI)
2. summarize_natural()   — 给 reply 用,自然语言总结
3. make_*_widget()       — 构造 widget Pydantic 模型(paper_list / recipe_card)

设计原则:
- 所有 helper 都是 pure function(无副作用),便于单测
- spoken_text 硬约束(per requirements §US-5):
  * 1-3 句
  * 总字符 ≤ 200
  * 严禁含论文标题 / 作者名 / URL / DOI
- 老调用方不传 widgets 不报错(summarize / make_* 安全降级)
- 不引入新 LRU cache(per feedback-python-lru-cache-bool-bug.md)

per MatWAU-v1.4-Academic-dev-plan-20260808.md §3 M2 Task 2.2 + Task 2.3
"""
from __future__ import annotations

from typing import Any

from agents.widget_schema import (
    Widget,
    WidgetAction,
    WidgetLayout,
    WidgetType,
)


# ============================================================================
# 硬约束常量(per requirements §US-5)
# ============================================================================

# TTS spoken_text 字符上限
SPOKEN_TEXT_MAX_LENGTH = 200

# 论文标题禁忌词(单测硬断言永不出现这些在 spoken_text)
PAPER_TITLE_FORBIDDEN_TERMS = ("title", "标题", "arxiv:", "doi:", "http://", "https://")


# ============================================================================
# 1. summarize_for_voice() — TTS 专用短摘要
# ============================================================================


def summarize_for_voice(
    records: list[dict[str, Any]] | None,
    user_intent: str,
    *,
    locale: str = "zh",
    kind: str = "papers",
) -> str:
    """生成 TTS 专用文本

    硬约束(违反即测试 fail):
    - 1-3 句
    - 总字符 ≤ SPOKEN_TEXT_MAX_LENGTH(200)
    - 严禁含论文标题 / 作者名 / URL / DOI
    - 严禁含列表项(不用 1. 2. 3.)

    Args:
        records: 数据列表(论文 records 或实验 recipes);None/空 = 0 命中
        user_intent: 用户原始 query(只用于"用户问的是 X"这种上下文,不出现在 spoken_text 标题)
        locale: "zh"(中文)或 "en"(英文)
        kind: "papers" / "recipes"(决定 TTS 文案主语)

    Returns:
        TTS 友好短摘要(≤ 200 字符)
    """
    n = len(records) if records else 0

    # 中文 / 英文 + kind 文案映射
    if kind == "recipes":
        cn_word = "实验方案"
        en_word = "recipe" if n == 1 else "recipes"
        en_empty = "No matching experiment recipes."
    else:  # papers (default)
        cn_word = "论文"
        en_word = "paper" if n == 1 else "papers"
        en_empty = "No matching papers."

    if locale == "zh":
        if n == 0:
            text = f"没有找到与您的需求匹配的{cn_word}。"
        elif n == 1:
            text = f"找到 1 个{cn_word}。"
        elif n <= 3:
            text = f"找到 {n} 个{cn_word}。"
        else:
            text = f"找到 {n} 个{cn_word},排在最前面的是最新结果。"
    else:  # en
        if n == 0:
            text = en_empty
        elif n == 1:
            text = f"Found 1 related {en_word}."
        elif n <= 3:
            text = f"Found {n} related {en_word}."
        else:
            text = f"Found {n} related {en_word}. The top results are the most recent."

    # 截断到上限(保险;正常情况不会到)
    text = text.strip()
    if len(text) > SPOKEN_TEXT_MAX_LENGTH:
        text = text[:SPOKEN_TEXT_MAX_LENGTH - 1] + "…"

    return text


def assert_spoken_text_safe(text: str) -> None:
    """硬断言 spoken_text 满足 TTS 安全约束(给单测用)

    Raises:
        AssertionError: 不满足约束时
    """
    assert isinstance(text, str), f"spoken_text must be str, got {type(text).__name__}"
    assert 0 < len(text) <= SPOKEN_TEXT_MAX_LENGTH, (
        f"spoken_text 长度必须 1-{SPOKEN_TEXT_MAX_LENGTH},实际 {len(text)}"
    )
    text_lower = text.lower()
    for forbidden in PAPER_TITLE_FORBIDDEN_TERMS:
        assert forbidden not in text_lower, (
            f"spoken_text 严禁含 '{forbidden}',实际: {text!r}"
        )


# ============================================================================
# 2. summarize_natural() — 自然语言摘要(给 reply 用)
# ============================================================================


def summarize_natural(
    records: list[dict[str, Any]] | None,
    user_intent: str,
    *,
    locale: str = "zh",
    max_results: int = 5,
) -> str:
    """生成自然语言 summary(给 reply 用)

    与 summarize_for_voice 区别:
    - 自然语言可包含更多信息(论文标题列表、平台、DOI 等)
    - 主要用于前端右栏对话显示,不走 TTS
    - max_results 控制显示前几条论文标题

    Args:
        records: 论文 records 列表;None/空 = 0 命中
        user_intent: 用户原始 query
        locale: "zh" / "en"
        max_results: 显示前几条论文标题

    Returns:
        自然语言 summary
    """
    if not records:
        if locale == "zh":
            return f"⚠️ 没有找到与您需求相关的论文。"
        return "⚠️ No matching papers found for your query."

    n = len(records)
    top = records[:max_results]

    if locale == "zh":
        lines = [f"📚 找到 {n} 篇相关论文:"]
        for r in top:
            title = str(r.get("title", "(无标题)")).strip()
            year = str(r.get("year", "?")).strip()
            url = str(r.get("url", "")).strip()
            doi = str(r.get("doi", "")).strip()
            line = f"  • [{year}] {title[:80]}"
            if url:
                line += f" | {url}"
            if doi:
                line += f" | DOI: {doi}"
            lines.append(line)
        return "\n".join(lines)

    # en
    lines = [f"📚 Found {n} related papers:"]
    for r in top:
        title = str(r.get("title", "(no title)")).strip()
        year = str(r.get("year", "?")).strip()
        url = str(r.get("url", "")).strip()
        doi = str(r.get("doi", "")).strip()
        line = f"  • [{year}] {title[:80]}"
        if url:
            line += f" | {url}"
        if doi:
            line += f" | DOI: {doi}"
        lines.append(line)
    return "\n".join(lines)


def summarize_recipe_natural(
    recipes: list[Any] | None,
    user_intent: str,
    *,
    locale: str = "zh",
) -> str:
    """生成实验方案的自然语言 summary(给 mat_exp_agent reply 用)

    Args:
        recipes: List[ExpRecipe] 或 List[dict];None/空 = 0 命中
        user_intent: 用户原始 query
        locale: "zh" / "en"

    Returns:
        自然语言 summary
    """
    if not recipes:
        if locale == "zh":
            return "⚠️ 没有找到匹配的实验方案。"
        return "⚠️ No matching experiment recipes found."

    n = len(recipes)
    if locale == "zh":
        return f"🧪 生成 {n} 个实验方案(XRD + 烧结参数)。"
    return f"🧪 Generated {n} experiment recipes (XRD + sintering parameters)."


# ============================================================================
# 3. make_paper_list_widget() — 构造 matwau_paper_list widget
# ============================================================================


def make_paper_list_widget(
    records: list[dict[str, Any]] | None,
    *,
    title: str | None = None,
    fallback_text: str | None = None,
    max_records: int = 10,
) -> Widget:
    """构造 matwau_paper_list widget

    Args:
        records: 论文 records 列表(mat_arxiv_agent 输出)
        title: widget 标题(可空)
        fallback_text: 渲染失败降级文本(强烈建议填)
        max_records: 最大记录数(避免前端卡片过多,默认 10)

    Returns:
        Widget(type="matwau_paper_list", data_ref="records", data={records: [...]})
    """
    # 截断到 max_records
    safe_records = (records or [])[:max_records]

    # fallback_text 默认:自然语言 summary
    if fallback_text is None:
        fallback_text = summarize_natural(safe_records, "", locale="zh")

    return Widget(
        type=WidgetType.MATWAU_PAPER_LIST.value,
        title=title or "推荐论文",
        data_ref="records",
        layout=WidgetLayout.CARD_GRID,
        actions=[
            WidgetAction.OPEN_URL,
            WidgetAction.COPY_DOI,
            WidgetAction.EXPAND_ABSTRACT,
        ],
        fallback_text=fallback_text,
        data={"records": safe_records, "visual": "matwau_paper_list"},
    )


# ============================================================================
# 4. make_recipe_card_widget() — 构造 matwau_recipe_card widget
# ============================================================================


def make_recipe_card_widget(
    recipes: list[dict[str, Any]] | None,
    *,
    title: str | None = None,
    fallback_text: str | None = None,
    max_recipes: int = 10,
) -> Widget:
    """构造 matwau_recipe_card widget

    Args:
        recipes: 实验方案列表(每条 ExpRecipe 经 .to_dict() 或 dict 形态)
        title: widget 标题(可空)
        fallback_text: 渲染失败降级文本
        max_recipes: 最大方案数(默认 10)

    Returns:
        Widget(type="matwau_recipe_card", data_ref="recipe", data={recipe: [...]})
    """
    safe_recipes = (recipes or [])[:max_recipes]

    if fallback_text is None:
        fallback_text = summarize_recipe_natural(safe_recipes, "", locale="zh")

    return Widget(
        type=WidgetType.MATWAU_RECIPE_CARD.value,
        title=title or "实验方案",
        data_ref="recipe",
        layout=WidgetLayout.LIST,
        actions=[
            WidgetAction.EXPAND_STEPS,
            WidgetAction.SHOW_SOURCES,
        ],
        fallback_text=fallback_text,
        data={"recipe": safe_recipes, "visual": "matwau_recipe_card"},
    )


# ============================================================================
# 5. attach_widget_protocol() — 给 AgentResponse 加 widget 协议层字段
# ============================================================================


def attach_widget_protocol(
    response,  # AgentResponse(dataclass,不 import 避免循环)
    *,
    widgets: list[Widget] | None = None,
    spoken_text: str | None = None,
    structured_data: dict[str, Any] | None = None,
):
    """给 AgentResponse 加 widget 协议层字段(原地修改)

    Args:
        response: AgentResponse 实例
        widgets: widget 列表(为空时不修改 response.widgets)
        spoken_text: TTS 短摘要(长度 > 0 才设置)
        structured_data: records 副本(前端直接消费)

    Returns:
        修改后的 response(同 instance,链式调用友好)
    """
    if widgets is not None and len(widgets) > 0:
        response.widgets = widgets
    if spoken_text is not None and spoken_text.strip():
        # 硬约束:长度 > 200 自动截断
        if len(spoken_text) > SPOKEN_TEXT_MAX_LENGTH:
            spoken_text = spoken_text[:SPOKEN_TEXT_MAX_LENGTH - 1] + "…"
        response.spoken_text = spoken_text
    if structured_data is not None:
        response.structured_data = structured_data
    return response


__all__ = [
    "SPOKEN_TEXT_MAX_LENGTH",
    "PAPER_TITLE_FORBIDDEN_TERMS",
    "summarize_for_voice",
    "assert_spoken_text_safe",
    "summarize_natural",
    "summarize_recipe_natural",
    "make_paper_list_widget",
    "make_recipe_card_widget",
    "attach_widget_protocol",
]