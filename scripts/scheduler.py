"""定时调度器：按计划自动运行采集和筛选流水线。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline_job():
    """定时任务：执行完整流水线。"""
    logger.info("定时任务触发，开始执行流水线...")
    from engine.cli import cli
    import sys
    sys.argv = ["intel", "pipe"]
    try:
        cli(standalone_mode=False)
    except Exception as e:
        logger.error(f"流水线执行失败: {e}")


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
