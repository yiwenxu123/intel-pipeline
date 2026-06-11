"""筛选编排：正文补全 → 规则预筛 → 评分 → 质量闸门 → 简报提炼。"""

from __future__ import annotations

import logging

from engine.config import settings
from engine.domain import DomainConfig
from engine.filter.briefing import enrich_briefings
from engine.filter.enrichment import enrich_items_for_scoring
from engine.filter.pipeline import get_score_stats, score_items
from engine.filter.quality_gates import apply_quality_gates
from engine.filter.rule_prefilter import rule_prefilter_items
from engine.models import FilterResult, RawItem, ScoredItem
from engine.store import Store

logger = logging.getLogger(__name__)


def filter_and_score(
    items: list[RawItem],
    domain: DomainConfig,
    store: Store,
    *,
    enable_rule_prefilter: bool | None = None,
) -> tuple[list[ScoredItem], FilterResult]:
    """完整筛选流水线，返回评分结果与统计。"""
    if not items:
        return [], FilterResult(scored_items=[])

    items = enrich_items_for_scoring(items, store)

    rule_rejected: list[ScoredItem] = []
    to_score = items
    use_rules = (
        settings.rule_prefilter_enabled
        if enable_rule_prefilter is None
        else enable_rule_prefilter
    )
    if use_rules:
        to_score, rule_rejected = rule_prefilter_items(items)

    scored = score_items(to_score, domain) if to_score else []
    scored = [apply_quality_gates(si) for si in scored]
    scored = enrich_briefings(scored, domain, store=store)

    all_scored = rule_rejected + scored
    score_stats = get_score_stats()
    result = FilterResult(
        scored_items=all_scored,
        pre_filter_total=len(items),
        pre_filter_passed=len(to_score),
        pre_filter_skipped=len(rule_rejected),
        scored_total=len(all_scored),
        json_parse_failures=score_stats.get("json_parse_failures", 0),
        retry_success=score_stats.get("retry_success", 0),
    )
    return all_scored, result
