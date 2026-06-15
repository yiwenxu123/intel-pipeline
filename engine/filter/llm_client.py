"""LLM 客户端封装，支持 token 用量追踪与自动重试。"""

from __future__ import annotations

import logging
import threading
import time

from openai import OpenAI

from engine.config import settings

logger = logging.getLogger(__name__)

# LLM 调用重试参数
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 3, 5]  # 秒


class LLMUsageTracker:
    """线程安全的 LLM 用量追踪器。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._call_count: int = 0
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def reset(self):
        """重置用量计数器（线程安全）。"""
        with self._lock:
            self._call_count = 0
            self._input_tokens = 0
            self._output_tokens = 0

    def record(self, input_tokens: int, output_tokens: int):
        """记录一次调用的 token 用量（线程安全）。"""
        with self._lock:
            self._call_count += 1
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def get_usage(self) -> dict:
        """获取当前用量统计快照（线程安全）。"""
        with self._lock:
            return {
                "calls": self._call_count,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": self._input_tokens + self._output_tokens,
            }


# 模块级单例
usage_tracker = LLMUsageTracker()

# 向后兼容的函数接口
def reset_usage():
    """重置 token 用量计数器。"""
    usage_tracker.reset()


def get_usage() -> dict:
    """获取当前 token 用量统计。"""
    return usage_tracker.get_usage()


# OpenAI 客户端单例
_client: OpenAI | None = None
_client_lock = threading.Lock()


def get_client() -> OpenAI:
    """获取 OpenAI 客户端单例（线程安全）。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(
                    base_url=settings.llm_base_url,
                    api_key=settings.llm_api_key,
                    timeout=120.0,  # 120 秒超时，防止 API 卡死阻塞流水线
                )
    return _client


def chat(model: str, system: str, user: str, temperature: float = 0.3) -> str:
    """调用 LLM，返回文本响应。自动追踪 token 用量，支持重试。

    重试策略：最多 3 次，延迟 1/3/5 秒指数退避。
    """
    client = get_client()

    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
            usage_tracker.record(
                resp.usage.prompt_tokens if resp.usage else 0,
                resp.usage.completion_tokens if resp.usage else 0,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    f"LLM 调用失败（第{attempt + 1}次），{delay}s 后重试: {e}"
                )
                time.sleep(delay)
            else:
                logger.error(f"LLM 调用失败（已重试{_MAX_RETRIES}次）model={model}: {e}")

    return ""
