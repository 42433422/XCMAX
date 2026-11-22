"""Application boundary for the local Kellai customer-inbox integration."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.shared_services import kellai_binding_store
from app.infrastructure.kellai_client import KellaiRequestError

_REVOKED_CODES = {"xcmax_grant_revoked", "xcmax_grant_invalid", "xcmax_reauthorization_required"}


class KellaiAuthorizationError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def connection_identity_sha256(connection: dict[str, Any] | None = None) -> str:
    """Bind original approvals and observations to one server-owned pairing."""
    current = connection if connection is not None else connection_metadata()
    if not current or not current.get("connection_id"):
        return ""
    identity = {
        key: current.get(key) for key in ("connection_id", "xcmax_user_id", "xcmax_tenant_id")
    }
    identity["authorized_by"] = str((current.get("authorized_by") or {}).get("id") or "")
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def scoped_connection(*, actor: int | None, tenant_id: str, scope: str) -> dict[str, Any]:
    if actor is None:
        raise KellaiAuthorizationError("请先登录 XCMAX 企业账号", 401)
    try:
        connection = kellai_binding_store.connection_credentials()
    except ValueError as exc:
        raise KellaiAuthorizationError(str(exc), 503) from exc
    if not connection:
        raise KellaiAuthorizationError("客来来尚未连接", 409)
    if (
        connection.get("xcmax_user_id") != actor
        or str(connection.get("xcmax_tenant_id") or "") != tenant_id
    ):
        raise KellaiAuthorizationError("请由当前账号重新申请客来来模块授权")
    if scope not in connection.get("authorized_scopes", []):
        raise KellaiAuthorizationError(f"尚未授权 {scope}，请在连接与账号中申请")
    return connection


def binding_status() -> dict[str, Any]:
    current = kellai_binding_store.status()
    if current["state"] != "connected":
        return current
    try:
        connection = kellai_binding_store.connection_credentials()
        if not connection:
            return kellai_binding_store.status()
        grant = request_kellai("grant-status", connection).get("data")
        if (
            not isinstance(grant, dict)
            or grant.get("connection_id") != connection["connection_id"]
            or grant.get("protocol_version") != 2
        ):
            raise KellaiRequestError("客来来返回的授权身份不符", 502)
        return kellai_binding_store.status()
    except (KellaiRequestError, ValueError) as exc:
        latest = kellai_binding_store.status()
        if latest["state"] != "connected" or latest.get("connection") != current.get("connection"):
            return latest
        return {**latest, "state": "offline", "message": str(exc)}


def request_kellai(
    path: str, connection: dict[str, Any], body: dict | None = None, *, opener=None
) -> dict:
    from app.infrastructure.kellai_client import request_kellai as transport

    try:
        return transport(
            path, connection, body, **({"opener": opener} if opener is not None else {})
        )
    except KellaiRequestError as exc:
        if exc.code in _REVOKED_CODES:
            kellai_binding_store.mark_revoked(str(connection.get("connection_id") or ""))
        raise


def start_pairing(**kwargs: Any) -> dict[str, Any]:
    return kellai_binding_store.start_pairing(**kwargs)


def binding_owners() -> set[int]:
    return kellai_binding_store.binding_owners()


def claim_handoff() -> dict[str, Any] | None:
    return kellai_binding_store.claim_handoff()


def approve_pairing(**kwargs: Any) -> dict[str, Any]:
    return kellai_binding_store.approve_pairing(**kwargs)


def cancel_pairing(**kwargs: Any) -> None:
    kellai_binding_store.cancel_pairing(**kwargs)


def connection_metadata() -> dict[str, Any] | None:
    return kellai_binding_store.connection_metadata()


def disconnect() -> None:
    kellai_binding_store.disconnect()
