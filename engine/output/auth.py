"""API 写操作鉴权。"""

from __future__ import annotations

from fastapi import Header, HTTPException

from engine.config import settings


def verify_write_token(authorization: str | None = Header(default=None)) -> None:
    """POST 端点依赖：配置了 INTEL_API_TOKEN 时要求 Bearer Token。"""
    token = settings.api_token
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要 Authorization: Bearer <token>")
    if authorization.removeprefix("Bearer ").strip() != token:
        raise HTTPException(status_code=401, detail="Token 无效")
