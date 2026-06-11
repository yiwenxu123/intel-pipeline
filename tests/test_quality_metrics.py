"""质量指标模块测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from engine.models import RawItem, ScoredItem
from engine.ops.quality_metrics import compute_quality_metrics
from engine.store import Store


def test_compute_quality_metrics(store):
    raw = RawItem(
        source_id="s", title="测试", url="https://example.com/1",
        fetched_at=datetime.now(timezone.utc),
    )
    rid = store.save_raw(raw)
    store.save_scored(rid, "test-domain", ScoredItem(
        raw=raw, score=7.0, category="policy",
        headline="精炼标题", lead="发生某事", takeaway="有用",
    ))
    m = compute_quality_metrics("test-domain", store)
    assert m["metrics"]["selected_count"] == 1
    assert m["metrics"]["briefing_coverage_pct"] == 100.0
    assert m["dod"]["D2_briefing_ok"] is True
