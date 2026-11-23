# mypy: disable-error-code="import-not-found, import-untyped, attr-defined, no-any-return"
"""LiteLLM Router 适配层：多渠道路由、重试、冷却与故障转移。

本模块只做三件事，避免重复实现中转站能力：

1. 把现有 provider 凭据映射成 LiteLLM deployment；
2. 用 ``litellm.Router`` 承担重试、冷却（熔断语义）、fallback 链、负载均衡与并发上限；
3. 把 LiteLLM 的响应/流事件归一化成 ``llm_chat_proxy`` 既有契约。

LiteLLM 是可选依赖：未安装或显式关闭时 ``chat``/``stream_events`` 返回 ``None``，
调用方继续走原有链路，行为不变。
"""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import threading
import time
from collections.abc import Mapping
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from modstore_server.llm_gateway_contract import gateway_body, gateway_single_attempt
from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
)
from modstore_server.llm_quota_monitor import scrub_llm_error
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.platform_model_config import PlatformApiKey
from modstore_server.xiaoc_life_chat import (
    manual_life_scope_active,
    require_manual_life_capability,
)

try:
    from openai import OpenAIError
except ImportError:
    _UPSTREAM_ERRORS = RECOVERABLE_ERRORS
else:
    _UPSTREAM_ERRORS = (*RECOVERABLE_ERRORS, OpenAIError)

_PRIMARY_ALIAS = "modstore-primary"
_FALLBACK_PREFIX = "modstore-fallback-"
_ROUTER_LOCK = threading.Lock()
_ROUTER_CACHE: Dict[Tuple[Any, ...], Any] = {}
_ROUTER_CACHE_MAX = 64
_CACHE_FINGERPRINT_KEY = secrets.token_bytes(32)
_LITELLM_LOCK = threading.Lock()
_LITELLM_MODULE: Any = None
_LITELLM_FAILED = False


def _load_litellm() -> Any:
    global _LITELLM_MODULE, _LITELLM_FAILED
    if _LITELLM_MODULE is not None:
        return _LITELLM_MODULE
    if _LITELLM_FAILED:
        return None
    with _LITELLM_LOCK:
        if _LITELLM_MODULE is not None:
            return _LITELLM_MODULE
        try:
            # 避免首次导入时联网拉取 model cost map（生产环境可能不可达且拖慢启动）。
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
            import litellm  # type: ignore[import-not-found]

            _LITELLM_MODULE = litellm
        except (ImportError, RuntimeError, OSError):
            _LITELLM_FAILED = True
            return None
    return _LITELLM_MODULE


def model_registry_entry(provider: str, model: str) -> dict[str, Any]:
    """Read the pinned LiteLLM registry for the matching provider."""
    module = _load_litellm()
    if module is None:
        return {}
    namespace = {
        "google": "gemini",
        "xiaomi": "xiaomi_mimo",
        "together": "together_ai",
        "doubao": "volcengine",
    }.get(provider, provider)
    registry = getattr(module, "model_cost", {})
    info = registry.get(f"{namespace}/{model}") or registry.get(model) or {}
    if not isinstance(info, dict) or info.get("litellm_provider") != namespace:
        return {}
    lookup = getattr(module, "get_model_info", None)
    if callable(lookup):
        try:
            resolved = lookup(model=model, custom_llm_provider=namespace)
        except RECOVERABLE_ERRORS:
            pass  # Unknown aliases have no inferred capacity; use the pinned registry only.
        else:
            if isinstance(resolved, dict) and resolved.get("litellm_provider") == namespace:
                info = resolved
    return info


def model_limits(provider: str, model: str) -> dict[str, int]:
    info = model_registry_entry(provider, model)
    return {
        key: value
        for key in ("context_window", "max_input_tokens", "max_output_tokens")
        if type(value := info.get(key)) is int and value > 0
    }


def available() -> bool:
    """LiteLLM 已安装且管理端/环境开关打开。"""

    from modstore_server.llm_router_config import settings

    if not settings()["enabled"]:
        return False
    return _load_litellm() is not None


def _key_fingerprint(api_key: Any) -> str:
    raw = str(api_key or "")
    return hmac.new(_CACHE_FINGERPRINT_KEY, raw.encode("utf-8"), "sha256").hexdigest()


def _extra_headers(provider: str, api_key: Any) -> Dict[str, str]:
    # MiMo Token Plan 文档推荐 api-key；其余厂商走 Authorization。
    if provider == "xiaomi":
        return {"api-key": str(api_key)}
    return {}


