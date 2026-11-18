"""管理员可配置的 LiteLLM Router 参数（不包含密钥）。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modstore_server.api.deps import _require_admin
from modstore_server.llm_router_config import (
    RouterConfigError,
    public_state,
    read_state_cached,
    save_state,
    settings,
)
from modstore_server.models import User

router = APIRouter(prefix="/admin/llm-router-config", tags=["llm-router-config"])


class RouterConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    routing_strategy: str = Field(min_length=1, max_length=64)
    num_retries: int = Field(ge=0, le=10)
    cooldown_seconds: float = Field(ge=0, le=3600)
    allowed_fails: int = Field(ge=0, le=20)
    max_parallel: int = Field(ge=0, le=1000)
    mid_stream_fallback: bool
    request_timeout_seconds: float = Field(ge=1, le=600)
    stream_timeout_seconds: float = Field(ge=1, le=1800)
    platform_fallbacks: list[str] = Field(default_factory=list, max_length=20)


def _translate(error: RouterConfigError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


@router.get("")
async def get_router_config(admin: Annotated[User, Depends(_require_admin)]):
    try:
        state = await asyncio.to_thread(read_state_cached)
        return {
            "ok": True,
            "config": public_state(state),
            "effective": settings(),
        }
    except RouterConfigError as exc:
        raise _translate(exc) from None


@router.put("")
async def put_router_config(
    payload: RouterConfigInput,
    admin: Annotated[User, Depends(_require_admin)],
):
    try:
        state = await asyncio.to_thread(
            save_state,
            payload.model_dump(),
            actor=f"admin:{admin.id}",
        )
        return {
            "ok": True,
            "message": "模型路由配置已保存",
            "config": public_state(state),
            "effective": settings(),
        }
    except RouterConfigError as exc:
        raise _translate(exc) from None
