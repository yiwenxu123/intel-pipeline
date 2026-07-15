"""评分后质量闸门：合集降分、低输入封顶、事实锚点校验。"""

from __future__ import annotations

import re

from engine.config import settings
from engine.filter.enrichment import input_char_count, scoring_input_text
from engine.models import ScoredItem

_DIGEST_MARKERS = ("快讯", "汇总", "要闻", "简报", "一览")
_VALID_CONTENT_TYPES = frozenset(
    {"news", "policy", "report", "analysis", "research", "opinion"}
)
_FACT_PATTERN = re.compile(
    r"(\d+[\d.,]*\s*[%％万亿千百]?元?"
    r"|\d{4}年"
    r"|〔\d{4}〕\d+号"
    r"|第\d+"
    r"|民发〔|国发〔|医保|银保监|卫健委)"
)


def is_digest_title(title: str) -> bool:
    """检测标题是否为多事件合集/快讯。"""
    t = (title or "").strip()
    if not t:
        return False
    if any(m in t for m in _DIGEST_MARKERS):
        return True
    if t.count("；") >= 2 or t.count(";") >= 2:
        return True
    if "|" in t and ("；" in t or "、" in t):
        return True
    return False


def has_factual_anchor(text: str) -> bool:
    """文本是否含可核验的事实锚点（数字、政策号、机构等）。"""
    return bool(text and _FACT_PATTERN.search(text))


def normalize_content_type(value: str | None) -> str:
    v = (value or "news").strip().lower()
    return v if v in _VALID_CONTENT_TYPES else "news"


def apply_quality_gates(item: ScoredItem) -> ScoredItem:
    """对单条评分结果应用规则，必要时调低分数。"""
    score = float(item.score)
    title = item.title_display or item.raw.title
    body = scoring_input_text(item.raw)
    combined = f"{title} {body} {item.summary}"

    if is_digest_title(title) or is_digest_title(item.raw.title):
        score = min(score, 5.0)

    if input_char_count(item.raw) < settings.low_input_threshold:
        if not (has_factual_anchor(title) or has_factual_anchor(body)):
            score = min(score, settings.low_input_max_score)

    if score >= 5.5 and not has_factual_anchor(item.summary):
        if not has_factual_anchor(combined):
            score = min(score, 5.4)

    item.score = round(score, 2)
    item.content_type = normalize_content_type(item.content_type)
    return item
