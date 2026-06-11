"""daily_stats 与变化叙事测试。"""

from __future__ import annotations

from datetime import datetime

from engine.models import RawItem, ScoredItem


def _make_raw(url="https://example.com/1"):
    return RawItem(
        source_id="s1", title="标题", url=url, content="内容",
        published=datetime.now(), fetched_at=datetime.now(), lang="zh",
    )


def test_save_daily_snapshot_and_narrative(store):
    today = datetime.now().strftime("%Y-%m-%d")
    store.save_daily_snapshot(
        "test-domain", today,
        fetched=100, scored=20, selected=5,
        category_breakdown={"policy": 3, "trade": 2},
    )
    series = store.get_daily_stats_series("test-domain", days=7)
    assert len(series) == 1
    assert series[0]["selected"] == 5
    assert series[0]["categories"]["policy"] == 3

    change = store.get_change_narrative("test-domain")
    assert "narrative" in change


def test_llm_usage_cost_estimate(store):
    store.save_llm_usage("test-domain", 2, 1_000_000, 500_000, 10.0, 5)
    usage = store.get_llm_usage("test-domain", days=30)
    assert usage["estimated_cost_cny"] > 0
    assert usage["daily"][0]["cost_cny"] > 0