def _deployment(
    alias: str,
    provider: str,
    model: str,
    api_key: Any,
    base_url: Optional[str],
) -> Optional[Dict[str, Any]]:
    """把既有 provider 协议映射为 LiteLLM 识别的 model 字符串。"""

    if isinstance(api_key, PlatformApiKey) and api_key.configuration["provider"] != provider:
        raise ValueError("平台密钥不允许跨供应商使用")
    if isinstance(api_key, PlatformApiKey):
        base_url = api_key.configuration["base_url"]

    params: Dict[str, Any]
    if provider == "anthropic":
        litellm_model, params = f"anthropic/{model}", {"api_key": str(api_key)}
    elif provider == "google":
        litellm_model, params = f"gemini/{model}", {"api_key": str(api_key)}
    elif provider == "minimax" and is_minimax_token_plan_key(api_key):
        litellm_model = f"anthropic/{model}"
        params = {
            "api_key": normalize_minimax_api_key(api_key),
            "api_base": minimax_anthropic_base_url(
                base_url,
                prefer_base=isinstance(api_key, PlatformApiKey) and api_key.managed,
            ),
            "extra_headers": {"anthropic-version": "2023-06-01"},
        }
    elif provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        from modstore_server.llm_chat_proxy import _normalize_openai_base

        litellm_model = f"openai/{model}"
        params = {
            "api_key": str(api_key),
            "api_base": _normalize_openai_base(provider, base_url, api_key),
        }
        headers = _extra_headers(provider, api_key)
        if headers:
            params["extra_headers"] = headers
        if provider == "xiaomi":
            # 与既有适配保持一致：默认关闭 thinking，避免推理段挤占正文额度。
            params["extra_body"] = {"thinking": {"type": "disabled"}}
    else:
        return None

    max_parallel = int(_router_settings()["max_parallel"])
    if max_parallel > 0:
        params["max_parallel_requests"] = max_parallel
    return {
        "model_name": alias,
        "litellm_params": {**params, "model": litellm_model},
        "model_info": {
            "id": alias,
            "provider": provider,
            "model": model,
            **model_limits(provider, model),
        },
    }


def _router_key(
    deployments: List[Dict[str, Any]],
    fallback_aliases: List[str],
) -> Tuple[Any, ...]:
    from modstore_server.llm_router_config import settings

    cfg = settings()
    primary = deployments[0]["litellm_params"]
    return (
        primary.get("model"),
        primary.get("api_base"),
        _key_fingerprint(primary.get("api_key")),
        tuple(fallback_aliases),
        tuple(
            (
                row["litellm_params"].get("model"),
                row["litellm_params"].get("api_base"),
                _key_fingerprint(row["litellm_params"].get("api_key")),
            )
            for row in deployments[1:]
        ),
        cfg["revision"],
        cfg["num_retries"],
        cfg["cooldown_seconds"],
        cfg["allowed_fails"],
        cfg["routing_strategy"],
        cfg["max_parallel"],
        cfg["request_timeout_seconds"],
        cfg["stream_timeout_seconds"],
        cfg["mid_stream_fallback"],
        (os.environ.get("MODSTORE_REDIS_URL") or "").strip(),
    )


def _get_router(
    deployments: List[Dict[str, Any]],
    fallback_aliases: List[str],
) -> Any:
    from modstore_server.llm_router_config import settings

    litellm = _load_litellm()
    if litellm is None:
        return None
    cfg = settings()
    cache_key = _router_key(deployments, fallback_aliases)
    with _ROUTER_LOCK:
        cached = _ROUTER_CACHE.get(cache_key)
        if cached is not None:
            return cached
    fallbacks = [{_PRIMARY_ALIAS: fallback_aliases}] if fallback_aliases else []
    kwargs: Dict[str, Any] = {
        "model_list": deployments,
        # LiteLLM 自带重试、冷却（熔断）、fallback 与并发上限。
        "num_retries": int(cfg["num_retries"]),
        "cooldown_time": float(cfg["cooldown_seconds"]),
        "allowed_fails": int(cfg["allowed_fails"]),
        "routing_strategy": str(cfg["routing_strategy"]),
        "timeout": float(cfg["request_timeout_seconds"]),
        "stream_timeout": float(cfg["stream_timeout_seconds"]),
        "enable_pre_call_checks": True,
        "fallbacks": fallbacks,
        "enable_mid_stream_fallback_continuation": bool(cfg["mid_stream_fallback"]),
    }
    max_parallel = int(cfg["max_parallel"])
    if max_parallel > 0:
        kwargs["default_max_parallel_requests"] = max_parallel
    redis_url = (os.environ.get("MODSTORE_REDIS_URL") or "").strip()
    if redis_url:
        # 共享冷却/路由状态，支持多 worker。
        kwargs["redis_url"] = redis_url
    router = litellm.Router(**kwargs)
    with _ROUTER_LOCK:
        if len(_ROUTER_CACHE) >= _ROUTER_CACHE_MAX:
            _ROUTER_CACHE.pop(next(iter(_ROUTER_CACHE)))
        _ROUTER_CACHE[cache_key] = router
    return router


