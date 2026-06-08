"""统一聊天代理：OpenAI 兼容 / Anthropic / Google Gemini。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    openai_compat_default_root,
)
from modstore_server.multimodal_llm import messages_use_openai_multipart_content

_MODEL_ALIASES: dict[tuple[str, str], str] = {
    # 小米 2026-05 模型目录已不再接受 mimo-v2-base；兼容前端/账户缓存中的旧选择。
    ("xiaomi", "mimo-v2-base"): "mimo-v2.5-pro",
    # 旧基准默认 / 历史 env 仍写此 ID 时，映射到当前网关支持的对话模型。
    ("xiaomi", "MiMo-7B-RL-Think"): "mimo-v2.5-pro",
    # 部分区域网关不报 flash；统一映射到 pro（与 services.llm 基准默认一致）
    ("xiaomi", "mimo-v2-flash"): "mimo-v2.5-pro",
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


async def chat_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    provider: str = "openai",
    max_tokens: Optional[int] = None,
    forbid_reasoning_fallback: bool = False,
    response_format: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = _openai_chat_body(
        provider,
        model,
        messages,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, limits=_LLM_LIMITS) as client:
        r = await client.post(
            url,
            headers=_openai_request_headers(provider, api_key),
            json=body,
        )
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") or {}
    content, reasoning_trace = _openai_assistant_message_parts(msg)
    if forbid_reasoning_fallback:
        if not (content or "").strip():
            msg_err = (
                "模型未输出正文 content（常见于推理模型占满 max_tokens 或仅返回 reasoning）。"
                "代码生成路径禁止将推理链当作正文；请增大 max_tokens、换用非推理模型，或降低推理长度。"
            )
            out_fail: Dict[str, Any] = {
                "ok": False,
                "error": msg_err,
                "content": "",
                "usage": data.get("usage") or {},
                "raw": data,
            }
            if reasoning_trace:
                out_fail["reasoning_trace"] = reasoning_trace
            return out_fail
        text_out = content
    else:
        text_out = content if content else reasoning_trace
    out: Dict[str, Any] = {
        "ok": True,
        "content": text_out,
        "usage": data.get("usage") or {},
        "raw": data,
    }
    if reasoning_trace:
        out["reasoning_trace"] = reasoning_trace
    return out


async def stream_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    provider: str = "openai",
    max_tokens: Optional[int] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream OpenAI-compatible chat completions as normalized events.

    Yields:
      {"type": "delta", "delta": "..."}
      {"type": "usage", "usage": {...}} when upstream provides stream_options.include_usage
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = _openai_chat_body(
        provider,
        model,
        messages,
        max_tokens=max_tokens,
        stream=True,
    )
    async with httpx.AsyncClient(timeout=None, limits=_STREAM_LIMITS) as client:
        async with client.stream(
            "POST",
            url,
            headers=_openai_request_headers(provider, api_key),
            json=body,
        ) as r:
            if r.status_code >= 400:
                text = await r.aread()
                yield {
                    "type": "error",
                    "status": r.status_code,
                    "error": text.decode("utf-8", errors="ignore")[:2000],
                }
                return
            async for line in r.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("usage"):
                    yield {"type": "usage", "usage": data.get("usage") or {}}
                choice0 = (data.get("choices") or [{}])[0] or {}
                delta = choice0.get("delta") or {}
                content = delta.get("content")
                if content:
                    yield {"type": "delta", "delta": str(content)}


def _oai_to_anthropic(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, Any]]]:
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = (m.get("role") or "user").strip()
        content = (m.get("content") or "").strip()
        if role == "system":
            system_parts.append(content)
            continue
        if role not in ("user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    system = "\n\n".join(system_parts) if system_parts else ""
    return system, out


async def chat_anthropic(
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    *,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    system, msgs = _oai_to_anthropic(messages)
    url = "https://api.anthropic.com/v1/messages"
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": msgs,
    }
    if system:
        body["system"] = system
    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, limits=_LLM_LIMITS) as client:
        r = await client.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    blocks = data.get("content") or []
    parts: List[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text") or ""))
    return {"ok": True, "content": "\n".join(parts), "usage": data.get("usage") or {}, "raw": data}


def _oai_to_gemini(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    contents: List[Dict[str, Any]] = []
    system_chunks: List[str] = []
    for m in messages:
        role = (m.get("role") or "user").strip()
        content = (m.get("content") or "").strip()
        if role == "system":
            system_chunks.append(content)
            continue
        g_role = "user" if role == "user" else "model"
        text = content
        if system_chunks and g_role == "user" and not contents:
            text = "\n\n".join(system_chunks) + "\n\n" + text
            system_chunks = []
        contents.append({"role": g_role, "parts": [{"text": text}]})
    return contents


async def chat_google(
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    contents = _oai_to_gemini(messages)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, limits=_LLM_LIMITS) as client:
        r = await client.post(
            url,
            params={"key": api_key},
            json={"contents": contents},
        )
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        return {"ok": False, "error": "no candidates", "raw": data}
    parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    usage = data.get("usageMetadata") or data.get("usage") or {}
    return {"ok": True, "content": "\n".join(texts), "usage": usage, "raw": data}


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
            if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
                return {
                    "ok": False,
                    "error": "图文多模态输入仅支持 OpenAI 兼容接口（chat/completions）；"
                    "请切换供应商或使用纯文本消息。",
                }
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
    except (_asyncio.TimeoutError, Exception) as exc:
        primary_error = f"{type(exc).__name__}: {exc}"

    # ---- fallback
    fb_provider = str(fallback_provider)
    fb_model = normalize_model(fb_provider, str(fallback_model))
    fb_key = str(fallback_api_key or api_key)
    fb_base = fallback_base_url or base_url
    try:
        if fb_provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
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
            fb_result = {"ok": False, "error": f"unsupported fallback provider: {fb_provider}"}
    except Exception as exc2:  # noqa: BLE001
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
) -> AsyncIterator[Dict[str, Any]]:
    model = normalize_model(provider, model)
    if (
        messages_use_openai_multipart_content(messages)
        and provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    ):
        yield {
            "type": "error",
            "error": "图文多模态输入仅支持 OpenAI 兼容接口；请切换供应商或使用纯文本。",
        }
        return
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        b = _normalize_openai_base(provider, base_url)
        async for ev in stream_openai_compatible(
            b, api_key, model, messages, provider=provider, max_tokens=max_tokens
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


async def image_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    size: str = "1024x1024",
    n: int = 1,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/images/generations"
    body: Dict[str, Any] = {
        "model": model or "gpt-image-1",
        "prompt": prompt,
        "size": size,
        "n": max(1, min(int(n or 1), 4)),
    }
    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT, limits=_LLM_LIMITS) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    images: List[str] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        if item.get("url"):
            images.append(str(item["url"]))
        elif item.get("b64_json"):
            images.append(f"data:image/png;base64,{item['b64_json']}")
    return {"ok": True, "images": images, "raw": data}


async def image_dispatch(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    prompt: str,
    size: str = "1024x1024",
    n: int = 1,
) -> Dict[str, Any]:
    if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return {
            "ok": False,
            "error": f"provider {provider} does not expose OpenAI-compatible images API",
        }
    b = _normalize_openai_base(provider, base_url)
    return await image_openai_compatible(b, api_key, model or "gpt-image-1", prompt, size=size, n=n)
