"""LLM 客户端封装，支持 token 用量追踪。"""

from __future__ import annotations

import logging
import threading

from openai import OpenAI

from engine.config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None
_lock: threading.Lock = threading.Lock()

# Token 用量追踪（模块级别，CLI 可在每次 run 前 reset）
_call_count: int = 0
_input_tokens: int = 0
_output_tokens: int = 0


def reset_usage():
    """重置 token 用量计数器。"""
    global _call_count, _input_tokens, _output_tokens
    _call_count = 0
    _input_tokens = 0
    _output_tokens = 0


def get_usage() -> dict:
    """获取当前 token 用量统计。"""
    return {
        "calls": _call_count,
        "input_tokens": _input_tokens,
        "output_tokens": _output_tokens,
        "total_tokens": _input_tokens + _output_tokens,
    }


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=120.0,  # 120 秒超时，防止 API 卡死阻塞流水线
        )
    return _client


def chat(model: str, system: str, user: str, temperature: float = 0.3) -> str:
    """调用 LLM，返回文本响应。自动追踪 token 用量（线程安全）。"""
    global _call_count, _input_tokens, _output_tokens
    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        with _lock:
            _call_count += 1
            if resp.usage:
                _input_tokens += resp.usage.prompt_tokens or 0
                _output_tokens += resp.usage.completion_tokens or 0
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"LLM 调用失败 model={model}: {e}")
        return ""
