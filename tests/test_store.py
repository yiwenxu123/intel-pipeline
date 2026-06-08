"""Store 层单元测试。"""

from __future__ import annotations

from datetime import datetime

from engine.models import RawItem, ScoredItem


def _make_raw(source_id="src1", title="标题", url="https://example.com/1", **kwargs):
    defaults = dict(
        source_id=source_id,
        title=title,
        url=url,
        content="内容摘要",
        published=datetime(2026, 6, 8, 10, 0, 0),
        fetched_at=datetime(2026, 6, 8, 12, 0, 0),
        lang="zh",
    )
    defaults.update(kwargs)
    return RawItem(**defaults)


def _make_scored(raw, score=7.5, category="industry", summary="摘要"):
    return ScoredItem(
        raw=raw, score=score, category=category,
        summary=summary, reason="推荐理由",
    )


# ── save_raw ──

def test_save_raw_returns_id(store):
    item = _make_raw()
    rid = store.save_raw(item)
    assert rid > 0


def test_save_raw_dedup(store):
    item = _make_raw()
    rid1 = store.save_raw(item)
    rid2 = store.save_raw(item)
    assert rid1 == rid2


def test_save_raw_multiple(store):
    ids = []
    for i in range(3):
        item = _make_raw(url=f"https://example.com/{i}", title=f"标题{i}")
        ids.append(store.save_raw(item))
    assert len(set(ids)) == 3


# ── exists ──

def test_exists_true(store):
    item = _make_raw()
    store.save_raw(item)
    assert store.exists(item.url) is True


def test_exists_false(store):
    assert store.exists("https://nonexistent.com") is False


# ── save_scored ──

def test_save_scored(store):
    raw = _make_raw()
    rid = store.save_raw(raw)
    scored = _make_scored(raw)
    sid = store.save_scored(rid, "test-domain", scored)
    assert sid > 0


# ── get_selected ──

def test_get_selected_basic(store):
    raw = _make_raw()
    rid = store.save_raw(raw)
    scored = _make_scored(raw, score=7.5)
    store.save_scored(rid, "test-domain", scored)

    results = store.get_selected("test-domain", min_score=6.0)
    assert len(results) == 1
    assert results[0]["score"] == 7.5
    assert results[0]["source_id"] == "src1"


def test_get_selected_filters_low_score(store):
    raw1 = _make_raw(url="https://example.com/high")
    raw2 = _make_raw(url="https://example.com/low", title="低分")
    rid1 = store.save_raw(raw1)
    rid2 = store.save_raw(raw2)
    store.save_scored(rid1, "test-domain", _make_scored(raw1, score=8.0))
    store.save_scored(rid2, "test-domain", _make_scored(raw2, score=4.0))

    results = store.get_selected("test-domain", min_score=6.0)
    assert len(results) == 1
    assert results[0]["score"] == 8.0


def test_get_selected_by_category(store):
    raw = _make_raw()
    rid = store.save_raw(raw)
    store.save_scored(rid, "test-domain", _make_scored(raw, category="policy"))

    results = store.get_selected("test-domain", min_score=6.0, category="policy")
    assert len(results) == 1

    results = store.get_selected("test-domain", min_score=6.0, category="industry")
    assert len(results) == 0


def test_get_selected_by_query(store):
    raw = _make_raw(title="养老政策更新", content="民政部发布新规")
    rid = store.save_raw(raw)
    store.save_scored(rid, "test-domain", _make_scored(raw, summary="民政部发布养老新规"))

    results = store.get_selected("test-domain", min_score=6.0, q="养老")
    assert len(results) == 1

    results = store.get_selected("test-domain", min_score=6.0, q="不存在的词")
    assert len(results) == 0


# ── get_stats ──

def test_get_stats(store):
    raw = _make_raw()
    rid = store.save_raw(raw)
    store.save_scored(rid, "test-domain", _make_scored(raw, score=7.0))

    stats = store.get_stats("test-domain", date="2026-06-08")
    assert stats["total_fetched"] >= 1
    assert stats["selected"] >= 1


# ── 上下文管理器 ──

def test_context_manager(tmp_path):
    db_path = tmp_path / "ctx_test.db"
    from engine.config import settings
    from engine.store import Store
    original = settings.db_path
    settings.db_path = str(db_path)
    try:
        with Store(db_path) as s:
            assert s.conn is not None
        # 连接已关闭，后续操作应失败
        import sqlite3
        try:
            s.conn.execute("SELECT 1")
            assert False, "连接应该已关闭"
        except Exception:
            pass
    finally:
        settings.db_path = original
