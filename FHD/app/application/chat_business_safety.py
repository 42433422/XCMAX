"""Application facade for verified business chat actions.

Keeps infrastructure auth resolution out of domain.app_pure.
"""

from __future__ import annotations

from typing import Any

from app.domain.app_pure.chat_business_safety import (
    BusinessChatIntent,
    classify_business_chat_intent,
    try_handle_business_chat_action,
)
from app.domain.app_pure.chat_business_safety import (
    _db_path as _db_path,
)
from app.mod_sdk.workspace import resolve_safe_workspace_relpath as resolve_safe_workspace_relpath
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _authenticated_user_from_request(request: Any) -> Any | None:
    if request is None:
        return None
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        return resolve_session_user(request)
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - identity resolution must fail closed
        return None


__all__ = [
    "BusinessChatIntent",
    "classify_business_chat_intent",
    "try_handle_business_chat_action",
]
