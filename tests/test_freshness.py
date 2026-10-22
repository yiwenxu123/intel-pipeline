"""数据新鲜度检查测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

from engine.ops.freshness import check_freshness
from tests.test_store import _make_raw


def test_missing_fetch_is_unhealthy(store):
    result = check_freshness("test-domain")
    assert result["healthy"] is False
    assert "没有采集记录" in " ".join(result["problems"])


def test_fresh_fetch_is_healthy(store):
    store.save_raw(_make_raw(url="https://example.com/fresh", fetched_at=datetime.now()))
    result = check_freshness("test-domain", max_age_hours=8)
    assert result["healthy"] is True
    assert result["age_hours"] is not None
    assert result["age_hours"] < 8


def test_old_fetch_is_unhealthy(store):
    old = datetime.now() - timedelta(hours=9)
    store.save_raw(_make_raw(url="https://example.com/old", fetched_at=old))
    result = check_freshness("test-domain", max_age_hours=8)
    assert result["healthy"] is False
    assert any("最近采集已" in problem for problem in result["problems"])
