"""Pure OpenAI shape conversion and owned adaptation of a native market stream."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Dict

from .ports import Messages, OpenAIPorts, Payload


def _to_openai_object(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_openai_object(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_openai_object(v) for v in value]
    return value


def _normalize_stream_choice(choice: Dict[str, Any]) -> Dict[str, Any]:
    if "delta" in choice:
        return choice
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    delta: Dict[str, Any] = {}
    if not isinstance(message, dict):
        message = {}
    if message.get("content"):
        delta["content"] = message.get("content")
    if message.get("tool_calls"):
        delta["tool_calls"] = message.get("tool_calls")
    return {
        "index": choice.get("index", 0),
        "delta": delta,
        "finish_reason": choice.get("finish_reason"),
    }


def _platform_stream_payload_to_openai_chunk(data: str) -> Dict[str, Any] | None:
    raw_text = (data or "").strip()
    if not raw_text or raw_text == "[DONE]":
        return None
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"choices": [{"delta": {"content": raw_text}, "finish_reason": None}]}

    if isinstance(raw, dict) and raw.get("choices"):
        choices = raw.get("choices") or []
        return {
            **raw,
            "choices": [
                _normalize_stream_choice(c if isinstance(c, dict) else {}) for c in choices
            ],
        }

    if isinstance(raw, dict) and raw.get("type") == "error":
        raise ValueError(str(raw.get("message") or raw.get("error") or "平台模型流式错误"))

    if isinstance(raw, dict):
        content = raw.get("content") or raw.get("text") or raw.get("delta") or ""
        delta: Dict[str, Any] = {}
        if content:
            delta["content"] = str(content)
        tool_calls = raw.get("tool_calls")
        if tool_calls:
            delta["tool_calls"] = tool_calls
        finish_reason = raw.get("finish_reason")
        if delta or finish_reason:
            return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}

    return None


def _market_sse_payload_has_content(data: str) -> bool:
    """True when a market SSE data payload carries visible delta content."""
    try:
        chunk = _platform_stream_payload_to_openai_chunk(data)
    except ValueError:
        return False
    if not chunk:
        return False
    for choice in chunk.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return True
    return False


def stream_response(
    ports: OpenAIPorts,
    *,
    messages: Messages,
    model: str | None,
    temperature: float,
    max_tokens: int,
    extra: Payload,
) -> Iterator[Any]:
    # Emit a valid role prelude while the provider is waiting for its first token.
    yield _to_openai_object(
        {
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            "model": model or ports.model_name,
        }
    )
    if os.environ.get("XCAGI_MODSTORE_USE_NATIVE_STREAM", "").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        result = ports.complete(
            messages=messages, temperature=temperature, max_tokens=max_tokens, model=model, **extra
        )
        choice = (result.get("choices") or [{}])[0]
        yield _to_openai_object(
            {"choices": [_normalize_stream_choice(choice)], "model": result.get("model")}
        )
        return
    source = ports.stream(
        messages=messages, temperature=temperature, max_tokens=max_tokens, model=model, **extra
    )
    try:
        for data in source:
            chunk = _platform_stream_payload_to_openai_chunk(data)
            if chunk is not None:
                yield _to_openai_object(chunk)
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
