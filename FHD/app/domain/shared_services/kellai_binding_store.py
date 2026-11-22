"""Explicit, revocable loopback grants for the 客来来 product module."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import keyring
from filelock import FileLock
from keyring.errors import KeyringError, PasswordDeleteError

from app.desktop_runtime.desktop_runtime_paths import ensure_desktop_dirs

PAIRING_TTL_MINUTES = 15
PROTOCOL_VERSION = 2
ALLOWED_SCOPES: tuple[dict[str, str], ...] = (
    {
        "id": "channels.read",
        "label": "读取账号连接",
        "description": "读取账号连接状态和收发能力，不读取凭据。",
    },
    {
        "id": "messages.read",
        "label": "读取联系人与消息",
        "description": "按账号连接读取外部联系人映射和消息。",
    },
    {
        "id": "messages.send",
        "label": "经确认发送消息",
        "description": "允许当前 XCMAX 账号发送经确认的消息并查询原回执。",
    },
)
DEFAULT_SCOPES = ("channels.read", "messages.read")
_SCOPE_IDS = frozenset(scope["id"] for scope in ALLOWED_SCOPES)
_LOCK = threading.Lock()
_KEYRING_SERVICE = "com.xcagi.kellai"
_LOGGER = logging.getLogger(__name__)
_NATIVE_KEYRINGS = {
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
}


def _credential_backend():
    backend = keyring.get_keyring()
    candidates = getattr(backend, "backends", [backend])
    for candidate in candidates:
        if type(candidate).__module__ in _NATIVE_KEYRINGS and candidate.priority > 0:
            return candidate
    raise ValueError("系统安全凭据库不可用，无法保存客来来授权；请启用系统钥匙串")


def _save_secret(value: str) -> str:
    reference = secrets.token_urlsafe(24)
    try:
        _credential_backend().set_password(_KEYRING_SERVICE, reference, value)
    except (KeyringError, OSError, RuntimeError) as exc:
        raise ValueError("系统凭据库写入失败，客来来授权未保存") from exc
    return reference


def _secret(reference: str) -> str:
    try:
        value = _credential_backend().get_password(_KEYRING_SERVICE, reference)
    except (KeyringError, OSError, RuntimeError) as exc:
        raise ValueError("无法读取系统凭据库，请重新授权客来来") from exc
    if not value:
        raise ValueError("客来来授权凭据已失效，请重新授权")
    return value


def _delete_secret(reference: str | None) -> None:
    if reference:
        try:
            _credential_backend().delete_password(_KEYRING_SERVICE, reference)
        except PasswordDeleteError:
            pass
        except (KeyringError, OSError, RuntimeError, ValueError):
            # Revocation already removed the durable reference. Do not turn a
            # successful revocation into a false failure if the OS vault locks.
            _LOGGER.warning("Revoked Kellai credential reference; OS vault cleanup unavailable")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _store_path() -> Path:
    root = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))["root"]
    path = root / "config" / "kellai-binding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _state_lock():
    # Single-use handoffs must stay single-use even with multiple API workers.
    with _LOCK, FileLock(str(_store_path()) + ".lock", timeout=5):
        yield


def _read() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": PROTOCOL_VERSION, "pending": None, "connection": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": PROTOCOL_VERSION, "pending": None, "connection": None}
    if not isinstance(raw, dict):
        return {"version": PROTOCOL_VERSION, "pending": None, "connection": None}
    if raw.get("version") != PROTOCOL_VERSION:
        # Old grants cannot silently acquire the consolidated messages.read scope.
        # Retire plaintext credentials; the delivery ledger remains in the tool.
        raw = {
            "version": PROTOCOL_VERSION,
            "pending": None,
            "connection": None,
            "requires_reauthorization": bool(raw.get("connection")),
        }
        _write(raw)
    return raw


def _write(value: dict[str, Any]) -> None:
    path = _store_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _pending_is_valid(pending: Any) -> bool:
    if not isinstance(pending, dict):
        return False
    try:
        return datetime.fromisoformat(str(pending.get("expires_at") or "")) > _now()
    except ValueError:
        return False


def _public_connection(connection: Any) -> dict[str, Any] | None:
    if not isinstance(connection, dict):
        return None
    return {
        "connection_id": str(connection.get("connection_id") or ""),
        "source": "kellai",
        "authorized_scopes": list(connection.get("authorized_scopes") or []),
        "connected_at": str(connection.get("connected_at") or ""),
        "authorized_by": connection.get("authorized_by")
        if isinstance(connection.get("authorized_by"), dict)
        else {},
        "source_name": "客来来账号工具",
        "protocol_version": PROTOCOL_VERSION,
    }


def status() -> dict[str, Any]:
    with _state_lock():
        state = _read()
        pending = state.get("pending")
        if pending and not _pending_is_valid(pending):
            state["pending"] = None
            _write(state)
            _delete_secret(pending.get("authorization_secret_ref"))
            pending = None
        connection = _public_connection(state.get("connection"))
        revoked = bool((state.get("connection") or {}).get("revoked"))
        return {
            "state": "connected"
            if connection and not revoked
            else "pending"
            if pending
            else "revoked"
            if connection
            else "not_connected",
            "connection": connection,
            "pending": {
                "request_id": str(pending.get("request_id") or ""),
                "expires_at": str(pending.get("expires_at") or ""),
            }
            if isinstance(pending, dict)
            else None,
            "available_scopes": list(ALLOWED_SCOPES),
            "requires_reauthorization": bool(state.get("requires_reauthorization")),
        }


def start_pairing(
    *,
    requested_scopes: list[str] | None = None,
    actor: int | None = None,
    tenant_id: str = "",
) -> dict[str, Any]:
    selected = list(
        dict.fromkeys(requested_scopes if requested_scopes is not None else DEFAULT_SCOPES)
    )
    if not selected or any(scope not in _SCOPE_IDS for scope in selected):
        raise ValueError("授权范围无效")
    if actor is None:
        raise ValueError("请先登录 XCMAX 企业账号，再申请客来来权限")
    with _state_lock():
        state = _read()
        expires_at = _now() + timedelta(minutes=PAIRING_TTL_MINUTES)
        pending = {
            "request_id": secrets.token_urlsafe(18),
            "authorization_secret_ref": _save_secret(secrets.token_urlsafe(32)),
            "protocol_version": PROTOCOL_VERSION,
            "handoff_claimed": False,
            "requested_scopes": selected,
            "xcmax_user_id": actor,
            "xcmax_tenant_id": tenant_id,
            "created_at": _iso(),
            "expires_at": _iso(expires_at),
        }
        previous = state.get("pending")
        state["pending"] = pending
        try:
            _write(state)
        except OSError:
            _delete_secret(pending["authorization_secret_ref"])
            raise
        if isinstance(previous, dict):
            _delete_secret(previous.get("authorization_secret_ref"))
        return {
            "request_id": pending["request_id"],
            "expires_at": pending["expires_at"],
            "requested_scopes": [scope for scope in ALLOWED_SCOPES if scope["id"] in selected],
        }


def claim_handoff() -> dict[str, Any] | None:
    with _state_lock():
        state = _read()
        pending = state.get("pending")
        if not _pending_is_valid(pending):
            if pending:
                state["pending"] = None
                _write(state)
                _delete_secret(pending.get("authorization_secret_ref"))
            return None
        assert isinstance(pending, dict)
        if pending.get("handoff_claimed"):
            raise ValueError("本次连接已交接，请回到 XCMAX 重新发起授权")
        secret = _secret(pending["authorization_secret_ref"])
        pending["handoff_claimed"] = True
        _write(state)
        return {
            "request_id": str(pending["request_id"]),
            "authorization_secret": secret,
            "protocol_version": PROTOCOL_VERSION,
            "xcmax_user_id": pending["xcmax_user_id"],
            "xcmax_tenant_id": pending["xcmax_tenant_id"],
            "requested_scopes": [
                scope for scope in ALLOWED_SCOPES if scope["id"] in pending["requested_scopes"]
            ],
            "created_at": str(pending["created_at"]),
            "expires_at": str(pending["expires_at"]),
        }


def approve_pairing(
    *,
    request_id: str,
    authorization_secret: str,
    accepted_scopes: list[str],
    access_token: str,
    authorized_by: dict[str, Any],
) -> dict[str, Any]:
    with _state_lock():
        state = _read()
        pending = state.get("pending")
        if not _pending_is_valid(pending) or not isinstance(pending, dict):
            raise ValueError("绑定请求已过期，请回到 XCMAX 重新发起")
        if not secrets.compare_digest(str(pending.get("request_id") or ""), request_id):
            raise ValueError("绑定请求不匹配")
        if not secrets.compare_digest(
            _secret(str(pending.get("authorization_secret_ref") or "")), authorization_secret
        ):
            raise ValueError("授权校验失败")
        if not pending.get("handoff_claimed"):
            raise ValueError("尚未完成本机授权交接")
        selected = list(dict.fromkeys(accepted_scopes))
        if (
            not selected
            or any(scope not in _SCOPE_IDS for scope in selected)
            or not set(selected).issubset(pending.get("requested_scopes") or [])
        ):
            raise ValueError("请选择本次申请范围内的至少一项权限")
        if len(access_token) < 32:
            raise ValueError("本地连接令牌无效")

        connection = {
            "connection_id": request_id,
            "access_token_ref": _save_secret(access_token),
            "protocol_version": PROTOCOL_VERSION,
            "authorized_scopes": selected,
            "xcmax_user_id": pending.get("xcmax_user_id"),
            "xcmax_tenant_id": str(pending.get("xcmax_tenant_id") or ""),
            "connected_at": _iso(),
            "authorized_by": {
                "id": str(authorized_by.get("id") or ""),
                "display_name": str(authorized_by.get("display_name") or ""),
            },
        }
        previous = state.get("connection")
        state["pending"] = None
        state["connection"] = connection
        state["requires_reauthorization"] = False
        try:
            _write(state)
        except OSError:
            _delete_secret(connection["access_token_ref"])
            raise
        _delete_secret(pending.get("authorization_secret_ref"))
        if isinstance(previous, dict):
            _delete_secret(previous.get("access_token_ref"))
        return _public_connection(connection) or {}


def cancel_pairing(*, request_id: str, authorization_secret: str) -> None:
    with _state_lock():
        state = _read()
        pending = state.get("pending")
        if not isinstance(pending, dict):
            return
        if not secrets.compare_digest(str(pending.get("request_id") or ""), request_id):
            raise ValueError("绑定请求不匹配")
        if not secrets.compare_digest(
            _secret(str(pending.get("authorization_secret_ref") or "")), authorization_secret
        ):
            raise ValueError("授权校验失败")
        state["pending"] = None
        _write(state)
        _delete_secret(pending.get("authorization_secret_ref"))


def connection_metadata() -> dict[str, Any] | None:
    """Read owner and grant metadata without unlocking the OS credential vault."""
    with _state_lock():
        connection = _read().get("connection")
        return dict(connection) if isinstance(connection, dict) else None


def connection_credentials() -> dict[str, Any] | None:
    with _state_lock():
        state = _read()
        connection = state.get("connection")
        if not isinstance(connection, dict) or connection.get("revoked"):
            return None
        return {**connection, "access_token": _secret(connection["access_token_ref"])}


def mark_revoked(connection_id: str) -> None:
    """Retire only the observed grant; preserve its owner and receipt identity."""
    with _state_lock():
        state = _read()
        connection = state.get("connection")
        if not isinstance(connection, dict) or connection.get("connection_id") != connection_id:
            return
        reference = connection.pop("access_token_ref", None)
        connection["revoked"] = True
        state["requires_reauthorization"] = True
        _write(state)
        _delete_secret(reference)


def binding_owners() -> set[int]:
    """Every current grant belongs to the authenticated host actor."""
    with _state_lock():
        state = _read()
        return {
            int(item["xcmax_user_id"])
            for item in (state.get("connection"), state.get("pending"))
            if isinstance(item, dict)
            and item.get("xcmax_user_id") is not None
            and (item is state.get("connection") or _pending_is_valid(item))
        }


def disconnect() -> None:
    with _state_lock():
        state = _read()
        pending, connection = state.get("pending"), state.get("connection")
        state["pending"] = None
        state["connection"] = None
        _write(state)
        if isinstance(pending, dict):
            _delete_secret(pending.get("authorization_secret_ref"))
        if isinstance(connection, dict):
            _delete_secret(connection.get("access_token_ref"))
