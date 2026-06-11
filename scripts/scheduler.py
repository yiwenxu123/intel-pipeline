"""定时调度器：按计划自动运行采集和筛选流水线。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 领域定时任务配置：(hour, minute, notify)
DOMAIN_SCHEDULES: dict[str, list[tuple[int, int, bool, str]]] = {
    "elderly-care": [
        (8, 0, True, "morning"),
        (20, 0, False, "evening"),
    ],
    "china-africa": [
        (8, 30, True, "morning"),
        (14, 0, False, "afternoon"),
    ],
}


def run_pipeline_job(domain: str, notify: bool = True, max_items: int = 50):
    """定时任务：调用公共管道函数。"""
    if settings.is_domain_paused(domain):
        logger.info(f"[{domain}] 领域已暂停（INTEL_PAUSED_DOMAINS），跳过定时管道")
        return

    from engine.domain import load_domain
    from engine.pipeline import run_full_pipeline

    original_domain = settings.domain
    settings.domain = domain
    try:
        domain_config = load_domain(domain)
        logger.info(f"[{domain_config.name}] 定时管道触发")
        result = run_full_pipeline(domain_config, notify=notify, max_items=max_items)

        if result.error:
            logger.error(f"[{domain_config.name}] 管道执行失败: {result.error}")
        else:
            fr = result.fetch
            flt = result.filter
            logger.info(
                f"[{domain_config.name}] 管道执行完毕 | "
                f"采集 {len(fr.new_items) if fr else 0} 条 | "
                f"筛选 {flt.scored_total if flt else 0} 条 | "
                f"耗时 {result.duration_seconds}s"
            )
    finally:
        settings.domain = original_domain


def run_weekly_report_job(domain: str = "elderly-care"):
    """每周运营周报。"""
    if settings.is_domain_paused(domain):
        return
    from engine.ops.weekly_report import notify_weekly_report, save_weekly_report

    path, _ = save_weekly_report(domain)
    logger.info(f"[{domain}] 运营周报已生成: {path}")
    if settings.notify_webhook:
        notify_weekly_report(domain)


def start_scheduler():
    """启动调度器。"""
    scheduler = BlockingScheduler()
    paused = settings.get_paused_domains()

    if paused:
        logger.info(f"已暂停领域（不注册定时任务）: {', '.join(sorted(paused))}")

    for domain, jobs in DOMAIN_SCHEDULES.items():
        if domain in paused:
            continue
        for hour, minute, notify, suffix in jobs:
            scheduler.add_job(
                run_pipeline_job,
                CronTrigger(hour=hour, minute=minute),
                id=f"{domain}_{suffix}",
                name=f"{domain} 定时管道 ({suffix})",
                kwargs={"domain": domain, "notify": notify},
            )
        times = ", ".join(f"{h:02d}:{m:02d}" for h, m, _, _ in jobs)
        logger.info(f"{domain}: 已注册 {len(jobs)} 个任务 ({times})")

    if "elderly-care" not in paused:
        scheduler.add_job(
            run_weekly_report_job,
            CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="elderly-care_weekly_report",
            name="elderly-care 周一运营周报",
            kwargs={"domain": "elderly-care"},
        )
        logger.info("elderly-care: 周一 09:00 运营周报")

    logger.info("调度器已启动")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("调度器已停止")


if __name__ == "__main__":
    start_scheduler()
