"""OpenAI 兼容响应规范化（从 ModstorePlatformAdapter 抽出）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def normalize_market_chat_response(
    raw_response: Dict[str, Any], provider: str, model: str
) -> Dict[str, Any]:
    """
    将修茈市场响应标准化为OpenAI格式

    修茈市场返回格式:
    {
        "success": True,
        "content": "...",
        "usage": {...},
        "charge_amount": 0.01,
        "key_source": "platform",
        "provider": "xiaomi",
        "model": "mimo-v2.5-pro",
        ...
    }

    OpenAI标准格式:
    {
        "choices": [{
            "message": {"role": "assistant", "content": "..."},
            "index": 0,
            "finish_reason": "stop"
        }],
        "usage": {...},
        "model": "..."
    }
    """
    raw_choices = raw_response.get("choices")
    if isinstance(raw_choices, list) and raw_choices:
        normalized_choices: List[Dict[str, Any]] = []
        for idx, choice in enumerate(raw_choices):
            choice_dict = choice if isinstance(choice, dict) else {}
            message = (
                choice_dict.get("message")
                if isinstance(choice_dict.get("message"), dict)
                else {}
            )
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
        usage = raw_response.get("usage", {})
        usage_dict = dict(usage) if isinstance(usage, dict) else {}
        return {
            "choices": normalized_choices,
            "usage": usage_dict,
            "model": raw_response.get("model") or f"{provider}/{model}",
            "_modstore_meta": {
                "success": raw_response.get("success"),
                "provider": raw_response.get("provider") or provider,
                "model": raw_response.get("model") or model,
                "resolved_model": raw_response.get("model") or f"{provider}/{model}",
                "key_source": raw_response.get("key_source"),
                "billed": raw_response.get("billed"),
                "charge_amount": raw_response.get("charge_amount"),
                "charge_amount_cny": raw_response.get("charge_amount"),
                "conversation_id": raw_response.get("conversation_id"),
                "request_id": raw_response.get("request_id"),
                "category": "llm",
            },
            "_xcagi_billing": {
                "provider": raw_response.get("provider") or provider,
                "model": raw_response.get("model") or model,
                "resolved_model": raw_response.get("model") or f"{provider}/{model}",
                "key_source": raw_response.get("key_source"),
                "billed": raw_response.get("billed"),
                "charge_amount_cny": raw_response.get("charge_amount"),
                "request_id": raw_response.get("request_id"),
                "category": "llm",
            },
        }

    content = raw_response.get("content", "")
    usage = raw_response.get("usage", {})
    tool_calls = raw_response.get("tool_calls")

    # 处理usage对象（可能是dataclass或dict）
    if hasattr(usage, "__dict__"):
        usage_dict = usage.__dict__
    else:
        usage_dict = dict(usage) if isinstance(usage, dict) else {}

    normalized = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "usage": usage_dict,
        "model": f"{provider}/{model}",
        "_modstore_meta": {
            "success": raw_response.get("success"),
            "provider": raw_response.get("provider") or provider,
            "model": raw_response.get("model") or model,
            "resolved_model": f"{provider}/{model}",
            "key_source": raw_response.get("key_source"),
            "billed": raw_response.get("billed"),
            "charge_amount": raw_response.get("charge_amount"),
            "charge_amount_cny": raw_response.get("charge_amount"),
            "conversation_id": raw_response.get("conversation_id"),
            "request_id": raw_response.get("request_id"),
            "category": "llm",
        },
        "_xcagi_billing": {
            "provider": raw_response.get("provider") or provider,
            "model": raw_response.get("model") or model,
            "resolved_model": f"{provider}/{model}",
            "key_source": raw_response.get("key_source"),
            "billed": raw_response.get("billed"),
            "charge_amount_cny": raw_response.get("charge_amount"),
            "request_id": raw_response.get("request_id"),
            "category": "llm",
        },
    }

    return normalized
