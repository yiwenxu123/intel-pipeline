"""pipe 端到端集成测试（mock 采集与 LLM）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from engine.config import settings
from engine.domain import load_domain
from engine.models import FetchResult, FilterResult, RawItem, ScoredItem
from engine.pipeline import run_full_pipeline
from engine.store import Store


@pytest.fixture
def pipe_domain(tmp_path, monkeypatch):
    """临时领域目录 + 独立数据库。"""
    domain_name = "test-domain"
    d = tmp_path / "domains" / domain_name
    d.mkdir(parents=True)
    (d / "sources.yaml").write_text(
        "sources:\n"
        "  - id: test_src\n"
        "    name: 测试信源\n"
        "    kind: rss\n"
        "    url: https://example.com/feed\n"
        "    tier: T1\n"
        "    lang: zh\n",
        encoding="utf-8",
    )
    (d / "categories.yaml").write_text(
        json.dumps({
            "categories": [
                {"id": "policy", "name": "政策法规", "freshness_days": 30},
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (d / "keywords.yaml").write_text("keywords:\n  - 测试\n", encoding="utf-8")
    (d / "scoring.md").write_text("评分 prompt", encoding="utf-8")
    (d / "pre_filter.md").write_text("预筛 prompt", encoding="utf-8")

    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "domain", domain_name)
    monkeypatch.setattr(settings, "db_path", f"data/intel-{domain_name}.db")
    monkeypatch.setattr(settings, "pre_filter_backlog_threshold", 9999)
    monkeypatch.setattr(settings, "notify_webhook", "")
    monkeypatch.setattr(settings, "score_window_days", 7)

    return load_domain(domain_name)


def _seed_unscored_raw(domain_name: str) -> RawItem:
    now = datetime.now(timezone.utc)
    raw = RawItem(
        source_id="test_src",
        title="测试政策条目",
        url="https://example.com/article-pipe-1",
        content="正文摘要",
        published=now,
        fetched_at=now,
    )
    with Store() as store:
        store.save_raw(raw)
    return raw


@patch("engine.evolution.scoring_injector.run_calibration_check", return_value={"calibrations": []})
@patch("engine.evolution.keyword_staging.get_staged_keywords", return_value=[])
@patch("engine.evolution.source_lifecycle.run_lifecycle_check", return_value={"disabled": []})
@patch("engine.filter.runner.filter_and_score")
@patch("engine.pipeline.fetch_all")
def test_run_full_pipeline_happy_path(
    mock_fetch,
    mock_filter,
    _mock_lifecycle,
    _mock_kw,
    _mock_cal,
    pipe_domain,
):
    raw = _seed_unscored_raw(pipe_domain.name)
    scored = ScoredItem(raw=raw, score=7.5, category="policy", summary="摘要", reason="相关")

    mock_fetch.return_value = FetchResult(
        new_items=[],
        sources_total=1,
        sources_success=1,
        duration_seconds=0.5,
    )
    mock_filter.return_value = (
        [scored],
        FilterResult(scored_items=[scored], scored_total=1, pre_filter_total=1, pre_filter_passed=1),
    )

    result = run_full_pipeline(pipe_domain, notify=False, max_items=50)

    assert result.error is None
    assert result.fetch is not None
    assert result.filter is not None
    assert result.filter.scored_total == 1
    mock_fetch.assert_called_once()
    mock_filter.assert_called_once()

    with Store() as store:
        row = store.conn.execute(
            "SELECT score, category FROM scored_items WHERE domain = ?",
            (pipe_domain.name,),
        ).fetchone()
        assert row is not None
        assert row["score"] == 7.5

        last_run = store.get_last_pipe_run(pipe_domain.name)
        assert last_run is not None
        assert last_run["scored"] == 1


@patch("engine.evolution.scoring_injector.run_calibration_check", return_value={"calibrations": []})
@patch("engine.evolution.keyword_staging.get_staged_keywords", return_value=[])
@patch("engine.evolution.source_lifecycle.run_lifecycle_check", return_value={"disabled": []})
@patch("engine.pipeline.fetch_all")
def test_run_full_pipeline_fetch_failure(
    mock_fetch,
    _mock_lifecycle,
    _mock_kw,
    _mock_cal,
    pipe_domain,
):
    mock_fetch.side_effect = RuntimeError("network down")

    result = run_full_pipeline(pipe_domain, notify=False)

    assert result.error is not None
    assert "采集失败" in result.error

    with Store() as store:
        last_run = store.get_last_pipe_run(pipe_domain.name)
        assert last_run is not None
        assert last_run["error"] is not None
