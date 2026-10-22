"""导出精选条目为 intel-data.json（ADR-002 摄入契约）。

消费方：内容运营agent api-server 的 IntelPipelineSource
（api-server/services/workflow/IntelPipelineSource.js），经文件监听 +
cron 幂等去重后写入 signals 集合 → TopicEngine 生成选题。

schema 口径见 docs/SIGNAL_SCHEMA.md；title 保留为 title_zh 的兼容别名，
外文条目优先输出中文标题，原文标题放 title_original。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_MIN_SCORE = 5.5
DEFAULT_DAYS = 2
DEFAULT_TAKE = 200


def _parse_list_field(value) -> list:
    """tags/entities/key_points 在 SQLite 里可能是 JSON 字符串或已解析的列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _source_maps(domain_name: str) -> tuple[dict[str, str], dict[str, str]]:
    try:
        from engine.domain import load_domain

        domain = load_domain(domain_name)
        tiers = {s.id: s.tier for s in domain.sources}
        names = {s.id: s.name for s in domain.sources}
        return tiers, names
    except Exception as e:
        logger.warning("加载领域信源映射失败（%s）：%s", domain_name, e)
        return {}, {}


def export_intel_data(
    domain_name: str,
    *,
    days: int = DEFAULT_DAYS,
    min_score: float = DEFAULT_MIN_SCORE,
    take: int = DEFAULT_TAKE,
    output: Path | None = None,
    project_id: str = "",
    account_id: str = "",
) -> tuple[dict, Path]:
    """导出最近 N 天发布的高分精选条目。

    消费方按 url/title 幂等去重，重叠窗口重复导出安全（只会 skipped）。
    project_id/account_id 为空时保持旧版单项目行为；多项目场景由调用方显式传入。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    tier_map, name_map = _source_maps(domain_name)

    with Store() as store:
        rows = store.get_selected(
            domain_name,
            published_since=cutoff,
            take=take,
            min_score=min_score,
        )

    items = []
    for r in rows:
        source_id = r.get("source_id", "")
        title_zh = (r.get("title_display") or r.get("headline") or "").strip()
        title_original = (r.get("title") or "").strip()
        items.append({
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "account_id": account_id,
            "domain": domain_name,
            "title": title_zh or title_original,
            "title_zh": title_zh,
            "title_original": title_original,
            "language": r.get("lang") or "",
            "url": r.get("url", ""),
            # 最佳正文：全文提取优先，其次 RSS 摘要
            "content": r.get("full_text") or r.get("content") or r.get("summary") or "",
            "summary": r.get("summary", ""),
            "key_points": _parse_list_field(r.get("key_points")),
            "score": round(float(r.get("score") or 0.0), 2),
            "score_breakdown": None,
            "category": r.get("category", ""),
            "tags": _parse_list_field(r.get("tags")),
            "entities": _parse_list_field(r.get("entities")),
            "reason": r.get("reason", ""),
            "published": r.get("published") or "",
            "source_id": source_id,
            "source_name": name_map.get(source_id, r.get("source_display") or ""),
            "source_tier": tier_map.get(source_id, ""),
            "event_id": None,
            "content_type": r.get("content_type") or "news",
            "fact_check_status": None,
        })
    items.sort(key=lambda x: x["score"], reverse=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "domain": domain_name,
        "project_id": project_id,
        "account_id": account_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "min_score": min_score,
        "count": len(items),
        "items": items,
    }

    out_path = Path(output) if output else (settings.project_root / "data" / "intel-data.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out_path)  # 原子落盘，消费方文件监听不会读到半截 JSON
    logger.info("导出 intel-data.json：%s 条 → %s", len(items), out_path)
    return payload, out_path
