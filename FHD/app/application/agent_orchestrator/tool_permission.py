"""Server-side tool authorization and tenant-scoped idempotent replay.

Client fields never grant a tool. A bound session is checked against the
live role permissions, and an employee allowlist is checked again at execution.
"""

from __future__ import annotations

import threading
from typing import Any

from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, get_tool_action_spec
from app.utils.operational_errors import RECOVERABLE_ERRORS

_IDEMPOTENCY: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_LOCK = threading.Lock()
_FINGERPRINT_SKIP = frozenset(
    {
        "_runtime_context",
        "tenant_id",
        "user_id",
        "actor_id",
        "mod_id",
        "active_mod_id",
        "_actor_authorization",
        "_mod_authorization",
        "local_user_id",
        "authenticated_local_user_id",
        "idempotency_key",
    }
)


def _denial(
    code: str,
    message: str,
    *,
    context: dict[str, Any],
    tool_id: str,
    action: str,
    reason: str,
) -> dict[str, Any]:
    user_id = str(context.get("user_id") or "")
    task_id = str(context.get("task_id") or context.get("run_id") or "")
    return {
        "success": False,
        "error_code": code,
        "outcome": "denied",
        "retryable": False,
        "message": message,
        "tool_id": tool_id,
        "action": action,
        "reason": reason,
        "user_id": user_id,
        "task_id": task_id,
        "audit": {
            "reason": reason,
            "user_id": user_id,
            "tool_id": tool_id,
            "task_id": task_id,
        },
    }


def _allowlist_denial(
    spec: ToolActionSpecV2, context: dict[str, Any]
) -> dict[str, Any] | None:
    raw = context.get("employee_tool_allowlist")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return _denial(
            "tool_permission_denied",
            "员工工具授权无效，已拒绝执行",
            context=context,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="employee_allowlist_invalid",
        )
    allowed = {str(item) for item in raw}
    if spec.tool_id in allowed or f"{spec.tool_id}.{spec.action}" in allowed:
        return None
    return _denial(
        "tool_permission_denied",
        "AI 员工未被授权调用该工具",
        context=context,
        tool_id=spec.tool_id,
        action=spec.action,
        reason="employee_tool_not_granted",
    )


def actor_tool_denial(
    tool_id: str, action: str, context: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Deny when a sealed actor or employee allowlist does not grant this tool."""
    ctx = dict(context or {})
    spec = get_tool_action_spec(tool_id, action)
    if not isinstance(ctx.get("_actor_authorization"), dict) and "employee_tool_allowlist" not in ctx:
        return None
    if spec is None:
        return _denial(
            "tool_contract_unavailable",
            "工具契约不可用，已拒绝执行",
            context=ctx,
            tool_id=str(tool_id or ""),
            action=str(action or ""),
            reason="tool_contract_unavailable",
        )
    allow_denial = _allowlist_denial(spec, ctx)
    if allow_denial is not None:
        return allow_denial
    if not isinstance(ctx.get("_actor_authorization"), dict):
        return None
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

    try:
        actor = _bound_actor(ctx)
        if not spec.permission or not get_auth_service().has_permission(actor, spec.permission):
            return _denial(
                "tool_permission_denied",
                "权限不足，已拒绝执行工具",
                context=ctx,
                tool_id=spec.tool_id,
                action=spec.action,
                reason="permission_denied",
            )
    except AgentModAuthorizationError:
        return _denial(
            "tool_identity_required",
            "工具任务需要有效的身份授权，请重新登录或授权",
            context=ctx,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="actor_binding_rejected",
        )
    except RECOVERABLE_ERRORS:
        return _denial(
            "tool_permission_denied",
            "权限校验失败，已拒绝执行",
            context=ctx,
            tool_id=spec.tool_id,
            action=spec.action,
            reason="permission_check_failed",
        )
    return None


def _fingerprint(params: dict[str, Any]) -> str:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    visible = {key: value for key, value in params.items() if key not in _FINGERPRINT_SKIP}
    return canonical_hash(visible)


def idempotency_scope_key(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any]
) -> str:
    client_key = str(params.get("idempotency_key") or "").strip()
    server_key = str(context.get("idempotency_key") or "").strip()
    raw = client_key or server_key
    tenant = str(context.get("tenant_id") or "")
    return f"{tenant}:{tool_id}:{action}:{raw}"


def begin_idempotent_replay(
    context: dict[str, Any], tool_id: str, action: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """Return a cached success, or claim the key. Failures stay retryable."""
    key = idempotency_scope_key(context, tool_id, action, params)
    if key.endswith(":"):
        return "", None
    try:
        fingerprint = _fingerprint(params)
    except RECOVERABLE_ERRORS:
        return key, _denial(
            "idempotency_conflict",
            "幂等参数无法校验，已拒绝执行",
            context=context,
            tool_id=tool_id,
            action=action,
            reason="idempotency_fingerprint_rejected",
        )
    with _IDEMPOTENCY_LOCK:
        current = _IDEMPOTENCY.get(key)
        if current and current.get("fingerprint") != fingerprint:
            return key, _denial(
                "idempotency_conflict",
                "相同幂等键不能改用新的执行参数",
                context=context,
                tool_id=tool_id,
                action=action,
                reason="idempotency_conflict",
            )
        cached = current.get("output") if current else None
        if isinstance(cached, dict) and cached.get("success") is True:
            return key, dict(cached)
        if current and current.get("inflight"):
            return key, _denial(
                "idempotency_in_progress",
                "相同幂等键的调用正在执行",
                context=context,
                tool_id=tool_id,
                action=action,
                reason="idempotency_in_progress",
            )
        _IDEMPOTENCY[key] = {"fingerprint": fingerprint, "inflight": True, "output": None}
    return key, None


def finish_idempotent_replay(key: str, output: dict[str, Any]) -> None:
    if not key:
        return
    with _IDEMPOTENCY_LOCK:
        current = _IDEMPOTENCY.get(key)
        if current is None:
            return
        if output.get("success") is True:
            current["output"] = dict(output)
            current["inflight"] = False
            return
        _IDEMPOTENCY.pop(key, None)


def clear_idempotent_replay_for_tests() -> None:
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY.clear()
