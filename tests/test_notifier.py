"""notifier 模块单元测试。"""

from __future__ import annotations

from unittest.mock import patch

from engine.output.notifier import (
    notify_pipe_alert,
    notify_scoring_calibration,
    notify_unscored_backlog,
    send_webhook,
)


@patch("engine.output.notifier.httpx.post")
def test_send_webhook_feishu(mock_post):
    mock_post.return_value.raise_for_status = lambda: None
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    ok = send_webhook(url, "标题", "内容")
    assert ok is True
    payload = mock_post.call_args.kwargs["json"]
    assert payload["msg_type"] == "interactive"


@patch("engine.output.notifier.settings")
@patch("engine.output.notifier.send_webhook")
def test_notify_pipe_alert_on_error(mock_send, mock_settings):
    mock_settings.notify_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    mock_send.return_value = True
    ok = notify_pipe_alert(
        "china-africa",
        error="采集失败: timeout",
        fetch_errors=5,
        fetch_error_sources=["src_a", "src_b"],
        duration_seconds=12.3,
        scored=0,
    )
    assert ok is True
    title = mock_send.call_args[0][1]
    content = mock_send.call_args[0][2]
    assert "告警" in title
    assert "采集失败" in content
    assert "src_a" in content


@patch("engine.output.notifier.settings")
def test_notify_pipe_alert_no_webhook(mock_settings):
    mock_settings.notify_webhook = ""
    ok = notify_pipe_alert("elderly-care", error="fail")
    assert ok is False


@patch("engine.output.notifier.settings")
@patch("engine.output.notifier.send_webhook")
def test_notify_unscored_backlog(mock_send, mock_settings):
    mock_settings.notify_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    mock_send.return_value = True
    ok = notify_unscored_backlog("elderly-care", 150, 100)
    assert ok is True
    assert "150" in mock_send.call_args[0][2]

    mock_send.reset_mock()
    ok = notify_unscored_backlog("elderly-care", 50, 100)
    assert ok is False
    mock_send.assert_not_called()


@patch("engine.output.notifier.settings")
@patch("engine.output.notifier.send_webhook")
def test_notify_scoring_calibration(mock_send, mock_settings):
    mock_settings.notify_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    mock_send.return_value = True
    cals = [{"instruction": "分类 policy 平均分偏高，请严格评分"}]
    ok = notify_scoring_calibration("elderly-care", cals)
    assert ok is True
    assert "校准" in mock_send.call_args[0][1]
