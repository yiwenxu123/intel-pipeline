"""RSS 信源采集器。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from engine.models import RawItem, SourceDef

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
_WX_URL_RE = re.compile(r'https?://mp\.weixin\.qq\.com/[^\s"<>' + "'" + r']+')


def _resolve_rsshub_url(url: str) -> str | None:
    """从 RSSHub 代理页面提取原始微信文章链接。"""
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        m = _WX_URL_RE.search(resp.text)
        return m.group(0) if m else None
    except Exception:
        return None


def _parse_date(entry) -> Optional[datetime]:
    """从 feed entry 提取发布时间。"""
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
            except Exception:
                continue
    return None


def fetch_rss(source: SourceDef) -> list[RawItem]:
    """拉取一个 RSS 信源，返回原始条目列表。"""
    items: list[RawItem] = []
    try:
        resp = httpx.get(source.url, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"RSS 拉取失败 [{source.id}]: {e}")
        return []

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        # 修复协议相对 URL（如 //views/article/...）和缺少协议的链接
        from urllib.parse import urljoin
        if link.startswith("//") or link.startswith("/"):
            link = urljoin(source.url, link)

        # RSSHub 代理链接 → 提取原始微信 URL
        if "/views/article/" in link:
            original = _resolve_rsshub_url(link)
            if original:
                link = original

        # 提取摘要/内容
        content = ""
        if entry.get("summary"):
            content = entry.summary
        elif entry.get("description"):
            content = entry.description
        # 清理 HTML 标签
        if content:
            from bs4 import BeautifulSoup
            content = BeautifulSoup(content, "lxml").get_text(strip=True)[:2000]

        items.append(
            RawItem(
                source_id=source.id,
                title=title,
                url=link,
                content=content,
                published=_parse_date(entry),
                lang=source.lang,
            )
        )

    logger.info(f"RSS [{source.id}] 拉取到 {len(items)} 条")
    return items
