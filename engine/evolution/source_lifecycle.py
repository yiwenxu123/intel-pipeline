"""信源生命周期管理：度量追踪 → 降级检测 → 自动禁用 → 通知。

实现 AutoResearch 的"评分门控"模式：
- 每天记录信源产出指标
- 连续 N 天产出率低于阈值 → 自动降级（禁用）
- 降级事件通过飞书通知用户
- 用户可通过 CLI 一键恢复
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)

# 门控参数
DEGRADATION_THRESHOLD = 0.05   # 产出率 < 5% 视为低效
DEGRADATION_WINDOW_DAYS = 7    # 连续 7 天低效则降级
MIN_FETCH_COUNT = 5            # 至少采集 5 条才计算产出率（避免小样本误判）


def record_daily_metrics(domain: str) -> list[dict]:
    """记录当天各信源的产出指标。在管道执行后调用。"""
    today = datetime.now().strftime("%Y-%m-%d")
    with Store() as store:
        # 各信源今日采集数
        fetched = store.conn.execute(
            """SELECT source_id, COUNT(*) as cnt
               FROM raw_items WHERE DATE(fetched_at) = ?
               GROUP BY source_id""",
            (today,),
        ).fetchall()
        fetched_map = {r["source_id"]: r["cnt"] for r in fetched}

        # 各信源今日精选数
        scored = store.conn.execute(
            """SELECT r.source_id, COUNT(*) as cnt
               FROM scored_items s JOIN raw_items r ON s.raw_id = r.id
               WHERE s.domain = ? AND DATE(s.created_at) = ? AND s.score >= 6.0
               GROUP BY r.source_id""",
            (domain, today),
        ).fetchall()
        scored_map = {r["source_id"]: r["cnt"] for r in scored}

        # 写入 source_metrics 表
        records = []
        for source_id, fetch_cnt in fetched_map.items():
            select_cnt = scored_map.get(source_id, 0)
            yield_rate = select_cnt / fetch_cnt if fetch_cnt > 0 else 0.0
            store.conn.execute(
                """INSERT OR REPLACE INTO source_metrics
                   (domain, source_id, date, fetched, selected, yield_rate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (domain, source_id, today, fetch_cnt, select_cnt, round(yield_rate, 4)),
            )
            records.append({
                "source_id": source_id, "fetched": fetch_cnt,
                "selected": select_cnt, "yield_rate": round(yield_rate, 4),
            })
        store.conn.commit()

    logger.info(f"[{domain}] 记录 {len(records)} 个信源的日产出指标")
    return records


