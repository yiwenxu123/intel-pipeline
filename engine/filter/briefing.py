"""精选条目简报提炼：评分与简报分层。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.config import settings
from engine.domain import DomainConfig
from engine.filter.enrichment import enrich_items_for_scoring, scoring_input_text
from engine.filter.pipeline import _parse_json_array
from engine.filter.quality_gates import normalize_content_type
from engine.filter.llm_client import chat
from engine.models import ScoredItem

logger = logging.getLogger(__name__)

# 简报提炼并行线程数
BRIEFING_MAX_PARALLEL = 3

_DEFAULT_BRIEFING_PROMPT = """你是情报简报编辑。将入选条目改写为 JSON：
{"headline":"","lead":"","takeaway":"","facts":[],"insight_type":"fact","content_type":"news"}
lead 含具体事实；takeaway 指明对谁有用；facts 最多3条。"""


def _briefing_prompt(domain: DomainConfig) -> str:
    prompt = getattr(domain, "briefing_prompt", "") or ""
    return prompt.strip() or _DEFAULT_BRIEFING_PROMPT


def _apply_briefing_fields(item: ScoredItem, data: dict) -> ScoredItem:
    headline = (data.get("headline") or "").strip()
    lead = (data.get("lead") or "").strip()
    takeaway = (data.get("takeaway") or "").strip()
    facts = data.get("facts") or []
    if not isinstance(facts, list):
        facts = []
    facts = [str(f).strip() for f in facts if str(f).strip()][:3]

    if headline:
        item.headline = headline
        item.title_display = headline
    if lead:
        item.lead = lead
        item.summary = lead
    if takeaway:
        item.takeaway = takeaway
        item.reason = takeaway
    if facts:
        item.key_points = facts

    item.insight_type = (data.get("insight_type") or "fact").strip().lower()
    if item.insight_type not in ("fact", "opinion", "mixed"):
        item.insight_type = "fact"
    item.content_type = normalize_content_type(data.get("content_type") or item.content_type)
    return item


def _brief_one(item: ScoredItem, system: str) -> ScoredItem:
    body = scoring_input_text(item.raw)
    user_msg = (
        f"标题：{item.title_display or item.raw.title}\n"
        f"分类：{item.category}\n"
        f"评分：{item.score}\n"
        f"正文：{body}\n"
        f"链接：{item.raw.url}\n\n"
        "请输出一个 JSON 对象（headline/lead/takeaway/facts/insight_type/content_type）。"
    )
    response = chat(
        model=settings.llm_scoring_model,
        system=system,
        user=user_msg,
        temperature=0.2,
    )
    results = _parse_json_array(response)
    if results:
        return _apply_briefing_fields(item, results[0])
    logger.warning(f"简报提炼失败，保留原评分字段 [{item.raw.title[:30]}]")
    return item


def enrich_briefings(
    items: list[ScoredItem],
    domain: DomainConfig,
    store=None,
) -> list[ScoredItem]:
    """对精选条目补全文并生成简报字段。"""
    if not settings.briefing_enabled:
        return items

    selected_idx = [i for i, it in enumerate(items) if it.score >= 5.5]
    if not selected_idx:
        return items

    raw_items = [items[i].raw for i in selected_idx]
    enriched = enrich_items_for_scoring(raw_items, store=store)
    for idx, raw in zip(selected_idx, enriched):
        items[idx].raw = raw

    system = _briefing_prompt(domain)

    # 并行简报提炼
    with ThreadPoolExecutor(max_workers=BRIEFING_MAX_PARALLEL) as pool:
        futures = {pool.submit(_brief_one, items[idx], system): idx for idx in selected_idx}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                items[idx] = future.result()
            except Exception as e:
                logger.warning(f"简报提炼失败 [{items[idx].raw.title[:30]}]: {e}")

    logger.info(f"简报提炼完成：{len(selected_idx)} 条精选")
    return items
