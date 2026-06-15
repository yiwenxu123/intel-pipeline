"""LLM 重试机制与线程安全测试。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from engine.filter.llm_client import LLMUsageTracker, chat, usage_tracker
from engine.filter.pipeline import ScoreStats


# ── 辅助：构造 mock OpenAI 响应 ──

def _make_mock_response(content: str, input_tokens: int = 10, output_tokens: int = 20):
    """构造一个模拟的 OpenAI ChatCompletion 响应对象。"""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


# ── 测试：LLM 调用失败时自动重试 ──

@pytest.fixture(autouse=True)
def _override_conftest_mock_llm():
    """覆盖 conftest.py 中的 autouse mock_llm fixture。

    conftest 的 mock_llm 会 monkeypatch engine.filter.llm_client.chat，
    导致本测试文件无法测试 chat() 内部的重试逻辑。
    这里用空 fixture 覆盖它，让 chat() 的真实实现生效。
    """
    pass


@pytest.fixture(autouse=True)
def _mock_openai_client():
    """Mock OpenAI 客户端单例，避免真实 API 调用。"""
    mock_client = MagicMock()
    with patch("engine.filter.llm_client.get_client", return_value=mock_client):
        yield mock_client


@pytest.fixture(autouse=True)
def _reset_usage_tracker():
    """每个测试前重置全局用量追踪器。"""
    usage_tracker.reset()
    yield
    usage_tracker.reset()


@pytest.fixture(autouse=True)
def _skip_retry_delay(monkeypatch):
    """跳过重试等待时间，加速测试。"""
    monkeypatch.setattr("engine.filter.llm_client.time.sleep", lambda _: None)


def test_retry_on_failure(_mock_openai_client):
    """LLM 调用失败时应自动重试，最多 3 次。"""
    # 模拟所有调用都抛出异常
    _mock_openai_client.chat.completions.create.side_effect = RuntimeError("API Error")

    result = chat(model="test-model", system="sys", user="usr")

    # 3 次全部失败，返回空字符串
    assert result == ""
    # 确认确实尝试了 3 次
    assert _mock_openai_client.chat.completions.create.call_count == 3


def test_retry_succeeds_on_third_attempt(_mock_openai_client):
    """前 2 次失败，第 3 次成功时应返回正确结果。"""
    mock_resp = _make_mock_response("成功响应", input_tokens=15, output_tokens=25)

    # 前 2 次抛异常，第 3 次返回正常结果
    _mock_openai_client.chat.completions.create.side_effect = [
        RuntimeError("第1次失败"),
        RuntimeError("第2次失败"),
        mock_resp,
    ]

    result = chat(model="test-model", system="sys", user="usr")

    # 第 3 次成功，返回响应内容
    assert result == "成功响应"
    assert _mock_openai_client.chat.completions.create.call_count == 3

    # 用量追踪器应只记录成功的那次调用
    usage = usage_tracker.get_usage()
    assert usage["calls"] == 1
    assert usage["input_tokens"] == 15
    assert usage["output_tokens"] == 25


def test_all_retries_exhausted_returns_empty(_mock_openai_client):
    """3 次全部失败后应返回空字符串。"""
    _mock_openai_client.chat.completions.create.side_effect = ConnectionError("网络不可达")

    result = chat(model="test-model", system="sys", user="usr")

    assert result == ""
    assert _mock_openai_client.chat.completions.create.call_count == 3

    # 全部失败，不应记录任何用量
    usage = usage_tracker.get_usage()
    assert usage["calls"] == 0
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0


# ── 测试：LLMUsageTracker 线程安全性 ──

def test_usage_tracker_thread_safety():
    """多线程并发调用 record() 时，计数应准确无误。"""
    tracker = LLMUsageTracker()
    thread_count = 50
    records_per_thread = 100

    def worker():
        for _ in range(records_per_thread):
            tracker.record(input_tokens=5, output_tokens=10)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    usage = tracker.get_usage()
    assert usage["calls"] == thread_count * records_per_thread
    assert usage["input_tokens"] == thread_count * records_per_thread * 5
    assert usage["output_tokens"] == thread_count * records_per_thread * 10
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


def test_usage_tracker_reset_thread_safety():
    """reset() 与 record() 并发时不应导致数据不一致。"""
    tracker = LLMUsageTracker()
    errors = []

    def recorder():
        try:
            for _ in range(200):
                tracker.record(input_tokens=1, output_tokens=1)
        except Exception as e:
            errors.append(e)

    def resetter():
        try:
            for _ in range(50):
                tracker.reset()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=recorder),
        threading.Thread(target=resetter),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 不应有异常
    assert len(errors) == 0

    # 最终状态应是合法的（非负整数）
    usage = tracker.get_usage()
    assert usage["calls"] >= 0
    assert usage["input_tokens"] >= 0
    assert usage["output_tokens"] >= 0


# ── 测试：ScoreStats 线程安全性 ──

def test_score_stats_thread_safety():
    """多线程并发调用 increment() 时，计数应准确无误。"""
    stats = ScoreStats()
    thread_count = 50
    increments_per_thread = 100

    def worker():
        for _ in range(increments_per_thread):
            stats.increment("json_parse_failures")

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = stats.get_stats()
    assert result["json_parse_failures"] == thread_count * increments_per_thread


def test_score_stats_multiple_keys_thread_safety():
    """多线程并发操作不同 key 时，各 key 计数应准确。"""
    stats = ScoreStats()
    thread_count = 30

    def worker_json():
        for _ in range(100):
            stats.increment("json_parse_failures")

    def worker_retry():
        for _ in range(80):
            stats.increment("retry_success")

    def worker_batch():
        for _ in range(60):
            stats.increment("batch_retries")

    threads = (
        [threading.Thread(target=worker_json) for _ in range(thread_count)]
        + [threading.Thread(target=worker_retry) for _ in range(thread_count)]
        + [threading.Thread(target=worker_batch) for _ in range(thread_count)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = stats.get_stats()
    assert result["json_parse_failures"] == thread_count * 100
    assert result["retry_success"] == thread_count * 80
    assert result["batch_retries"] == thread_count * 60


def test_score_stats_reset_thread_safety():
    """reset() 与 increment() 并发时不应导致数据不一致。"""
    stats = ScoreStats()
    errors = []

    def incrementer():
        try:
            for _ in range(200):
                stats.increment("json_parse_failures")
        except Exception as e:
            errors.append(e)

    def resetter():
        try:
            for _ in range(50):
                stats.reset()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=incrementer),
        threading.Thread(target=resetter),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    result = stats.get_stats()
    assert result["json_parse_failures"] >= 0