def _router_settings() -> Dict[str, Any]:
    from modstore_server.llm_router_config import settings

    return settings()


def _build_specs(
    provider: str,
    model: str,
    api_key: Any,
    base_url: Optional[str],
    fallbacks: Optional[List[Dict[str, Any]]],
) -> Optional[Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]]:
    # Platform credentials require the legacy pinned transport and billed route lifecycle.
    if isinstance(api_key, PlatformApiKey) or any(
        isinstance(row.get("api_key"), PlatformApiKey)
        for row in fallbacks or []
        if isinstance(row, dict)
    ):
        return None
    primary = _deployment(_PRIMARY_ALIAS, provider, model, api_key, base_url)
    if primary is None:
        return None
    deployments = [primary]
    fallback_aliases: List[str] = []
    fallback_rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(fallbacks or []):
        alias = f"{_FALLBACK_PREFIX}{idx}"
        if not isinstance(row, dict):
            continue
        fb_provider = str(row.get("provider") or "").strip()
        fb_model = str(row.get("model") or "").strip()
        fb_key = row.get("api_key")
        if not fb_provider or not fb_model or not fb_key:
            continue
        fb = _deployment(alias, fb_provider, fb_model, fb_key, row.get("base_url"))
        if fb is None:
            continue
        deployments.append(fb)
        fallback_aliases.append(alias)
        fallback_rows.append(
            {
                "provider": fb_provider,
                "model": fb_model,
                "api_key": fb_key,
            }
        )
    return deployments, fallback_aliases, fallback_rows


def _usage_dict(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            return dict(usage.model_dump())
        except (TypeError, ValueError, AttributeError):
            return {}
    if isinstance(usage, dict):
        return dict(usage)
    try:
        return dict(usage)
    except (TypeError, ValueError):
        return {}


def fallback_receipt_from_headers(headers: Any) -> Dict[str, Any]:
    """Preserve local and upstream gateway fallback evidence for settlement."""
    attempted = 0
    unknown = False
    if isinstance(headers, Mapping):
        for name, value in headers.items():
            # LiteLLM namespaces raw gateway headers so they cannot impersonate
            # its own router metadata. Both layers can report a real fallback.
            if str(name).lower() not in {
                "x-litellm-attempted-fallbacks",
                "llm_provider-x-litellm-attempted-fallbacks",
            }:
                continue
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int)):
                    raise ValueError("invalid fallback receipt")
                count = int(value)
                if count < 0:
                    raise ValueError("negative fallback receipt")
                attempted = max(attempted, count)
            except (TypeError, ValueError):
                unknown = True
    # An unreadable explicit receipt cannot prove one approved model call.
    # Keep the existing unknown-usage hold instead of inventing zero fallbacks.
    return {
        "fallback_used": unknown or attempted > 0,
        "fallback_count": None if unknown else attempted,
    }


def _fallback_meta(response: Any) -> Dict[str, Any]:
    hidden = getattr(response, "_hidden_params", None) or {}
    headers = hidden.get("additional_headers") if isinstance(hidden, dict) else None
    return fallback_receipt_from_headers(headers)


