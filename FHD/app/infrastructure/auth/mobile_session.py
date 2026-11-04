"""Current host-session authority for privileged mobile access and refresh."""

from __future__ import annotations

from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

ADMIN_ACCOUNT_KINDS = frozenset({"admin", "admin_portal"})
ADMIN_ROLES = frozenset({"admin", "super_admin", "owner"})


def current_mobile_admin(user_id: Any, session_id: Any):
    """Never reconstruct privilege from signed but historical token claims."""
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import joinedload

    from app.db.models.user import Session
    from app.db.session import get_host_db
    from app.utils.time import utc_now_naive

    try:
        if (
            isinstance(user_id, bool)
            or not isinstance(user_id, (int, str))
            or not isinstance(session_id, str)
        ):
            return None
        uid = int(user_id)
        sid = str(session_id or "").strip()
        if uid <= 0 or not sid:
            return None
        with get_host_db() as db:
            row = (
                db.query(Session)
                .options(joinedload(Session.user))
                .filter(
                    Session.session_id == sid,
                    Session.user_id == uid,
                    Session.expires_at > utc_now_naive(),
                )
                .first()
            )
            if row is None or str(row.account_kind).strip().lower() not in ADMIN_ACCOUNT_KINDS:
                return None
            user = row.user
            if (
                user is None
                or not user.is_active
                or str(user.role).strip().lower() not in ADMIN_ROLES
            ):
                return None
            db.expunge(user)
            return user
    except (TypeError, ValueError, SQLAlchemyError):
        return None
    except RECOVERABLE_ERRORS:
        return None
