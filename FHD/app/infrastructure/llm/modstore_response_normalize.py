"""OpenAI 兼容响应规范化（从 ModstorePlatformAdapter 抽出）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.infrastructure.modstore_transport import safe_route_metadata


def normalize_market_chat_response(
    raw_response: Dict[str, Any], provider: str, model: str
) -> Dict[str, Any]:
    """Normalize gateway output and keep the actual public route identity."""
    route = {"provider": provider, "model": model, **safe_route_metadata(raw_response)}
    resolved_model = raw_response.get("model") or f"{route['provider']}/{route['model']}"
    usage = raw_response.get("usage", {})
    usage_dict = (
        vars(usage)
        if hasattr(usage, "__dict__")
        else dict(usage)
        if isinstance(usage, dict)
        else {}
    )
    raw_choices = raw_response.get("choices")
    normalized_choices: List[Dict[str, Any]] = []
    if isinstance(raw_choices, list) and raw_choices:
        for idx, choice in enumerate(raw_choices):
            choice_dict = choice if isinstance(choice, dict) else {}
            message = (
                choice_dict.get("message") if isinstance(choice_dict.get("message"), dict) else {}
            )
            if not isinstance(message, dict):
                message = {}
            normalized_message: Dict[str, Any] = {
                "role": message.get("role") or "assistant",
                "content": message.get("content") or "",
            }
            if message.get("tool_calls"):
                normalized_message["tool_calls"] = message.get("tool_calls")
            normalized_choices.append(
                {
                    "message": normalized_message,
                    "index": choice_dict.get("index", idx),
                    "finish_reason": choice_dict.get("finish_reason", "stop"),
                }
            )
    else:
        tool_calls = raw_response.get("tool_calls")
        normalized_choices = [
            {
                "message": {
                    "role": "assistant",
                    "content": raw_response.get("content", ""),
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ]
    billing = {
        **route,
        "resolved_model": resolved_model,
        "key_source": route.get("key_source"),
        "billed": raw_response.get("billed"),
        "charge_amount_cny": raw_response.get("charge_amount"),
        "request_id": raw_response.get("request_id"),
        "category": "llm",
    }
    return {
        "choices": normalized_choices,
        "usage": usage_dict,
        "model": resolved_model,
        "route_metadata": safe_route_metadata(raw_response),
        "_modstore_meta": {
            **billing,
            "success": raw_response.get("success"),
            "charge_amount": raw_response.get("charge_amount"),
            "conversation_id": raw_response.get("conversation_id"),
        },
        "_xcagi_billing": billing,
    }


def _reasoning_delta(payload: dict) -> str:
    """取平台 SSE 载荷里的推理增量；正文增量另走 content，二者互不混入。"""
    holders: list[Any] = [payload.get("delta"), payload]
    for choice in payload.get("choices") or []:
        if isinstance(choice, dict):
            holders.append(choice.get("delta"))
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        for key in ("reasoning_content", "reasoning"):
            value = holder.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def normalize_collected_stream(
    pieces: list[str],
    provider,
    model,
    ending: dict,
    max_tokens: int,
    reasoning: str = "",
    *,
    route,
    default_provider,
    default_model,
) -> Dict[str, Any]:
    """Normalize an assembled SSE response, keeping reasoning separate from body text."""
    route = route if isinstance(route, dict) else {}
    content = "".join(pieces)
    raw = {
        "content": content,
        "provider": route.get("provider") or provider or default_provider,
        "model": route.get("model") or model or default_model,
        **{key: value for key, value in route.items() if key not in {"provider", "model"}},
    }
    ending = ending if isinstance(ending, dict) else {}
    finish = ending.get("finish_reason")
    usage_value = ending.get("usage")
    usage: dict = usage_value if isinstance(usage_value, dict) else {}
    completion = usage.get("completion_tokens")
    if not finish and isinstance(completion, int) and max_tokens and completion >= max_tokens:
        # A market that does not relay finish_reason still reports the spent budget.
        finish = "length"
    if finish:
        raw["choices"] = [{"message": {"content": content}, "finish_reason": finish}]
    if usage:
        raw["usage"] = usage
    response = normalize_market_chat_response(raw, str(raw["provider"]), str(raw["model"]))
    if reasoning.strip():
        # 推理文本与正文分开返回，供上层作为思考步骤展示与持久化。
        response["reasoning_content"] = reasoning
    if ending.get("replayed") is True:
        response["replayed"] = True
    return response


def absorb_stream_payload(
    data: str,
    status_cb,
    pieces: list[str],
    ending: dict | None = None,
    reasoning: list[str] | None = None,
    *,
    payload_has_content,
) -> None:
    """Collect answer/reasoning deltas and terminal metadata from one SSE payload."""
    # Only payloads that carry real answer content show the call is still producing;
    # market heartbeats must never extend the caller's idle wait.
    if not data:
        return
    try:
        payload = json.loads(data)
    except (ValueError, TypeError):
        pieces.append(str(data))
        if status_cb is not None:
            status_cb()
        return
    if payload_has_content(payload) and status_cb is not None:
        status_cb()
    if not isinstance(payload, dict):
        return
    if reasoning is not None:
        reasoning_delta = _reasoning_delta(payload)
        if reasoning_delta:
            reasoning.append(reasoning_delta)
    if ending is not None:
        for key in ("finish_reason", "usage", "replayed"):
            if payload.get(key) is not None:
                ending[key] = payload[key]
        for choice in payload.get("choices") or []:
            if isinstance(choice, dict) and choice.get("finish_reason"):
                ending["finish_reason"] = choice["finish_reason"]
    if payload.get("status") == "processing" or payload.get("state") == "accepted":
        return
    delta = payload.get("delta")
    content = delta if isinstance(delta, str) and delta else payload.get("content")
    if isinstance(content, str) and content:
        pieces.append(content)
        return
    for choice in payload.get("choices") or []:
        message = choice.get("delta") if isinstance(choice, dict) else None
        if isinstance(message, dict) and message.get("content"):
            pieces.append(str(message["content"]))
