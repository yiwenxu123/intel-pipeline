"""推送通知模块：支持飞书/企业微信 Webhook。"""

from __future__ import annotations

import json
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


def notify_report(domain_name: str, stats: dict, top_items: list[dict]) -> bool:
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

    if top_items:
        lines.append("**🔴 热门：**")
        for i, item in enumerate(top_items[:5], 1):
            score = item.get("score", 0)
            item_title = item.get("title_display") or item.get("title", "")
            lines.append(f"{i}. [{score:.1f}] {item_title}")
        lines.append("")

    from engine.config import settings as s
    host = f"http://{s.api_host}:{s.api_port}" if s.api_host != "0.0.0.0" else f"http://localhost:{s.api_port}"
    link = f"{host}/?domain={domain_name}&date={date}"
    lines.append(f"[查看今日情报 →]({link})")

    return send_webhook(webhook_url, title, "\n".join(lines))