def _budgeted_stream_client(
    provider: str,
    model: str,
    params: Dict[str, Any],
    reported: Dict[str, Any],
    *,
    stream: bool = True,
    http_client: Any = None,
) -> Any:
    """Use LiteLLM's client injection to observe raw SDK chunks before its router.

    The router reads a first chunk and wraps the provider stream before returning
    it. Observing its returned wrapper is too late: usage may be normalized or
    synthesized already. A request-local SDK stream preserves the actual receipt.
    """
    from openai import AsyncOpenAI, AsyncStream, DefaultAsyncHttpxClient
    from openai.types.chat import ChatCompletionChunk

    def record(chunk):
        if not isinstance(chunk, ChatCompletionChunk):
            return
        # LiteLLM rewrites chunk.model to its requested alias. Retain raw
        # identity from every SDK frame; later aliases cannot erase a mismatch.
        if chunk.model and reported.get("model", model) == model:
            reported["model"] = chunk.model
        if values := _usage_dict(chunk):
            reported["usage"] = values

    class ReceiptStream(AsyncStream[ChatCompletionChunk]):
        async def __aiter__(self):
            async for chunk in super().__aiter__():
                record(chunk)
                yield chunk

        async def __anext__(self):
            chunk = await super().__anext__()
            record(chunk)
            return chunk

    class ReceiptClient(AsyncOpenAI):
        gateway_attempts_verified = False

        async def post(self, path, **kwargs):
            from modstore_server.strategic_portfolio import PortfolioError
            from modstore_server.strategic_portfolio_usage import (
                require_call_reservation,
                transport_headers,
            )

            if path != "/chat/completions" or bool(kwargs.get("stream")) != stream:
                raise PortfolioError("metered client requires the approved chat request")
            require_call_reservation(provider=provider, model=model, start_transport=True)
            options = dict(kwargs.get("options") or {})
            options["headers"] = {
                **(options.get("headers") or {}),
                **transport_headers(provider),
            }
            kwargs["options"] = options
            if stream:
                kwargs["stream_cls"] = ReceiptStream
            response = await super().post(path, **kwargs)
            if provider == "litellm":
                # LiteLLM requests the native SDK raw response here. Its own
                # Router later replaces attempt headers with local-hop counts.
                self.gateway_attempts_verified = gateway_single_attempt(
                    getattr(response, "headers", {})
                )
            return response

    return ReceiptClient(
        api_key=params["api_key"],
        base_url=params["api_base"],
        max_retries=0,
        http_client=http_client or DefaultAsyncHttpxClient(follow_redirects=False, trust_env=False),
    )


def _reported_stream_usage(reported: Dict[str, Any], usage: Dict[str, Any]) -> bool:
    return (
        bool(reported)
        and reported.get("estimated") is not True
        and all(
            type(reported.get(key)) is int
            and reported[key] >= 0
            and reported[key] == usage.get(key)
            for key in ("prompt_tokens", "completion_tokens")
        )
    )


def _error_payload(exc: BaseException, *, timeout_s: Optional[float]) -> Dict[str, Any]:
    if isinstance(exc, asyncio.TimeoutError):
        if timeout_s:
            return {
                "ok": False,
                "status": 504,
                "error": f"上游调用超过总预算 {float(timeout_s):.1f}s，已中止",
            }
        return {"ok": False, "status": 504, "error": "上游调用超时，已中止"}
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    try:
        status_code = int(status) if status is not None else 502
    except (TypeError, ValueError):
        status_code = 502
    message = scrub_llm_error(f"{type(exc).__name__}: {exc}")[:2000]
    return {"ok": False, "status": status_code, "error": message or "上游模型调用失败"}


def _normalize_response(
    response: Any,
    *,
    provider: str,
    model: str,
    forbid_reasoning_fallback: bool,
) -> Dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = str(getattr(message, "content", "") or "").strip()
    reasoning = str(
        getattr(message, "reasoning_content", "")
        or getattr(message, "reasoning", "")
        or getattr(message, "thinking", "")
        or ""
    ).strip()
    usage = _usage_dict(response)
    meta = _fallback_meta(response)
    used_model = str(getattr(response, "model", "") or model)
    if forbid_reasoning_fallback and not content:
        return {
            "ok": False,
            "error": (
                "模型未输出正文 content（常见于推理模型占满 max_tokens 或仅返回 reasoning）。"
                "代码生成路径禁止将推理链当作正文；请增大 max_tokens、换用非推理模型，或降低推理长度。"
            ),
            "content": "",
            "provider": provider,
            "model": used_model,
            "usage": usage,
            "reasoning_trace": reasoning,
            **meta,
        }
    out: Dict[str, Any] = {
        "ok": True,
        "content": content or reasoning,
        "finish_reason": getattr(choices[0], "finish_reason", None) if choices else None,
        "usage": usage,
        "provider": provider,
        "model": used_model,
        "router": "litellm",
        **meta,
    }
    if reasoning and content:
        out["reasoning_trace"] = reasoning
    return out


