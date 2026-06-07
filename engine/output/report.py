"""每日情报简报生成器。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.config import settings
from engine.domain import DomainConfig
from engine.models import ScoredItem, DailyReport


def generate_report(scored: list[ScoredItem], domain: DomainConfig, total_fetched: int = 0) -> DailyReport:
    """生成每日情报简报。"""
    date = datetime.now().strftime("%Y-%m-%d")
    selected = [s for s in scored if s.score >= 6.0]

    report = DailyReport(
        date=date,
        domain=domain.name,
        items=selected,
        stats={
            "total_fetched": total_fetched,
            "total_scored": len(scored),
            "selected": len(selected),
            "select_rate": f"{len(selected)/max(total_fetched,1)*100:.1f}%",
        },
    )
    return report


def report_to_markdown(report: DailyReport) -> str:
    """将简报转为 Markdown 格式。"""
    lines = []
    lines.append(f"# {report.domain} 情报日报 — {report.date}\n")

    stats = report.stats
    lines.append(f"> 采集 {stats.get('total_fetched', '?')} 条 → 评分 {stats.get('total_scored', '?')} 条 → 精选 {stats.get('selected', '?')} 条（精选率 {stats.get('select_rate', '?')}）\n")

    # 按分类分组
    by_category: dict[str, list[ScoredItem]] = {}
    for item in report.items:
        cat = item.category or "未分类"
        by_category.setdefault(cat, []).append(item)

    for cat, items in by_category.items():
        lines.append(f"## {cat}\n")
        for item in items:
            score_emoji = "🔴" if item.score >= 8 else ("🟡" if item.score >= 6.5 else "🟢")
            lines.append(f"### {score_emoji} [{item.raw.title}]({item.raw.url})\n")
            lines.append(f"**评分：{item.score:.1f}** | 来源：{item.raw.source_id}\n")
            if item.summary:
                lines.append(f"> {item.summary}\n")
            if item.reason:
                lines.append(f"💡 {item.reason}\n")
            if item.tags:
                lines.append(f"🏷️ {' · '.join(item.tags)}\n")
            if item.entities:
                lines.append(f"📌 {' · '.join(item.entities)}\n")
            lines.append("")

    return "\n".join(lines)


def save_report(report: DailyReport, output_dir: Path | None = None):
    """保存简报到文件。"""
    output_dir = output_dir or (settings.project_root / settings.report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Markdown 版
    md_path = output_dir / f"{report.date}-{report.domain}.md"
    md_path.write_text(report_to_markdown(report), encoding="utf-8")

    # JSON 版（结构化数据，供 API 和 Agent 使用）
    json_path = output_dir / f"{report.date}-{report.domain}.json"
    data = {
        "date": report.date,
        "domain": report.domain,
        "stats": report.stats,
        "items": [
            {
                "title": item.raw.title,
                "url": item.raw.url,
                "source_id": item.raw.source_id,
                "score": item.score,
                "category": item.category,
                "tags": item.tags,
                "summary": item.summary,
                "reason": item.reason,
                "entities": item.entities,
                "published": item.raw.published.isoformat() if item.raw.published else None,
            }
            for item in report.items
        ],
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path
