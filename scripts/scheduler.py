"""定时调度器：按计划自动运行采集和筛选流水线。"""

from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline_job(domain: str, notify: bool = True):
    """定时任务：调用公共管道函数。"""
    from engine.domain import load_domain
    from engine.pipeline import run_full_pipeline

    # 临时切换领域
    original_domain = settings.domain
    settings.domain = domain
    try:
        domain_config = load_domain(domain)
        logger.info(f"[{domain_config.name}] 定时管道触发")
        result = run_full_pipeline(domain_config, notify=notify)

        if result.error:
            logger.error(f"[{domain_config.name}] 管道执行失败: {result.error}")
        else:
            fr = result.fetch
            flt = result.filter
            logger.info(f"[{domain_config.name}] 管道执行完毕 | "
                         f"采集 {len(fr.new_items) if fr else 0} 条 | "
                         f"筛选 {flt.scored_total if flt else 0} 条 | "
                         f"耗时 {result.duration_seconds}s")
    finally:
        settings.domain = original_domain


def start_scheduler():
    """启动调度器。"""
    scheduler = BlockingScheduler()

    # 配置 elderly-care 领域的定时任务
    # 早间：采集 + 推送
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=8, minute=0),
        id="elderly-care_morning",
        name="elderly-care 早间情报采集",
        kwargs={"domain": "elderly-care", "notify": True},
    )
    # 晚间：只采集，不推送
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=20, minute=0),
        id="elderly-care_evening",
        name="elderly-care 晚间情报采集",
        kwargs={"domain": "elderly-care", "notify": False},
    )

    logger.info("调度器已启动")
    logger.info("elderly-care: 早间 8:00（采集+推送）, 晚间 20:00（仅采集）")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("调度器已停止")


if __name__ == "__main__":
    start_scheduler()
