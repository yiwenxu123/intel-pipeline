"""全文提取：从原文链接抓取正文，用于替换 RSS 摘要。"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 通用提取误抓导航/页眉时的特征（如 AgeClub SSR 壳层）
_NAV_BOILERPLATE_MARKERS = ("首页", "品牌矩阵", "会员专区", "发布商机", "登录")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
}

# 正文提取 Score: 通过密度算法找到正文区域
MIN_TEXT_LENGTH = 200
MAX_TEXT_LENGTH = 8000


def _score_node(node) -> tuple[int, str]:
    """对节点递归打分：文本密度越高分越高。"""
    text_len = 0
    link_text_len = 0
    text_parts: list[str] = []

    for child in node.descendants:
        if child.name == "a" or child.name == "link":
            link_text_len += len(child.get_text(strip=True))
        elif child.string:
            t = child.string.strip()
            if t:
                text_len += len(t)
                text_parts.append(t)

    # 正文区域特征：文本多、链接少、不含导航类 class/id
    score = text_len - link_text_len * 2
    # 惩罚导航类元素
    parent_classes = (node.get("class", []) or [])
    parent_id = node.get("id", "") or ""
    nav_keywords = ["nav", "menu", "sidebar", "footer", "comment", "header",
                    "breadcrumb", "related", "widget", "advertisement"]
    for kw in nav_keywords:
        if kw in " ".join(parent_classes) or kw in parent_id:
            score = max(0, score - text_len)

    return score, " ".join(text_parts)


def is_nav_boilerplate(text: str) -> bool:
    """检测是否为站点导航/壳层文本而非正文。"""
    if not text or len(text) < 80:
        return False
    hits = sum(1 for m in _NAV_BOILERPLATE_MARKERS if m in text)
    return hits >= 3


def _extract_ageclub_nuxt(html: str) -> Optional[str]:
    """AgeClub 为 Nuxt SPA：正文在 window.__NUXT__ 的 content 字段（HTML）。"""
    idx = html.find("article/article-detail")
    if idx < 0:
        return None
    chunk = html[idx : idx + 120_000]
    match = re.search(r'content:("(?:\\.|[^"\\])*")', chunk)
    if not match:
        return None
    try:
        content_html = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not content_html or len(content_html) < 50:
        return None
    soup = BeautifulSoup(content_html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    # NUXT payload 为可信正文源，阈值低于通用 DOM 提取
    min_len = 80
    return _clean_text(text)[:MAX_TEXT_LENGTH] if len(text) >= min_len else None


def extract_full_text(html: str, url: str = "") -> Optional[str]:
    """从 HTML 中提取正文。

    流程：
    1. 站点特例（如 AgeClub NUXT payload）
    2. 用 BeautifulSoup 解析通用页面
    3. 移除无用元素（script, style, nav, footer 等）
    4. 对 p、div、article 等容器打分
    5. 取最高分区域的文本

    返回纯文本，最长 MAX_TEXT_LENGTH 字符。
    """
    host = urlparse(url).netloc.lower()
    if "ageclub.net" in host:
        nuxt_text = _extract_ageclub_nuxt(html)
        if nuxt_text and not is_nav_boilerplate(nuxt_text):
            return nuxt_text

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:
        logger.debug(f"HTML 解析失败 [{url}]: {e}")
        return None

    # 移除无用元素
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                      "noscript", "iframe", "form", "button", "svg", "canvas"]):
        tag.decompose()

    # 尝试按 <article> 优先
    article = soup.find("article")
    if article:
        texts = article.get_text(separator="\n", strip=True)
        if len(texts) >= MIN_TEXT_LENGTH:
            return _clean_text(texts)[:MAX_TEXT_LENGTH]

    # 对 <div> / <section> / <main> 容器打分
    candidates: list[tuple[int, str]] = []
    for tag_name in ("main", "section", "div", "pre"):
        for node in soup.find_all(tag_name):
            # 只找包含足够文本的节点
            text = node.get_text(separator="\n", strip=True)
            if len(text) < MIN_TEXT_LENGTH:
                continue
            score, _ = _score_node(node)
            candidates.append((score, text))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_text = candidates[0]
        # 如果最佳候选分太低，可能是误判
        if best_score > MIN_TEXT_LENGTH * 3:
            return _clean_text(best_text)[:MAX_TEXT_LENGTH]

    # 兜底：取 body 全文（去标签），但拒绝明显导航壳层
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        if len(text) >= MIN_TEXT_LENGTH and not is_nav_boilerplate(text):
            return _clean_text(text)[:MAX_TEXT_LENGTH]

    return None


def _clean_text(text: str) -> str:
    """清理文本：合并空行、去除多余空白。"""
    # 合并连续换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    # 过滤纯空白行
    lines = [line for line in lines if line]
    return "\n".join(lines)


def fetch_and_extract(url: str, timeout: int = 15) -> Optional[str]:
    """抓取 URL 并提取正文。

    Args:
        url: 原文链接。
        timeout: HTTP 超时秒数。

    Returns:
        提取到的正文纯文本，失败返回 None。
    """
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        # 自动检测编码
        if resp.encoding and resp.encoding.lower() != "utf-8":
            resp.encoding = resp.encoding
    except Exception as e:
        logger.debug(f"全文抓取失败 [{url}]: {e}")
        return None

    return extract_full_text(resp.text, url=url)
