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

    # 中文 / 英文 + kind 文案映射(v1.4-Academic M3 扩 6 种 kind)
    if kind == "recipes":
        cn_word = "实验方案"
        en_word = "recipe" if n == 1 else "recipes"
        en_empty = "No matching experiment recipes."
    elif kind == "compounds":
        cn_word = "化合物"
        en_word = "compound" if n == 1 else "compounds"
        en_empty = "No matching compounds."
    elif kind == "journals":
        cn_word = "期刊文章"
        en_word = "journal article" if n == 1 else "journal articles"
        en_empty = "No matching journal articles."
    elif kind == "cross_source":
        # N 个数据源 + 命中 records 一致性
        # records 是 list[platform]，每个 element 是该 platform 的 records
        n_platforms = n
        if locale == "zh":
            if n_platforms == 0:
                return "没有可用的数据源结果。"
            return f"查询了 {n_platforms} 个数据源。"
        else:
            if n_platforms == 0:
                return "No source results available."
            return f"Queried {n_platforms} data sources."
    elif kind == "properties":
        cn_word = "物性"
        en_word = "property" if n == 1 else "properties"
        en_empty = "No matching material properties."
    elif kind == "fulltext":
        cn_word = "段全文"
        en_word = "paragraph" if n == 1 else "paragraphs"
        en_empty = "No fulltext paragraphs parsed."
    # v1.4.1-Academic:删除 kind="semantic" 分支(语义搜索 pipeline 整体删除)
    elif kind == "markdown":
        # v1.4.2-Academic:Markdown widget 的 spoken_text — LLM 主体内容已 TTS 渲染,
        # 这里给个 "以下是详细 Markdown 回答" 的兜底提示。
        cn_word = "段 Markdown 内容"
        en_word = "markdown section" if n == 1 else "markdown sections"
        en_empty = "No markdown content generated."
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


# ============================================================================
# v1.4-Academic M3 — 6 新 make_*_widget() 工厂(per FE 6 个 Matwau*Widget 期望 data shape)
# ============================================================================


def make_compound_list_widget(
    records: list[dict[str, Any]] | None,
    *,
    title: str | None = None,
    fallback_text: str | None = None,
    max_records: int = 10,
) -> Widget:
    """构造 matwau_compound_list widget(mat-pubchem-agent)

    Wire format(对照 MatwauCompoundListWidget.vue):
    data.records[i]: {cid, name, molecular_formula, molecular_weight, canonical_smiles, iupac_name, synonyms, url}

    Args:
        records: PubChemReference.to_dict() 列表
        title: widget 标题(默认 "PubChem 化合物")
        fallback_text: 渲染失败降级文本
        max_records: 上限默认 10

    Returns:
        Widget(type="matwau_compound_list", data_ref="records", layout=CARD_GRID)
    """
    safe_records = (records or [])[:max_records]
    if fallback_text is None:
        fallback_text = summarize_for_voice(safe_records, "", locale="zh", kind="compounds")

    return Widget(
        type=WidgetType.MATWAU_COMPOUND_LIST.value,
        title=title or "PubChem 化合物",
        data_ref="records",
        layout=WidgetLayout.CARD_GRID,
        actions=[
            WidgetAction.OPEN_URL,
            WidgetAction.EXPAND_ABSTRACT,  # 复用"展开"语义(化合物别名展开)
        ],
        fallback_text=fallback_text,
        data={
            "records": safe_records,
            "visual": "matwau_compound_list",
        },
    )


def make_journal_list_widget(
    records: list[dict[str, Any]] | None,
    *,
    title: str | None = None,
    fallback_text: str | None = None,
    max_records: int = 10,
) -> Widget:
    """构造 matwau_journal_list widget(mat-crossref-agent)

    Wire format(对照 MatwauJournalListWidget.vue):
    data.records[i]: {doi, title, authors, journal, year, volume, issue, pages, url, abstract}

    Args:
        records: CrossRefReference.to_dict() 列表
        title: widget 标题(默认 "CrossRef 期刊文章")
        fallback_text: 渲染失败降级文本
        max_records: 上限默认 10

    Returns:
        Widget(type="matwau_journal_list", data_ref="records", layout=CARD_GRID)
    """
    safe_records = (records or [])[:max_records]
    if fallback_text is None:
        fallback_text = summarize_for_voice(safe_records, "", locale="zh", kind="journals")

    return Widget(
        type=WidgetType.MATWAU_JOURNAL_LIST.value,
        title=title or "CrossRef 期刊文章",
        data_ref="records",
        layout=WidgetLayout.CARD_GRID,
        actions=[
            WidgetAction.OPEN_URL,
            WidgetAction.COPY_DOI,
            WidgetAction.EXPAND_ABSTRACT,
        ],
        fallback_text=fallback_text,
        data={
            "records": safe_records,
            "visual": "matwau_journal_list",
        },
    )


