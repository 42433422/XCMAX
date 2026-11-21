"""Use the pinned OpenAI SDK for the existing OpenCode Responses protocol.

The authenticated remote adapter restores the approved portfolio scope. This
module owns each outbound call and its SQL reservation; it does not trust worker
usage reports or proxy estimates. SDK parsing/stream cleanup remain upstream.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any, cast

from modstore_server import strategic_portfolio_usage as budget
from modstore_server.strategic_portfolio import PortfolioError, _json

_FIELDS = {
    "model",
    "input",
    "instructions",
    "max_output_tokens",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "reasoning",
    "text",
    "temperature",
    "top_p",
    "metadata",
    "store",
    "stream",
    "include",
    "previous_response_id",
    "background",
    "service_tier",
    "prompt_cache_key",
    "prompt_cache_retention",
    "safety_identifier",
    "user",
    "truncation",
}


def _text_content(value: Any) -> bool:
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(
        isinstance(part, dict)
        and part.get("type") in {"input_text", "output_text", "refusal"}
        and isinstance(part.get("text", part.get("refusal")), str)
        for part in value
    )


def _explicit_input(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        kind = item.get("type", "message")
        if kind == "message":
            if item.get("role") not in {
                "user",
                "assistant",
                "system",
                "developer",
            } or not _text_content(item.get("content")):
                return False
        elif kind == "function_call":
            if any(not isinstance(item.get(key), str) for key in ("call_id", "name", "arguments")):
                return False
        elif kind == "function_call_output":
            if not isinstance(item.get("call_id"), str) or not _text_content(item.get("output")):
                return False
        elif kind == "reasoning":
            # Manual stateless context uses the provider's encrypted reasoning
            # item; an ID alone could load unbounded prior server-side context.
            if not isinstance(item.get("encrypted_content"), str) or not item["encrypted_content"]:
                return False
        else:
            return False
    return True


def _request(
    payload: dict[str, Any],
    *,
    provider: str,
    stream: bool,
    caller_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from modstore_server.llm_chat_proxy import _normalize_openai_base
    from modstore_server.llm_gateway_contract import gateway_body
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        platform_api_key,
        platform_base_url,
    )

    if budget._SCOPE.get() is None:
        raise PortfolioError("Responses requires an authenticated strategic execution scope")
    if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        raise PortfolioError("approved provider does not use the Responses transport")
    if not isinstance(payload, dict) or payload.keys() - _FIELDS:
        raise PortfolioError("unsupported strategic Responses request fields")
    if payload.get("previous_response_id") or payload.get("store") not in (None, False):
        raise PortfolioError("strategic Responses requires explicit stateless input")
    if payload.get("background") not in (None, False) or payload.get("service_tier") not in (
        None,
        "default",
    ):
        raise PortfolioError("strategic Responses requires foreground default-tier execution")
    if not _explicit_input(payload.get("input")):
        raise PortfolioError("strategic Responses requires explicit text/function input")
    tools = payload.get("tools") or []
    if not isinstance(tools, list) or any(
        not isinstance(tool, dict) or tool.get("type") != "function" for tool in tools
    ):
        raise PortfolioError("strategic Responses only supports worker-owned function tools")
    if any(item != "reasoning.encrypted_content" for item in payload.get("include") or []):
        raise PortfolioError("unsupported strategic Responses include")
    requested_tokens = payload.get("max_output_tokens")
    if requested_tokens is not None and (
        type(requested_tokens) is not int or requested_tokens <= 0
    ):
        raise PortfolioError("max_output_tokens must be a positive integer")
    serialized = _json(payload)
    if len(serialized.encode("utf-8")) > 2_000_000:
        raise PortfolioError("strategic Responses request exceeds 2000000 bytes")
    body = json.loads(serialized)
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise PortfolioError("strategic Responses requires the approved model")
    route: dict[str, Any] = {
        "model": model,
        "api_key": platform_api_key(provider),
        "base_url": platform_base_url(provider),
    }
    budget._authorize_platform_route(provider, route)
    route["base_url"] = _normalize_openai_base(provider, route["base_url"], route["api_key"])
    body.update(
        model=route["model"],
        stream=stream,
        store=False,
        background=False,
        service_tier="default",
        truncation="disabled",
    )
    body.pop("previous_response_id", None)
    if controls := gateway_body(provider):
        # These transport controls come from the server, never worker input.
        body["extra_body"] = controls
    # Include instructions, function schemas and explicit history in the same
    # conservative text bound used by the platform's existing ledger.
    reservation = budget.prepare_platform_call(
        provider,
        route["model"],
        [{"role": "user", "content": _json(body)}],
        requested_tokens or 4096,
        caller_binding=caller_binding,
    )
    assert reservation is not None
    body["max_output_tokens"] = reservation["max_tokens"]
    return route, body, reservation


def _client(route: dict[str, Any], provider: str, timeout: float):
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient

    from modstore_server.llm_litellm_router import _extra_headers

    return AsyncOpenAI(
        api_key=route["api_key"],
        base_url=route["base_url"],
        max_retries=0,
        timeout=timeout,
        default_headers=_extra_headers(provider, route["api_key"]),
        http_client=DefaultAsyncHttpxClient(trust_env=False, follow_redirects=False),
    )


def _measurement(
    response: dict[str, Any],
    provider: str,
    model: str,
    *,
    gateway_attempts_verified: bool = False,
) -> dict[str, Any] | None:
    usage = response.get("usage")
    if (
        response.get("status") != "completed"
        or response.get("error")
        or response.get("incomplete_details")
        or not isinstance(response.get("id"), str)
        or not response["id"]
        or not isinstance(usage, dict)
        or any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("input_tokens", "output_tokens")
        )
        or usage.get("estimated") is True
        or response.get("usage_estimated") is True
        or response.get("fallback_used")
        or response.get("_fallback_used")
        or (provider == "litellm" and not gateway_attempts_verified)
    ):
        return None
    return {
        "provider": provider,
        "model": model,
        "usage": usage,
        "response_id": response["id"],
        "upstream_model": response.get("model"),
        **({"gateway_attempts_verified": True} if provider == "litellm" else {}),
    }


async def budgeted_responses(
    payload: dict[str, Any],
    *,
    provider: str,
    caller_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from modstore_server.llm_gateway_contract import gateway_single_attempt

    route, body, reservation = _request(
        payload, provider=provider, stream=False, caller_binding=caller_binding
    )
    client = None
    result = None
    closed = False
    gateway_verified = False
    try:
        client = _client(route, provider, reservation["timeout_seconds"])
        with budget.platform_call_reservation(reservation):
            budget.require_call_reservation(
                provider=provider, model=route["model"], start_transport=True
            )
            raw = await asyncio.wait_for(
                client.responses.with_raw_response.create(**body),
                timeout=reservation["timeout_seconds"],
            )
        gateway_verified = provider != "litellm" or gateway_single_attempt(raw.headers)
        if not gateway_verified:
            raise PortfolioError("gateway did not confirm a single original provider attempt")
        response = raw.parse()
        result = cast(dict[str, Any], response.model_dump(mode="json", exclude_unset=True))
        return result
    finally:
        try:
            if client is not None:
                await client.close()
            closed = True
        finally:
            budget.complete_platform_call(
                reservation,
                (
                    _measurement(
                        result,
                        provider,
                        route["model"],
                        gateway_attempts_verified=gateway_verified,
                    )
                    if closed and result
                    else None
                ),
            )


async def budgeted_responses_stream(
    payload: dict[str, Any],
    *,
    provider: str,
    caller_binding: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    from modstore_server.llm_gateway_contract import gateway_single_attempt

    route, body, reservation = _request(
        payload, provider=provider, stream=True, caller_binding=caller_binding
    )
    client = source = None
    measured = None
    exhausted = closed = failed = False
    completed_seen = False
    response_id = None
    deadline = asyncio.get_running_loop().time() + reservation["timeout_seconds"]
    try:
        client = _client(route, provider, reservation["timeout_seconds"])
        with budget.platform_call_reservation(reservation):
            budget.require_call_reservation(
                provider=provider, model=route["model"], start_transport=True
            )
            raw = await asyncio.wait_for(
                client.responses.with_raw_response.create(**body),
                timeout=reservation["timeout_seconds"],
            )
        source = raw.parse()
        gateway_verified = provider != "litellm" or gateway_single_attempt(raw.headers)
        if not gateway_verified:
            raise PortfolioError("gateway did not confirm a single original provider attempt")
        while True:
            budget.remaining_execution_seconds()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("strategic Responses deadline expired")
            try:
                event = await asyncio.wait_for(anext(source), timeout=remaining)
            except StopAsyncIteration:
                exhausted = True
                break
            data = event.model_dump(mode="json", exclude_unset=True)
            kind = data.get("type")
            failed = failed or kind in {"error", "response.failed", "response.incomplete"}
            response = data.get("response")
            if isinstance(response, dict):
                current_id = response.get("id")
                failed = (
                    failed
                    or not current_id
                    or (response_id is not None and response_id != current_id)
                )
                response_id = response_id or current_id
                if kind == "response.completed":
                    if completed_seen:
                        failed = True
                    completed_seen = True
                    measured = _measurement(
                        response,
                        provider,
                        route["model"],
                        gateway_attempts_verified=gateway_verified,
                    )
            yield data
    finally:
        try:
            try:
                if source is not None:
                    await source.close()
            finally:
                if client is not None:
                    await client.close()
            closed = True
        finally:
            budget.complete_platform_call(
                reservation, measured if exhausted and closed and not failed else None
            )
