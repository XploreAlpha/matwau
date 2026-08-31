"""widget_to_markdown.py — matwau Widget → Frakio fenced markdown 转换

设计目标:
- 让 matwau 输出能被 Frakio Work(或其他 rich-content 渲染器)直接显示成卡片
- 跟 frakio-work-wau-bridge/lib/widgets-to-markdown.mjs 保持 kind→fence 一致
- 优先返回纯文本 markdown,作为 WauDispatchResponse.frakio_markdown 字段
  透传,这样调用方(MCP server / homerail / 任何 client)可以省去二次转换

支持的 widget type(per agents/widget_schema.py WidgetType):
  matwau_markdown            → markdown-preview
  matwau_paper_list          → datatable
  matwau_paper_fulltext      → markdown-preview
  matwau_compound_list       → datatable
  matwau_property_table      → datatable
  matwau_journal_list        → datatable
  matwau_recipe_card         → markdown-preview
  matwau_cross_source_summary→ markdown-preview
  未知 type                   → markdown-preview(兜底)

对应 Frakio RichMarkdown.tsx 的 RICH_LANGUAGES:
  mermaid / datatable / image-preview / pdf-preview / html-preview /
  markdown-preview / latex / math / diff / json

MatWAU-Harness-Loop 心法(per /home/inamoto888/WAU-develop/develop-log/matwau/):
- 失败吞掉:data 缺失/类型错 → 不抛,返回兜底 fence(空 markdown-preview body)
- BaseHTTPRequestHandler 风格:不引入第三方(只 stdlib)
- 后向兼容:老 caller 不读 frakio_markdown 字段也兼容(默认值 None)
"""
from __future__ import annotations

import json
from typing import Any, Iterable


# kind → fence language
WIDGET_KIND_FENCE_MAP: dict[str, str] = {
    "matwau_markdown": "markdown-preview",
    "matwau_paper_list": "datatable",
    "matwau_paper_fulltext": "markdown-preview",
    "matwau_compound_list": "datatable",
    "matwau_property_table": "datatable",
    "matwau_journal_list": "datatable",
    "matwau_recipe_card": "markdown-preview",
    "matwau_cross_source_summary": "markdown-preview",
}

SUPPORTED_WIDGET_TYPES: list[str] = list(WIDGET_KIND_FENCE_MAP.keys())

# 50 KiB per widget — 防 Frakio 1MB 单次展示上限(per apps/api/runtime/presentation.mjs:3)
MAX_WIDGET_BYTES = 50 * 1024

# 截断尾巴(与 JS 版保持一致,便于跨语言对比)
TRUNCATION_TAIL = "\n…(截断,完整内容请到 matwau UI 查看)"


def _safe_string(v: Any) -> str:
    """把任意值安全转 str。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def _truncate(s: str, max_bytes: int = MAX_WIDGET_BYTES) -> str:
    """超长字符串截断(按字符数,与 JS 版保持一致)。"""
    if len(s) <= max_bytes:
        return s
    return s[:max_bytes] + TRUNCATION_TAIL


def _datatable_payload(title: str | None, data: dict[str, Any]) -> dict[str, Any]:
    """构造 datatable fence 的 JSON body(过滤 null 字段,降低噪音)。"""
    payload: dict[str, Any] = {
        "title": title or data.get("title"),
        "columns": data.get("columns") if isinstance(data.get("columns"), list) else None,
        "rows": data.get("rows") if isinstance(data.get("rows"), list) else None,
        "records": data.get("records") if isinstance(data.get("records"), list) else None,
        "summary": data.get("summary"),
    }
    # 过滤 null 字段
    return {k: v for k, v in payload.items() if v is not None}


def widget_to_fenced_markdown(widget: dict[str, Any]) -> str:
    """单个 widget → 单个 fenced block。

    输入:widget dict(来自 widget_to_dict 或 Pydantic .model_dump())
    输出:"```fence\\nbody\\n```"
    """
    if not widget or not widget.get("type"):
        return ""

    wtype = widget["type"]
    fence = WIDGET_KIND_FENCE_MAP.get(wtype, "markdown-preview")
    data = widget.get("data") if isinstance(widget.get("data"), dict) else {}
    title = widget.get("title") or data.get("title")

    body = ""
    if fence == "mermaid":
        body = _safe_string(
            data.get("code") or data.get("diagram") or data.get("mermaid") or data.get("text") or ""
        )
        if not body and data.get("chart_data"):
            body = _safe_string(data["chart_data"])
    elif fence == "datatable":
        body = json.dumps(_datatable_payload(title, data), ensure_ascii=False, indent=2)
    elif fence == "image-preview":
        body = json.dumps(
            {
                "src": data.get("src") or data.get("url") or "",
                "alt": data.get("alt") or title or "",
                "caption": data.get("caption") or "",
            },
            ensure_ascii=False,
        )
    elif fence == "pdf-preview":
        body = json.dumps(
            {
                "src": data.get("src") or data.get("url") or "",
                "title": title or data.get("title") or "",
                "page": data.get("page"),
            },
            ensure_ascii=False,
        )
    elif fence == "html-preview":
        body = _safe_string(data.get("html") or data.get("content") or "")
    elif fence == "markdown-preview":
        body = _safe_string(
            data.get("markdown")
            or data.get("content")
            or data.get("text")
            or data.get("body")
            or widget.get("fallback_text")
            or json.dumps(data, ensure_ascii=False, indent=2)
        )
    elif fence == "latex":
        body = _safe_string(data.get("tex") or data.get("latex") or data.get("formula") or "")
    elif fence == "math":
        body = _safe_string(data.get("math") or data.get("tex") or data.get("formula") or "")
    elif fence == "json":
        body = json.dumps(data, ensure_ascii=False, indent=2)
    elif fence == "diff":
        body = _safe_string(data.get("diff") or data.get("patch") or "")
    else:
        body = json.dumps(data, ensure_ascii=False, indent=2)

    return f"```{fence}\n{_truncate(body)}\n```"


def widgets_to_markdown(
    widgets: Iterable[dict[str, Any]] | None,
    reply: str | None = None,
    final_outputs: dict[str, Any] | None = None,
) -> str:
    """整组 widget + reply → Frakio 友好的 markdown 字符串。

    调用方:serve.py 把结果放到 WauDispatchResponse.frakio_markdown。
    """
    parts: list[str] = []

    if reply and reply.strip():
        parts.append(reply.strip())

    if widgets:
        for w in widgets:
            block = widget_to_fenced_markdown(w)
            if block:
                parts.append(block)

    if not parts and final_outputs:
        # 兜底:final_outputs dict → datatable
        rows = [
            [k, _truncate(_safe_string(v), 500)]
            for k, v in final_outputs.items()
        ]
        parts.append(
            widget_to_fenced_markdown(
                {
                    "type": "matwau_property_table",
                    "title": "Workflow final outputs",
                    "data": {"columns": ["key", "value"], "rows": rows},
                }
            )
        )

    return "\n\n".join(parts) if parts else "_No reply or widgets from wau agent._"