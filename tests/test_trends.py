"""周趋势叙事一致性测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.models import RawItem, ScoredItem


def _add_scored(store, domain: str, url: str, created_at: datetime, score: float = 7.0):
    raw = RawItem(
        source_id="test_src",
        title=f"标题 {url}",
        url=url,
        content="内容",
        published=created_at,
        lang="zh",
    )
    rid = store.save_raw(raw)
    sid = store.save_scored(
        rid,
        domain,
        ScoredItem(raw=raw, score=score, category="industry", summary="摘要", reason="理由"),
    )
    store.conn.execute(
        "UPDATE scored_items SET created_at = ? WHERE id = ?",
        (created_at.isoformat(), sid),
    )
    store.conn.commit()


def test_change_narrative_matches_weekly_trend(store):
    now = datetime.now(timezone.utc)
    _add_scored(store, "test-domain", "https://example.com/this-week", now)
    _add_scored(store, "test-domain", "https://example.com/last-week-1", now - timedelta(days=14))
    _add_scored(store, "test-domain", "https://example.com/last-week-2", now - timedelta(days=15))

    trends = store.get_trends("test-domain", days=30)
    change = store.get_change_narrative("test-domain")

    assert len(trends["weekly"]) >= 2
    assert change["this_week"]["selected"] == trends["weekly"][-1]["selected_items"]
    assert change["last_week"]["selected"] == trends["weekly"][-2]["selected_items"]
    assert change["narrative"] == "本周精选 1 条，较上周 ↓ 50%"
