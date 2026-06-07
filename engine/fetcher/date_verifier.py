"""日期验证器：对无日期条目，抓文章详情页从正文中提取日期。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from engine.models import RawItem

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def extract_date_from_article(url: str) -> Optional[datetime]:
    """抓取文章详情页，从正文前 500 字中提取最早日期作为发布日期近似值。"""
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
    except Exception as e:
        logger.debug(f"详情页抓取失败: {e}")
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text(separator=" ", strip=True)[:800]

    # 提取所有日期
    dates = []
    for pattern in [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        r'(\d{4})-(\d{2})-(\d{2})',
    ]:
        for m in re.finditer(pattern, text):
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2020 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
                    dt = datetime(y, mo, d, tzinfo=timezone.utc)
                    # 排除未来日期
                    now = datetime.now(timezone.utc)
                    if dt <= now:
                        dates.append(dt)
            except (ValueError, IndexError):
                continue

    if not dates:
        return None

    # 返回最早的日期（最可能是文章发布时间或事件时间）
    # 但要排除太早的历史日期（如果最早日期比最晚日期早超过1年，取最晚的）
    dates.sort()
    earliest = dates[0]
    latest = dates[-1]
    if (latest - earliest).days > 365:
        # 日期跨度太大，取最晚的（更可能是近期事件）
        return latest
    return earliest


def verify_dates_batch(items: list[RawItem], max_fetches: int = 30) -> dict[str, datetime]:
    """批量验证无日期条目：抓详情页提取日期。

    返回 {url: datetime} 映射。
    """
    undated = [i for i in items if i.published is None]
    if not undated:
        return {}

    logger.info(f"开始详情页日期验证：{len(undated)} 条无日期条目（最多抓 {max_fetches} 页）")
    results: dict[str, datetime] = {}

    for item in undated[:max_fetches]:
        dt = extract_date_from_article(item.url)
        if dt:
            results[item.url] = dt
            logger.info(f"详情页日期 [{item.source_id}] {dt.date()} {item.title[:30]}")

    logger.info(f"详情页日期验证完成：{len(results)}/{min(len(undated), max_fetches)} 条获得日期")
    return results
