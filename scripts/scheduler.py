"""定时调度器：按计划自动运行采集和筛选流水线。"""

from __future__ import annotations

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline_job():
    """定时任务：直接调用管道函数（fetch → filter → report）。"""
    from engine.domain import load_domain
    from engine.fetcher.runner import fetch_all
    from engine.filter.pipeline import pre_filter, score_items
    from engine.models import RawItem
    from engine.store import Store

    domain = load_domain()
    logger.info(f"[{domain.name}] 管道执行开始")

    # ── 1. 采集 ──
    try:
        t0 = time.time()
        with Store() as store:
            result = fetch_all(domain, store)
        logger.info(f"[{domain.name}] 采集完成: 新增 {len(result.new_items)} 条, "
                     f"信源 {result.sources_success}/{result.sources_total}, "
                     f"耗时 {result.duration_seconds}s")
        if result.errors:
            for err in result.errors:
                logger.warning(f"[{domain.name}] 信源 {err.source_id} 采集失败: {err.error}")
    except Exception as e:
        logger.error(f"[{domain.name}] 采集阶段失败: {e}")
        return

    # ── 2. 筛选 ──
    try:
        from datetime import datetime, timedelta, timezone
        t0 = time.time()
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
                duration = time.time() - t0
                logger.info(f"[{domain.name}] 筛选完成: {len(scored)}/{len(items)} 条, 耗时 {duration:.1f}s")
            else:
                logger.info(f"[{domain.name}] 无待筛选条目")
    except Exception as e:
        logger.error(f"[{domain.name}] 筛选阶段失败: {e}")
        return

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
                    from engine.models import ScoredItem
                    items.append(ScoredItem(
                        raw=raw, score=r["score"], category=r.get("category", ""),
                        summary=r.get("summary", ""), reason=r.get("reason", ""),
                    ))
                stats = store.get_stats(domain.name)
                report = generate_report(items, domain, total_fetched=stats.get("total_fetched", 0))
                md_path, json_path = save_report(report)
                logger.info(f"[{domain.name}] 日报已生成: {md_path}")
            else:
                logger.info(f"[{domain.name}] 无精选条目，跳过日报")
    except Exception as e:
        logger.error(f"[{domain.name}] 日报阶段失败: {e}")

    # ── 4. 推送通知 ──
    try:
        from engine.output.notifier import notify_report
        if settings.notify_webhook:
            with Store() as store:
                selected = store.get_selected(domain.name, take=5, min_score=6.0)
                stats = store.get_stats(domain.name)
            notify_report(domain.name, stats, selected)
            logger.info(f"[{domain.name}] 推送通知已发送")
    except Exception as e:
        logger.error(f"[{domain.name}] 推送通知失败: {e}")

    logger.info(f"[{domain.name}] 管道执行完毕")


def start_scheduler():
    """启动调度器。"""
    scheduler = BlockingScheduler()

    # 每天 8:00 和 14:00 执行完整流水线
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=8, minute=0),
        id="morning_pipeline",
        name="早间情报采集",
    )
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=14, minute=0),
        id="afternoon_pipeline",
        name="午间情报采集",
    )

    logger.info("调度器已启动，将在每天 8:00 和 14:00 执行流水线")
    logger.info(f"当前领域：{settings.domain}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("调度器已停止")


if __name__ == "__main__":
    start_scheduler()
