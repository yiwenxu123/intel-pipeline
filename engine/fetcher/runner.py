"""采集调度器：遍历信源 → 关键词过滤 → 日期验证 → 去重入库（无时间过滤）。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.domain import DomainConfig
from engine.fetcher.date_verifier import verify_dates_batch
from engine.fetcher.rss_fetcher import fetch_rss
from engine.fetcher.web_fetcher import fetch_web
from engine.fetcher.ageclub_fetcher import fetch_ageclub
from engine.fetcher.searxng_fetcher import fetch_searxng
from engine.models import RawItem, SourceDef, SourceKind, FetchError, FetchResult
from engine.store import Store

logger = logging.getLogger(__name__)


def _match_keywords(item: RawItem, keywords: list[str]) -> bool:
    """检查条目标题或内容是否匹配任一关键词。"""
    text = f"{item.title} {item.content}".lower()
    return any(kw.lower() in text for kw in keywords)


def fetch_all(domain: DomainConfig, store: Store, max_workers: int = 4) -> FetchResult:
    """完整采集流水线：采集 → 关键词过滤 → 日期验证 → 去重入库。

    注意：不做时间过滤，所有条目入库。时间过滤在展示层处理。
    """
    import time
    start_time = time.time()

    keywords = domain.keywords
    fetch_errors: list[FetchError] = []

    def _fetch_one(source: SourceDef) -> tuple[list[RawItem], int]:
        """采集单个信源，返回 (条目列表, 关键词过滤数)。"""
        try:
            if source.kind == SourceKind.RSS:
                items = fetch_rss(source)
            elif source.kind == SourceKind.WEB:
                items = fetch_web(source)
            elif source.kind == SourceKind.SEARXNG:
                items = fetch_searxng(source)
            elif source.kind == SourceKind.AGECLUB:
                items = fetch_ageclub(source)
            else:
                return [], 0

            # 关键词过滤
            kw_filtered = 0
            if source.keywords_filter and keywords:
                before = len(items)
                items = [i for i in items if _match_keywords(i, keywords)]
                kw_filtered = before - len(items)
                if kw_filtered > 0:
                    logger.info(f"关键词过滤 [{source.id}]: {before} → {len(items)} 条（过滤 {kw_filtered} 条）")
            return items, kw_filtered
        except Exception as e:
            logger.error(f"信源 [{source.id}] 处理异常: {e}")
            etype = type(e).__name__.lower()
            error_type = "timeout" if "timeout" in etype else \
                         "http_error" if "http" in etype else \
                         "parse_error" if "parse" in etype else "unknown"
            fetch_errors.append(FetchError(source_id=source.id, error=str(e), error_type=error_type))
            return [], 0

    # ── 采集所有信源（主线程汇总，避免数据竞争） ──
    all_raw: list[RawItem] = []
    keywords_filter_count = 0
    enabled_sources = [s for s in domain.sources if s.enabled]
    logger.info(f"开始采集领域 [{domain.name}]，共 {len(enabled_sources)} 个信源")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, src): src for src in enabled_sources}
        for future in as_completed(futures):
            items, kw_count = future.result()
            all_raw.extend(items)
            keywords_filter_count += kw_count

    if keywords_filter_count > 0:
        logger.info(f"关键词过滤总计丢弃 {keywords_filter_count} 条无关条目")
    logger.info(f"采集完成：共 {len(all_raw)} 条（去重前）")

    # ── 日期验证（仅对无日期条目） ──
    verified_dates = verify_dates_batch(all_raw, max_fetches=30)
    if verified_dates:
        for item in all_raw:
            if item.published is None and item.url in verified_dates:
                item.published = verified_dates[item.url]
                logger.info(f"日期验证补全 [{item.source_id}] {item.published.date()} {item.title[:30]}")

    # ── 去重入库（无时间过滤） ──
    new_items: list[RawItem] = []
    for item in all_raw:
        if store.exists(item.url):
            continue
        store.save_raw(item)
        new_items.append(item)

    duration = time.time() - start_time
    sources_success = len(enabled_sources) - len(fetch_errors)
    logger.info(f"入库完成：新增 {len(new_items)} 条（去重后），耗时 {duration:.1f}s")

    return FetchResult(
        new_items=new_items,
        errors=fetch_errors,
        duration_seconds=round(duration, 2),
        sources_total=len(enabled_sources),
        sources_success=sources_success,
    )
