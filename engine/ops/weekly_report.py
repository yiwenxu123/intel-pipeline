"""每周运营周报。"""

from __future__ import annotations

from datetime import datetime

from engine.config import settings
from engine.domain import load_domain
from engine.ops.quality_metrics import compute_quality_metrics
from engine.output.notifier import send_webhook


def generate_weekly_report_markdown(domain_name: str) -> str:
    domain = load_domain(domain_name)
    m = compute_quality_metrics(domain_name)
    metrics = m["metrics"]
    dod = m["dod"]
    pipe = metrics["pipe_7d"]
    fb = metrics["feedback_7d"]

    lines = [
        f"# {domain.name} 运营周报",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 核心指标",
        f"- 待评分积压：**{metrics['unscored_count']}**（目标 < {m['targets']['unscored_count']}）"
        f" {'✅' if dod['D1_unscored_ok'] else '❌'}",
        f"- 简报覆盖率：**{metrics['briefing_coverage_pct']}%**（目标 ≥ {m['targets']['briefing_coverage_pct']}%）"
        f" {'✅' if dod['D2_briefing_ok'] else '❌'}",
        f"- 规则拒绝累计：**{metrics['rule_rejected_count']}** 条",
        f"- 7日 pipe 成功率：**{pipe['success_rate_pct']}%**（{pipe['success_runs']}/{pipe['total_runs']}）",
        f"- 最近采集失败信源：**{metrics['last_fetch_errors']}**",
        "",
        "## 评分分布",
        f"- 8+：{metrics['score_bands']['8+']} | 6-8：{metrics['score_bands']['6-8']} | "
        f"4-6：{metrics['score_bands']['4-6']} | <4：{metrics['score_bands']['<4']}",
        "",
        "## 用户反馈（7天）",
        f"- 总计 {fb['total']} 次 | 👍 {fb['upvotes']} | 👎 {fb['downvotes']}",
    ]
    if fb["total"] < 5:
        lines.append("- ⚠️ 反馈样本不足，请运行 `quality-review` 人工验收")

    lines.extend([
        "",
        "## 建议动作",
    ])
    if not dod["D1_unscored_ok"]:
        lines.append("- 运行 `python -m engine.cli -d {0} pipe` 消化积压".format(domain_name))
    if not dod["D2_briefing_ok"]:
        lines.append("- 运行 `briefing-backfill` 补全历史简报")
    if metrics["last_fetch_errors"] >= 3:
        lines.append("- 检查健康 Tab 失败信源，运行 `evolve sources`")

    return "\n".join(lines)


def save_weekly_report(domain_name: str) -> tuple[str, str]:
    md = generate_weekly_report_markdown(domain_name)
    out_dir = settings.project_root / settings.report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"weekly-{date}-{domain_name}.md"
    path.write_text(md, encoding="utf-8")
    return str(path), md


def notify_weekly_report(domain_name: str) -> bool:
    if not settings.notify_webhook:
        return False
    _, md = save_weekly_report(domain_name)
    from engine.output.notifier import DOMAIN_NAMES

    title = f"📋 {DOMAIN_NAMES.get(domain_name, domain_name)}运营周报"
    return send_webhook(settings.notify_webhook, title, md)
