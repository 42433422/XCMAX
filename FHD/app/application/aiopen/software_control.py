"""Internal AI screen bridge. Identity comes from host context, never model args."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_screen_actor: ContextVar[dict[str, str] | None] = ContextVar("software_screen_actor", default=None)


@contextmanager
def screen_actor_scope(runtime_context: dict[str, Any]) -> Iterator[None]:
    """Only trusted task execution code may restore a persisted task's identity."""
    identity = {
        "owner_id": str(
            runtime_context.get("local_user_id") or runtime_context.get("actor_id") or ""
        ),
        "tenant_id": str(runtime_context.get("tenant_id") or ""),
    }
    token = _screen_actor.set(identity)
    try:
        yield
    finally:
        _screen_actor.reset(token)


def request_screen_owner(request: Any) -> dict[str, str]:
    from app.infrastructure.auth.dependencies import resolve_session_user

    if request is None:
        return {}
    user = resolve_session_user(request)
    if user is None or not getattr(user, "is_active", True):
        return {}
    actor = getattr(user, "id", None)
    tenant = getattr(user, "tenant_id", None)
    if actor is None or tenant is None:
        return {}
    return {"owner_id": str(actor), "tenant_id": str(tenant)}


def execute_software_control(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.aiopen.service import _UI_ACTIONS, AIOPEN_STATE
    from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
    from app.infrastructure.request_context import get_current_request

    # A public /tools/execute payload may contain _runtime_context. It is not
    # an authorization source; only sessions and trusted task scopes qualify.
    identity = _screen_actor.get() or request_screen_owner(get_current_request())
    owner = identity.get("owner_id", "")
    tenant = identity.get("tenant_id", "")
    if not owner or not tenant:
        return {
            "success": False,
            "code": "SCREEN_IDENTITY_REQUIRED",
            "message": "软件控制需要已登录账号和租户上下文",
        }
    if not AIOPEN_STATE.get("remote_control_enabled", False):
        return {
            "success": False,
            "code": "REMOTE_CONTROL_DISABLED",
            "message": "软件控制开关已关闭",
        }
    if action == "list":
        return {
            "success": True,
            "sessions": aiopen_cursor_hub.sessions_info(owner_id=owner, tenant_id=tenant),
        }
    if action not in set(_UI_ACTIONS.values()):
        return {"success": False, "code": "UNKNOWN_SCREEN_ACTION", "message": "未知软件控制动作"}
    session_id = str(params.get("session_id") or "") or None
    screen_params = {key: value for key, value in params.items() if key != "session_id"}
    return aiopen_cursor_hub.dispatch_sync(
        action, screen_params, session_id=session_id, owner_id=owner, tenant_id=tenant
    )