def detect_degradation(domain: str) -> list[dict]:
    """检测需要降级的信源：连续 N 天产出率 < 阈值。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DEGRADATION_WINDOW_DAYS)).isoformat()
    degraded = []

    with Store() as store:
        # 获取所有信源在窗口期内的指标
        rows = store.conn.execute(
            """SELECT source_id,
                      COUNT(*) as days_tracked,
                      SUM(fetched) as total_fetched,
                      SUM(selected) as total_selected,
                      AVG(yield_rate) as avg_yield
               FROM source_metrics
               WHERE domain = ? AND date >= ?
               GROUP BY source_id""",
            (domain, cutoff),
        ).fetchall()

        for r in rows:
            source_id = r["source_id"]
            days_tracked = r["days_tracked"]
            total_fetched = r["total_fetched"]
            avg_yield = r["avg_yield"] or 0.0

            # 门控条件：
            # 1. 跟踪天数足够（至少 window_days - 1 天）
            # 2. 总采集量足够（避免小样本）
            # 3. 平均产出率低于阈值
            if (days_tracked >= DEGRADATION_WINDOW_DAYS - 1
                    and total_fetched >= MIN_FETCH_COUNT * days_tracked
                    and avg_yield < DEGRADATION_THRESHOLD):
                degraded.append({
                    "source_id": source_id,
                    "days_tracked": days_tracked,
                    "total_fetched": total_fetched,
                    "total_selected": r["total_selected"] or 0,
                    "avg_yield": round(avg_yield, 4),
                })

    if degraded:
        logger.warning(f"[{domain}] 检测到 {len(degraded)} 个信源需要降级")
    return degraded


def apply_degradation(domain: str, degraded: list[dict]) -> list[str]:
    """将降级信源写入 YAML 配置（enabled: false）。返回被禁用的信源 ID 列表。"""
    if not degraded:
        return []

    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    if not yaml_path.exists():
        logger.error(f"sources.yaml 不存在: {yaml_path}")
        return []

    content = yaml_path.read_text(encoding="utf-8")
    disabled_ids = []

    for item in degraded:
        source_id = item["source_id"]
        # 在 YAML 中查找该信源并添加/修改 enabled: false
        # 匹配模式：找到 "- id: xxx" 块，在其中添加 enabled: false
        pattern = rf'(- id: {re.escape(source_id)}\n)((?:\s+\w+:.*\n)*)'
        match = re.search(pattern, content)
        if not match:
            continue

        block = match.group(0)
        # 检查是否已有 enabled 字段
        if "enabled:" in block:
            # 已经有 enabled 字段，跳过（可能是用户手动禁用的）
            continue

        # 在 id 行之后插入 enabled: false
        new_block = match.group(1) + f"    enabled: false  # auto-degraded on {datetime.now().strftime('%Y-%m-%d')}\n" + match.group(2)
        content = content.replace(block, new_block)
        disabled_ids.append(source_id)
        logger.info(f"[{domain}] 自动降级信源: {source_id} (连续 {item['days_tracked']} 天产出率 {item['avg_yield']*100:.1f}%)")

    if disabled_ids:
        yaml_path.write_text(content, encoding="utf-8")

    return disabled_ids


def restore_source(domain: str, source_id: str) -> bool:
    """恢复被自动降级的信源（移除 auto-degraded 标记）。"""
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    if not yaml_path.exists():
        return False

    content = yaml_path.read_text(encoding="utf-8")
    # 移除 auto-degraded 的 enabled: false 行
    pattern = rf'\n\s*enabled:\s*false\s*# auto-degraded.*\n'
    # 只在对应 source_id 块中替换
    source_pattern = rf'(- id: {re.escape(source_id)}\n)((?:\s+\w+:.*\n)*)'
    match = re.search(source_pattern, content)
    if not match:
        return False

    block = match.group(0)
    new_block = re.sub(pattern, '\n', block)
    if new_block != block:
        content = content.replace(block, new_block)
        yaml_path.write_text(content, encoding="utf-8")
        logger.info(f"[{domain}] 恢复信源: {source_id}")
        return True
    return False


def run_lifecycle_check(domain: str) -> dict:
    """完整的生命周期检查：记录指标 → 检测降级 → 执行降级。

    在每次管道执行后调用。
    返回 {"metrics": [...], "degraded": [...], "disabled": [...]}。
    """
    result = {"metrics": [], "degraded": [], "disabled": []}

    # 1. 记录今日指标
    result["metrics"] = record_daily_metrics(domain)

    # 2. 检测需要降级的信源
    result["degraded"] = detect_degradation(domain)

    # 3. 执行降级
    if result["degraded"]:
        result["disabled"] = apply_degradation(domain, result["degraded"])
        if result["disabled"]:
            # 4. 通知
            _notify_degradation(domain, result["degraded"], result["disabled"])

    return result


def _notify_degradation(domain: str, degraded: list[dict], disabled: list[str]):
    """通过飞书通知降级事件。"""
    if not settings.notify_webhook:
        return

    try:
        from engine.output.notifier import send_webhook, DOMAIN_NAMES
        display_name = DOMAIN_NAMES.get(domain, domain)
        date = datetime.now().strftime("%Y-%m-%d")

        title = f"⚠️ {display_name}信源降级通知 | {date}"
        lines = [
            f"以下 **{len(disabled)}** 个信源连续 {DEGRADATION_WINDOW_DAYS} 天产出率低于 {DEGRADATION_THRESHOLD*100:.0f}%，已自动禁用：",
            "",
        ]
        for item in degraded:
            if item["source_id"] in disabled:
                rate = f"{item['avg_yield']*100:.1f}%"
                lines.append(f"- **{item['source_id']}**：采集 {item['total_fetched']} 条，精选 {item['total_selected']} 条（{rate}）")

        lines.append("")
        lines.append(f"恢复命令：`python -m engine.cli -d {domain} evolve restore <source_id>`")

        send_webhook(settings.notify_webhook, title, "\n".join(lines))
    except Exception as e:
        logger.error(f"降级通知失败: {e}")


def get_lifecycle_status(domain: str) -> list[dict]:
    """获取所有信源的生命周期状态。"""
    with Store() as store:
        rows = store.conn.execute(
            """SELECT source_id,
                      COUNT(*) as days_tracked,
                      SUM(fetched) as total_fetched,
                      SUM(selected) as total_selected,
                      AVG(yield_rate) as avg_yield,
                      MAX(date) as last_date
               FROM source_metrics
               WHERE domain = ?
               GROUP BY source_id
               ORDER BY avg_yield DESC""",
            (domain,),
        ).fetchall()

        result = []
        for r in rows:
            avg_yield = r["avg_yield"] or 0.0
            if avg_yield >= 0.20:
                status = "excellent"
            elif avg_yield >= 0.10:
                status = "healthy"
            elif avg_yield >= DEGRADATION_THRESHOLD:
                status = "low"
            else:
                status = "critical"
            result.append({
                "source_id": r["source_id"],
                "days_tracked": r["days_tracked"],
                "total_fetched": r["total_fetched"],
                "total_selected": r["total_selected"],
                "avg_yield": round(avg_yield, 4),
                "last_date": r["last_date"],
                "status": status,
            })
    return result
