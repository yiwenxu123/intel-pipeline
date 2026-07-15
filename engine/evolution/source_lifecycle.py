"""信源生命周期管理：度量追踪 → 降级检测 → 自动禁用 → 通知。

实现 AutoResearch 的"评分门控"模式：
- 每天记录信源产出指标
- 连续 N 天产出率低于阈值 → 自动降级（禁用）
- 降级事件通过飞书通知用户
- 用户可通过 CLI 一键恢复
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ruamel.yaml import YAML

from engine.config import settings
from engine.models import SourceType, SOURCE_TYPE_CONFIG
from engine.store import Store

logger = logging.getLogger(__name__)

# 门控参数（默认值，会被信源类型配置覆盖）
DEGRADATION_THRESHOLD = 0.10   # 产出率 < 10% 视为低效
DEGRADATION_WINDOW_DAYS = 7    # 连续 7 天低效则降级
MIN_FETCH_COUNT = 10           # 至少采集 10 条才计算产出率
MIN_OBSERVATION_DAYS = 3       # 新信源前 3 天不标记为无效


def record_daily_metrics(domain: str, date: str | None = None) -> list[dict]:
    """记录指定日期各信源的产出指标。在管道执行后调用。

    Args:
        date: 日期 YYYY-MM-DD。留空自动使用数据库中最新日期。
    """
    with Store() as store:
        if not date:
            row = store.conn.execute(
                "SELECT DATE(fetched_at) as d FROM raw_items ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
            date = row["d"] if row else datetime.now().strftime("%Y-%m-%d")
    with Store() as store:
        # 各信源当日采集数
        fetched = store.conn.execute(
            """SELECT source_id, COUNT(*) as cnt
               FROM raw_items WHERE DATE(fetched_at) = ?
               GROUP BY source_id""",
            (date,),
        ).fetchall()
        fetched_map = {r["source_id"]: r["cnt"] for r in fetched}

        # 各信源当日精选数
        scored = store.conn.execute(
            """SELECT r.source_id, COUNT(*) as cnt
               FROM scored_items s JOIN raw_items r ON s.raw_id = r.id
               WHERE s.domain = ? AND DATE(s.created_at) = ? AND s.score >= 5.5
               GROUP BY r.source_id""",
            (domain, date),
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
                (domain, source_id, date, fetch_cnt, select_cnt, round(yield_rate, 4)),
            )
            records.append({
                "source_id": source_id, "fetched": fetch_cnt,
                "selected": select_cnt, "yield_rate": round(yield_rate, 4),
            })
        store.conn.commit()

    logger.info(f"[{domain}] 记录 {len(records)} 个信源的日产出指标")
    return records


def detect_degradation(domain: str) -> list[dict]:
    """检测需要降级的信源：连续 N 天产出率 < 阈值。

    根据信源类型使用不同的评估标准。
    跳过已确认的信源。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DEGRADATION_WINDOW_DAYS)).strftime("%Y-%m-%d")
    degraded = []

    # 加载领域配置，获取信源类型和确认状态
    from engine.domain import load_domain
    try:
        domain_config = load_domain(domain)
        source_type_map = {s.id: s.type for s in domain_config.sources}
        # 检查已确认的信源
        confirmed_sources = set()
        for s in domain_config.sources:
            if hasattr(s, 'confirmed') and s.confirmed:
                confirmed_sources.add(s.id)
    except Exception:
        source_type_map = {}
        confirmed_sources = set()

    with Store() as store:
        # 获取所有信源在窗口期内的指标
        rows = store.conn.execute(
            """SELECT source_id,
                      COUNT(*) as days_tracked,
                      SUM(fetched) as total_fetched,
                      SUM(selected) as total_selected,
                      AVG(yield_rate) as avg_yield,
                      MIN(date) as first_date,
                      MAX(date) as last_date
               FROM source_metrics
               WHERE domain = ? AND date >= ?
               GROUP BY source_id""",
            (domain, cutoff),
        ).fetchall()

        for r in rows:
            source_id = r["source_id"]

            # 跳过已确认的信源
            if source_id in confirmed_sources:
                continue

            days_tracked = r["days_tracked"]
            total_fetched = r["total_fetched"]
            avg_yield = r["avg_yield"] or 0.0

            # 获取信源类型配置
            source_type = source_type_map.get(source_id, SourceType.GENERAL)
            type_config = SOURCE_TYPE_CONFIG.get(source_type, SOURCE_TYPE_CONFIG[SourceType.GENERAL])
            min_yield_rate = type_config["min_yield_rate"]
            observation_days_required = type_config["observation_days"]
            auto_disable = type_config["auto_disable"]

            # 计算观察期天数
            first_date = datetime.fromisoformat(r["first_date"]) if r["first_date"] else None
            last_date = datetime.fromisoformat(r["last_date"]) if r["last_date"] else None
            observation_days = (last_date - first_date).days if first_date and last_date else 0

            # 门控条件：
            # 1. 观察期足够（根据信源类型）
            # 2. 跟踪天数足够（至少 window_days - 1 天）
            # 3. 总采集量足够（避免小样本）
            # 4. 平均产出率低于阈值（根据信源类型）
            # 5. 信源类型允许自动禁用
            if (observation_days >= observation_days_required
                    and days_tracked >= DEGRADATION_WINDOW_DAYS - 1
                    and total_fetched >= MIN_FETCH_COUNT * days_tracked
                    and avg_yield < min_yield_rate
                    and auto_disable):
                degraded.append({
                    "source_id": source_id,
                    "source_type": source_type.value,
                    "days_tracked": days_tracked,
                    "total_fetched": total_fetched,
                    "total_selected": r["total_selected"] or 0,
                    "avg_yield": round(avg_yield, 4),
                    "observation_days": observation_days,
                    "min_yield_rate": min_yield_rate,
                })

    if degraded:
        logger.warning(f"[{domain}] 检测到 {len(degraded)} 个信源需要降级")
    return degraded


