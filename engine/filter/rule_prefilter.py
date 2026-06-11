"""规则预筛：零成本去噪，被拒条目以 score=0 入库，避免积压重复捞取。"""

from __future__ import annotations

import logging

from engine.config import settings
from engine.filter.enrichment import input_char_count
from engine.filter.quality_gates import has_factual_anchor, is_digest_title
from engine.models import RawItem, ScoredItem

logger = logging.getLogger(__name__)

# 标题明显离题关键词（泛娱乐/体育/非银发）
_OFF_TOPIC_TITLE_KEYWORDS = (
    "足球", "篮球", "NBA", "欧冠", "世界杯", "奥运会",
    "娱乐八卦", "明星离婚", "追剧", "综艺", "票房",
    "手游", "网游", "电竞", "王者荣耀", "原神",
    "二战", "英军", "德军", "日军",
)


def reject_reason(item: RawItem) -> str | None:
    """返回拒绝原因；None 表示通过。"""
    title = (item.title or "").strip()
    if not title:
        return "标题为空"

    if is_digest_title(title):
        return "合集/快讯"

    for kw in _OFF_TOPIC_TITLE_KEYWORDS:
        if kw in title:
            return f"离题关键词「{kw}」"

    if input_char_count(item) < settings.low_input_threshold:
        if not has_factual_anchor(title):
            return "正文过短且无标题事实锚点"

    return None


def _to_rejected_scored(item: RawItem, reason: str) -> ScoredItem:
    return ScoredItem(
        raw=item,
        score=0.0,
        category="rejected",
        summary=(item.title or "")[:120],
        reason=f"规则过滤：{reason}",
    )


def rule_prefilter_items(
    items: list[RawItem],
) -> tuple[list[RawItem], list[ScoredItem]]:
    """规则预筛：返回 (待评分条目, 已拒绝条目)。"""
    passed: list[RawItem] = []
    rejected: list[ScoredItem] = []

    for item in items:
        reason = reject_reason(item)
        if reason:
            rejected.append(_to_rejected_scored(item, reason))
        else:
            passed.append(item)

    if rejected:
        logger.info(f"规则预筛：过滤 {len(rejected)}/{len(items)} 条，{len(passed)} 条进入评分")
    return passed, rejected
