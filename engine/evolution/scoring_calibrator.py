"""评分校准器：分析评分分布，识别异常，建议调整。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)


def analyze_scoring_distribution(domain: str, days: int = 7) -> dict:
    """分析评分分布，识别异常模式。"""
    s = Store()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 各分类的评分分布
    category_stats = s.conn.execute(
        """SELECT category,
                  COUNT(*) as total,
                  AVG(score) as avg_score,
                  MIN(score) as min_score,
                  MAX(score) as max_score,
                  SUM(CASE WHEN score >= 5.5 THEN 1 ELSE 0 END) as selected
           FROM scored_items
           WHERE domain = ? AND created_at >= ?
           GROUP BY category""",
        (domain, cutoff),
    ).fetchall()

    # 各信源的评分分布
    source_stats = s.conn.execute(
        """SELECT r.source_id,
                  COUNT(*) as total,
                  AVG(s.score) as avg_score,
                  SUM(CASE WHEN s.score >= 5.5 THEN 1 ELSE 0 END) as selected
           FROM scored_items s
           JOIN raw_items r ON s.raw_id = r.id
           WHERE s.domain = ? AND s.created_at >= ?
           GROUP BY r.source_id""",
        (domain, cutoff),
    ).fetchall()

    # 整体统计
    overall = s.conn.execute(
        """SELECT COUNT(*) as total,
                  AVG(score) as avg_score,
                  SUM(CASE WHEN score >= 5.5 THEN 1 ELSE 0 END) as selected
           FROM scored_items
           WHERE domain = ? AND created_at >= ?""",
        (domain, cutoff),
    ).fetchone()

    s.close()

    return {
        "domain": domain,
        "days": days,
        "overall": {
            "total": overall["total"],
            "avg_score": round(overall["avg_score"] or 0, 2),
            "selected": overall["selected"],
            "select_rate": round((overall["selected"] or 0) / max(overall["total"], 1) * 100, 1),
        },
        "by_category": [
            {
                "category": r["category"] or "uncategorized",
                "total": r["total"],
                "avg_score": round(r["avg_score"] or 0, 2),
                "selected": r["selected"],
            }
            for r in category_stats
        ],
        "by_source": [
            {
                "source_id": r["source_id"],
                "total": r["total"],
                "avg_score": round(r["avg_score"] or 0, 2),
                "selected": r["selected"],
            }
            for r in source_stats
        ],
    }


def generate_scoring_report(domain: str, days: int = 7) -> str:
    """生成评分分析报告（Markdown 格式）。"""
    data = analyze_scoring_distribution(domain, days)
    overall = data["overall"]

    lines = [
        f"# 评分分析报告 — {domain}",
        f"分析周期：最近 {days} 天",
        f"分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 整体统计",
        "",
        f"- 评分条目：{overall['total']} 条",
        f"- 平均分：{overall['avg_score']}",
        f"- 精选条目：{overall['selected']} 条",
        f"- 精选率：{overall['select_rate']}%",
        "",
        "## 分类分布",
        "",
        "| 分类 | 条目 | 平均分 | 精选 |",
        "|------|------|--------|------|",
    ]

    for cat in data["by_category"]:
        lines.append(f"| {cat['category']} | {cat['total']} | {cat['avg_score']} | {cat['selected']} |")

    lines.extend([
        "",
        "## 信源评分",
        "",
        "| 信源 | 条目 | 平均分 | 精选 |",
        "|------|------|--------|------|",
    ])

    for src in data["by_source"]:
        lines.append(f"| {src['source_id']} | {src['total']} | {src['avg_score']} | {src['selected']} |")

    # 异常检测
    anomalies = []
    for cat in data["by_category"]:
        if cat["avg_score"] > 9.0 and cat["total"] > 3:
            anomalies.append(f"分类 `{cat['category']}` 平均分异常高（{cat['avg_score']}），可能评分过松")
        if cat["avg_score"] < 4.0 and cat["total"] > 3:
            anomalies.append(f"分类 `{cat['category']}` 平均分异常低（{cat['avg_score']}），可能内容质量差")

    for src in data["by_source"]:
        if src["avg_score"] > 9.0 and src["total"] > 5:
            anomalies.append(f"信源 `{src['source_id']}` 平均分异常高（{src['avg_score']}），可能评分过松")
        if src["avg_score"] < 3.0 and src["total"] > 5:
            anomalies.append(f"信源 `{src['source_id']}` 平均分异常低（{src['avg_score']}），可能需要排除")

    if anomalies:
        lines.extend([
            "",
            "## 异常检测",
            "",
        ])
        for a in anomalies:
            lines.append(f"- ⚠️ {a}")

    return "\n".join(lines)


def save_scoring_report(domain: str, days: int = 7) -> Path:
    """保存评分分析报告到文件。"""
    report = generate_scoring_report(domain, days)
    output_dir = settings.project_root / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = output_dir / f"scoring-analysis-{domain}-{date}.md"
    path.write_text(report, encoding="utf-8")
    logger.info(f"评分分析报告已保存: {path}")
    return path


def suggest_adjustments(domain: str, days: int = 7) -> list[str]:
    """基于评分分布生成具体的 scoring.md prompt 调整建议。"""
    data = analyze_scoring_distribution(domain, days)
    suggestions = []

    # 整体精选率异常
    rate = data["overall"]["select_rate"]
    if rate > 80:
        suggestions.append(
            "整体精选率过高（{:.0f}%），建议在 scoring.md 中增加：\n"
            "  '评分要严格区分：7分以上必须包含具体数据（金额/用户数/增长率），泛泛而谈不超过5分'".format(rate)
        )
    elif rate < 10 and data["overall"]["total"] > 10:
        suggestions.append(
            "整体精选率过低（{:.0f}%），评分偏严，建议在 scoring.md 中放宽低分标准".format(rate)
        )

    # 分类维度异常
    for cat in data.get("by_category", []):
        if cat["avg_score"] > 9.0 and cat["total"] > 3:
            suggestions.append(
                "分类 '{}' 平均分异常高（{}），建议在 scoring.md 中强调该分类的评分标准".format(
                    cat["category"], cat["avg_score"])
            )
        if cat["avg_score"] < 4.0 and cat["total"] > 3:
            suggestions.append(
                "分类 '{}' 平均分异常低（{}），可能是该分类内容质量差，建议在 scoring.md 中降低该分类的打分门槛".format(
                    cat["category"], cat["avg_score"])
            )

    # 信源维度异常
    for src in data.get("by_source", []):
        if src["avg_score"] > 9.0 and src["total"] > 5:
            suggestions.append(
                "信源 '{}' 平均分异常高（{}），可能存在评分偏向，建议增加评分多样性要求".format(
                    src["source_id"], src["avg_score"])
            )

    if not suggestions:
        suggestions.append("当前评分分布正常，无需调整")

    return suggestions
