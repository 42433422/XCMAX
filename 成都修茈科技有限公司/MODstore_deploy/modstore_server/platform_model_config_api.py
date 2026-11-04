"""Administrator-only platform model settings; secrets are write-only."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from modstore_server.api.deps import _require_admin
from modstore_server.llm_crypto import fernet_configured
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
)
from modstore_server.models import User
from modstore_server.platform_model_config import (
    BYOK_POLICY,
    SCOPE,
    SCOPE_DESCRIPTION,
    PlatformConfigError,
    normalize_base_url,
    prepare_config,
    public_config,
    read_state,
    save_config,
)


class NoStoreRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def protected_response(request: Request):
            try:
                response = await handler(request)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response

        return protected_response


router = APIRouter(
    prefix="/admin/platform-model-config",
    tags=["platform-model-config"],
    route_class=NoStoreRoute,
)


class PlatformModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=256)
    api_key: SecretStr | None = None
    make_default: bool = True
    expected_revision: str | None = Field(default=None, max_length=64)


def _scope(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "default_provider": state.get("default_provider"),
        "effective_scope": SCOPE,
        "scope_description": SCOPE_DESCRIPTION,
        "byok_policy": BYOK_POLICY,
    }


async def _body(request: Request, provider: str) -> dict[str, Any]:
    if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        raise HTTPException(400, "请选择支持 OpenAI 兼容协议的模型供应商")
    try:
        raw = await request.body()
        if len(raw) > 16384:
            raise ValueError("too large")
        body = PlatformModelInput.model_validate_json(raw)
    except (ValueError, ValidationError):
        # FastAPI's default validation response includes raw input values.
        raise HTTPException(400, "模型配置格式不正确，请检查必填项和字段长度") from None
    return body.model_dump(exclude_unset=True)


def _translate(error: PlatformConfigError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


def _pin_url(url: str):
    from modstore_server.openapi_connector_runtime import (
        OutboundBlocked,
        pin_url_outbound_safe,
    )

    try:
        return pin_url_outbound_safe(url)
    except (OutboundBlocked, OSError, ValueError):
        raise PlatformConfigError("API 地址无法安全连接，仅允许可解析的公网 HTTPS 地址") from None


@router.get("")
async def get_platform_model_config(admin: Annotated[User, Depends(_require_admin)]):
    from modstore_server.llm_api import _provider_labels

    try:
        state = await asyncio.to_thread(read_state)
        labels = _provider_labels()
        labels["openai"] = "OpenAI / OpenAI 兼容"
        providers = [
            {**public_config(provider, state), "label": labels.get(provider, provider)}
            for provider in KNOWN_PROVIDERS
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        ]
        return {
            "ok": True,
            "encryption_ready": fernet_configured(),
            "providers": providers,
            **_scope(state),
        }
    except PlatformConfigError as exc:
        raise _translate(exc) from None


@router.put("/{provider}")
async def put_platform_model_config(
    provider: str, request: Request, admin: Annotated[User, Depends(_require_admin)]
):
    payload = await _body(request, provider)
    payload.setdefault("display_name", "")
    try:
        base = normalize_base_url(payload["base_url"])
        await asyncio.to_thread(_pin_url, base)
        state = await asyncio.to_thread(save_config, provider, payload, actor=f"admin:{admin.id}")
        from modstore_server.llm_catalog import clear_all_catalog_cache

        clear_all_catalog_cache()
        return {
            "ok": True,
            "message": "平台模型配置已保存",
            "config": public_config(provider, state),
            **_scope(state),
        }
    except PlatformConfigError as exc:
        raise _translate(exc) from None


async def _probe(provider: str, config: dict[str, str], key: str) -> bool:
    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.platform_model_config import PlatformApiKey

    result = await chat_dispatch(
        provider,
        api_key=PlatformApiKey(key, {**config, "revision": "unsaved-probe"}),
        base_url=config["base_url"],
        model=config["model"],
        messages=[{"role": "user", "content": "Reply OK."}],
        max_tokens=8,
    )
    if result.get("status") in (401, 403):
        raise PlatformConfigError("连接测试失败：供应商拒绝了密钥或模型权限", 502)
    return bool(result.get("ok"))


@router.post("/{provider}/test")
async def test_platform_model_config(
    provider: str, request: Request, admin: Annotated[User, Depends(_require_admin)]
):
    payload = await _body(request, provider)
    payload.setdefault("display_name", "")
    started = time.perf_counter()
    try:
        state = await asyncio.to_thread(read_state)
        config, key = prepare_config(provider, payload, state)
        if not await asyncio.wait_for(_probe(provider, config, key), timeout=20.0):
            raise PlatformConfigError("连接测试失败：供应商未返回有效的对话响应", 502)
        return {
            "ok": True,
            "message": "连接测试成功，配置尚未保存",
            "tested_model": config["model"],
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except PlatformConfigError as exc:
        raise _translate(exc) from None
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "连接测试超时，请检查 API 地址和网络") from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
        raise HTTPException(502, "连接测试失败，请检查 API 地址、模型和网络") from None