async def chat(
    provider: str,
    *,
    api_key: Any,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    forbid_reasoning_fallback: bool = False,
    response_format: Optional[Dict[str, str]] = None,
    total_timeout_s: Optional[float] = None,
    primary_timeout_s: Optional[float] = None,
    fallbacks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """走 LiteLLM Router 的非流式调用；不支持该 provider 时返回 ``None``。"""

    from modstore_server.strategic_portfolio_usage import (
        require_call_reservation,
        scope_active,
    )

    budgeted = scope_active()
    require_manual_life_capability()
    single_attempt = budgeted or manual_life_scope_active()
    if budgeted:
        require_call_reservation(provider=provider, model=model)
    if single_attempt:
        fallbacks = []

    specs = _build_specs(provider, model, api_key, base_url, fallbacks)
    if specs is None or not available():
        return None
    deployments, fallback_aliases, _ = specs
    router = _get_router(deployments, fallback_aliases)
    if router is None:
        return None

    timeout_s = total_timeout_s or float(_router_settings()["request_timeout_seconds"])
    started = time.perf_counter()
    outcome = "success"
    client = None
    try:
        if single_attempt and provider == "litellm":
            client = _budgeted_stream_client(
                provider, model, deployments[0]["litellm_params"], {}, stream=False
            )
        call = router.acompletion(
            model=_PRIMARY_ALIAS,
            messages=messages,
            max_tokens=max_tokens,
            response_format=response_format,
            **(
                {"num_retries": 0, "max_retries": 0, "disable_fallbacks": True}
                if single_attempt
                else {}
            ),
            **({"timeout": float(primary_timeout_s)} if primary_timeout_s else {}),
            **(
                {"extra_body": gateway_body(provider), "client": client}
                if client is not None
                else {}
            ),
        )
        response = await asyncio.wait_for(call, timeout=float(timeout_s))
        hidden = getattr(response, "_hidden_params", None) or {}
        used_id = hidden.get("model_id") if isinstance(hidden, dict) else None
        used_provider = next(
            (
                row["model_info"]["provider"]
                for row in deployments
                if row["model_info"]["id"] == used_id
            ),
            provider,
        )
        result = _normalize_response(
            response,
            provider=used_provider,
            model=model,
            forbid_reasoning_fallback=forbid_reasoning_fallback,
        )
        if provider == "litellm":
            result["gateway_attempts_verified"] = (
                client is not None and client.gateway_attempts_verified is True
            )
        outcome = "success" if result.get("ok") else "error"
        return result
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except _UPSTREAM_ERRORS as exc:
        outcome = "error"
        return _error_payload(exc, timeout_s=timeout_s)
    finally:
        try:
            if client is not None:
                await client.close()
        finally:
            _observe(provider, model, time.perf_counter() - started, "chat", outcome)


def _stream_delta_events(
    chunk: Any, pending_calls: Dict[int, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return events
    choice0 = choices[0]
    delta = getattr(choice0, "delta", None)
    content = getattr(delta, "content", None) if delta is not None else None
    if content:
        events.append({"type": "delta", "delta": str(content)})
    tool_calls = getattr(delta, "tool_calls", None) if delta is not None else None
    if tool_calls:
        normalized: List[Dict[str, Any]] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                normalized.append(tc)
            else:
                normalized.append(
                    {
                        "index": getattr(tc, "index", 0),
                        "id": getattr(tc, "id", "") or "",
                        "type": getattr(tc, "type", "function") or "function",
                        "function": {
                            "name": getattr(getattr(tc, "function", None), "name", "") or "",
                            "arguments": getattr(getattr(tc, "function", None), "arguments", "")
                            or "",
                        },
                    }
                )
        for call in normalized:
            index = int(call.get("index", 0))
            current = pending_calls.setdefault(
                index,
                {
                    "index": index,
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if call.get("id"):
                current["id"] = call["id"]
            function = call.get("function") or {}
            for field in ("name", "arguments"):
                current["function"][field] += function.get(field) or ""
    finish_reason = getattr(choice0, "finish_reason", None)
    if finish_reason == "tool_calls" and pending_calls:
        events.append(
            {
                "type": "toolcall",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [pending_calls[i] for i in sorted(pending_calls)]},
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )
        pending_calls.clear()
    if finish_reason:
        events.append({"type": "finish", "finish_reason": str(finish_reason)[:32]})
    return events


async def _stream_impl(
    provider: str,
    *,
    api_key: Any,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int],
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: Any,
    fallbacks: Optional[List[Dict[str, Any]]],
) -> AsyncIterator[Dict[str, Any]]:
    from modstore_server.strategic_portfolio_usage import (
        require_call_reservation,
        scope_active,
    )

    budgeted = scope_active()
    require_manual_life_capability()
    single_attempt = budgeted or manual_life_scope_active()
    if budgeted:
        require_call_reservation(provider=provider, model=model)
    if single_attempt:
        fallbacks = []
    specs = _build_specs(provider, model, api_key, base_url, fallbacks)
    if specs is None:
        yield {"type": "error", "error": f"unsupported provider: {provider}"}
        return
    deployments, fallback_aliases, _ = specs
    router = _get_router(deployments, fallback_aliases)
    if router is None:
        yield {"type": "error", "error": "LiteLLM Router 不可用"}
        return
    started = time.perf_counter()
    outcome = "success"
    response = None
    client = None
    reported_receipt: Dict[str, Any] = {}
    try:
        if budgeted or (
            single_attempt and str(deployments[0]["litellm_params"]["model"]).startswith("openai/")
        ):
            client = _budgeted_stream_client(
                provider, model, deployments[0]["litellm_params"], reported_receipt
            )
        response = await router.acompletion(
            model=_PRIMARY_ALIAS,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            stream_options={"include_usage": True},
            **(
                {
                    "num_retries": 0,
                    "max_retries": 0,
                    "disable_fallbacks": True,
                    "enable_mid_stream_fallback_continuation": False,
                    **({"client": client} if client is not None else {}),
                    **({"extra_body": gateway_body(provider)} if provider == "litellm" else {}),
                }
                if single_attempt
                else {}
            ),
        )
        pending_calls: Dict[int, Dict[str, Any]] = {}
        async for chunk in response:
            usage = _usage_dict(chunk)
            if usage:
                yield {
                    "type": "usage",
                    "usage": usage,
                    **(
                        {
                            "provider": provider,
                            "model": reported_receipt.get("model") or getattr(chunk, "model", None),
                            **_fallback_meta(chunk),
                            "usage_estimated": not _reported_stream_usage(
                                reported_receipt.get("usage", {}), usage
                            ),
                            **(
                                {
                                    "gateway_attempts_verified": (
                                        client is not None
                                        and client.gateway_attempts_verified is True
                                    ),
                                    "model": reported_receipt.get("model"),
                                }
                                if provider == "litellm"
                                else {}
                            ),
                        }
                        if budgeted
                        else {}
                    ),
                }
            for event in _stream_delta_events(chunk, pending_calls):
                yield event
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except _UPSTREAM_ERRORS as exc:
        outcome = "error"
        payload = _error_payload(exc, timeout_s=None)
        yield {
            "type": "error",
            "status": payload.get("status"),
            "error": payload.get("error"),
        }
    finally:
        try:
            closer = getattr(response, "aclose", None)
            if closer is not None:
                await closer()
        finally:
            if client is not None:
                await client.close()
        _observe(provider, model, time.perf_counter() - started, "stream", outcome)


def stream_events(
    provider: str,
    *,
    api_key: Any,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Any = None,
    fallbacks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[AsyncIterator[Dict[str, Any]]]:
    """返回 LiteLLM 流事件迭代器；不支持时返回 ``None`` 由调用方降级。"""
    from modstore_server.strategic_portfolio_usage import (
        require_call_reservation,
        scope_active,
    )

    require_manual_life_capability()
    if scope_active():
        require_call_reservation(provider=provider, model=model)
        fallbacks = []
    if _build_specs(provider, model, api_key, base_url, fallbacks) is None or not available():
        return None
    return _stream_impl(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        fallbacks=fallbacks,
    )


def _observe(
    provider: str, model: str, elapsed: float, mode: str, outcome: str = "success"
) -> None:
    try:
        from modstore_server.metrics import observe_llm_router

        observe_llm_router(provider, model, mode, outcome, elapsed)
    except RECOVERABLE_ERRORS:
        return


def reset_cache() -> None:
    """测试用：清空 Router 与导入状态。"""

    global _LITELLM_MODULE, _LITELLM_FAILED
    with _ROUTER_LOCK:
        _ROUTER_CACHE.clear()
    with _LITELLM_LOCK:
        _LITELLM_MODULE = None
        _LITELLM_FAILED = False


__all__ = [
    "available",
    "chat",
    "reset_cache",
    "stream_events",
    "supports",
]


def supports(provider: str) -> bool:
    return provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS or provider in {
        "anthropic",
        "google",
    }
