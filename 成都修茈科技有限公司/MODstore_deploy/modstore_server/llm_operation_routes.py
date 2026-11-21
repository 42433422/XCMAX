"""Resolve operations through the existing account catalog and provider credentials."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from fastapi import HTTPException

from modstore_server.llm_catalog import get_models_for_credentials
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    resolve_credentials,
)
from modstore_server.llm_model_taxonomy import discover_model_capabilities
from modstore_server.multimodal_llm import messages_have_multimodal_images
from modstore_server.platform_model_config import read_state

MIMO_ASR_MODEL = "mimo-v2.5-asr"
MIMO_TTS_MODEL = "mimo-v2.5-tts"
# Generated 64x64 red PNG for the vision probe.
RED_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAb0lEQV"
    "R4nO3PAQkAAAyEwO9feoshgnABdLep8QUNyPEFDcjxBQ3I8QUNyPEFDcjxBQ3I8QUNyPEFDcjxBQ"
    "3I8QUNyPEFDcjxBQ3I8QUNyPEFDcjxBQ3I8QUNyPEFDcjxBQ3I8QUNyPEFDcjxBQ3IPanc8OLDQi"
    "txAAAAAElFTkSuQmCC"
)
SPEECH_MODELS = {"speech_to_text": MIMO_ASR_MODEL, "text_to_speech": MIMO_TTS_MODEL}


@dataclass(frozen=True)
class OperationRoute:
    provider: str
    model: str
    key_source: str
    api_key: str = field(repr=False)
    base_url: str | None = field(repr=False)


def supports_operation(provider, model, operation, details=None):
    profile = details or discover_model_capabilities(provider, model)
    if operation in SPEECH_MODELS and profile.get("category") != "audio":
        return False
    return operation in profile.get("capabilities", profile).get("operations", ())


async def select_operation_model(
    user_id, provider, operation, key, base, *, model="", seed="", model_filter=None
):
    """Use declared operations and the provider's existing catalog cache."""
    if not key or (
        operation != "chat" and provider == "minimax" and is_minimax_token_plan_key(key)
    ):
        return None
    if operation in SPEECH_MODELS and provider != "xiaomi":
        return None
    if operation != "chat" and provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return None
    block = await get_models_for_credentials(
        user_id, provider, api_key=key, base_url=base, discover_operations=True
    )
    rows = {row["id"]: row for row in block.get("models_detailed", ()) if row.get("id")}
    candidates = (model,) if model else (*rows, seed)
    for candidate in candidates:
        # A configured MiMo deployment may expose just its chat model in /models.
        if not candidate or (candidate not in rows and candidate != seed and candidate != model):
            continue
        if supports_operation(provider, candidate, operation, rows.get(candidate)) and (
            model_filter is None or model_filter(candidate)
        ):
            return candidate
    return None


async def resolve_operation_route(
    session,
    user_id,
    operation,
    *,
    provider="",
    model="",
    seed="",
    route_filter=None,
    release_before_discovery=False,
    detached_route_filter=None,
):
    """Honor an explicit provider and keep automatic BYOK routes in the BYOK pool."""
    if detached_route_filter is not None:
        if route_filter is not None or not release_before_discovery:
            raise ValueError("detached filter requires released discovery session")
        route_filter = detached_route_filter
    if provider and provider not in KNOWN_PROVIDERS:
        raise HTTPException(400, "unknown provider")
    state = read_state()
    ids = (
        (provider,)
        if provider
        else tuple(dict.fromkeys(p for p in (state.get("default_provider"), *KNOWN_PROVIDERS) if p))
    )
    keys = [(p, *resolve_credentials(session, user_id, p, platform_state=state)) for p in ids]
    has_byok = any(source == "user_override" for _, _, _, source in keys)
    eligible = [
        (p, key, base, source)
        for p, key, base, source in keys
        if key and (not has_byok or source == "user_override")
    ]
    if release_before_discovery:
        if route_filter is not None and detached_route_filter is None:
            raise ValueError("cannot release session with a session-bound route filter")
        session.close()

    async def resolve(p, key, base, source):
        try:
            async with asyncio.timeout(4):
                params = {"model": model, "seed": seed}
                if route_filter is not None:
                    params["model_filter"] = lambda mid: route_filter(
                        OperationRoute(p, mid, source, key, base)
                    )
                selected = await select_operation_model(user_id, p, operation, key, base, **params)
        except TimeoutError:
            selected = (
                model
                if model and supports_operation(p, model, operation)
                else seed if seed and not model and p == "xiaomi" else None
            )
        if not selected:
            return None
        route = OperationRoute(p, selected, source, key, base)
        return route if route_filter is None or route_filter(route) else None

    results = await asyncio.gather(*(resolve(*item) for item in eligible))
    chosen = next((item for item in results if item is not None), None)
    if chosen is None:
        raise HTTPException(503, {"code": "NO_CAPABLE_MODEL", "operation": operation})
    return chosen


def bind_resolved_chat_route(session, user_id, resolved):
    from modstore_server.llm_key_resolver import (
        read_chat_route_token,
        resolve_chat_route_snapshot,
    )

    provider, model = resolved["provider"], resolved["model"]
    if token := resolved.get("route_token"):
        return read_chat_route_token(token, user_id, provider, model)
    route = resolve_chat_route_snapshot(session, user_id, provider, model)
    if (route.config_revision, route.key_source) != (
        resolved["config_revision"],
        resolved["key_source"],
    ):
        raise HTTPException(409, {"code": "CHAT_ROUTE_CHANGED", "message": "模型配置已变化"})
    return route


