"""SearXNG 信源采集器：通过自建 SearXNG 搜索引擎采集公众号文章。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from engine.models import RawItem, SourceDef

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _parse_published(date_str: Optional[str]) -> Optional[datetime]:
    """解析 SearXNG 返回的日期字符串。"""
    if not date_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(date_str[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def fetch_searxng(source: SourceDef) -> list[RawItem]:
    """通过 SearXNG 搜索采集文章。

    source.url: SearXNG 基础地址，如 http://10.207.251.137:8080
    source.selectors: 包含 search_queries 列表
        例如: {"search_queries": ["养老 最新政策", "银发经济 产业"]}
    """
    base_url = source.url.rstrip("/")
    queries = (source.selectors or {}).get("search_queries", [])
    time_range = (source.selectors or {}).get("time_range", "")
    # 可选：只保留匹配的 URL 模式（如 mp.weixin.qq.com）
    url_filter = (source.selectors or {}).get("url_filter", "")

    if not queries:
        logger.warning(f"SearXNG [{source.id}] 未配置 search_queries")
        return []

    items: list[RawItem] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            params = {
                "q": query,
                "format": "json",
                "language": "zh",
            }
            if time_range:
                params["time_range"] = time_range
            resp = httpx.get(
                f"{base_url}/search",
                params=params,
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])

            for r in results:
                url = r.get("url", "")
                title = r.get("title", "").strip()
                if not url or not title:
                    continue
                if url in seen_urls:
                    continue
                # URL 过滤
                if url_filter and url_filter not in url:
                    continue
                seen_urls.add(url)

                content = r.get("content", "") or ""
                published = _parse_published(r.get("publishedDate"))

                items.append(
                    RawItem(
                        source_id=source.id,
                        title=title,
                        url=url,
                        content=content[:1000],
                        published=published,
                        lang=source.lang,
                    )
                )

            logger.info(f"SearXNG [{source.id}] 查询 \"{query}\" → {len(results)} 条结果")
        except Exception as e:
            logger.warning(f"SearXNG [{source.id}] 查询 \"{query}\" 失败: {e}")

    logger.info(f"SearXNG [{source.id}] 共采集 {len(items)} 条（去重后）")
    return items
