"""export_intel 导出映射测试（消费方 IntelPipelineSource schema）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from engine.ops.export_intel import export_intel_data
from tests.test_store import _make_raw, _make_scored


def test_export_maps_fields(store, tmp_path):
    raw = _make_raw(
        title="银发经济新政策出台",
        url="https://example.com/a?utm_source=x#frag",
        content="RSS 摘要文本",
    )
    rid = store.save_raw(raw)
    store.save_scored(rid, "elderly-care", _make_scored(raw, score=7.2, category="policy"))
    store.update_full_text(raw.url, "提取后的全文正文")

    payload, out = export_intel_data(
        "elderly-care", days=2, min_score=5.5, output=tmp_path / "intel-data.json"
    )

    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["title"] == "银发经济新政策出台"
    assert item["content"] == "提取后的全文正文"  # full_text 优先于 RSS 摘要
    assert item["domain"] == "elderly-care"  # item 级 domain（消费方命名 source 用）
    assert item["score"] == 7.2
    assert item["published"]  # 原样透传 isoformat

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["domain"] == "elderly-care"
    assert data["items"][0]["url"] == "https://example.com/a?utm_source=x#frag"


def test_export_filters_low_score(store, tmp_path):
    raw = _make_raw(url="https://example.com/low")
    rid = store.save_raw(raw)
    store.save_scored(rid, "elderly-care", _make_scored(raw, score=3.0))

    payload, _ = export_intel_data(
        "elderly-care", days=2, min_score=5.5, output=tmp_path / "out.json"
    )
    assert payload["count"] == 0


def test_export_respects_published_window(store, tmp_path):
    old_raw = _make_raw(
        url="https://example.com/old",
        published=datetime.now() - timedelta(days=10),
    )
    rid = store.save_raw(old_raw)
    store.save_scored(rid, "elderly-care", _make_scored(old_raw, score=8.0))

    payload, _ = export_intel_data("elderly-care", days=2, output=tmp_path / "out.json")
    assert payload["count"] == 0


def test_export_parses_json_string_list_fields(store, tmp_path):
    """tags/entities 存为 JSON 字符串时应被解析为列表。"""
    raw = _make_raw(url="https://example.com/tags")
    rid = store.save_raw(raw)
    scored = _make_scored(raw, score=6.0)
    scored.tags = ["养老", "政策"]
    scored.entities = ["民政部"]
    store.save_scored(rid, "elderly-care", scored)

    payload, _ = export_intel_data("elderly-care", days=2, output=tmp_path / "out.json")
    item = payload["items"][0]
    assert item["tags"] == ["养老", "政策"]
    assert item["entities"] == ["民政部"]


def test_export_atomic_write_no_tmp_left(store, tmp_path):
    raw = _make_raw(url="https://example.com/atomic")
    rid = store.save_raw(raw)
    store.save_scored(rid, "elderly-care", _make_scored(raw, score=6.0))

    out = tmp_path / "intel-data.json"
    export_intel_data("elderly-care", days=2, output=out)
    assert out.exists()
    assert not out.with_suffix(out.suffix + ".tmp").exists()