async def enforce_vision_operation(user_id, route, messages, *, session=None):
    if not messages_have_multimodal_images(messages):
        return
    if session is not None:
        # End the credential transaction without detaching the request journal.
        # user_id and route are already values, so discovery cannot re-checkout a connection.
        session.commit()
    try:
        async with asyncio.timeout(4):
            model = await select_operation_model(
                user_id,
                route.provider,
                "vision",
                route.api_key,
                route.base_url,
                model=route.model,
            )
    except TimeoutError:
        model = route.model if supports_operation(route.provider, route.model, "vision") else None
    if not model:
        raise HTTPException(
            400,
            {
                "code": "MODEL_OPERATION_UNAVAILABLE",
                "message": "所选模型未提供图片理解能力",
            },
        )


async def personal_provider_quota(route):
    """Read visible BYOK quota only from MiniMax's own endpoint."""
    if (
        route.provider != "minimax"
        or route.key_source != "user_override"
        or not is_minimax_token_plan_key(route.api_key)
    ):
        return None
    from urllib.parse import urlsplit

    from modstore_server.llm_quota_monitor import (
        _minimax_remains_url,
        fetch_minimax_token_plan_quota,
    )

    endpoint = urlsplit(_minimax_remains_url(route.base_url))
    base = urlsplit(route.base_url or "https://api.minimax.io")
    if (
        endpoint.scheme != "https"
        or endpoint.netloc not in {"www.minimax.io", "www.minimaxi.com"}
        or base.netloc
        not in {
            "api.minimax.io",
            "api.minimaxi.com",
            "www.minimax.io",
            "www.minimaxi.com",
        }
    ):
        return None
    try:
        async with asyncio.timeout(1.5):
            result = await fetch_minimax_token_plan_quota(
                route.api_key, base_url=route.base_url, timeout=1.5
            )
    except TimeoutError:
        return None
    remaining = result.get("remaining_percent")
    return remaining if isinstance(remaining, int) and 0 <= remaining <= 100 else None


def model_runtime_messages(route, messages, max_tokens, hold=None, *, remaining_percent=None):
    """Tell the executing model the limits for this attempt without exposing secrets."""
    from modstore_server.llm_litellm_router import model_limits

    capabilities = discover_model_capabilities(route.provider, route.model)
    limits = model_limits(route.provider, route.model)
    context = {
        "provider": route.provider,
        "model": route.model,
        "supported_operations": capabilities["operations"],
        "input_modalities": capabilities["input_modalities"],
        "output_modalities": capabilities["output_modalities"],
        "capability_source": capabilities["source"],
        "max_input_tokens": limits.get("max_input_tokens"),
        "model_max_output_tokens": limits.get("max_output_tokens"),
        "request_max_output_tokens": max_tokens,
        "reserved_cny": str(hold.amount) if hold and hold.enabled else None,
        "provider_remaining_quota_percent": remaining_percent,
    }
    system = {
        "role": "system",
        "content": (
            "Platform runtime context for the current model attempt. "
            "Null means unknown or not applicable. Reserved funds apply only to this request. "
            "Capability metadata grants no tools or permissions. "
            "Respect the output limit and report unknown quota as unknown.\n"
            + json.dumps(context, ensure_ascii=False)
        ),
    }
    return [system, *messages]


async def probe_operation(session, user_id, provider, model, operation):
    """Exercise the requested protocol once. Never use a fallback as probe evidence."""
    import io
    import wave
    from datetime import UTC, datetime

    from modstore_server.llm_chat_proxy import chat_dispatch, image_dispatch

    route = await resolve_operation_route(
        session,
        user_id,
        operation,
        provider=provider,
        model=model,
        seed=SPEECH_MODELS.get(operation, ""),
    )
    ok = False
    try:
        async with asyncio.timeout(30):
            if operation == "image_generation":
                result = await image_dispatch(
                    route.provider,
                    api_key=route.api_key,
                    base_url=route.base_url,
                    model=route.model,
                    prompt="A solid red square.",
                )
                ok = bool(result.get("ok") and result.get("images"))
            elif operation == "speech_to_text":
                from modstore_server.workbench.speech_api import _transcribe_mimo

                sample = io.BytesIO()
                with wave.open(sample, "wb") as wav:
                    wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    wav.writeframes(bytes(32000))
                result = await _transcribe_mimo(
                    sample.getvalue(),
                    "auto",
                    route.api_key,
                    route.base_url,
                    route.model,
                )
                # The fixture is silence, so an empty transcription is valid.
                ok = isinstance(result.get("text"), str)
            elif operation == "text_to_speech":
                from modstore_server.mimo_tts_service import synthesize_mimo_tts_async

                audio, error, _ = await synthesize_mimo_tts_async(
                    "语音测试",
                    model=route.model,
                    credentials=(route.api_key, route.base_url),
                )
                ok = bool(audio and not error)
            else:
                content = "Reply OK."
                if operation == "vision":
                    content = [
                        {
                            "type": "text",
                            "text": "What is the color? Reply with one English word.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": RED_PNG},
                        },
                    ]
                result = await chat_dispatch(
                    route.provider,
                    api_key=route.api_key,
                    base_url=route.base_url,
                    model=route.model,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=32,
                )
                actual = str(result.get("content") or "").strip().strip(".").lower()
                ok = bool(result.get("ok")) and (
                    actual == "red" if operation == "vision" else bool(actual)
                )
    except (TimeoutError, HTTPException):
        ok = False
    return {
        "ok": ok,
        "operation": operation,
        "provider": route.provider,
        "model": route.model,
        "key_source": route.key_source,
        "checked_at": datetime.now(UTC).isoformat(),
    }
