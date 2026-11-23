"""Decode provider JSON envelopes and retain explicit completion evidence."""

import json
import re
from typing import Any

# 模型偶尔在 JSON 字符串值里输出裸控制字符（\x00-\x1f），json.loads 会直接拒绝。
_BARE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_model_json(raw: str) -> str:
    """清洗模型输出中的裸控制字符，保留换行与制表符，避免合法计划被误拒。"""
    return _BARE_CONTROL_CHARS.sub("", raw)


def load_model_json(raw: str) -> Any:
    """严格 JSON 优先；失败时用 json-repair 容忍模型常见截断/尾逗号。"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        try:
            from json_repair import loads as repair_loads
        except ImportError:
            return None
        try:
            return repair_loads(raw)
        except (ValueError, TypeError):
            return None


def model_payload(response_data: dict[str, Any]) -> tuple[Any, str]:
    """返回（解析后的 JSON, 原始正文）；不校验业务结构。"""
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None, ""
    raw = str(message.get("content") or "").strip()
    if not raw:
        return None, ""
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return load_model_json(sanitize_model_json(raw)), raw


def normal_finish_reason(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"stop", "end_turn", "stop_sequence"}


def provider_supports_streaming(provider: Any) -> bool:
    return callable(getattr(provider, "stream_chat_completion", None)) and bool(
        getattr(provider, "supports_streaming", True)
    )


def completion_is_incomplete(response: Any) -> bool:
    choices = response.get("choices") if isinstance(response, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(first, dict):
        return False
    reason = first.get("finish_reason")
    # Existing non-streaming completion ports can omit terminal metadata.
    # An explicit abnormal reason always wins over a parseable reply body.
    if "finish_reason" not in first or normal_finish_reason(reason):
        return False
    message = first.get("message")
    return not (reason == "tool_calls" and isinstance(message, dict) and message.get("tool_calls"))
