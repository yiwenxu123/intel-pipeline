"""评分批次空响应时逐条重试的测试。"""

from __future__ import annotations

import json

from engine.filter.pipeline import _score_batch, get_score_stats, reset_score_stats
from engine.models import RawItem


def test_empty_batch_response_retries_each_item(monkeypatch):
    calls = {"n": 0}

    def fake_chat(model, system, user, temperature=0.3):
        calls["n"] += 1
        if calls["n"] == 1:
            return ""
        return json.dumps([{
            "score": 7.0,
            "category": "industry",
            "tags": [],
            "title": "标题",
            "summary": "摘要",
            "key_points": [],
            "reason": "理由",
            "content_type": "news",
        }], ensure_ascii=False)

    monkeypatch.setattr("engine.filter.pipeline.chat", fake_chat)
    reset_score_stats()
    items = [
        RawItem(source_id="s1", title="条目一", url="https://example.com/1", content="正文一"),
        RawItem(source_id="s2", title="条目二", url="https://example.com/2", content="正文二"),
    ]

    scored = _score_batch(items, 0, "评分 prompt", "test-domain")

    assert len(scored) == 2
    assert all(item.score == 7.0 for item in scored)
    assert calls["n"] == 3  # 1 次批量 + 2 次逐条重试
    assert get_score_stats()["retry_success"] == 2
