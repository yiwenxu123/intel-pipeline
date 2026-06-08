"""完整情报管道：fetch → filter → report → notify。

CLI 和 scheduler 共同调用此模块，避免代码重复。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from engine.config import settings
from engine.domain import DomainConfig
from engine.fetcher.runner import fetch_all
from engine.filter.pipeline import pre_filter, score_items
from engine.models import RawItem, ScoredItem, FetchResult, FilterResult
from engine.store import Store

logger = logging.getLogger(__name__)


class PipelineResult:
    """管道执行结果。"""

    def __init__(self):
        self.fetch: FetchResult | None = None
        self.filter: FilterResult | None = None
        self.report_path: str | None = None
        self.notified: bool = False
        self.error: str | None = None
        self.duration_seconds: float = 0.0


def run_full_pipeline(domain: DomainConfig) -> PipelineResult:
    """执行完整管道：采集 → 筛选 → 日报 → 推送。"""
    result = PipelineResult()
    start = time.time()

    # ── 1. 采集 ──
    try:
        with Store() as store:
            result.fetch = fetch_all(domain, store)
        fr = result.fetch
        logger.info(f"[{domain.name}] 采集完成: 新增 {len(fr.new_items)} 条, "
                     f"信源 {fr.sources_success}/{fr.sources_total}, 耗时 {fr.duration_seconds}s")
        for err in fr.errors:
            logger.warning(f"[{domain.name}] 信源 {err.source_id} 采集失败: {err.error}")
    except Exception as e:
        logger.error(f"[{domain.name}] 采集阶段失败: {e}")
        result.error = f"采集失败: {e}"
        result.duration_seconds = time.time() - start
        return result

    # ── 2. 筛选 ──
    try:
        with Store() as store:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.score_window_days)).isoformat()
            rows = store.conn.execute(
                """SELECT r.* FROM raw_items r
                   WHERE r.published >= ?
                   AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)
                   ORDER BY r.published DESC""",
                (cutoff, domain.name),
            ).fetchall()

            if rows:
                items = [
                    RawItem(source_id=r["source_id"], title=r["title"], url=r["url"],
                            content=r["content"] or "", lang=r["lang"] or "zh")
                    for r in rows
                ]
                filtered = pre_filter(items, domain)
                scored = score_items(filtered, domain)
                for si in scored:
                    raw_id = store.save_raw(si.raw)
                    store.save_scored(raw_id, domain.name, si)
                result.filter = FilterResult(
                    scored_items=scored, pre_filter_total=len(items),
                    pre_filter_passed=len(filtered), scored_total=len(scored),
                )
                logger.info(f"[{domain.name}] 筛选完成: {len(scored)}/{len(items)} 条")
            else:
                logger.info(f"[{domain.name}] 无待筛选条目")
    except Exception as e:
        logger.error(f"[{domain.name}] 筛选阶段失败: {e}")
        result.error = f"筛选失败: {e}"
        result.duration_seconds = time.time() - start
        return result

    # ── 3. 日报 ──
    try:
        from engine.output.report import generate_report, save_report
        with Store() as store:
            rows = store.get_selected(domain.name, take=100, min_score=6.0)
            if rows:
                items = []
                for r in rows:
                    raw = RawItem(source_id=r["source_id"], title=r["title"],
                                  url=r["url"], content=r.get("content", ""))
                    items.append(ScoredItem(
                        raw=raw, score=r["score"], category=r.get("category", ""),
                        summary=r.get("summary", ""), reason=r.get("reason", ""),
                    ))
                stats = store.get_stats(domain.name)
                report = generate_report(items, domain, total_fetched=stats.get("total_fetched", 0))
                md_path, json_path = save_report(report)
                result.report_path = str(md_path)
                logger.info(f"[{domain.name}] 日报已生成: {md_path}")
            else:
                logger.info(f"[{domain.name}] 无精选条目，跳过日报")
    except Exception as e:
        logger.error(f"[{domain.name}] 日报阶段失败: {e}")

    # ── 4. 推送通知 ──
    try:
        if settings.notify_webhook:
            from engine.output.notifier import notify_report
            with Store() as store:
                selected = store.get_selected(domain.name, take=5, min_score=6.0)
                stats = store.get_stats(domain.name)
            notify_report(domain.name, stats, selected)
            result.notified = True
            logger.info(f"[{domain.name}] 推送通知已发送")
    except Exception as e:
        logger.error(f"[{domain.name}] 推送通知失败: {e}")

    result.duration_seconds = round(time.time() - start, 2)
    return result
