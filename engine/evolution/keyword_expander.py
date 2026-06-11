"""关键词扩展器：从高分情报中提取高频词，建议新增关键词。"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)

# 停用词（中文常见虚词）
STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "他", "她", "它", "们", "那", "里", "为", "什么", "被", "把",
    "从", "对", "等", "可以", "这个", "那个", "而", "但", "与", "中", "年", "月",
    "日", "大", "小", "多", "少", "新", "旧", "最", "更", "比较", "已经", "正在",
    "将", "将要", "可能", "可以", "能够", "应该", "必须", "需要",
}


def extract_keywords_from_text(text: str, min_length: int = 2, max_length: int = 8) -> list[str]:
    """从文本中提取关键词（简单分词 + 过滤）。"""
    # 提取中文词组：滑动窗口 2-4 字（避免非重叠匹配切分合成词）
    zh_words = []
    for length in range(min_length, min(5, max_length + 1)):
        for i in range(len(text) - length + 1):
            window = text[i:i + length]
            if all('\u4e00' <= c <= '\u9fff' for c in window):
                zh_words.append(window)
    # 移除是更长词子串的短词（如 '人工' 是 '人工智能' 的子串）
    zh_words = [w for w in zh_words if not any(w != lw and w in lw for lw in zh_words)]
    # 提取英文词组
    en_words = re.findall(r'[a-zA-Z]{3,}', text)
    # 合并并过滤
    all_words = zh_words + en_words
    return [
        w for w in all_words
        if len(w) >= min_length
        and w not in STOPWORDS
        and not w.isdigit()
    ]


def analyze_keyword_frequency(domain: str, days: int = 7, min_score: float = 7.0) -> dict:
    """从高分情报中提取高频关键词。"""
    s = Store()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 获取高分条目的标题和摘要
    rows = s.conn.execute(
        """SELECT r.title, s.summary, s.title_display
           FROM scored_items s
           JOIN raw_items r ON s.raw_id = r.id
           WHERE s.domain = ? AND s.score >= ? AND s.created_at >= ?""",
        (domain, min_score, cutoff),
    ).fetchall()

    s.close()

    # 提取关键词
    all_keywords: list[str] = []
    for r in rows:
        title_display = r["title_display"] if "title_display" in r.keys() else ""
        text = f"{r['title']} {r['summary']} {title_display}"
        keywords = extract_keywords_from_text(text)
        all_keywords.extend(keywords)

    # 统计频率
    counter = Counter(all_keywords)
    top_keywords = counter.most_common(50)

    return {
        "domain": domain,
        "days": days,
        "min_score": min_score,
        "total_items": len(rows),
        "keywords": [
            {"keyword": kw, "count": cnt}
            for kw, cnt in top_keywords
        ],
    }


def suggest_new_keywords(domain: str, days: int = 7, min_score: float = 7.0) -> list[str]:
    """建议新增关键词：高频但不在现有 keywords.yaml 中的词。"""
    # 加载现有关键词
    keywords_path = settings.project_root / "domains" / domain / "keywords.yaml"
    existing_keywords: set[str] = set()
    if keywords_path.exists():
        import yaml
        with open(keywords_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            existing_keywords = set(data.get("keywords", []))

    # 分析高频词
    analysis = analyze_keyword_frequency(domain, days, min_score)

    # 过滤掉已有的关键词
    suggestions = []
    seen = set()
    for kw in analysis["keywords"]:
        keyword = kw["keyword"]
        # 检查是否已存在（包含匹配）
        if keyword in existing_keywords:
            continue
        if any(keyword in ek or ek in keyword for ek in existing_keywords):
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        suggestions.append(keyword)

    return suggestions[:20]  # 最多建议 20 个


def generate_keyword_report(domain: str, days: int = 7) -> str:
    """生成关键词分析报告。"""
    analysis = analyze_keyword_frequency(domain, days)
    suggestions = suggest_new_keywords(domain, days)

    lines = [
        f"# 关键词分析报告 — {domain}",
        f"分析周期：最近 {days} 天",
        f"分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"分析条目：{analysis['total_items']} 条（评分 ≥ 7.0）",
        "",
        "## 高频关键词 Top 20",
        "",
        "| 关键词 | 出现次数 |",
        "|--------|----------|",
    ]

    for kw in analysis["keywords"][:20]:
        lines.append(f"| {kw['keyword']} | {kw['count']} |")

    if suggestions:
        lines.extend([
            "",
            "## 建议新增关键词",
            "",
            "以下关键词在高分情报中频繁出现，但不在现有 keywords.yaml 中：",
            "",
        ])
        for kw in suggestions:
            lines.append(f"- `{kw}`")

    return "\n".join(lines)


def save_keyword_report(domain: str, days: int = 7) -> Path:
    """保存关键词分析报告。"""
    report = generate_keyword_report(domain, days)
    output_dir = settings.project_root / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"keyword-analysis-{domain}-{date}.md"
    path.write_text(report, encoding="utf-8")
    logger.info(f"关键词分析报告已保存: {path}")
    return path


def suggest_keywords_yaml(domain: str, days: int = 7) -> str:
    """生成可直接追加到 keywords.yaml 的 YAML 片段。"""
    suggestions = suggest_new_keywords(domain, days)
    if not suggestions:
        return ""
    date = datetime.now().strftime("%Y-%m-%d")
    lines = [f"  # auto-suggested on {date}"]
    for kw in suggestions:
        lines.append(f"  - {kw}")
    return "\n".join(lines)
