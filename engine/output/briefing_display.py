"""简报字段展示辅助：兼容旧数据与新分层字段。"""

from __future__ import annotations

from engine.models import ScoredItem

# 内容形态标签（仅 analysis/opinion 等需要额外标注时展示；日常以 category 为主）
_CONTENT_TYPE_LABELS: dict[str, str] = {
    "analysis": "行业观点",
    "opinion": "行业观点",
    "research": "研究报告",
    "report": "行业报告",
    "policy": "政策文件",
}


def item_headline(item: ScoredItem | dict) -> str:
    if isinstance(item, dict):
        return (
            item.get("headline")
            or item.get("title_display")
            or item.get("title")
            or ""
        )
    return item.headline or item.title_display or item.raw.title


def item_lead(item: ScoredItem | dict) -> str:
    if isinstance(item, dict):
        return item.get("lead") or item.get("summary") or ""
    return item.lead or item.summary


def item_takeaway(item: ScoredItem | dict) -> str:
    if isinstance(item, dict):
        return item.get("takeaway") or item.get("reason") or ""
    return item.takeaway or item.reason


def item_facts(item: ScoredItem | dict, limit: int = 2) -> list[str]:
    if isinstance(item, dict):
        raw = item.get("key_points") or []
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
    else:
        raw = item.key_points or []
    return [str(f) for f in raw if f][:limit]


def content_type_label(item: ScoredItem | dict) -> str:
    """返回内容形态中文标签；news 等常规报道返回空串（由 category 承担分类）。"""
    if isinstance(item, dict):
        t = (item.get("content_type") or "news").strip().lower()
    else:
        t = (item.content_type or "news").strip().lower()
    return _CONTENT_TYPE_LABELS.get(t, "")