def make_cross_source_summary_widget(
    *,
    consensus_text: str,
    confidence: float,
    consensus_rate: float,
    sources: list[dict[str, Any]],
    query: str = "",
    title: str | None = None,
    fallback_text: str | None = None,
) -> Widget:
    """构造 matwau_cross_source_summary widget(mat-critic-agent L5 跨源)

    Wire format(对照 MatwauCrossSourceSummaryWidget.vue):
    data: {
        query,
        consensus: {text, confidence, consensus_rate},
        sources: [{name, label, hit_count, agreed, error}]
    }

    Args:
        consensus_text: L4 critic 总结文本
        confidence: 0..1 综合置信度
        consensus_rate: 0..1 跨源一致率
        sources: 4 个 platform 的 hit 信息 list
        query: 用户原始 query(供前端展示)
        title: widget 标题(默认 "跨源一致性")
        fallback_text: 渲染失败降级文本

    Returns:
        Widget(type="matwau_cross_source_summary", data_ref="sources", layout=LIST)
    """
    if fallback_text is None:
        n_sources = len(sources)
        fallback_text = summarize_for_voice(
            sources, "", locale="zh", kind="cross_source"
        ) if n_sources == 0 else consensus_text[:SPOKEN_TEXT_MAX_LENGTH]

    return Widget(
        type=WidgetType.MATWAU_CROSS_SOURCE_SUMMARY.value,
        title=title or "跨源一致性",
        data_ref="sources",
        layout=WidgetLayout.LIST,
        actions=[
            WidgetAction.SHOW_SOURCES,
            WidgetAction.EXPAND_ABSTRACT,
        ],
        fallback_text=fallback_text,
        data={
            "visual": "matwau_cross_source_summary",
            "query": query,
            "consensus": {
                "text": consensus_text,
                "confidence": round(confidence, 3),
                "consensus_rate": round(consensus_rate, 3),
            },
            "sources": sources,
        },
    )


def make_property_table_widget(
    *,
    formula: str,
    properties: list[dict[str, Any]],
    title: str | None = None,
    fallback_text: str | None = None,
    source_platform: str = "",
) -> Widget:
    """构造 matwau_property_table widget(mat-oqmd/cod/nomad/jarvis-agent)

    Wire format(对照 MatwauPropertyTableWidget.vue):
    data: {
        formula,
        properties: [{name, label, value, unit, source}]
    }

    Args:
        formula: 化学式(主键,用作 widget 标题前缀)
        properties: 物性 list
        title: widget 标题(默认 "{formula} 物性")
        fallback_text: 渲染失败降级文本
        source_platform: 数据源平台(OQMD/COD/NOMAD/JARVIS),用于 fallback

    Returns:
        Widget(type="matwau_property_table", data_ref="properties", layout=TABLE)
    """
    if fallback_text is None:
        fallback_text = summarize_for_voice(
            properties, "", locale="zh", kind="properties"
        )

    # 构造 title(per widget)
    widget_title = title or f"{formula or source_platform or '材料'} 物性"

    return Widget(
        type=WidgetType.MATWAU_PROPERTY_TABLE.value,
        title=widget_title,
        data_ref="properties",
        layout=WidgetLayout.TABLE,
        actions=[
            WidgetAction.SHOW_SOURCES,
        ],
        fallback_text=fallback_text,
        data={
            "visual": "matwau_property_table",
            "formula": formula,
            "properties": properties,
        },
    )


