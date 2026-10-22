"""数据新鲜度检查：采集是否在预期窗口内、最近 pipe 是否失败。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def check_freshness(domain: str, max_age_hours: int = 8, now: datetime | None = None) -> dict:
    """返回新鲜度检查结果；healthy=False 表示需要告警。"""
    now = now or datetime.now()
    with Store() as store:
        stats = store.get_stats(domain)
        last_pipe = store.get_last_pipe_run(domain)

    last_fetch_raw = stats.get("last_fetch_time")
    last_fetch = _parse_dt(last_fetch_raw)
    age_hours = None
    if last_fetch is not None:
        age_hours = round((now - last_fetch).total_seconds() / 3600, 1)

    fetch_errors = int(stats.get("last_fetch_errors") or 0)
    pipe_error = (last_pipe or {}).get("error") if last_pipe else None
    problems: list[str] = []

    if last_fetch is None:
        problems.append("没有采集记录")
    elif age_hours is not None and age_hours > max_age_hours:
        problems.append(f"最近采集已 {age_hours}h（阈值 {max_age_hours}h）")
    if pipe_error:
        problems.append(f"最近 pipe 失败：{pipe_error}")
    if fetch_errors >= 3:
        problems.append(f"最近一次采集失败 {fetch_errors} 个信源")

    return {
        "domain": domain,
        "healthy": not problems,
        "last_fetch_time": last_fetch_raw,
        "age_hours": age_hours,
        "max_age_hours": max_age_hours,
        "last_pipe_at": stats.get("last_pipe_at"),
        "pipe_error": pipe_error,
        "fetch_errors": fetch_errors,
        "problems": problems,
    }


def run_freshness_check(domain: str, max_age_hours: int = 8, notify: bool = False) -> dict:
    """检查并按天去重发送告警。返回检查结果。"""
    result = check_freshness(domain, max_age_hours=max_age_hours)
    if result["healthy"]:
        logger.info("[%s] 数据新鲜度正常：最近采集 %s", domain, result["last_fetch_time"])
        return result

    logger.warning("[%s] 数据新鲜度异常：%s", domain, "；".join(result["problems"]))
    if not notify:
        return result

    state_path = settings.project_root / "data" / "freshness_state.json"
    today = datetime.now().strftime("%Y-%m-%d")
    state: dict = {}
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state = {}

    if state.get("last_alert_date") == today:
        logger.info("[%s] 今日已告警过，跳过重复发送", domain)
        return result

    from engine.output.notifier import notify_freshness

    if notify_freshness(domain, result):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"last_alert_date": today, "domain": domain, "problems": result["problems"]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return result
