"""启动前配置检查。"""

from __future__ import annotations

from engine.config import settings


def check_llm_config() -> list[str]:
    """返回错误列表，空表示通过。"""
    errors: list[str] = []
    if not settings.llm_api_key:
        errors.append("INTEL_LLM_API_KEY 未配置")
    if not settings.llm_base_url:
        errors.append("INTEL_LLM_BASE_URL 未配置")
    if not settings.llm_scoring_model:
        errors.append("INTEL_LLM_SCORING_MODEL 未配置")
    return errors


def run_preflight() -> tuple[bool, list[str]]:
    errors = check_llm_config()
    return len(errors) == 0, errors
