"""信源质量分析器：统计信源产出率，标记低效信源。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)


def analyze_source_quality(domain: str, days: int = 7) -> dict:
    """分析信源质量，返回各信源的产出率统计。"""
    s = Store()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 统计各信源的采集条数和精选条数
    raw_stats = s.conn.execute(
        """SELECT source_id, COUNT(*) as total
           FROM raw_items
           WHERE fetched_at >= ?
           GROUP BY source_id""",
        (cutoff,),
    ).fetchall()

    scored_stats = s.conn.execute(
        """SELECT r.source_id, COUNT(*) as selected
           FROM scored_items s
           JOIN raw_items r ON s.raw_id = r.id
           WHERE s.domain = ? AND s.score >= 6.0 AND s.created_at >= ?
           GROUP BY r.source_id""",
        (domain, cutoff),
    ).fetchall()

    s.close()

    # 构建统计结果
    scored_map = {r["source_id"]: r["selected"] for r in scored_stats}
    results = []

    for r in raw_stats:
        src_id = r["source_id"]
        total = r["total"]
        selected = scored_map.get(src_id, 0)
        rate = selected / total if total > 0 else 0

        # 判断状态
        if total == 0:
            status = "dormant"
        elif rate == 0:
            status = "ineffective"
        elif rate < 0.05:
            status = "low"
        else:
            status = "healthy"

        results.append({
            "source_id": src_id,
            "total": total,
            "selected": selected,
            "rate": round(rate, 3),
            "status": status,
        })

    # 按产出率排序
    results.sort(key=lambda x: x["rate"], reverse=True)
    return {"domain": domain, "days": days, "sources": results}


def generate_source_report(domain: str, days: int = 7) -> str:
    """生成信源质量报告（Markdown 格式）。"""
    data = analyze_source_quality(domain, days)
    sources = data["sources"]

    lines = [
        f"# 信源质量报告 — {domain}",
        f"分析周期：最近 {days} 天",
        f"分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 统计概览",
        "",
        f"- 总信源数：{len(sources)}",
        f"- 健康信源：{len([s for s in sources if s['status'] == 'healthy'])}",
        f"- 低效信源：{len([s for s in sources if s['status'] == 'low'])}",
        f"- 无效信源：{len([s for s in sources if s['status'] == 'ineffective'])}",
        f"- 休眠信源：{len([s for s in sources if s['status'] == 'dormant'])}",
        "",
        "## 信源详情",
        "",
        "| 信源 | 采集 | 精选 | 产出率 | 状态 |",
        "|------|------|------|--------|------|",
    ]

    status_emoji = {
        "healthy": "🟢",
        "low": "🟡",
        "ineffective": "🔴",
        "dormant": "⚫",
    }

    for s in sources:
        emoji = status_emoji.get(s["status"], "❓")
        rate_pct = f"{s['rate'] * 100:.1f}%"
        lines.append(
            f"| {s['source_id']} | {s['total']} | {s['selected']} | {rate_pct} | {emoji} {s['status']} |"
        )

    # 建议
    ineffective = [s for s in sources if s["status"] in ("ineffective", "dormant")]
    if ineffective:
        lines.extend([
            "",
            "## 建议",
            "",
            "以下信源连续 7 天无有效产出，建议检查或移除：",
            "",
        ])
        for s in ineffective:
            lines.append(f"- `{s['source_id']}`: {s['status']}（采集 {s['total']} 条，精选 0 条）")

    return "\n".join(lines)


def save_source_report(domain: str, days: int = 7) -> Path:
    """保存信源质量报告到文件。"""
    report = generate_source_report(domain, days)
    output_dir = settings.project_root / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"source-quality-{domain}-{date}.md"
    path.write_text(report, encoding="utf-8")
    logger.info(f"信源质量报告已保存: {path}")
    return path
