# ruff: noqa
"""Provider-specific chat protocols for the unified LLM proxy."""
from __future__ import annotations
import json
from typing import Any, AsyncIterator, Dict, List, Optional


def _facade() -> Any:
    from modstore_server import llm_chat_proxy

    return llm_chat_proxy


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
    body = _facade()._openai_chat_body(
        provider, model, messages, max_tokens=max_tokens, response_format=response_format
    )
    async with _facade().httpx.AsyncClient(
        timeout=_facade()._LLM_TIMEOUT, limits=_facade()._LLM_LIMITS
    ) as client:
        r = await client.post(
            url, headers=_facade()._openai_request_headers(provider, api_key), json=body
        )
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") or {}
    (content, reasoning_trace) = _facade()._openai_assistant_message_parts(msg)
    if forbid_reasoning_fallback:
        if not (content or "").strip():
            msg_err = "模型未输出正文 content（常见于推理模型占满 max_tokens 或仅返回 reasoning）。代码生成路径禁止将推理链当作正文；请增大 max_tokens、换用非推理模型，或降低推理长度。"
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
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Any = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream OpenAI-compatible chat completions as normalized events.

    Yields:
      {"type": "delta", "delta": "..."}
      {"type": "toolcall", "choices": [{"index":0,"delta":{"tool_calls":[...]},"finish_reason":"tool_calls"}]}
      {"type": "usage", "usage": {...}} when upstream provides stream_options.include_usage
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = _facade()._openai_chat_body(
        provider,
        model,
        messages,
        max_tokens=max_tokens,
        stream=True,
        tools=tools,
        tool_choice=tool_choice,
    )
    async with _facade().httpx.AsyncClient(timeout=None, limits=_facade()._STREAM_LIMITS) as client:
        async with client.stream(
            "POST", url, headers=_facade()._openai_request_headers(provider, api_key), json=body
        ) as r:
            if r.status_code >= 400:
                text = await r.aread()
                yield {
                    "type": "error",
                    "status": r.status_code,
                    "error": text.decode("utf-8", errors="ignore")[:2000],
                }
                return
            tool_calls_accum: dict[int, dict[str, Any]] = {}
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
                for tc in delta.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    idx = int(tc.get("index") or 0)
                    cur = tool_calls_accum.get(idx)
                    if cur is None:
                        cur = {
                            "id": tc.get("id") or "",
                            "type": tc.get("type") or "function",
                            "function": {"name": "", "arguments": ""},
                        }
                        tool_calls_accum[idx] = cur
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        cur["function"]["name"] = str(fn["name"])
                    if fn.get("arguments"):
                        cur["function"]["arguments"] += str(fn["arguments"])
                    if tc.get("id"):
                        cur["id"] = str(tc["id"])
                if choice0.get("finish_reason") == "tool_calls" and tool_calls_accum:
                    ordered = [tool_calls_accum[i] for i in sorted(tool_calls_accum)]
                    yield {
                        "type": "toolcall",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"tool_calls": ordered},
                                "finish_reason": "tool_calls",
                            }
                        ],
                    }


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
    return (system, out)


async def chat_anthropic(
    api_key: str, model: str, messages: List[Dict[str, str]], *, max_tokens: int = 1024
) -> Dict[str, Any]:
    return await _facade().chat_anthropic_compatible(
        "https://api.anthropic.com", api_key, model, messages, max_tokens=max_tokens
    )


async def chat_anthropic_compatible(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    *,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    (system, msgs) = _facade()._oai_to_anthropic(messages)
    url = f"{base_url.rstrip('/')}/v1/messages"
    body: Dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if system:
        body["system"] = system
    async with _facade().httpx.AsyncClient(
        timeout=_facade()._LLM_TIMEOUT, limits=_facade()._LLM_LIMITS
    ) as client:
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
        if system_chunks and g_role == "user" and (not contents):
            text = "\n\n".join(system_chunks) + "\n\n" + text
            system_chunks = []
        contents.append({"role": g_role, "parts": [{"text": text}]})
    return contents


async def chat_google(api_key: str, model: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    contents = _facade()._oai_to_gemini(messages)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with _facade().httpx.AsyncClient(
        timeout=_facade()._LLM_TIMEOUT, limits=_facade()._LLM_LIMITS
    ) as client:
        r = await client.post(url, params={"key": api_key}, json={"contents": contents})
        text = r.text
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": text[:2000]}
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        return {"ok": False, "error": "no candidates", "raw": data}
    parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
    texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    usage = data.get("usageMetadata") or data.get("usage") or {}
    return {"ok": True, "content": "\n".join(texts), "usage": usage, "raw": data}
