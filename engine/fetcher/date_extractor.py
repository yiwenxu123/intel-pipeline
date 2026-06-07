"""日期提取器：从 URL、HTML、正文中提取发布日期。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from bs4 import BeautifulSoup


def extract_date(url: str, html: Optional[str] = None, text_prefix: str = "") -> Optional[datetime]:
    """多策略提取日期，按可靠性从高到低尝试。"""

    # 策略 1: 从 URL 中提取
    dt = _from_url(url)
    if dt:
        return dt

    # 策略 2: 从 HTML 元素中提取
    if html:
        dt = _from_html_elements(html)
        if dt:
            return dt

    # 策略 3: 从正文前 200 字中正则匹配
    if text_prefix:
        dt = _from_text(text_prefix)
        if dt:
            return dt

    return None


def _from_url(url: str) -> Optional[datetime]:
    """从 URL 路径中提取日期。

    已知模式:
    - /202606/t20260606_xxxxx.htm  (FOCAC 风格)
    - /2026/06/06/                  (WordPress 风格)
    - /2026-06-06/                  (横线分隔)
    - /article/20260606/            (数字连续)
    """
    patterns = [
        # FOCAC 风格: /202606/t20260606_
        r'/t(\d{4})(\d{2})(\d{2})_',
        # 年月目录 + 年月日文件: /202606/t20260606 或 /202606/20260606
        r'/(\d{4})(\d{2})/t?(\d{4})(\d{2})(\d{2})',
        # WordPress 风格: /2026/06/06/ 或 /2026/6/14/ (允许单数字)
        r'/(\d{4})/(\d{1,2})/(\d{1,2})/',
        # 横线分隔: /2026-06-06/
        r'/(\d{4})-(\d{2})-(\d{2})[/_.-]',
        # 连续数字日期: /20260606/ 或 _20260606_
        r'[/_.-](\d{4})(\d{2})(\d{2})[/_.-]',
    ]

    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 3:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif len(groups) == 5:
                    # 取后三组（更精确的日级日期）
                    y, mo, d = int(groups[2]), int(groups[3]), int(groups[4])
                else:
                    continue
                if 2000 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return datetime(y, mo, d, tzinfo=timezone.utc)
            except (ValueError, IndexError):
                continue
    return None


def _from_html_elements(html: str) -> Optional[datetime]:
    """从 HTML 中常见的日期元素提取。"""
    soup = BeautifulSoup(html, "lxml")

    # 常见日期选择器
    selectors = [
        "time[datetime]",
        ".pub-date", ".publish-date", ".post-date", ".article-date",
        ".date", ".time", ".pubtime", ".pub_time",
        "[class*='date']", "[class*='time']",
        "[property='article:published_time']",
        "[name='pubdate']", "[name='publishdate']",
        ".info", ".meta", ".source",
    ]

    for sel in selectors:
        elements = soup.select(sel)
        for el in elements:
            # 优先取 datetime 属性
            dt_attr = el.get("datetime") or el.get("content")
            if dt_attr:
                parsed = _parse_date_string(dt_attr)
                if parsed:
                    return parsed
            # 取文本内容
            text = el.get_text(strip=True)
            if text and len(text) < 50:
                parsed = _parse_date_string(text)
                if parsed:
                    return parsed

    return None


def _from_text(text: str) -> Optional[datetime]:
    """从正文中正则匹配日期。"""
    # 只取前 300 字，避免匹配到正文中的历史日期
    text = text[:300]

    patterns = [
        # 2026-06-06 或 2026/06/06 或 2026.06.06
        r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})',
        # 2026年6月6日
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2020 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return datetime(y, mo, d, tzinfo=timezone.utc)
            except (ValueError, IndexError):
                continue
    return None


def _parse_date_string(s: str) -> Optional[datetime]:
    """解析各种格式的日期字符串。"""
    s = s.strip()

    # ISO 8601: 2026-06-06T12:00:00Z 或 2026-06-06T12:00:00+08:00
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
    ]:
        try:
            return datetime.strptime(s[:30], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # 纯数字: 20260606
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def is_fresh(published: Optional[datetime], max_days: int = 3) -> bool:
    """判断是否在新鲜度窗口内。无日期的返回 True（不硬过滤，留给 LLM 判断）。"""
    if published is None:
        return True  # 无日期的不硬过滤
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_days)
    return published >= cutoff
