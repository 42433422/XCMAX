"""Budgeted redaction of model-visible context without leaking authority fields."""

from __future__ import annotations

import re
from typing import Any

_MODEL_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|密码|口令)\b\s*[:=]\s*)([^\s,;]+)|"
    r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+"
)
_MODEL_CONTEXT_PRIVATE_KEYS = (
    "authorization",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "credential",
    "cookie",
    "session",
    "conversation_id",
    "turn_id",
    "idempotency",
    "user_id",
    "actor_id",
    "tenant_id",
    "workspace_id",
    "permission",
    "secret",
    "token",
)
_MODEL_CONTEXT_MAX_CHARS = 24_000
_MODEL_CONTEXT_PRIORITY_KEYS = (
    "chat_knowledge_evidence",
    "chat_knowledge_dataset_ids",
    "chat_customer_evidence",
    "chat_memory_evidence",
    "memory_v2",
    "user_memory_rag",
    "available_employees",
    "file_context",
    "file_analysis",
    "excel_analysis",
)


def _model_context_value(
    value: Any, _remaining: list[int] | None = None, *, newest_first: bool = False
) -> Any:
    """Bound, redact, and strip identity/authority fields before model IO."""
    if _remaining is None:
        _remaining = [_MODEL_CONTEXT_MAX_CHARS]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        priority = {key: index for index, key in enumerate(_MODEL_CONTEXT_PRIORITY_KEYS)}
        entries = sorted(
            value.items(),
            key=lambda pair: (priority.get(str(pair[0]), len(priority)), str(pair[0])),
        )
        for raw_key, item in entries:
            key = str(raw_key)
            lowered = key.lower()
            if (
                key
                in {
                    "recent_messages",
                    "chat_owned_history",
                    "chat_history_summary",
                    "planning_diagnostics",
                    "goal_coverage_trace",
                    "plan_shape_repair_trace",
                    "plan_repair_trace",
                }
                or key.startswith("_")
                or any(part in lowered for part in _MODEL_CONTEXT_PRIVATE_KEYS)
            ):
                continue
            if key == "attachment_evidence" and isinstance(item, str):
                # This is the current turn's evidence. The shared model gateway
                # budgets it with the whole turn instead of silently cutting it.
                safe[key] = _MODEL_SECRET_TEXT.sub(
                    lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", item
                )
                continue
            safe[key] = _model_context_value(
                item, _remaining, newest_first=key in {"recent_messages", "chat_owned_history"}
            )
        return safe
    if isinstance(value, list):
        items = reversed(value[-200:]) if newest_first else iter(value[:200])
        safe_items = [_model_context_value(item, _remaining) for item in items if _remaining[0] > 0]
        return list(reversed(safe_items)) if newest_first else safe_items
    if isinstance(value, str):
        if _remaining[0] <= 0:
            return ""
        bounded = value[: min(12_000, _remaining[0])]
        _remaining[0] -= len(bounded)
        return _MODEL_SECRET_TEXT.sub(
            lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", bounded
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]
