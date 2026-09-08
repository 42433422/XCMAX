"""Account-bound screen delegation; runtime keys never store a login secret."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fastapi import HTTPException

from app.application.aiopen.software_control import request_screen_owner


def capture_screen_grant(request: Any) -> dict[str, Any]:
    from app.db import HostSessionLocal
    from app.db.models.user import Session
    from app.infrastructure.auth.dependencies import session_id_from_request

    identity = request_screen_owner(request)
    if not identity:
        raise HTTPException(401, "连接口令需要已登录账号")
    with HostSessionLocal() as db:
        row = db.query(Session).filter_by(session_id=session_id_from_request(request)).one_or_none()
        if row is None or str(row.user_id) != identity["owner_id"]:
            raise HTTPException(401, "连接口令需要有效的本机会话")
        expiry = (
            row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
        )
        if expiry <= datetime.now(UTC):
            raise HTTPException(401, "登录会话已过期")
        return {
            **identity,
            "session_record_id": row.id,
            "session_digest": sha256(row.session_id.encode()).hexdigest(),
            "expires_at": min(expiry, datetime.now(UTC) + timedelta(days=1)).timestamp(),
        }


def validate_screen_grant(grant: Any) -> dict[str, str]:
    from app.db import HostSessionLocal
    from app.db.models.user import Session, User

    if not isinstance(grant, dict) or type(grant.get("session_record_id")) is not int:
        return {}
    if (
        not isinstance(grant.get("expires_at"), (int, float))
        or grant["expires_at"] <= datetime.now(UTC).timestamp()
    ):
        return {}
    with HostSessionLocal() as db:
        row = db.get(Session, grant["session_record_id"])
        user = db.get(User, row.user_id) if row else None
        if row is None or user is None or not user.is_active:
            return {}
        expiry = (
            row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
        )
        if (
            expiry <= datetime.now(UTC)
            or sha256(row.session_id.encode()).hexdigest() != grant.get("session_digest")
            or str(user.id) != grant.get("owner_id")
            or str(user.tenant_id or "") != grant.get("tenant_id")
        ):
            return {}
    return {"owner_id": grant["owner_id"], "tenant_id": grant["tenant_id"]}


def external_screen_identity() -> dict[str, str]:
    from app.application.aiopen.service import AIOPEN_STATE
    from app.infrastructure.request_context import get_current_request

    request = get_current_request()
    if request is None:
        return {}
    key = str(request.headers.get("X-AIOPEN-Key") or "").strip()
    if key:
        # A supplied credential is authoritative: never fall back to another
        # browser account when the delegated key is revoked or invalid.
        meta = AIOPEN_STATE.get("runtime_keys", {}).get(key, {})
        return validate_screen_grant(meta.get("screen_grant"))
    return request_screen_owner(request)
