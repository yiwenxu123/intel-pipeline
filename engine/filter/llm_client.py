"""LLM 客户端封装。"""

from __future__ import annotations

import logging

from openai import OpenAI

from engine.config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
    return _client


def chat(model: str, system: str, user: str, temperature: float = 0.3) -> str:
    """调用 LLM，返回文本响应。"""
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
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"LLM 调用失败 model={model}: {e}")
        return ""
