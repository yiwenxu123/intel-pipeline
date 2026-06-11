"""质量闸门单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from engine.filter.quality_gates import (
    apply_quality_gates,
    has_factual_anchor,
    is_digest_title,
)
from engine.models import RawItem, ScoredItem


def _item(title: str, content: str = "", score: float = 7.5) -> ScoredItem:
    return ScoredItem(
        raw=RawItem(
            source_id="s1",
            title=title,
            url="https://example.com/a",
            content=content,
            fetched_at=datetime.now(timezone.utc),
        ),
        score=score,
        category="industry",
        summary="某企业完成融资，金额未披露",
        title_display=title,
    )


def test_is_digest_title():
    assert is_digest_title("银发快讯 | A融资；B合作；C发布")
    assert is_digest_title("行业要闻汇总")
    assert not is_digest_title("三部门发布长护险经办规程")


def test_has_factual_anchor():
    assert has_factual_anchor("融资 5000 万美元")
    assert has_factual_anchor("民发〔2026〕18 号")
    assert not has_factual_anchor("内容非常丰富值得关注")


def test_digest_caps_score():
    si = _item("银发快讯 | NAVO融资；途牛数据", score=8.0)
    out = apply_quality_gates(si)
    assert out.score <= 5.0


def test_low_input_caps_score():
    si = _item("某养老企业动态", content="", score=8.0)
    si.summary = "企业发布新产品"
    out = apply_quality_gates(si)
    assert out.score <= 6.5


def test_factual_summary_keeps_score():
    si = _item("American House 转型", content="x" * 100, score=8.5)
    si.summary = "American House 承担全部利润亏损，母公司 REDICO 2008 年收购"
    out = apply_quality_gates(si)
    assert out.score == 8.5