def _get_yaml() -> YAML:
    """获取配置好的 ruamel.yaml 实例（保留注释和格式）。"""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.allow_duplicate_keys = True
    return yaml


def _load_sources_yaml(yaml_path) -> dict | None:
    """加载 sources.yaml 文件（保留注释和格式）。返回解析后的字典，失败返回 None。"""
    if not yaml_path.exists():
        return None
    yaml = _get_yaml()
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.load(f)


def _save_sources_yaml(yaml_path, data: dict):
    """保存 sources.yaml 文件（保留注释和格式）。"""
    yaml = _get_yaml()
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def apply_degradation(domain: str, degraded: list[dict]) -> list[str]:
    """将降级信源写入 YAML 配置（enabled: false）。返回被禁用的信源 ID 列表。"""
    if not degraded:
        return []

    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    data = _load_sources_yaml(yaml_path)
    if data is None:
        logger.error(f"sources.yaml 不存在: {yaml_path}")
        return []

    disabled_ids = []
    degraded_ids = {item["source_id"] for item in degraded}

    for source in data.get("sources", []):
        source_id = source.get("id", "")
        if source_id not in degraded_ids:
            continue
        # 已有 enabled 字段则跳过（可能是用户手动设置的）
        if "enabled" in source:
            continue
        source["enabled"] = False
        source["_auto_degraded_at"] = datetime.now().strftime("%Y-%m-%d")
        disabled_ids.append(source_id)
        logger.info(f"[{domain}] 自动降级信源: {source_id}")

    if disabled_ids:
        _save_sources_yaml(yaml_path, data)

    return disabled_ids


def restore_source(domain: str, source_id: str) -> bool:
    """恢复被自动降级的信源（移除 auto-degraded 标记）。"""
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    data = _load_sources_yaml(yaml_path)
    if data is None:
        return False

    for source in data.get("sources", []):
        if source.get("id") != source_id:
            continue
        # 只恢复自动降级的信源
        if source.get("enabled") is False and "_auto_degraded_at" in source:
            del source["enabled"]
            del source["_auto_degraded_at"]
            _save_sources_yaml(yaml_path, data)
            logger.info(f"[{domain}] 恢复信源: {source_id}")
            return True
    return False


def confirm_source_status(domain: str, source_id: str) -> bool:
    """人工确认信源状态（标记为已确认，不会被自动禁用）。"""
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    data = _load_sources_yaml(yaml_path)
    if data is None:
        return False

    for source in data.get("sources", []):
        if source.get("id") != source_id:
            continue
        source["confirmed"] = True
        _save_sources_yaml(yaml_path, data)
        logger.info(f"[{domain}] 人工确认信源: {source_id}")
        return True
    return False


def manual_disable_source(domain: str, source_id: str) -> bool:
    """手动禁用信源。"""
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    data = _load_sources_yaml(yaml_path)
    if data is None:
        return False

    for source in data.get("sources", []):
        if source.get("id") != source_id:
            continue
        source["enabled"] = False
        _save_sources_yaml(yaml_path, data)
        logger.info(f"[{domain}] 手动禁用信源: {source_id}")
        return True
    return False


def manual_enable_source(domain: str, source_id: str) -> bool:
    """手动启用信源。"""
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    data = _load_sources_yaml(yaml_path)
    if data is None:
        return False

    for source in data.get("sources", []):
        if source.get("id") != source_id:
            continue
        source["enabled"] = True
        # 如果是恢复自动降级的信源，也清除标记
        source.pop("_auto_degraded_at", None)
        _save_sources_yaml(yaml_path, data)
        logger.info(f"[{domain}] 手动启用信源: {source_id}")
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
