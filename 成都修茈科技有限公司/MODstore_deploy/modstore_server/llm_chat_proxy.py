# mypy: disable-error-code="arg-type"
"""统一聊天代理：OpenAI 兼容 / Anthropic / Google Gemini。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from modstore_server.llm_chat_providers import _oai_to_anthropic as _oai_to_anthropic
from modstore_server.llm_chat_providers import _oai_to_gemini as _oai_to_gemini
from modstore_server.llm_chat_providers import chat_anthropic as chat_anthropic
from modstore_server.llm_chat_providers import (
    chat_anthropic_compatible as chat_anthropic_compatible,
)
from modstore_server.llm_chat_providers import chat_google as chat_google
from modstore_server.llm_chat_providers import chat_openai_compatible as chat_openai_compatible
from modstore_server.llm_chat_providers import stream_openai_compatible as stream_openai_compatible
from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
    openai_compat_default_root,
)
from modstore_server.llm_media_proxy import _first_video_url as _first_video_url
from modstore_server.llm_media_proxy import image_dispatch as image_dispatch
from modstore_server.llm_media_proxy import image_openai_compatible as image_openai_compatible
from modstore_server.llm_media_proxy import video_dispatch as video_dispatch
from modstore_server.llm_media_proxy import video_openai_compatible as video_openai_compatible
from modstore_server.multimodal_llm import messages_use_openai_multipart_content
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

_MODEL_ALIASES: dict[tuple[str, str], str] = {
    # 小米 2026-05 模型目录已不再接受 mimo-v2-base；兼容前端/账户缓存中的旧选择。
    ("xiaomi", "mimo-v2-base"): "mimo-v2.5-pro",
    # 旧基准默认 / 历史 env 仍写此 ID 时，映射到当前网关支持的对话模型。
    ("xiaomi", "MiMo-7B-RL-Think"): "mimo-v2.5-pro",
    # 部分区域网关不报 flash；统一映射到 pro（与 services.llm 基准默认一致）
    ("xiaomi", "mimo-v2-flash"): "mimo-v2.5-pro",
    # 2026-06-30 下线的 V2 系列（官方替换表：platform.xiaomimimo.com/docs/.../deprecate）
    ("xiaomi", "mimo-v2-pro"): "mimo-v2.5-pro",
    ("xiaomi", "mimo-v2-omni"): "mimo-v2.5",
    ("xiaomi", "mimo-v2-tts"): "mimo-v2.5-tts",
    # MiniMax legacy ABAB ids are no longer the platform default; keep stale
    # account/env selections working by routing them to the current agent model.
    ("minimax", "abab6.5s-chat"): "MiniMax-M2.7",
}

# 禁止使用进程级单例 AsyncClient：会在 ``asyncio.run()`` / 线程池等多事件循环场景下
# 绑定已关闭的 loop，触发 ``RuntimeError: Event loop is closed``（httpx aclose）。
_LLM_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
_LLM_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=30.0)
_STREAM_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=200)


def _normalize_openai_base(provider: str, base_url: Optional[str]) -> str:
    b = (base_url or openai_compat_default_root(provider)).rstrip("/")
    if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
        b = b + "/v1"
    return b


def normalize_model(provider: str, model: str) -> str:
    return _MODEL_ALIASES.get((provider, model), model)


def _openai_request_headers(provider: str, api_key: str) -> Dict[str, str]:
    """MiMo Token Plan 文档推荐 api-key；其余厂商用 Bearer。"""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if provider == "xiaomi":
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _openai_chat_body(
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, str]] = None,
    stream: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Any = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "messages": messages}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
        if provider == "xiaomi":
            body["max_completion_tokens"] = max_tokens
            body.setdefault("thinking", {"type": "disabled"})
    if response_format:
        body["response_format"] = response_format
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    return body


def _openai_assistant_message_parts(msg: Dict[str, Any]) -> tuple[str, str]:
    """Extract visible answer and reasoning trace from an OpenAI-style assistant message.

    Thinking/reasoning models (DeepSeek-R1、MiMo、部分兼容网关) 常在 ``reasoning_content``
    中返回长链推理，正式回复仍在 ``content``；若 ``max_tokens`` 预算不足，可能出现
    ``content`` 为空仅保留推理段 —— 下游若只读 ``content`` 会得到「像没有思考」或解析失败。
    """
    if not isinstance(msg, dict):
        return "", ""
    content = str(msg.get("content") or "").strip()
    reasoning = str(
        msg.get("reasoning_content") or msg.get("reasoning") or msg.get("thinking") or ""
    ).strip()
    return content, reasoning


async def chat_dispatch(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    forbid_reasoning_fallback: bool = False,
    response_format: Optional[Dict[str, str]] = None,
    # Timeout fallback: if primary call exceeds this (seconds), retry with fallback_provider/model
    timeout_fallback_s: Optional[float] = None,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
    fallback_api_key: Optional[str] = None,
    fallback_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    model = normalize_model(provider, model)
    has_fallback = bool(timeout_fallback_s and fallback_provider and fallback_model)

    async def _primary() -> Dict[str, Any]:
        if messages_use_openai_multipart_content(messages):
            if provider == "minimax" and is_minimax_token_plan_key(api_key):
                return {
                    "ok": False,
                    "error": "MiniMax Token Plan 的 Anthropic 兼容入口当前只接收纯文本消息。",
                }
            if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
                return {
                    "ok": False,
                    "error": "图文多模态输入仅支持 OpenAI 兼容接口（chat/completions）；"
                    "请切换供应商或使用纯文本消息。",
                }
        if provider == "minimax" and is_minimax_token_plan_key(api_key):
            return await chat_anthropic_compatible(
                minimax_anthropic_base_url(base_url),
                normalize_minimax_api_key(api_key),
                model,
                messages,
                max_tokens=max_tokens or 1024,
            )
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            b = _normalize_openai_base(provider, base_url)
            return await chat_openai_compatible(
                b,
                api_key,
                model,
                messages,
                provider=provider,
                max_tokens=max_tokens,
                forbid_reasoning_fallback=forbid_reasoning_fallback,
                response_format=response_format,
            )
        if provider == "anthropic":
            return await chat_anthropic(api_key, model, messages, max_tokens=max_tokens or 1024)
        if provider == "google":
            return await chat_google(api_key, model, messages)
        return {"ok": False, "error": f"unsupported provider: {provider}"}

    async def _primary_with_retries() -> Dict[str, Any]:
        import asyncio as _asyncio

        last: Dict[str, Any] = {"ok": False, "error": "no primary attempt"}
        for attempt in range(3):
            transient_exc = False
            try:
                last = await _primary()
            except httpx.TransportError as exc:
                # 对端中断连接 / 读写超时 / 协议错误（RemoteProtocolError 等）等瞬时网络故障：
                # 当作可重试，转成错误 dict 而非向上抛，避免无 fallback 的调用方（如员工大会）直接判为异常。
                last = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                transient_exc = True
            if last.get("ok"):
                return last
            err = str(last.get("error") or "")
            st = last.get("status")
            retryable = (
                transient_exc
                or st in (429, 502, 503, 504)
                or any(
                    x in err.lower()
                    for x in (
                        "timeout",
                        "timed out",
                        "connection",
                        "rate limit",
                        "disconnect",
                        "protocol",
                    )
                )
            )
            if attempt < 2 and retryable:
                await _asyncio.sleep(0.35 * (2**attempt))
                continue
            break
        return last

    if not has_fallback:
        return await _primary_with_retries()

    import asyncio as _asyncio

    try:
        result = await _asyncio.wait_for(_primary_with_retries(), timeout=float(timeout_fallback_s))
        if result.get("ok"):
            return result
        # provider returned error — fall through to fallback
        primary_error = result.get("error") or "primary returned error"
    except RECOVERABLE_ERRORS as exc:
        primary_error = f"{type(exc).__name__}: {exc}"

    # ---- fallback
    fb_provider = str(fallback_provider)
    fb_model = normalize_model(fb_provider, str(fallback_model))
    fb_key = str(fallback_api_key or api_key)
    fb_base = fallback_base_url or base_url
    try:
        if fb_provider == "minimax" and is_minimax_token_plan_key(fb_key):
            fb_result = await chat_anthropic_compatible(
                minimax_anthropic_base_url(fallback_base_url),
                normalize_minimax_api_key(fb_key),
                fb_model,
                messages,
                max_tokens=max_tokens or 1024,
            )
        elif fb_provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            fb_b = _normalize_openai_base(fb_provider, fb_base)
            fb_result = await chat_openai_compatible(
                fb_b,
                fb_key,
                fb_model,
                messages,
                provider=fb_provider,
                max_tokens=max_tokens,
                forbid_reasoning_fallback=forbid_reasoning_fallback,
                response_format=response_format,
            )
        elif fb_provider == "anthropic":
            fb_result = await chat_anthropic(
                fb_key, fb_model, messages, max_tokens=max_tokens or 1024
            )
        elif fb_provider == "google":
            fb_result = await chat_google(fb_key, fb_model, messages)
        else:
            fb_result = {
                "ok": False,
                "error": f"unsupported fallback provider: {fb_provider}",
            }
    except BOUNDARY_ERRORS as exc2:  # noqa: BLE001
        fb_result = {"ok": False, "error": f"fallback failed: {exc2}"}

    if fb_result.get("ok"):
        fb_result["_fallback_used"] = True
        fb_result["_primary_error"] = primary_error
    return fb_result


async def chat_dispatch_stream(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Any = None,
) -> AsyncIterator[Dict[str, Any]]:
    model = normalize_model(provider, model)
    if messages_use_openai_multipart_content(messages) and (
        provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        or (provider == "minimax" and is_minimax_token_plan_key(api_key))
    ):
        yield {
            "type": "error",
            "error": "图文多模态输入仅支持 OpenAI 兼容接口；请切换供应商或使用纯文本。",
        }
        return
    if provider == "minimax" and is_minimax_token_plan_key(api_key):
        result = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if not result.get("ok"):
            yield {"type": "error", "error": result.get("error") or "upstream error"}
            return
        content = str(result.get("content") or "")
        if content:
            yield {"type": "delta", "delta": content}
        if result.get("usage"):
            yield {"type": "usage", "usage": result.get("usage") or {}}
        return
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        b = _normalize_openai_base(provider, base_url)
        async for ev in stream_openai_compatible(
            b,
            api_key,
            model,
            messages,
            provider=provider,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        ):
            yield ev
        return
    # Anthropic / Google 后续可接各自原生 stream；当前保持兼容，回退成一次性结果。
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    if not result.get("ok"):
        yield {"type": "error", "error": result.get("error") or "upstream error"}
        return
    content = str(result.get("content") or "")
    if content:
        yield {"type": "delta", "delta": content}
    if result.get("usage"):
        yield {"type": "usage", "usage": result.get("usage") or {}}
