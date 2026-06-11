"""API 写操作鉴权测试。"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from engine.models import RawItem, ScoredItem


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    import engine.config as cfg
    import engine.output.api as api_mod

    cfg.settings.db_path = str(tmp_path / "test.db")
    cfg.settings.project_root = tmp_path
    cfg.settings.api_token = "secret-token"

    domain_dir = tmp_path / "domains" / "test-domain"
    domain_dir.mkdir(parents=True)
    for name, content in {
        "sources.yaml": "sources:\n  - id: s1\n    name: t\n    kind: rss\n    url: https://x.com/f\n    tier: T1\n    lang: zh\n",
        "categories.yaml": '{"categories": []}',
        "keywords.yaml": "keywords: []",
        "scoring.md": "p",
        "pre_filter.md": "p",
    }.items():
        (domain_dir / name).write_text(content, encoding="utf-8")

    api_mod.store = None
    return TestClient(api_mod.app)


def test_post_feedback_requires_token(auth_client):
    r = auth_client.post(
        "/api/items/feedback?raw_id=1&domain=test-domain&corrected_score=5",
    )
    assert r.status_code == 401


def test_post_feedback_with_token(auth_client):
    from engine.store import Store

    with Store() as store:
        raw = RawItem(
            source_id="s", title="t", url="https://x.com",
            fetched_at=datetime.now(),
        )
        rid = store.save_raw(raw)
        store.save_scored(rid, "test-domain", ScoredItem(raw=raw, score=6.0))

    r = auth_client.post(
        f"/api/items/feedback?raw_id={rid}&domain=test-domain&corrected_score=5",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_api_config_shows_auth_required(auth_client):
    r = auth_client.get("/api/config")
    assert r.json()["auth_required"] is True
