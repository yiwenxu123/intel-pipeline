"""网页信源采集器：通过 CSS 选择器提取文章列表，同时提取发布日期。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from engine.fetcher.date_extractor import extract_date
from engine.models import RawItem, SourceDef

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def _extract_date_from_url(url: str) -> Optional[datetime]:
    """从 URL 中快速提取日期（零网络请求）。"""
    return extract_date(url, html=None, text_prefix="")


def fetch_web(source: SourceDef) -> list[RawItem]:
    """抓取一个网页信源，用 CSS 选择器提取文章列表，同时提取日期。"""
    items: list[RawItem] = []
    selectors = source.selectors or {}

    try:
        resp = httpx.get(source.url, headers=HEADERS, timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0), follow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"网页抓取失败 [{source.id}]: {e}")
        return []

    article_sel = selectors.get("article", "")
    title_sel = selectors.get("title", "a")

    if article_sel:
        articles = soup.select(article_sel)
        for art in articles[:30]:
            title_el = art.select_one(title_sel) if title_sel else art.select_one("a")
            if not title_el:
                continue
            # 优先取 title 属性（更干净），再取文本
            title = title_el.get("title", "") or title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if not href:
                link_el = art.select_one("a[href]")
                href = link_el.get("href", "") if link_el else ""
            if not title or not href:
                continue
            url = urljoin(source.url, href)

            # 提取摘要
            content = ""
            desc_el = art.select_one(".desc, .summary, .intro, p")
            if desc_el:
                content = desc_el.get_text(strip=True)[:1000]

            # 日期提取：优先从 date 选择器，再从 URL，再从 HTML
            published = None
            date_sel = selectors.get("date", "")
            if date_sel:
                date_el = art.select_one(date_sel)
                if date_el:
                    date_text = date_el.get_text(strip=True)
                    published = extract_date(url, html=None, text_prefix=date_text)
            if not published:
                published = _extract_date_from_url(url)
            if not published:
                published = extract_date(url, html=str(art), text_prefix="")

            items.append(
                RawItem(
                    source_id=source.id,
                    title=title,
                    url=url,
                    content=content,
                    published=published,
                    lang=source.lang,
                )
            )
    else:
        # 通用提取模式
        links = soup.select("a[href]")
        seen = set()
        for a in links:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue
            url = urljoin(source.url, href)
            if url in seen:
                continue
            seen.add(url)

            published = _extract_date_from_url(url)

            items.append(
                RawItem(
                    source_id=source.id,
                    title=title,
                    url=url,
                    content="",
                    published=published,
                    lang=source.lang,
                )
            )
            if len(items) >= 30:
                break

    logger.info(f"Web [{source.id}] 提取到 {len(items)} 条")
    return items
