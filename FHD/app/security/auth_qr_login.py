"""PC 扫码登录 nonce 存储（对标钉钉 PC 端手机确认）。"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

_lock = threading.Lock()
_qr_sessions: dict[str, dict[str, Any]] = {}


def issue_auth_qr(*, client_hint: str = "", ttl_seconds: int = 120) -> dict[str, Any]:
    qr_id = secrets.token_urlsafe(18)
    poll_secret = secrets.token_urlsafe(12)
    exp = int(time.time()) + ttl_seconds
    payload = {
        "qr_id": qr_id,
        "poll_secret": poll_secret,
        "status": "pending",
        "exp": exp,
        "client_hint": (client_hint or "")[:256],
        "session_id": None,
        "login_payload": None,
    }
    with _lock:
        _qr_sessions[qr_id] = payload
    return {
        "qr_id": qr_id,
        "poll_secret": poll_secret,
        "expires_at": exp,
        "client_hint": payload["client_hint"],
    }


def get_auth_qr(qr_id: str) -> dict[str, Any] | None:
    with _lock:
        rec = _qr_sessions.get((qr_id or "").strip())
    if not rec:
        return None
    if int(rec.get("exp") or 0) < int(time.time()):
        rec["status"] = "expired"
    return dict(rec)


def poll_auth_qr(qr_id: str, poll_secret: str) -> dict[str, Any] | None:
    rec = get_auth_qr(qr_id)
    if not rec:
        return None
    if rec.get("poll_secret") != (poll_secret or "").strip():
        return None
    return rec


def confirm_auth_qr(
    qr_id: str,
    *,
    session_id: str,
    login_payload: dict[str, Any],
) -> bool:
    sid = (qr_id or "").strip()
    with _lock:
        rec = _qr_sessions.get(sid)
        if not rec:
            return False
        if int(rec.get("exp") or 0) < int(time.time()):
            rec["status"] = "expired"
            return False
        rec["status"] = "confirmed"
        rec["session_id"] = (session_id or "").strip()
        rec["login_payload"] = dict(login_payload or {})
    return True


def consume_confirmed_qr(qr_id: str, poll_secret: str) -> dict[str, Any] | None:
    sid = (qr_id or "").strip()
    with _lock:
        rec = _qr_sessions.get(sid)
        if not rec or rec.get("poll_secret") != (poll_secret or "").strip():
            return None
        if rec.get("status") != "confirmed":
            return dict(rec)
        out = dict(rec)
        _qr_sessions.pop(sid, None)
    return out
