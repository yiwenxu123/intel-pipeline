"""导出精选条目为 intel-data.json（ADR-002 摄入契约）。

消费方：内容运营agent api-server 的 IntelPipelineSource
（api-server/services/workflow/IntelPipelineSource.js），经文件监听 +
cron 幂等去重后写入 signals 集合 → TopicEngine 生成选题。

schema 口径以 IntelPipelineSource.parseDataFile/sync() 的读取字段为准，
两侧改动需同步：{items: [{title, url, content, score, tags, domain,
published, category, entities, reason, source_id, summary}]}。
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

DEFAULT_MIN_SCORE = 5.5
DEFAULT_DAYS = 2
DEFAULT_TAKE = 200


def _parse_list_field(value) -> list:
    """tags/entities 在 SQLite 里可能是 JSON 字符串或已解析的列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def export_intel_data(
    domain_name: str,
    *,
    days: int = DEFAULT_DAYS,
    min_score: float = DEFAULT_MIN_SCORE,
    take: int = DEFAULT_TAKE,
    output: Path | None = None,
) -> tuple[dict, Path]:
    """导出最近 N 天发布的高分精选条目。

    消费方按 url/title 幂等去重，重叠窗口重复导出安全（只会 skipped）。
    返回 (payload, 输出路径)。
    """
    # published 在库中为 isoformat 文本，日期级字符串 cutoff 对任何 ISO 变体都成立
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    with Store() as store:
        rows = store.get_selected(
            domain_name,
            published_since=cutoff,
            take=take,
            min_score=min_score,
        )

    items = []
    for r in rows:
        items.append({
            "title": r.get("title") or r.get("title_display") or "",
            "url": r.get("url", ""),
            # 最佳正文：全文提取优先，其次 RSS 摘要
            "content": r.get("full_text") or r.get("content") or r.get("summary") or "",
            "summary": r.get("summary", ""),
            "score": round(float(r.get("score") or 0.0), 2),
            "category": r.get("category", ""),
            "tags": _parse_list_field(r.get("tags")),
            "entities": _parse_list_field(r.get("entities")),
            "reason": r.get("reason", ""),
            "published": r.get("published") or "",
            "source_id": r.get("source_id", ""),
            # item 级 domain：消费方以 intel-pipeline:{domain} 命名 source
            "domain": domain_name,
        })
    items.sort(key=lambda x: x["score"], reverse=True)

    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "domain": domain_name,
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
