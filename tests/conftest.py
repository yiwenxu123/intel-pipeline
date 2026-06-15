"""共用测试 fixtures。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.store import Store


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Mock 所有 LLM 调用，防止测试意外产生 API 费用。"""
    def _mock_chat(model, system, user, temperature=0.3):
        return json.dumps([{
            "score": 7.0,
            "category": "test",
            "tags": [],
            "title": "测试标题",
            "summary": "测试摘要",
            "key_points": ["要点1"],
            "reason": "测试理由",
            "content_type": "news",
            "headline": "测试简报标题",
            "lead": "测试导语",
            "takeaway": "测试要点",
            "insight_type": "fact",
        }])

    monkeypatch.setattr("engine.filter.llm_client.chat", _mock_chat)


@pytest.fixture
def store(tmp_path):
    """创建使用临时数据库的 Store 实例。"""
    db_path = tmp_path / "test.db"
    from engine.config import settings
    original_db_path = settings.db_path
    settings.db_path = str(db_path)
    s = Store(db_path)
    yield s
    s.close()
    settings.db_path = original_db_path


@pytest.fixture
def domain_dir(tmp_path):
    """创建临时领域配置目录。"""
    d = tmp_path / "test-domain"
    d.mkdir()
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
                {"id": "industry", "name": "行业动态", "freshness_days": 7},
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (d / "keywords.yaml").write_text(
        "keywords:\n  - 测试\n  - 示例\n",
        encoding="utf-8",
    )
    (d / "scoring.md").write_text("评分 prompt", encoding="utf-8")
    (d / "pre_filter.md").write_text("预筛 prompt", encoding="utf-8")
    (d / "briefing.md").write_text("简报 prompt", encoding="utf-8")
    return d
