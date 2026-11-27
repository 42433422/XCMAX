"""Application boundary for the local Kellai customer-inbox integration."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.shared_services import kellai_binding_store, kellai_customer_copilot

KellaiCopilotError = kellai_customer_copilot.KellaiCopilotError


class KellaiAuthorizationError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def connection_identity_sha256(connection: dict[str, Any] | None = None) -> str:
    """Bind original approvals and observations to one server-owned pairing."""
    current = connection if connection is not None else connection_credentials()
    if not current or not current.get("connection_id"):
        return ""
    identity = {
        key: current.get(key) for key in ("connection_id", "xcmax_user_id", "xcmax_tenant_id")
    }
    identity["authorized_by"] = str((current.get("authorized_by") or {}).get("id") or "")
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def scoped_connection(*, context: dict[str, Any], scope: str) -> dict[str, Any]:
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    actor = _bound_actor(context)
    # _bound_actor compares this sealed session metadata against its live row.
    account = context["_actor_authorization"]["market_authorization"]
    if actor.account_tier == "personal" or account.get("account_kind") == "personal":
        raise KellaiAuthorizationError("个人版不开放客来来企业通信能力")
    if account.get("account_kind") == "admin" or account.get("is_admin"):
        raise KellaiAuthorizationError("平台管理账号无权读取客户原始会话")
    connection = kellai_binding_store.connection_credentials()
    if not connection:
        raise KellaiAuthorizationError("客来来尚未连接", 409)
    if connection.get("xcmax_user_id") != int(actor.id) or str(
        connection.get("xcmax_tenant_id") or ""
    ) != str(context.get("tenant_id") or ""):
        raise KellaiAuthorizationError("请由当前账号重新申请客来来模块授权")
    if scope not in connection.get("authorized_scopes", []):
        raise KellaiAuthorizationError(f"尚未授权 {scope}，请在连接与账号中申请")
    return connection


def binding_status() -> dict[str, Any]:
    return kellai_binding_store.status()


def start_pairing(**kwargs: Any) -> dict[str, Any]:
    return kellai_binding_store.start_pairing(**kwargs)


def binding_owners() -> set[int]:
    return kellai_binding_store.binding_owners()


def pending_for_kellai() -> dict[str, Any] | None:
    return kellai_binding_store.pending_for_kellai()


def approve_pairing(**kwargs: Any) -> dict[str, Any]:
    return kellai_binding_store.approve_pairing(**kwargs)


def cancel_pairing(**kwargs: Any) -> None:
    kellai_binding_store.cancel_pairing(**kwargs)


def connection_credentials() -> dict[str, Any] | None:
    return kellai_binding_store.connection_credentials()


def disconnect() -> None:
    kellai_binding_store.disconnect()


def purge_all(*, actor: int | str | None = None) -> None:
    kellai_customer_copilot.purge_all(actor=actor)


def latest_draft(customer_id: int) -> dict[str, Any] | None:
    return kellai_customer_copilot.latest_draft(customer_id)


def list_follow_up_tasks(customer_id: int) -> list[dict[str, Any]]:
    return kellai_customer_copilot.list_follow_up_tasks(customer_id)


def follow_up_metrics(customer_id: int) -> dict[str, Any]:
    return kellai_customer_copilot.follow_up_metrics(customer_id)


async def generate_draft(**kwargs: Any) -> dict[str, Any]:
    return await kellai_customer_copilot.generate_draft(**kwargs)


def decide_draft(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.decide_draft(**kwargs)


def create_follow_up_task(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.create_follow_up_task(**kwargs)


def decide_follow_up_task(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.decide_follow_up_task(**kwargs)
