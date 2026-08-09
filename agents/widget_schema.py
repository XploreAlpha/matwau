"""widget_schema.py — MatWAU v1.4.1-Academic widget 协议层 Pydantic 模型

设计:
- 7 种 widget type(m2 阶段实现 2 种 matwau_paper_list + matwau_recipe_card;m3 加 5 种)
- Widget 是 envelope,内含 type + data_ref + data + layout + actions + fallback_text
- 老调用方不用 widget 不报错(默认 widgets=[])
- homerail 端 normalizeMatwauWidget() 用 MATWAU_WIDGET_TYPES 白名单过滤

per MatWAU-v1.4-Academic-dev-plan-20260808.md §3 M2 + requirements §4.3 +
    v1.4.1-Academic 删除 matwau_semantic_hits(语义搜索 pipeline 已删,M3 6→5;ALL 8→7)
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# 枚举:widget type + layout + action
# ============================================================================


class WidgetType(str, Enum):
    """7 种 widget type(matwau 团队定义,严格匹配 homerail 端 MATWAU_WIDGET_TYPES 白名单)

    M2 阶段实现 matwau_paper_list + matwau_recipe_card。
    M3 阶段实现:matwau_compound_list + matwau_journal_list + matwau_cross_source_summary
                + matwau_property_table + matwau_paper_fulltext
    v1.4.1-Academic 删除:matwau_semantic_hits(语义搜索 pipeline 已删)
    """

    MATWAU_PAPER_LIST = "matwau_paper_list"
    MATWAU_RECIPE_CARD = "matwau_recipe_card"
    # M3:
    MATWAU_COMPOUND_LIST = "matwau_compound_list"
    MATWAU_JOURNAL_LIST = "matwau_journal_list"
    MATWAU_CROSS_SOURCE_SUMMARY = "matwau_cross_source_summary"
    MATWAU_PROPERTY_TABLE = "matwau_property_table"
    MATWAU_PAPER_FULLTEXT = "matwau_paper_fulltext"
    # v1.4.1-Academic: MATWAU_SEMANTIC_HITS 已删除


class WidgetLayout(str, Enum):
    """widget 布局(m2 用 card_grid / list;M3 加 table)"""

    CARD_GRID = "card_grid"
    LIST = "list"
    TABLE = "table"


class WidgetAction(str, Enum):
    """widget 可执行动作(per type 自由组合)"""

    OPEN_URL = "open_url"  # 新窗口打开 arxiv 链接
    COPY_DOI = "copy_doi"  # 复制 DOI 到剪贴板
    EXPAND_ABSTRACT = "expand_abstract"  # 展开 / 折叠摘要
    EXPAND_STEPS = "expand_steps"  # 展开 / 折叠实验步骤
    SHOW_SOURCES = "show_sources"  # 显示数据源对比
    VIEW_HIT = "view_hit"  # 跳转到具体 hit 详情


# ============================================================================
# Widget Pydantic 模型(envelope)
# ============================================================================


class Widget(BaseModel):
    """matwau widget schema(envelope)

    严格对照 homerail normalizeMatwauWidget() 翻译规则:
    - type:    widget type(必须以 matwau_ 前缀)
    - version: schema version(默认 1.0,后续不破旧 caller)
    - id:      widget id(可空;homerail 自动用 type+title 生成稳定 id)
    - title:   widget 标题(可空;homerail 兜底用 type)
    - data_ref: 指向 data.records / data.paragraphs / data.hits / data.recipe
                默认 "records"
    - layout:  布局枚举(CARD_GRID / LIST / TABLE)
    - actions: 可选动作列表(per type)
    - fallback_text: 渲染失败降级文本(强烈建议填)
    - data:    实际数据 dict(包含 data_ref 指向的字段)
    """

    model_config = ConfigDict(
        # 允许额外字段(向后兼容,homerail 翻译时可丢字段但不报)
        extra="ignore",
        # 启用 str→enum 自动转换("card_grid" → WidgetLayout.CARD_GRID)
        use_enum_values=False,
    )

    type: str = Field(..., description="widget type identifier (必须 matwau_* 前缀)")
    version: str = Field(default="1.0", description="schema version,默认 1.0")
    id: str | None = Field(default=None, description="widget id;为空时由 homerail 自动生成")
    title: str | None = Field(default=None, description="widget 标题;为空时由 homerail 兜底")
    data_ref: str | None = Field(
        default="records",
        description="data 字段名(records / paragraphs / hits / recipe / platforms / properties)",
    )
    layout: WidgetLayout = Field(
        default=WidgetLayout.CARD_GRID,
        description="布局(card_grid / list / table)",
    )
    actions: list[WidgetAction] = Field(
        default_factory=list,
        description="可选动作(open_url / copy_doi / expand_abstract / ...)",
    )
    fallback_text: str | None = Field(
        default=None,
        description="渲染失败降级文本;强烈建议填",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="实际数据,包含 data_ref 指向的字段",
    )


# ============================================================================
# 7 种 widget type 白名单(M2 阶段只开放 2 种;M3 加 5 种,v1.4.1-Academic 起去掉 semantic_hits)
# ============================================================================

M2_SUPPORTED_TYPES: frozenset[str] = frozenset({
    WidgetType.MATWAU_PAPER_LIST.value,
    WidgetType.MATWAU_RECIPE_CARD.value,
})

# v1.4.1-Academic M3 — 5 个新 widget type(去掉 matwau_semantic_hits)
M3_SUPPORTED_TYPES: frozenset[str] = frozenset({
    WidgetType.MATWAU_COMPOUND_LIST.value,
    WidgetType.MATWAU_JOURNAL_LIST.value,
    WidgetType.MATWAU_CROSS_SOURCE_SUMMARY.value,
    WidgetType.MATWAU_PROPERTY_TABLE.value,
    WidgetType.MATWAU_PAPER_FULLTEXT.value,
})

# 全集(M2 + M3)= 7 种
ALL_SUPPORTED_TYPES: frozenset[str] = M2_SUPPORTED_TYPES | M3_SUPPORTED_TYPES


def is_supported_widget_type(widget_type: str) -> bool:
    """判断 widget type 是否在 ALL 支持列表(M2 + M3)

    Args:
        widget_type: e.g. "matwau_paper_list"

    Returns:
        True if supported (M2 or M3), False otherwise
    """
    return widget_type in ALL_SUPPORTED_TYPES


def is_m3_widget_type(widget_type: str) -> bool:
    """判断 widget type 是否是 M3 新增(6 种)

    给 serve.py / homerail 用,方便区分 widget 来自哪个 milestone。

    Args:
        widget_type: e.g. "matwau_compound_list"

    Returns:
        True if M3 specific, False otherwise
    """
    return widget_type in M3_SUPPORTED_TYPES


# ============================================================================
# 便利:Widget.model_dump() 序列化为 dict(给 HTTP JSON 响应)
# ============================================================================


def widget_to_dict(widget: Widget) -> dict[str, Any]:
    """Widget → dict(JSON-serializable)

    方便 /wau/dispatch handler 嵌入 JSON 响应。
    """
    return widget.model_dump(mode="json", exclude_none=False)


__all__ = [
    "Widget",
    "WidgetType",
    "WidgetLayout",
    "WidgetAction",
    "M2_SUPPORTED_TYPES",
    "M3_SUPPORTED_TYPES",
    "ALL_SUPPORTED_TYPES",
    "is_supported_widget_type",
    "is_m3_widget_type",
    "widget_to_dict",
]