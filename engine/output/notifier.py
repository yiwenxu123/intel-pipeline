"""推送通知模块：支持飞书/企业微信 Webhook。"""

from __future__ import annotations

import logging

import httpx

from engine.config import settings

logger = logging.getLogger(__name__)

DOMAIN_NAMES = {
    "elderly-care": "银发产业",
    "china-africa": "中非经贸",
}


def send_webhook(webhook_url: str, title: str, content: str) -> bool:
    """向 Webhook 发送消息。自动检测飞书/企业微信格式。

    Args:
        webhook_url: Webhook URL
        title: 消息标题
        content: 消息内容（纯文本，支持换行）

    Returns:
        是否发送成功
    """
    if not webhook_url:
        return False

    # 飞书 Webhook
    if "feishu.cn" in webhook_url or "larksuite.com" in webhook_url:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "yellow",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
    # 企业微信 Webhook
    elif "qyapi.weixin.qq.com" in webhook_url:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"**{title}**\n\n{content}",
            },
        }
    # 通用 Webhook（JSON POST）
    else:
        payload = {
            "title": title,
            "content": content,
        }

    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"推送成功: {title}")
        return True
    except Exception as e:
        logger.error(f"推送失败: {e}")
        return False


def notify_report(
    domain_name: str,
    stats: dict,
    top_items: list[dict],
    report_extra: dict | None = None,
) -> bool:
    """推送情报日报摘要。

    Args:
        domain_name: 领域中文名
        stats: 统计数据 {total_fetched, selected}
        top_items: Top 条目列表 [{title, score, category}]
    """
    webhook_url = settings.notify_webhook
    if not webhook_url:
        return False

    from datetime import datetime
    date = datetime.now().strftime("%Y-%m-%d")

    display_name = DOMAIN_NAMES.get(domain_name, domain_name)
    total = stats.get("total_fetched", 0)
    selected = stats.get("selected", 0)
    rate = f"{selected / max(total, 1) * 100:.1f}%" if total else "0%"

    title = f"📊 {display_name}情报 | {date}"

    lines = [
        f"采集 **{total}** 条 → 精选 **{selected}** 条（精选率 {rate}）",
        "",
    ]

    extra_stats = (report_extra or {}).get("stats") or stats
    cat_top3 = extra_stats.get("category_top3") or []
    if cat_top3:
        parts = [f"{c.get('category', '?')} {c.get('count', 0)}条" for c in cat_top3]
        lines.append(f"**📂 分类 Top3**：{' · '.join(parts)}")
        lines.append("")

    top_ents = extra_stats.get("top_entities") or []
    if top_ents:
        lines.append(f"**📌 热点实体**：{' · '.join(top_ents[:5])}")
        lines.append("")

    if top_items:
        lines.append("**🔴 今日精选：**")
        for i, item in enumerate(top_items[:3], 1):
            score = item.get("score", 0)
            item_title = item.get("headline") or item.get("title_display") or item.get("title", "")
            takeaway = item.get("takeaway") or item.get("reason") or ""
            if takeaway:
                lines.append(f"{i}. **[{score:.1f}] {item_title}**")
                lines.append(f"   {takeaway}")
            else:
                lines.append(f"{i}. [{score:.1f}] {item_title}")
        lines.append("")

    from engine.config import settings as s
    host = f"http://{s.api_host}:{s.api_port}" if s.api_host != "0.0.0.0" else f"http://localhost:{s.api_port}"
    link = f"{host}/?domain={domain_name}&date={date}"
    lines.append(f"[查看今日情报 →]({link})")

    return send_webhook(webhook_url, title, "\n".join(lines))


def notify_pipe_alert(
    domain_name: str,
    *,
    error: str | None = None,
    fetch_errors: int = 0,
    fetch_error_sources: list[str] | None = None,
    duration_seconds: float = 0,
    scored: int = 0,
) -> bool:
    """pipe 异常告警：阶段失败或采集失败信源过多时推送（不受 notify 开关影响）。"""
    webhook_url = settings.notify_webhook
    if not webhook_url:
        return False

    display_name = DOMAIN_NAMES.get(domain_name, domain_name)
    title = f"⚠️ {display_name}情报管道告警"

    lines = []
    if error:
        lines.append(f"**管道错误**：{error}")
    if fetch_errors > 0:
        lines.append(f"**采集失败**：{fetch_errors} 个信源")
        sources = fetch_error_sources or []
        if sources:
            preview = "、".join(sources[:8])
            if len(sources) > 8:
                preview += f" 等 {len(sources)} 个"
            lines.append(f"失败信源：{preview}")
    lines.append(f"筛选 **{scored}** 条 | 耗时 **{duration_seconds}s**")
    lines.append("")
    lines.append("请检查 Dashboard 系统健康 Tab 或运行：")
    lines.append(f"`python -m engine.cli -d {domain_name} evolve sources`")

    return send_webhook(webhook_url, title, "\n".join(lines))


def notify_unscored_backlog(domain_name: str, unscored_count: int, threshold: int) -> bool:
    """待评分堆积告警。"""
    webhook_url = settings.notify_webhook
    if not webhook_url or unscored_count < threshold:
        return False

    display_name = DOMAIN_NAMES.get(domain_name, domain_name)
    title = f"📋 {display_name}待评分堆积告警"
    content = (
        f"窗口内待评分条目 **{unscored_count}** 条（阈值 {threshold}）\n\n"
        "建议操作：\n"
        "1. 运行 `pipe` 消化积压（可调大 max_items）\n"
        "2. 或缩小 `INTEL_SCORE_WINDOW_DAYS`\n"
        "3. 检查 scheduler 是否正常运行"
    )
    return send_webhook(webhook_url, title, content)


def notify_scoring_calibration(domain_name: str, calibrations: list[dict]) -> bool:
    """评分校准建议推送（pipe 后自动触发）。"""
    webhook_url = settings.notify_webhook
    if not webhook_url or not calibrations:
        return False

    display_name = DOMAIN_NAMES.get(domain_name, domain_name)
    title = f"📋 {display_name}评分校准建议"
    lines = [f"共 **{len(calibrations)}** 条建议，下次评分将自动注入：", ""]
    for i, cal in enumerate(calibrations[:5], 1):
        instruction = cal.get("instruction") or cal.get("message") or str(cal)
        lines.append(f"{i}. {instruction[:120]}")
    if len(calibrations) > 5:
        lines.append(f"... 另有 {len(calibrations) - 5} 条")
    lines.append("")
    lines.append(f"审阅：`domains/{domain_name}/scoring.md`")
    return send_webhook(webhook_url, title, "\n".join(lines))
