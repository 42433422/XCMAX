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
import hashlib
import os
import threading
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
    platform_api_key,
    platform_base_url,
)
from modstore_server.llm_quota_monitor import scrub_llm_error
from modstore_server.platform_model_config import PlatformApiKey

_PRIMARY_ALIAS = "modstore-primary"
_FALLBACK_PREFIX = "modstore-fallback-"
_ROUTER_LOCK = threading.Lock()
_ROUTER_CACHE: Dict[Tuple[Any, ...], Any] = {}
_ROUTER_CACHE_MAX = 64
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
        except Exception:  # noqa: BLE001 - 可选依赖缺失必须降级而不是中断服务
            _LITELLM_FAILED = True
            return None
    return _LITELLM_MODULE


def available() -> bool:
    """LiteLLM 已安装且管理端/环境开关打开。"""

    from modstore_server.llm_router_config import settings

    if not settings()["enabled"]:
        return False
    return _load_litellm() is not None


def _key_fingerprint(api_key: Any) -> str:
    raw = str(api_key or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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

    if provider == "anthropic":
        litellm_model, params = f"anthropic/{model}", {"api_key": str(api_key)}
    elif provider == "google":
        litellm_model, params = f"gemini/{model}", {"api_key": str(api_key)}
    elif provider == "minimax" and is_minimax_token_plan_key(api_key):
        litellm_model = f"anthropic/{model}"
        params = {
            "api_key": normalize_minimax_api_key(api_key),
            "api_base": minimax_anthropic_base_url(base_url),
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
        "model_info": {"id": alias, "provider": provider, "model": model},
    }


def _key_pool(provider: str, api_key: Any, base_url: Optional[str]) -> List[Any]:
    """平台托管 Key 支持 ``MODSTORE_LLM_KEY_POOL_<PROVIDER>`` 轮询池。"""

    if not isinstance(api_key, PlatformApiKey):
        return []
    raw = (os.environ.get(f"MODSTORE_LLM_KEY_POOL_{provider.upper()}") or "").strip()
    if not raw:
        return []
    pool: List[Any] = []
    for item in raw.split(","):
        candidate = item.strip()
        if candidate and candidate != str(api_key):
            pool.append(PlatformApiKey(candidate, dict(api_key.configuration)))
    return pool


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


def env_platform_fallbacks(provider: str, model: str) -> List[Dict[str, Any]]:
    """返回管理端配置的平台 fallback 链（环境变量可覆盖）。

    格式：``minimax/MiniMax-M2.7,deepseek/deepseek-chat``；仅使用平台 Key，
    不会把用户 BYOK 请求切到平台付费。
    """

    raw = ",".join(_router_settings()["platform_fallbacks"])
    if not raw:
        return []
    rows: List[Dict[str, Any]] = []
    for item in raw.split(","):
        part = item.strip()
        if not part or "/" not in part:
            continue
        fb_provider, _, fb_model = part.partition("/")
        fb_provider = fb_provider.strip().lower()
        fb_model = fb_model.strip()
        if not fb_provider or not fb_model:
            continue
        if fb_provider == provider and fb_model == model:
            continue
        key = platform_api_key(fb_provider)
        if not key:
            continue
        rows.append(
            {
                "provider": fb_provider,
                "model": fb_model,
                "api_key": key,
                "base_url": (
                    platform_base_url(fb_provider)
                    if fb_provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                    else None
                ),
            }
        )
    return rows


def _build_specs(
    provider: str,
    model: str,
    api_key: Any,
    base_url: Optional[str],
    fallbacks: Optional[List[Dict[str, Any]]],
) -> Optional[Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]]:
    primary = _deployment(_PRIMARY_ALIAS, provider, model, api_key, base_url)
    if primary is None:
        return None
    deployments = [primary]
    for extra_key in _key_pool(provider, api_key, base_url):
        extra = _deployment(_PRIMARY_ALIAS, provider, model, extra_key, base_url)
        if extra is not None:
            deployments.append(extra)

    if fallbacks is None and isinstance(api_key, PlatformApiKey):
        fallbacks = env_platform_fallbacks(provider, model)

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
        except Exception:  # noqa: BLE001
            return {}
    if isinstance(usage, dict):
        return dict(usage)
    try:
        return dict(usage)
    except (TypeError, ValueError):
        return {}


def _fallback_meta(response: Any) -> Dict[str, Any]:
    hidden = getattr(response, "_hidden_params", None) or {}
    headers = hidden.get("additional_headers") if isinstance(hidden, dict) else None
    attempted = 0
    if isinstance(headers, dict):
        try:
            attempted = int(headers.get("x-litellm-attempted-fallbacks") or 0)
        except (TypeError, ValueError):
            attempted = 0
    return {"fallback_used": attempted > 0, "fallback_count": attempted}


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
            "usage": usage,
            "reasoning_trace": reasoning,
            **meta,
        }
    out: Dict[str, Any] = {
        "ok": True,
        "content": content or reasoning,
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

    if not available():
        return None
    specs = _build_specs(provider, model, api_key, base_url, fallbacks)
    if specs is None:
        return None
    deployments, fallback_aliases, _ = specs
    router = _get_router(deployments, fallback_aliases)
    if router is None:
        return None

    timeout_s = total_timeout_s or float(_router_settings()["request_timeout_seconds"])
    started = time.perf_counter()
    outcome = "success"
    try:
        call = router.acompletion(
            model=_PRIMARY_ALIAS,
            messages=messages,
            max_tokens=max_tokens,
            response_format=response_format,
            **({"timeout": float(primary_timeout_s)} if primary_timeout_s else {}),
        )
        response = await asyncio.wait_for(call, timeout=float(timeout_s))
        result = _normalize_response(
            response,
            provider=provider,
            model=model,
            forbid_reasoning_fallback=forbid_reasoning_fallback,
        )
        outcome = "success" if result.get("ok") else "error"
        return result
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 - 上游异常统一归一化
        outcome = "error"
        return _error_payload(exc, timeout_s=timeout_s)
    finally:
        _observe(provider, model, time.perf_counter() - started, "chat", outcome)


def _stream_delta_events(chunk: Any) -> List[Dict[str, Any]]:
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
        events.append(
            {
                "type": "toolcall",
                "choices": [
                    {"index": 0, "delta": {"tool_calls": normalized}, "finish_reason": "tool_calls"}
                ],
            }
        )
    finish_reason = getattr(choice0, "finish_reason", None)
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
    try:
        response = await router.acompletion(
            model=_PRIMARY_ALIAS,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in response:
            usage = _usage_dict(chunk)
            if usage:
                yield {"type": "usage", "usage": usage}
            for event in _stream_delta_events(chunk):
                yield event
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        outcome = "error"
        payload = _error_payload(exc, timeout_s=None)
        yield {"type": "error", "status": payload.get("status"), "error": payload.get("error")}
    finally:
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

    if not available() or _build_specs(provider, model, api_key, base_url, fallbacks) is None:
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
    except Exception:  # noqa: BLE001 - 指标失败不影响主链路
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
    "env_platform_fallbacks",
    "reset_cache",
    "stream_events",
    "supports",
]


def supports(provider: str) -> bool:
    return provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS or provider in {"anthropic", "google"}
