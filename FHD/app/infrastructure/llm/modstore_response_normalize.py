"""OpenAI 兼容响应规范化（从 ModstorePlatformAdapter 抽出）。"""

from __future__ import annotations

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
