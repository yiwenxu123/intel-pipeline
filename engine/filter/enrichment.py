"""评分前正文补全：对摘要过短的条目抓取全文。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.config import settings
from engine.models import RawItem
from engine.store import Store

logger = logging.getLogger(__name__)


def scoring_input_text(item: RawItem, max_chars: int | None = None) -> str:
    """评分/简报使用的正文（优先全文）。"""
    limit = max_chars or settings.score_input_max_chars
    text = (item.full_text or item.content or "").strip()
    return text[:limit] if text else ""


def input_char_count(item: RawItem) -> int:
    return len((item.full_text or item.content or "").strip())


def enrich_items_for_scoring(
    items: list[RawItem],
    store: Store | None = None,
    max_workers: int = 3,
) -> list[RawItem]:
    """对正文不足的条目抓取全文，供后续评分使用。"""
    if not items:
        return items

    threshold = settings.enrich_min_content_length
    need_fetch = [it for it in items if input_char_count(it) < threshold]
    if not need_fetch:
        return items

    from engine.fetcher.full_text_fetcher import fetch_and_extract

    logger.info(f"评分前正文补全：{len(need_fetch)}/{len(items)} 条需抓取全文")

    from engine.fetcher.full_text_fetcher import is_nav_boilerplate

    def _fetch_one(item: RawItem) -> RawItem:
        text = fetch_and_extract(item.url)
        if text and not is_nav_boilerplate(text):
            item.full_text = text
            if store:
                store.update_full_text(item.url, text)
        return item

    enriched: dict[str, RawItem] = {it.url: it for it in items}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, it): it.url for it in need_fetch}
        for future in as_completed(futures):
            url = futures[future]
            try:
                enriched[url] = future.result()
            except Exception as e:
                logger.debug(f"正文补全失败 [{url}]: {e}")

    success = sum(1 for it in need_fetch if input_char_count(enriched[it.url]) >= threshold)
    logger.info(f"正文补全完成：{success}/{len(need_fetch)} 条达到阈值")
    return [enriched[it.url] for it in items]
