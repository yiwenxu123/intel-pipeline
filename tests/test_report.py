"""report 模块单元测试。"""

from __future__ import annotations

from datetime import datetime

from engine.models import RawItem, ScoredItem
from engine.output.report import _category_top3, _top_entities, report_to_markdown
from engine.models import DailyReport


def _item(score, category="policy", entities=None):
    raw = RawItem(
        source_id="s1", title="标题", url="https://example.com",
        content="内容", published=datetime.now(), fetched_at=datetime.now(),
    )
    return ScoredItem(
        raw=raw, score=score, category=category,
        summary="摘要", entities=entities or [],
    )


def test_category_top3():
    items = [
        _item(8, "policy"), _item(7, "policy"), _item(6.5, "trade"),
        _item(4, "risk"),
    ]
    top = _category_top3(items)
    assert top[0]["category"] == "policy"
    assert top[0]["count"] == 2


def test_top_entities():
    items = [
        _item(7, entities=["肯尼亚", "基建"]),
        _item(8, entities=["肯尼亚", "投资"]),
        _item(6, entities=["南非"]),
    ]
    ents = _top_entities(items)
    assert ents[0] == "肯尼亚"
    assert "南非" in ents


def test_report_markdown_includes_top3():
    report = DailyReport(
        date="2026-06-11", domain="test",
        items=[_item(7, "policy")],
        stats={
            "total_fetched": 100, "total_scored": 10, "selected": 1,
            "select_rate": "1.0%",
            "category_top3": [{"category": "policy", "count": 1}],
            "top_entities": ["肯尼亚"],
        },
    )
    md = report_to_markdown(report)
    assert "分类 Top3" in md
    assert "热点实体" in md
    assert "肯尼亚" in md


def test_report_markdown_briefing_layers():
    raw = RawItem(
        source_id="s1", title="原标题", url="https://example.com",
        content="内容", published=datetime.now(), fetched_at=datetime.now(),
    )
    item = ScoredItem(
        raw=raw, score=7.5, category="policy",
        headline="精炼标题", lead="三部门发文规范保健品营销，6月起专项整治",
        takeaway="对养老机构：提前调整营销合规流程",
        key_points=["时间：6月起全国专项整治", "范围：老年保健品会销"],
        insight_type="fact",
    )
    report = DailyReport(
        date="2026-06-11", domain="test", items=[item],
        stats={"total_fetched": 10, "total_scored": 1, "selected": 1, "select_rate": "10%"},
    )
    md = report_to_markdown(report)
    assert "精炼标题" in md
    assert "6月起专项整治" in md
    assert "营销合规流程" in md
    assert "时间：6月起" in md
    assert "🏷️" not in md
