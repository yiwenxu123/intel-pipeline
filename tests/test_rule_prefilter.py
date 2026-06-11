"""规则预筛单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from engine.filter.rule_prefilter import reject_reason, rule_prefilter_items
from engine.models import RawItem


def _raw(title: str, content: str = "") -> RawItem:
    return RawItem(
        source_id="s1",
        title=title,
        url="https://example.com/x",
        content=content,
        fetched_at=datetime.now(timezone.utc),
    )


def test_reject_digest():
    assert reject_reason(_raw("银发快讯 | A融资；B合作；C发布")) == "合集/快讯"


def test_reject_off_topic():
    assert "离题" in (reject_reason(_raw("二战时英军为何执意摧毁法国舰队")) or "")


def test_reject_thin_without_anchor():
    assert reject_reason(_raw("某养老企业动态", "")) == "正文过短且无标题事实锚点"


def test_pass_with_title_anchor():
    assert reject_reason(_raw("蚂蚁美团领投5000万美元外骨骼项目", "")) is None


def test_rule_prefilter_writes_rejected_scored():
    items = [
        _raw("银发快讯 | 多条动态"),
        _raw("长护险2028年全覆盖政策发布", "正文" * 50),
    ]
    passed, rejected = rule_prefilter_items(items)
    assert len(passed) == 1
    assert len(rejected) == 1
    assert rejected[0].score == 0.0
    assert rejected[0].category == "rejected"
    assert "规则过滤" in rejected[0].reason
