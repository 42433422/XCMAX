"""Local pairing state for the 客来来 customer-IM data source.

The two desktop apps deliberately pair over loopback.  The pairing request is
short-lived, carries a one-time secret, and the resulting token is only used
for XCMAX to read the customer data that the user explicitly approved.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.desktop_runtime.paths import ensure_desktop_dirs

PAIRING_TTL_MINUTES = 15
ALLOWED_SCOPES: tuple[dict[str, str], ...] = (
    {
        "id": "customer_profiles.read",
        "label": "读取客户档案",
        "description": "让 XCMAX AI 识别客户名称、来源、阶段和跟进摘要。",
    },
    {
        "id": "customer_conversations.read",
        "label": "读取客户会话",
        "description": "让 XCMAX AI 基于客来来中的客户消息生成建议。",
    },
)
_SCOPE_IDS = frozenset(scope["id"] for scope in ALLOWED_SCOPES)
_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _store_path() -> Path:
    root = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))["root"]
    path = root / "config" / "kellai-binding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": 1, "pending": None, "connection": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "pending": None, "connection": None}
    return raw if isinstance(raw, dict) else {"version": 1, "pending": None, "connection": None}


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
        "authorized_by": connection.get("authorized_by") if isinstance(connection.get("authorized_by"), dict) else {},
        "source_name": "客来来客户 IM",
    }


def status() -> dict[str, Any]:
    with _LOCK:
        state = _read()
        pending = state.get("pending")
        if pending and not _pending_is_valid(pending):
            state["pending"] = None
            _write(state)
            pending = None
        connection = _public_connection(state.get("connection"))
        return {
            "state": "connected" if connection else "pending" if pending else "not_connected",
            "connection": connection,
            "pending": {
                "request_id": str(pending.get("request_id") or ""),
                "expires_at": str(pending.get("expires_at") or ""),
            }
            if isinstance(pending, dict)
            else None,
            "available_scopes": list(ALLOWED_SCOPES),
        }


def start_pairing() -> dict[str, Any]:
    with _LOCK:
        state = _read()
        expires_at = _now() + timedelta(minutes=PAIRING_TTL_MINUTES)
        pending = {
            "request_id": secrets.token_urlsafe(18),
            "authorization_secret": secrets.token_urlsafe(32),
            "requested_scopes": [scope["id"] for scope in ALLOWED_SCOPES],
            "created_at": _iso(),
            "expires_at": _iso(expires_at),
        }
        state["pending"] = pending
        _write(state)
        return {
            "request_id": pending["request_id"],
            "expires_at": pending["expires_at"],
            "requested_scopes": list(ALLOWED_SCOPES),
        }


def pending_for_kellai() -> dict[str, Any] | None:
    with _LOCK:
        state = _read()
        pending = state.get("pending")
        if not _pending_is_valid(pending):
            if pending:
                state["pending"] = None
                _write(state)
            return None
        assert isinstance(pending, dict)
        return {
            "request_id": str(pending["request_id"]),
            "authorization_secret": str(pending["authorization_secret"]),
            "requested_scopes": list(ALLOWED_SCOPES),
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
    with _LOCK:
        state = _read()
        pending = state.get("pending")
        if not _pending_is_valid(pending) or not isinstance(pending, dict):
            raise ValueError("绑定请求已过期，请回到 XCMAX 重新发起")
        if not secrets.compare_digest(str(pending.get("request_id") or ""), request_id):
            raise ValueError("绑定请求不匹配")
        if not secrets.compare_digest(str(pending.get("authorization_secret") or ""), authorization_secret):
            raise ValueError("授权校验失败")
        selected = [scope for scope in accepted_scopes if scope in _SCOPE_IDS]
        if set(selected) != set(pending.get("requested_scopes") or []):
            raise ValueError("必须确认全部只读权限后才能连接")
        if len(access_token) < 32:
            raise ValueError("本地连接令牌无效")

        connection = {
            "connection_id": request_id,
            "access_token": access_token,
            "authorized_scopes": selected,
            "connected_at": _iso(),
            "authorized_by": {
                "id": str(authorized_by.get("id") or ""),
                "display_name": str(authorized_by.get("display_name") or ""),
            },
        }
        state["pending"] = None
        state["connection"] = connection
        _write(state)
        return _public_connection(connection) or {}


def cancel_pairing(*, request_id: str, authorization_secret: str) -> None:
    with _LOCK:
        state = _read()
        pending = state.get("pending")
        if not isinstance(pending, dict):
            return
        if not secrets.compare_digest(str(pending.get("request_id") or ""), request_id):
            raise ValueError("绑定请求不匹配")
        if not secrets.compare_digest(str(pending.get("authorization_secret") or ""), authorization_secret):
            raise ValueError("授权校验失败")
        state["pending"] = None
        _write(state)


def connection_credentials() -> dict[str, Any] | None:
    with _LOCK:
        state = _read()
        connection = state.get("connection")
        return dict(connection) if isinstance(connection, dict) else None


def disconnect() -> None:
    with _LOCK:
        state = _read()
        state["pending"] = None
        state["connection"] = None
        _write(state)
