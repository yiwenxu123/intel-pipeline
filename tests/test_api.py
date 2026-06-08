"""API 端点集成测试。"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from engine.models import RawItem, ScoredItem
from engine.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建使用临时数据库的测试客户端。"""
    import engine.config as cfg
    original_db = cfg.settings.db_path
    original_root = cfg.settings.project_root
    cfg.settings.db_path = str(tmp_path / "test.db")
    cfg.settings.project_root = tmp_path

    # 创建最小领域配置
    domain_dir = tmp_path / "domains" / "test-domain"
    domain_dir.mkdir(parents=True)
    (domain_dir / "sources.yaml").write_text(
        "sources:\n  - id: s1\n    name: 测试源\n    kind: rss\n"
        "    url: https://example.com/f\n    tier: T1\n    lang: zh\n",
        encoding="utf-8",
    )
    (domain_dir / "categories.yaml").write_text(
        '{"categories": [{"id": "cat1", "name": "分类一", "freshness_days": 7}]}',
        encoding="utf-8",
    )
    (domain_dir / "keywords.yaml").write_text("keywords: []", encoding="utf-8")
    (domain_dir / "scoring.md").write_text("prompt", encoding="utf-8")
    (domain_dir / "pre_filter.md").write_text("prompt", encoding="utf-8")

    # 复制 dashboard 模板到 tmp_path
    import shutil
    real_template = original_root / "engine" / "output" / "templates" / "dashboard.html"
    tpl_dir = tmp_path / "engine" / "output" / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    if real_template.exists():
        shutil.copy(str(real_template), str(tpl_dir / "dashboard.html"))

    # 清除缓存
    import engine.output.api as api_mod
    api_mod._domain_source_map.clear()
    api_mod.store = None

    from engine.output.api import app
    c = TestClient(app)

    yield c

    cfg.settings.db_path = original_db
    cfg.settings.project_root = original_root
    api_mod.store = None
    api_mod._domain_source_map.clear()


def _seed_data(client):
    """向数据库写入测试数据。"""
    import engine.output.api as api_mod
    s = api_mod.get_store()

    raw = RawItem(source_id="s1", title="测试标题", url="https://example.com/t1",
                  content="内容", published=datetime.now(), fetched_at=datetime.now(), lang="zh")
    rid = s.save_raw(raw)
    scored = ScoredItem(raw=raw, score=8.0, category="cat1", summary="摘要",
                        reason="理由", title_display="中文标题")
    s.save_scored(rid, "test-domain", scored)

    raw2 = RawItem(source_id="s1", title="低分条目", url="https://example.com/t2",
                   content="内容2", published=datetime.now(), fetched_at=datetime.now(), lang="zh")
    rid2 = s.save_raw(raw2)
    scored2 = ScoredItem(raw=raw2, score=3.0, category="cat1", summary="低分摘要")
    s.save_scored(rid2, "test-domain", scored2)


# ── 端点测试 ──

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "情报面板" in r.text


def test_stats(client):
    _seed_data(client)
    r = client.get("/api/stats?domain=test-domain")
    assert r.status_code == 200
    data = r.json()
    assert data["total_fetched"] >= 2
    assert data["selected"] >= 1


def test_items_selected(client):
    _seed_data(client)
    r = client.get("/api/items?domain=test-domain&mode=selected&min_score=6")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["score"] == 8.0
    assert data["items"][0]["source_name"] == "测试源"


def test_items_all(client):
    _seed_data(client)
    r = client.get("/api/items?domain=test-domain&mode=all&min_score=0")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2


def test_items_query(client):
    _seed_data(client)
    r = client.get("/api/items?domain=test-domain&mode=selected&q=测试")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = client.get("/api/items?domain=test-domain&mode=selected&q=不存在")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_categories(client):
    _seed_data(client)
    r = client.get("/api/categories?domain=test-domain")
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert len(cats) >= 1
    assert cats[0]["name"] == "分类一"


def test_sources(client):
    _seed_data(client)
    r = client.get("/api/sources?domain=test-domain")
    assert r.status_code == 200
    sources = r.json()["sources"]
    assert len(sources) >= 1
    assert sources[0]["name"] == "测试源"
    assert "health" in sources[0]


def test_evolution(client):
    _seed_data(client)
    r = client.get("/api/evolution?domain=test-domain")
    assert r.status_code == 200


def test_rss(client):
    _seed_data(client)
    r = client.get("/rss/curated?domain=test-domain")
    assert r.status_code == 200
    assert "xml" in r.headers.get("content-type", "")
