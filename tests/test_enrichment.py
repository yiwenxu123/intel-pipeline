"""正文补全模块测试。"""

from __future__ import annotations

from unittest.mock import patch

from engine.filter.enrichment import enrich_items_for_scoring, input_char_count, scoring_input_text
from engine.models import RawItem


def test_scoring_input_text_prefers_full_text():
    item = RawItem(
        source_id="s", title="t", url="https://x.com",
        content="短摘要", full_text="完整正文" * 50,
    )
    text = scoring_input_text(item, max_chars=100)
    assert text.startswith("完整正文")
    assert "短摘要" not in text


@patch("engine.fetcher.full_text_fetcher.fetch_and_extract")
def test_enrich_fetches_thin_content(mock_fetch):
    mock_fetch.return_value = "抓取到的正文。" * 40
    item = RawItem(source_id="s", title="t", url="https://x.com", content="短")
    out = enrich_items_for_scoring([item], store=None)
    assert out[0].full_text
    assert input_char_count(out[0]) > len("短")
    mock_fetch.assert_called_once()
