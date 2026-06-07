"""AgeClub 信源采集器：银发经济垂直媒体，提取标题、日期、原始来源。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from engine.models import RawItem, SourceDef

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def fetch_ageclub(source: SourceDef) -> list[RawItem]:
    """采集 AgeClub 文章列表，提取标题、链接、日期、原始来源。"""
    try:
        resp = httpx.get(source.url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"AgeClub 采集失败: {e}")
        return []

    items: list[RawItem] = []
    seen_urls: set[str] = set()

    # 找所有日期文本，向上回溯找到对应的文章链接和来源
    for text_node in soup.find_all(string=re.compile(r"20\d{2}-\d{2}-\d{2}")):
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", str(text_node))
        if not date_match:
            continue
        date_str = date_match.group(1)
        try:
            pub_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # 向上找包含 article-detail 链接的容器
        container = text_node.parent
        link = None
        for _ in range(8):
            if container is None:
                break
            link = container.find("a", href=re.compile(r"/article-detail/\d+"))
            if link:
                break
            container = container.parent

        if not link:
            continue

        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not href or not title or len(title) < 5:
            continue

        url = urljoin(source.url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # 提取原始来源（author 链接）
        original_source = _extract_original_source(container, source.name)

        # 提取摘要
        content = ""
        desc = link.find_next_sibling(string=True)
        if desc:
            content = str(desc).strip()[:500]

        items.append(
            RawItem(
                source_id=source.id,
                title=title,
                url=url,
                content=content,
                published=pub_date,
                lang=source.lang,
                extra={"original_source": original_source},
            )
        )

    logger.info(f"AgeClub 采集到 {len(items)} 条")
    return items


def _extract_original_source(container, fallback: str) -> str:
    """从容器中提取原始来源名称。

    AgeClub 文章标注有来源（如"财经杂志"、"中商情报网"等）。
    如果来源是 "AgeClub" 或 "AgeClub记者"，则保留为 AgeClub。
    """
    if container is None:
        return fallback

    author_link = container.find("a", href=re.compile(r"/author/"))
    if author_link:
        author = author_link.get_text(strip=True)
        if author:
            # 过滤掉 "AgeClub记者 XXX" 格式，只保留 "AgeClub"
            if author.startswith("AgeClub"):
                return "AgeClub"
            return author

    return fallback
