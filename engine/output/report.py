"""每日情报简报生成器。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.config import settings
from engine.domain import DomainConfig
from engine.models import ScoredItem, DailyReport
from engine.output.briefing_display import (
    content_type_label,
    item_facts,
    item_headline,
    item_lead,
    item_takeaway,
)
from engine.store import Store


def _category_top3(items: list[ScoredItem]) -> list[dict]:
    from collections import Counter
    selected = [s for s in items if s.score >= 5.5]
    counts = Counter(s.category or "未分类" for s in selected)
    return [{"category": cat, "count": cnt} for cat, cnt in counts.most_common(3)]


def _top_entities(items: list[ScoredItem], limit: int = 5) -> list[str]:
    from collections import Counter
    counter: Counter[str] = Counter()
    for item in items:
        if item.score >= 5.5:
            for ent in item.entities or []:
                if ent:
                    counter[ent] += 1
    return [ent for ent, _ in counter.most_common(limit)]


def compute_trend_text(store: Store, domain_name: str, days: int = 14) -> str:
    """从本周/上周精选数对比生成趋势一句话。"""
    trends = store.get_trends(domain_name, days=days)
    weekly = trends.get("weekly", [])
    if len(weekly) < 2:
        return ""
    this_week = weekly[-1]
    prev_week = weekly[-2]
    this_selected = this_week.get("selected_items", 0) or 0
    prev_selected = prev_week.get("selected_items", 0) or 0
    if prev_selected == 0:
        return f"本周精选 {this_selected} 条（上周无精选）"
    change = (this_selected - prev_selected) / prev_selected * 100
    arrow = "↑" if change > 0 else "↓"
    return f"本周精选 {this_selected} 条，较上周 {arrow} {abs(change):.0f}%"


def generate_report(scored: list[ScoredItem], domain: DomainConfig, total_fetched: int = 0,
                    trend_text: str = "", date: str | None = None) -> DailyReport:
    """生成每日情报简报。

    Args:
        trend_text: 本周趋势一句话（如"本周精选 12 条，较上周 ↑ 20%"）。
        date: 日报日期 YYYY-MM-DD，留空自动设为今日。
    """
    report_date = date or datetime.now().strftime("%Y-%m-%d")
    selected = [s for s in scored if s.score >= 5.5]

    report = DailyReport(
        date=report_date,
        domain=domain.name,
        items=selected,
        trend_text=trend_text,
        stats={
            "total_fetched": total_fetched,
            "total_scored": len(scored),
            "selected": len(selected),
            "select_rate": f"{len(selected)/max(total_fetched,1)*100:.1f}%",
            "category_top3": _category_top3(scored),
            "top_entities": _top_entities(scored),
        },
    )
    return report


def report_to_markdown(report: DailyReport) -> str:
    """将简报转为 Markdown 格式。"""
    lines = []
    lines.append(f"# {report.domain} 情报日报 — {report.date}\n")

    stats = report.stats
    lines.append(f"> 采集 {stats.get('total_fetched', '?')} 条 → 评分 {stats.get('total_scored', '?')} 条 → 精选 {stats.get('selected', '?')} 条（精选率 {stats.get('select_rate', '?')}）\n")

    if report.trend_text:
        lines.append(f"> 📊 **趋势**：{report.trend_text}\n")

    cat_top3 = stats.get("category_top3") or []
    if cat_top3:
        parts = [f"{c['category']} {c['count']}条" for c in cat_top3]
        lines.append(f"> 📂 **分类 Top3**：{' · '.join(parts)}\n")

    top_ents = stats.get("top_entities") or []
    if top_ents:
        lines.append(f"> 📌 **热点实体**：{' · '.join(top_ents)}\n")

    # 按分类分组
    by_category: dict[str, list[ScoredItem]] = {}
    for item in report.items:
        cat = item.category or "未分类"
        by_category.setdefault(cat, []).append(item)

    for cat, items in by_category.items():
        lines.append(f"## {cat}\n")
        for item in items:
            score_emoji = "🔴" if item.score >= 8 else ("🟡" if item.score >= 6.5 else "🟢")
            display_title = item_headline(item)
            lines.append(f"### {score_emoji} [{display_title}]({item.raw.url})\n")
            pub_date = item.raw.published.strftime("%Y-%m-%d") if item.raw.published else ""
            source_part = f"来源：{item.raw.source_id}"
            date_part = f"日期：{pub_date}" if pub_date else ""
            sep = " | " if pub_date else ""
            ct_label = content_type_label(item)
            meta = f"**评分：{item.score:.1f}**"
            if ct_label:
                meta += f" | {ct_label}"
            meta += f" | {source_part}{sep}{date_part}"
            lines.append(f"{meta}\n")
            lead = item_lead(item)
            if lead:
                lines.append(f"> {lead}\n")
            facts = item_facts(item, limit=2)
            for kp in facts:
                lines.append(f"  • {kp}")
            takeaway = item_takeaway(item)
            if takeaway:
                lines.append(f"💡 {takeaway}\n")
            lines.append("")

    return "\n".join(lines)


def save_report(report: DailyReport, output_dir: Path | None = None):
    """保存简报到文件，并生成编辑审阅版。"""
    output_dir = output_dir or (settings.project_root / settings.report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    domain_cn = "银发产业" if report.domain == "elderly-care" else report.domain

    # Markdown 版（对外发布版）
    md_path = output_dir / f"{report.date}-{report.domain}.md"
    md_path.write_text(report_to_markdown(report), encoding="utf-8")

    # 编辑审阅版（供 Fred 每日审阅）
    review_path = output_dir / f"{report.date}-{report.domain}-待审.md"
    review_lines = []
    review_lines.append(f"# {domain_cn}情报日报 — {report.date}（编辑审阅版）")
    review_lines.append("")
    review_lines.append("> 请逐条审阅下方精选条目，标记通过/误报/降级，并可补充点评。")
    review_lines.append("")
    review_lines.append("---")
    review_lines.append("")
    review_lines.append("## 📝 今日总编点评（可选）")
    review_lines.append("")
    review_lines.append("写一句你今天对读者想说的话，或今天最重要的观察：")
    review_lines.append("")
    review_lines.append("> _（在此输入你的点评）_")
    review_lines.append("")
    review_lines.append("---")
    review_lines.append("")
    review_lines.append("## 精选条目审阅")
    review_lines.append("")

    for i, item in enumerate(report.items, 1):
        display_title = item_headline(item)
        score_emoji = "🔴" if item.score >= 8 else ("🟡" if item.score >= 6.5 else "🟢")
        takeaway = item_takeaway(item)
        review_lines.append(f"### {i}. {score_emoji} [{display_title}]({item.raw.url})")
        review_lines.append(f"")
        review_lines.append(f"- **评分**：{item.score:.1f} | **分类**：{item.category} | **信源**：{item.raw.source_id}")
        review_lines.append(f"- **摘要**：{item_lead(item)}")
        if takeaway:
            review_lines.append(f"- **价值**：{takeaway}")
        review_lines.append(f"")
        review_lines.append(f"**审阅**：[ ] 通过 ✅  [ ] 误报 ❌  [ ] 降级 ⬇️")
        review_lines.append(f"")
        review_lines.append(f"**补充点评**（可选）：")
        review_lines.append(f"> _（这条信息对你有没有用？对谁特别有用？）_")
        review_lines.append(f"")
        review_lines.append("---")
        review_lines.append("")

    review_path.write_text("\n".join(review_lines), encoding="utf-8")

    # JSON 版（结构化数据，供 API 和 Agent 使用）
    json_path = output_dir / f"{report.date}-{report.domain}.json"
    data = {
        "date": report.date,
        "domain": report.domain,
        "stats": report.stats,
        "trend_text": report.trend_text,
        "items": [
            {
                "title": item_headline(item),
                "url": item.raw.url,
                "source_id": item.raw.source_id,
                "score": item.score,
                "category": item.category,
                "headline": item.headline,
                "lead": item_lead(item),
                "takeaway": item_takeaway(item),
                "facts": item_facts(item, limit=3),
                "insight_type": item.insight_type,
                "content_type": item.content_type,
                "tags": item.tags,
                "summary": item.summary,
                "key_points": item.key_points,
                "reason": item.reason,
                "entities": item.entities,
                "published": item.raw.published.isoformat() if item.raw.published else None,
            }
            for item in report.items
        ],
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path
