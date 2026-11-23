"""Native SDK transport and the pinned LiteLLM Responses bridge.

LiteLLM owns Chat/Responses conversion. Product glue only observes the original
SDK receipt before normalization, and refuses a second physical provider call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from openai import AsyncOpenAI, AsyncStream, DefaultAsyncHttpxClient
from openai.types.chat import ChatCompletionChunk

from modstore_server.llm_billing_values import exact_reported_usage
from modstore_server.llm_chat_proxy import _normalize_openai_base
from modstore_server.llm_gateway_contract import gateway_single_attempt
from modstore_server.llm_key_resolver import ChatRouteSnapshot, is_minimax_token_plan_key
from modstore_server.llm_litellm_router import _deployment, _extra_headers, _load_litellm
from modstore_server.platform_model_config import PlatformApiKey

_COUNTERS = ("x-litellm-attempted-retries", "x-litellm-attempted-fallbacks")


def _independent_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and host not in {"127.0.0.1", "::1", "localhost"})
        or any(
            host == domain or host.endswith("." + domain)
            for domain in ("openai.com", "chatgpt.com", "openai.azure.com", "services.ai.azure.com")
        )
    ):
        raise ValueError("the selected runtime endpoint is not independent")


def validate_responses_route(route: ChatRouteSnapshot) -> None:
    try:
        _independent_endpoint(_normalize_openai_base(route.provider, route.base_url, route.api_key))
        if route.provider == "minimax" and is_minimax_token_plan_key(route.api_key):
            raise ValueError("this token plan uses a different native protocol")
    except ValueError:
        raise HTTPException(
            409,
            {
                "code": "CODEX_MODEL_UNSUPPORTED",
                "message": "当前模型地址或密钥协议不支持独立 Responses 运行，请检查已有模型设置。",
                "recovery": "choose_compatible_runtime_model",
            },
        ) from None


class ResponsesTransport:
    def __init__(self, route: ChatRouteSnapshot, timeout: float):
        self.route, self.timeout = route, timeout
        self.direct = route.provider != "litellm"
        self.attempts = 0
        self.denied = False
        self.source: Any = None
        self.client: Any = None
        self.headers: dict[str, str] = {}
        self.models: set[str] = set()
        self.usage: dict[str, Any] | None = None
        self.exhausted = False
        self.streaming = False
        self.finish_reasons: set[str] = set()
        self.tool_arguments: dict[int, str] = {}

    def observe(self, response: Any) -> None:
        value = response.model_dump(mode="json", exclude_unset=True)
        if isinstance(value.get("model"), str) and value["model"]:
            self.models.add(value["model"])
        if isinstance(value.get("usage"), dict):
            self.usage = value["usage"]
        for choice in value.get("choices") or []:
            if choice.get("index") != 0:
                raise ValueError("unexpected provider choice")
            if reason := choice.get("finish_reason"):
                self.finish_reasons.add(reason)
            message = choice.get("delta", choice.get("message")) or {}
            for index, call in enumerate(message.get("tool_calls") or []):
                position = call.get("index", index)
                arguments = (call.get("function") or {}).get("arguments")
                if isinstance(arguments, str):
                    self.tool_arguments[position] = (
                        self.tool_arguments.get(position, "") + arguments
                    )

    def project(self, value: dict[str, Any]) -> dict[str, Any]:
        # The bridge can prefix its requested model. Publish only the original
        # provider identity observed by our SDK, not that rewritten alias.
        if self.direct and len(self.models) == 1:
            response = value.get("response", value)
            if isinstance(response, dict) and "model" in response:
                response["model"] = next(iter(self.models))
        return value

    def verify(self, response: dict[str, Any], expected: str) -> None:
        if self.attempts != 1 or self.denied:
            raise ValueError("provider attempt count is unknown")
        if self.direct and (
            self.models != {expected}
            or not self.finish_reasons
            or not self.finish_reasons <= {"stop", "tool_calls"}
            or (self.streaming and not self.exhausted)
            or self.usage is None
            or self.usage.get("estimated") is True
            or (exact := exact_reported_usage(self.usage)) is None
            or exact != exact_reported_usage(response.get("usage"))
        ):
            raise ValueError("bridge result does not match the original provider receipt")
        if self.direct and any(
            not isinstance(json.loads(arguments), dict)
            for arguments in self.tool_arguments.values()
        ):
            raise ValueError("provider function arguments did not finish as a JSON object")

    async def open(self, body: dict[str, Any]) -> ResponsesTransport:
        owner = self
        self.streaming = body.get("stream") is True
        base = _normalize_openai_base(self.route.provider, self.route.base_url, self.route.api_key)
        expected_url = base.rstrip("/") + ("/chat/completions" if self.direct else "/responses")

        async def before_send(request: Any) -> None:
            _independent_endpoint(str(request.url))
            if (
                self.attempts
                or request.method != "POST"
                or str(request.url) != str(type(request.url)(expected_url))
                or json.loads(request.content).get("model") != self.route.model
            ):
                self.denied = True
                raise RuntimeError("a second provider attempt is forbidden")
            self.attempts += 1
            if isinstance(self.route.api_key, PlatformApiKey) and self.route.api_key.managed:
                from modstore_server.openapi_connector_runtime import pin_url_outbound_safe

                target = await asyncio.to_thread(pin_url_outbound_safe, str(request.url))
                request.url = type(request.url)(target.request_url)
                request.headers["host"] = target.host_header
                request.extensions["sni_hostname"] = target.server_hostname

        class ObservedStream(AsyncStream[ChatCompletionChunk]):
            async def __aiter__(self):
                async for chunk in super().__aiter__():
                    owner.observe(chunk)
                    yield chunk
                owner.exhausted = True

            async def __anext__(self):
                try:
                    chunk = await super().__anext__()
                except StopAsyncIteration:
                    owner.exhausted = True
                    raise
                owner.observe(chunk)
                return chunk

        class ObservedClient(AsyncOpenAI):
            async def post(self, path, **kwargs):
                if path != "/chat/completions" or bool(kwargs.get("stream")) != owner.streaming:
                    raise ValueError("bridge attempted an unapproved provider operation")
                if owner.streaming:
                    kwargs["stream_cls"] = ObservedStream
                raw = await super().post(path, **kwargs)
                if not owner.streaming:
                    owner.observe(raw.parse() if hasattr(raw, "parse") else raw)
                return raw

        client_type = ObservedClient if self.direct else AsyncOpenAI
        self.client = client_type(
            api_key=self.route.api_key,
            base_url=base,
            default_headers=_extra_headers(self.route.provider, self.route.api_key),
            timeout=self.timeout,
            max_retries=0,
            http_client=DefaultAsyncHttpxClient(
                trust_env=False, follow_redirects=False, event_hooks={"request": [before_send]}
            ),
        )
        if self.direct:
            module = _load_litellm()
            deployment = _deployment(
                "account-responses",
                self.route.provider,
                self.route.model,
                self.route.api_key,
                self.route.base_url,
            )
            if (
                module is None
                or not deployment
                or not deployment["litellm_params"]["model"].startswith("openai/")
            ):
                raise ValueError("selected provider has no approved Responses bridge")
            params = dict(deployment["litellm_params"])
            params.pop("max_parallel_requests", None)
            self.source = await module.aresponses(
                **{**body, **params},
                client=self.client,
                custom_llm_provider="openai",
                use_chat_completions_api=True,
                num_retries=0,
                max_retries=0,
                disable_fallbacks=True,
                fallbacks=[],
                context_window_fallbacks=[],
                content_policy_fallbacks=[],
                timeout=self.timeout,
            )
        else:
            raw = await self.client.responses.with_raw_response.create(**body)
            self.source = raw.parse()
            if not gateway_single_attempt(raw.headers):
                raise ValueError("gateway attempt count is unknown")
            self.headers.update({name: raw.headers[name] for name in _COUNTERS})
        if self.attempts != 1 or self.denied:
            raise ValueError("SDK did not use the approved provider transport")
        self.headers.update(
            {
                "X-XCMax-Upstream-Attempts": "1",
                "X-XCMax-Upstream-Fallbacks": "0",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            }
        )
        return self

    async def close(self) -> None:
        try:
            if self.source is not None:
                close = getattr(self.source, "aclose", None) or getattr(self.source, "close", None)
                if close is not None:
                    await close()
        finally:
            if self.client is not None:
                await self.client.close()
