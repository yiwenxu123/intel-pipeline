"""定时调度器：按计划自动运行采集和筛选流水线。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline_job(notify: bool = True):
    """定时任务：调用公共管道函数。"""
    from engine.domain import load_domain
    from engine.pipeline import run_full_pipeline

    domain = load_domain()
    logger.info(f"[{domain.name}] 定时管道触发")
    result = run_full_pipeline(domain, notify=notify)

    if result.error:
        logger.error(f"[{domain.name}] 管道执行失败: {result.error}")
    else:
        fr = result.fetch
        flt = result.filter
        logger.info(f"[{domain.name}] 管道执行完毕 | "
                     f"采集 {len(fr.new_items) if fr else 0} 条 | "
                     f"筛选 {flt.scored_total if flt else 0} 条 | "
                     f"耗时 {result.duration_seconds}s")


def start_scheduler():
    """启动调度器。"""
    scheduler = BlockingScheduler()

    # 早间：采集 + 推送
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=8, minute=0),
        id="morning_pipeline",
        name="早间情报采集",
        kwargs={"notify": True},
    )
    # 午间：只采集，不推送
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=14, minute=0),
        id="afternoon_pipeline",
        name="午间情报采集",
        kwargs={"notify": False},
    )

    logger.info("调度器已启动，将在每天 8:00 和 14:00 执行流水线")
    logger.info(f"当前领域：{settings.domain}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("调度器已停止")


if __name__ == "__main__":
    start_scheduler()
