"""简报展示辅助测试。"""

from __future__ import annotations

from engine.models import RawItem, ScoredItem
from engine.output.briefing_display import item_facts, item_headline, item_lead, item_takeaway


def test_briefing_fields_preferred():
    raw = RawItem(source_id="s", title="原标题", url="https://x.com")
    item = ScoredItem(
        raw=raw,
        headline="精炼标题",
        lead="发生了某事，融资 1 亿元",
        takeaway="对投资者：判断赛道热度",
        key_points=["金额：1 亿元", "领投：红杉"],
    )
    assert item_headline(item) == "精炼标题"
    assert item_lead(item) == "发生了某事，融资 1 亿元"
    assert item_takeaway(item) == "对投资者：判断赛道热度"
    assert item_facts(item, limit=2) == ["金额：1 亿元", "领投：红杉"]


def test_fallback_to_legacy_fields():
    raw = RawItem(source_id="s", title="原标题", url="https://x.com")
    item = ScoredItem(raw=raw, summary="旧摘要", reason="旧理由", title_display="显示标题")
    assert item_headline(item) == "显示标题"
    assert item_lead(item) == "旧摘要"
    assert item_takeaway(item) == "旧理由"
