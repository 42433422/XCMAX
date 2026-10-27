"""Revalidate durable Agent Mod scope against a host session, never a token cache."""

import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from typing import Any

from app.request_active_mod_ctx import (
    normalize_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


class AgentModAuthorizationError(ValueError):
    pass


def _actor_proof(binding: dict[str, Any]) -> str:
    secret = os.environ.get("SECRET_KEY", "").strip() or os.environ.setdefault(
        "XCAGI_AGENT_ACTOR_BINDING_KEY", secrets.token_urlsafe(48)
    )
    return hmac.new(
        secret.encode(),
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def actor_binding_is_sealed(binding: dict[str, Any]) -> bool:
    proof = binding.get("proof")
    return isinstance(proof, str) and hmac.compare_digest(
        proof, _actor_proof({key: value for key, value in binding.items() if key != "proof"})
    )


def _actor_binding(
    row: Any, execution_tenant_id: str | None = None, mod_id: str = ""
) -> dict[str, Any]:
    user = row.user
    tenant = str(user.tenant_id or "")
    binding = {
        "session_row_id": row.id,
        "user_id": str(user.id),
        "tenant_id": tenant,
        "execution_tenant_id": tenant if execution_tenant_id is None else execution_tenant_id,
        "role": str(user.role or ""),
        "tier": str(user.tier or "").strip().lower(),
        "mod_id": mod_id,
    }
    binding["proof"] = _actor_proof(binding)
    return binding


def _check_actor_row(row: Any, user_id: str) -> None:
    from app.utils.time import utc_now_naive

    if row is None or str(row.user_id) != user_id or row.expires_at <= utc_now_naive():
        raise AgentModAuthorizationError("任务绑定的登录会话已失效")
    if row.user is None or not row.user.is_active:
        raise AgentModAuthorizationError("任务所属账号已停用")


def bind_agent_actor_scope(
    *, session_id: str, user_id: str, execution_tenant_id: str | None = None, mod_id: str = ""
) -> dict[str, Any]:
    """Bind a verified session credential; a user id alone never grants execution."""
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    if not session_id:
        raise AgentModAuthorizationError("工具任务需要有效的登录会话")
    with HostSessionLocal() as db:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        _check_actor_row(row, user_id)
        if normalize_active_mod_id(mod_id) != mod_id:
            raise AgentModAuthorizationError("任务 Mod 标识无效")
        if mod_id:
            _check_row(row, user_id=user_id, mod_id=mod_id)
        return _actor_binding(row, execution_tenant_id, mod_id)


def _bound_actor(context: dict[str, Any]) -> Any:
    from app.application.tenant_rbac_policy import role_belongs_to_user
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    binding = context.get("_actor_authorization")
    if not isinstance(binding, dict) or type(binding.get("session_row_id")) is not int:
        raise AgentModAuthorizationError("工具缺少可信登录会话绑定")
    with HostSessionLocal() as db:
        row = db.get(UserSession, binding["session_row_id"])
        _check_actor_row(row, str(binding.get("user_id") or ""))
        effective_tenant = binding.get("execution_tenant_id")
        if not isinstance(effective_tenant, str):
            raise AgentModAuthorizationError("任务租户授权不完整")
        actor_mod = binding.get("mod_id")
        if not isinstance(actor_mod, str) or normalize_active_mod_id(actor_mod) != actor_mod:
            raise AgentModAuthorizationError("任务 Mod 授权不完整")
        actual = _actor_binding(row, effective_tenant, actor_mod)
        if (
            actual.keys() != binding.keys()
            or not hmac.compare_digest(str(actual["proof"]), str(binding.get("proof") or ""))
            or {k: v for k, v in actual.items() if k != "proof"}
            != {k: v for k, v in binding.items() if k != "proof"}
            or str(context.get("user_id") or "") != actual["user_id"]
            or str(context.get("actor_id") or actual["user_id"]) != actual["user_id"]
            or str(context.get("tenant_id") or "") != effective_tenant
            or not role_belongs_to_user(row.user.role, row.user.tenant_id)
        ):
            raise AgentModAuthorizationError("任务绑定的账号范围已变化，请重新授权")
        mod = context.get("_mod_authorization")
        selected_mod = str(context.get("mod_id") or context.get("active_mod_id") or "")
        if mod is not None:
            if (
                not isinstance(mod, dict)
                or not actor_mod
                or mod.get("mod_id") != actor_mod
                or mod.get("session_row_id") != row.id
                or mod.get("user_id") != actual["user_id"]
                or mod.get("account_tenant_id") != actual["tenant_id"]
                or mod.get("account_role") != actual["role"]
                or not isinstance(mod.get("mod_id"), str)
                or (selected_mod and selected_mod != mod["mod_id"])
            ):
                raise AgentModAuthorizationError("工具 Mod 授权与任务身份不匹配")
            _check_row(row, user_id=actual["user_id"], mod_id=mod["mod_id"])
        elif selected_mod or actor_mod:
            raise AgentModAuthorizationError("工具缺少当前 Mod 授权")
        db.expunge(row.user)
        return row.user


def validate_actor_context(runtime_context: dict[str, Any]) -> dict[str, Any] | None:
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        _bound_actor(runtime_context)
    except (AgentModAuthorizationError, *RECOVERABLE_ERRORS):
        return {
            "success": False,
            "error_code": "tool_identity_required",
            "message": "工具任务需要有效的身份授权，请重新登录或授权",
        }
    return None


def _check_row(row: Any, *, user_id: str, mod_id: str) -> None:
    from app.mod_sdk.industry_seed import open_industry_seed_mod_ids
    from app.mod_sdk.product_skus import bundled_mod_ids_for_sku, resolve_product_sku
    from app.utils.time import utc_now_naive

    if row is None or str(row.user_id) != user_id or row.expires_at <= utc_now_naive():
        raise AgentModAuthorizationError("任务绑定的登录会话已失效")
    if row.user is None or not row.user.is_active:
        raise AgentModAuthorizationError("任务所属账号已停用")
    ids = json.loads(row.entitled_mod_ids_json or "[]")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        raise AgentModAuthorizationError("任务 Mod 权益记录无效")
    public_ids = set(bundled_mod_ids_for_sku(resolve_product_sku()))
    public_ids.update(open_industry_seed_mod_ids())
    if mod_id not in set(ids) | public_ids:
        raise AgentModAuthorizationError("任务所属账号未开通该 Mod")


def bind_agent_mod_scope(*, session_id: str, user_id: str, mod_id: str) -> dict[str, Any]:
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    normalized = normalize_active_mod_id(mod_id)
    if not normalized or normalized != mod_id or not session_id:
        raise AgentModAuthorizationError("Mod 任务需要有效的登录会话")
    with HostSessionLocal() as db:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        _check_row(row, user_id=user_id, mod_id=normalized)
        return {
            "session_row_id": row.id,
            "user_id": user_id,
            "mod_id": normalized,
            "account_tenant_id": str(row.user.tenant_id or ""),
            "account_role": str(row.user.role or ""),
        }


@contextmanager
def agent_mod_execution_scope(binding: dict[str, Any] | None):
    if not binding:
        yield
        return
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession

    if not isinstance(binding, dict):
        raise AgentModAuthorizationError("任务 Mod 授权上下文无效")
    row_id = binding.get("session_row_id")
    mod_id = binding.get("mod_id")
    user_id = binding.get("user_id")
    if (
        type(row_id) is not int
        or row_id <= 0
        or not isinstance(user_id, str)
        or not isinstance(mod_id, str)
        or not mod_id
        or normalize_active_mod_id(mod_id) != mod_id
    ):
        raise AgentModAuthorizationError("任务 Mod 授权上下文无效")
    with HostSessionLocal() as db:
        row = db.get(UserSession, row_id)
        _check_row(row, user_id=user_id, mod_id=mod_id)
        if binding.get("account_tenant_id") != str(row.user.tenant_id or "") or binding.get(
            "account_role"
        ) != str(row.user.role or ""):
            raise AgentModAuthorizationError("任务绑定的账号范围已变化，请重新授权")
    token = set_request_active_mod_id(mod_id)
    try:
        yield
    finally:
        reset_request_active_mod_id(token)


def agent_dataset_access_context(runtime_context: dict[str, Any]):
    """Resolve dataset ACLs from the bound host session, never model arguments."""
    from app.application.dataset_rag.models import DatasetAccessContext
    from app.domain.shared_services.auth_service import get_auth_service

    user = _bound_actor(runtime_context)
    return DatasetAccessContext(
        actor_id=str(user.id),
        tenant_id=str(runtime_context.get("tenant_id") or ""),
        permissions=frozenset(get_auth_service().get_user_permissions(user)),
        is_admin=user.role == "admin" and user.tier == "admin" and user.tenant_id is None,
    )
