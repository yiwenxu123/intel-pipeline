"""历史精选条目简报字段补全。"""

from __future__ import annotations

import json
import logging

from engine.domain import DomainConfig
from engine.filter.briefing import enrich_briefings
from engine.models import RawItem, ScoredItem
from engine.store import Store

logger = logging.getLogger(__name__)


def _row_to_scored(row) -> ScoredItem:
    kp = row["key_points"]
    if isinstance(kp, str):
        try:
            kp = json.loads(kp)
        except json.JSONDecodeError:
            kp = []
    tags = row["tags"]
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = []
    entities = row["entities"]
    if isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except json.JSONDecodeError:
            entities = []

    published = row["published"]
    raw = RawItem(
        source_id=row["source_id"],
        title=row["title"],
        url=row["url"],
        content=row["content"] or "",
        full_text=row["full_text"],
        lang=row["lang"] or "zh",
        published=published,
    )
    return ScoredItem(
        raw=raw,
        score=row["score"],
        category=row["category"] or "",
        tags=tags if isinstance(tags, list) else [],
        summary=row["summary"] or "",
        key_points=kp if isinstance(kp, list) else [],
        reason=row["reason"] or "",
        entities=entities if isinstance(entities, list) else [],
        source_display=row["source_display"] or "",
        title_display=row["title_display"] or "",
        content_type=row["content_type"] or "news",
        headline=row["headline"] or "",
        lead=row["lead"] or "",
        takeaway=row["takeaway"] or "",
        insight_type=row["insight_type"] or "fact",
    )


def count_needing_briefing(store: Store, domain: str, days: int = 30) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = store.conn.execute(
        """SELECT COUNT(*) c FROM scored_items
           WHERE domain=? AND score>=6
           AND (headline IS NULL OR headline='')
           AND created_at>=?""",
        (domain, cutoff),
    ).fetchone()
    return row["c"] if row else 0


def backfill_briefings(
    domain: DomainConfig,
    store: Store,
    *,
    days: int = 30,
    limit: int = 50,
    dry_run: bool = False,
) -> dict:
    """对无 headline 的精选条目补跑简报提炼。"""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = store.conn.execute(
        """SELECT s.id as scored_id, s.score, s.category, s.tags, s.summary, s.key_points,
                  s.reason, s.entities, s.source_display, s.title_display, s.content_type,
                  s.headline, s.lead, s.takeaway, s.insight_type,
                  r.source_id, r.title, r.url, r.content, r.full_text, r.published, r.lang
           FROM scored_items s
           JOIN raw_items r ON s.raw_id = r.id
           WHERE s.domain=? AND s.score>=6
           AND (s.headline IS NULL OR s.headline='')
           AND s.created_at>=?
           ORDER BY s.created_at DESC
           LIMIT ?""",
        (domain.name, cutoff, limit),
    ).fetchall()

    pending = len(rows)
    if dry_run or pending == 0:
        return {"pending": pending, "updated": 0, "dry_run": dry_run}

    items = [_row_to_scored(r) for r in rows]
    enriched = enrich_briefings(items, domain, store=store)

    updated = 0
    for row, item in zip(rows, enriched):
        if item.headline or item.lead:
            store.update_scored_briefing(row["scored_id"], item)
            updated += 1

    logger.info(f"简报补全：{updated}/{pending} 条已更新")
    return {"pending": pending, "updated": updated, "dry_run": False}
