"""Verified business actions for natural-language chat.

The implementation is split by operation; this module preserves the stable
public and test seams used by the chat routes.
"""

from __future__ import annotations

from typing import Any

from app.application.chat_business_safety_attendance import _handle_attendance_read
from app.application.chat_business_safety_core import (
    BusinessChatIntent,
    _resolve_actor_identity,
    classify_business_chat_intent,
)
from app.application.chat_business_safety_core import (
    _authenticated_user_from_request as _core_authenticated_user_from_request,
)
from app.application.chat_business_safety_core import (
    _db_path as _core_db_path,
)
from app.application.chat_business_safety_leave import _handle_leave_write
from app.application.chat_business_safety_output import (
    _default_get_printer_service,
    _handle_attendance_export,
    _handle_attendance_print,
)
from app.application.chat_business_safety_personnel import _handle_personnel_read
from app.mod_sdk.workspace import resolve_safe_workspace_relpath as _resolve_safe_workspace_relpath

_authenticated_user_from_request = _core_authenticated_user_from_request
_db_path = _core_db_path
_get_printer_service = _default_get_printer_service
resolve_safe_workspace_relpath = _resolve_safe_workspace_relpath


def try_handle_business_chat_action(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    request: Any = None,
) -> dict[str, Any] | None:
    """Execute a protected business action or return ``None`` for normal chat."""

    intent = classify_business_chat_intent(message)
    if intent is None:
        return None
    context = runtime_context if isinstance(runtime_context, dict) else {}
    actor = _resolve_actor_identity(
        request=request,
        runtime_context=context,
        client_user_id=user_id or str(context.get("user_id") or ""),
    )
    handlers = {
        "personnel_read": _handle_personnel_read,
        "attendance_read": _handle_attendance_read,
        "leave_write": _handle_leave_write,
        "attendance_export": _handle_attendance_export,
        "attendance_print": _handle_attendance_print,
    }
    handler = handlers.get(intent.operation)
    return handler(message, intent, actor=actor) if handler else None


__all__ = [
    "BusinessChatIntent",
    "classify_business_chat_intent",
    "try_handle_business_chat_action",
]
