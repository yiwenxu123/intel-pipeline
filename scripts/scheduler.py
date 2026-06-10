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

    # 获取所有领域
    domains_dir = settings.project_root / "domains"
    domains = [d.name for d in domains_dir.iterdir() if d.is_dir()]

    logger.info(f"发现 {len(domains)} 个领域: {domains}")

    # 为每个领域配置定时任务
    for domain in domains:
        # 早间：采集 + 推送
        scheduler.add_job(
            run_pipeline_job,
            CronTrigger(hour=8, minute=0),
            id=f"{domain}_morning",
            name=f"{domain} 早间情报采集",
            kwargs={"domain": domain, "notify": True},
        )
        # 午间：只采集，不推送
        scheduler.add_job(
            run_pipeline_job,
            CronTrigger(hour=14, minute=0),
            id=f"{domain}_afternoon",
            name=f"{domain} 午间情报采集",
            kwargs={"domain": domain, "notify": False},
        )
        logger.info(f"  - {domain}: 早间 8:00（采集+推送）, 午间 14:00（仅采集）")

    logger.info("调度器已启动")
    logger.info(f"当前领域：{settings.domain}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("调度器已停止")


if __name__ == "__main__":
    start_scheduler()