def make_paper_fulltext_widget(
    *,
    arxiv_id: str,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    sections: list[dict[str, Any]] | None = None,
    url: str = "",
    parser: str = "pdfplumber",
    fallback_text: str | None = None,
) -> Widget:
    """构造 matwau_paper_fulltext widget(mat-pdf-agent)

    Wire format(对照 MatwauPaperFulltextWidget.vue):
    data: {
        arxiv_id, title, authors, abstract,
        sections: [{heading, text}],
        url, parser
    }

    Args:
        arxiv_id: 论文 ID(arxiv:2401.00001 → 前端期望 "2401.00001")
        title: 论文标题
        authors: 作者列表
        abstract: 摘要
        sections: 章节 list(每节 {heading, text})
        url: 原始 PDF URL
        parser: 解析器名(默认 pdfplumber)
        fallback_text: 渲染失败降级文本

    Returns:
        Widget(type="matwau_paper_fulltext", data_ref="sections", layout=LIST)
    """
    safe_authors = list(authors or [])
    safe_sections = list(sections or [])

    if fallback_text is None:
        fallback_text = summarize_for_voice(
            safe_sections, "", locale="zh", kind="fulltext"
        )

    return Widget(
        type=WidgetType.MATWAU_PAPER_FULLTEXT.value,
        title=title or f"论文 {arxiv_id}",
        data_ref="sections",
        layout=WidgetLayout.LIST,
        actions=[
            WidgetAction.OPEN_URL,
            WidgetAction.EXPAND_ABSTRACT,
        ],
        fallback_text=fallback_text,
        data={
            "visual": "matwau_paper_fulltext",
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": safe_authors,
            "abstract": abstract,
            "sections": safe_sections,
            "url": url,
            "parser": parser,
        },
    )


# v1.4.1-Academic: 删除 make_semantic_hits_widget — 语义搜索 pipeline 整体删除
# (semantic_search_agent + semantic_search workflow + SemanticSearchClient 都已删)


def make_markdown_widget(
    *,
    markdown: str,
    title: str = "",
    source: str | None = None,
    generated_at: str | None = None,
    data_ref: str = "markdown",
    fallback_text: str | None = None,
) -> Widget:
    """构造 matwau_markdown widget — free-form Markdown 内容(v1.4.2-Academic Option C)

    Wire format(对照 homerail MatwauMarkdownWidget.vue):
    data: {
        markdown: str,           # 必填,Markdown 原文
        source: str | None,      # 可选,数据来源 label(显示在 header)
        generated_at: str | None # 可选,生成时间(显示在 header)
    }

    与其他 matwau_* widget 的区别:
    - 不固定 schema(records / paragraphs / sections / hits),直接渲染 Markdown 原文
    - LLM 自由组织内容:heading + list + table + blockquote + inline code + 链接 都可
    - homerail 端用 markdown-it 渲染(html: false,XSS-safe)+ 外链强制 target=_blank rel=noopener
    - 16K 字符硬截断(在 FE widget 里),超过溢出区有提示

    Args:
        markdown: Markdown 原文(必填,空字符串会走空状态)
        title: widget 标题(默认 "MatWAU 内容卡片")
        source: 数据来源 label,如 "mat_summary_agent"
        generated_at: 生成时间 ISO string
        data_ref: 透传字段名,默认 "markdown",与 homerail MATWAU_DATA_REF_TO_VISUAL 对齐
        fallback_text: 渲染失败降级文本(默认 summarize_for_voice kind="markdown")

    Returns:
        Widget(type="matwau_markdown", data_ref="markdown", layout=LIST)
    """
    if not isinstance(markdown, str):
        raise TypeError(f"markdown must be str, got {type(markdown).__name__}")

    # 16K 上限对齐 FE MatwauMarkdownWidget.vue 的 MAX_MARKDOWN_CHARS,
    # 服务端先截一次,避免超长 markdown 走 wire 浪费带宽。
    MARKDOWN_MAX_CHARS = 16_000
    if len(markdown) > MARKDOWN_MAX_CHARS:
        markdown = markdown[: MARKDOWN_MAX_CHARS - 1].rstrip() + "…"

    if fallback_text is None:
        fallback_text = summarize_for_voice(markdown, "", locale="zh", kind="markdown")

    return Widget(
        type=WidgetType.MATWAU_MARKDOWN.value,
        title=title or "MatWAU 内容卡片",
        data_ref=data_ref,
        layout=WidgetLayout.LIST,
        actions=[],
        fallback_text=fallback_text,
        data={
            "visual": "matwau_markdown",
            "markdown": markdown,
            "source": source,
            "generated_at": generated_at,
        },
    )


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
    # v1.4.1-Academic M3 — 5 new factories(去掉 make_semantic_hits_widget)
    "make_compound_list_widget",
    "make_journal_list_widget",
    "make_cross_source_summary_widget",
    "make_property_table_widget",
    "make_paper_fulltext_widget",
    # v1.4.2-Academic: matwau_markdown widget — free-form Markdown
    "make_markdown_widget",
    "attach_widget_protocol",
]