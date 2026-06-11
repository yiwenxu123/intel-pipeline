"""批量重抓原文全文（按信源或 URL 模式）。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.fetcher.full_text_fetcher import fetch_and_extract, is_nav_boilerplate
from engine.store import Store

logger = logging.getLogger(__name__)


def refetch_full_text(
    *,
    source_id: str | None = None,
    url_pattern: str | None = None,
    limit: int = 200,
    max_workers: int = 3,
    sleep_sec: float = 0.5,
) -> dict:
    """重抓 raw_items 全文并写回 store。

    Returns:
        {"total": N, "ok": N, "skipped": N, "failed": N}
    """
    sql = "SELECT id, url, source_id, full_text FROM raw_items WHERE 1=1"
    params: list = []
    if source_id:
        sql += " AND source_id = ?"
        params.append(source_id)
    if url_pattern:
        sql += " AND url LIKE ?"
        params.append(f"%{url_pattern}%")
    sql += " ORDER BY fetched_at DESC LIMIT ?"
    params.append(limit)

    with Store() as store:
        rows = store.conn.execute(sql, params).fetchall()
        if not rows:
            return {"total": 0, "ok": 0, "cleared": 0, "skipped": 0, "failed": 0}

        stats = {"total": len(rows), "ok": 0, "cleared": 0, "skipped": 0, "failed": 0}

        def _one(row) -> str:
            time.sleep(sleep_sec)
            text = fetch_and_extract(row["url"])
            if text and not is_nav_boilerplate(text):
                store.update_full_text(row["url"], text)
                return "ok"
            # 清除历史导航壳层污染
            old = row["full_text"] or ""
            if old and is_nav_boilerplate(old):
                store.update_full_text(row["url"], "")
                return "cleared"
            if is_nav_boilerplate(text or ""):
                return "skipped"
            return "failed"

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_one, r): r["url"] for r in rows}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    stats[result] += 1
                    if result == "ok":
                        logger.info(f"全文已更新 [{url[:60]}]")
                    else:
                        logger.debug(f"全文跳过/失败 [{url[:60]}]: {result}")
                except Exception as e:
                    stats["failed"] += 1
                    logger.warning(f"全文重抓异常 [{url}]: {e}")

        return stats
