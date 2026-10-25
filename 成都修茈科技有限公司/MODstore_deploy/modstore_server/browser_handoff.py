"""One-use, database-backed sign-in handoff for the wallet and plans pages."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy import delete, update

from modstore_server.db.identity import BrowserHandoffCode, User
from modstore_server.models import get_session_factory

TTL_SECONDS = 60
PURPOSE_PATHS = {"wallet": "/wallet", "plans": "/plans"}


def normalize_target(target: str, purpose: str) -> str:
    """Accept only fixed local destinations and non-secret purchase parameters."""
    if not isinstance(target, str) or len(target) > 1024 or any(ord(c) < 32 for c in target):
        raise ValueError("Invalid handoff target")
    parts = urlsplit(target)
    if (
        purpose not in PURPOSE_PATHS
        or parts.scheme
        or parts.netloc
        or parts.fragment
        or parts.path != PURPOSE_PATHS[purpose]
        or "\\" in target
    ):
        raise ValueError("Invalid handoff target")
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    allowed = {"source", "recharge"} if purpose == "wallet" else {"source", "plan", "tier"}
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("Invalid handoff target")
    for key, value in pairs:
        if key not in allowed or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            raise ValueError("Invalid handoff target")
        if key == "source" and value != "fhd":
            raise ValueError("Invalid handoff target")
        if key == "recharge" and not re.fullmatch(r"[1-9][0-9]{0,5}", value):
            raise ValueError("Invalid handoff target")
    query = urlencode(sorted(pairs))
    return parts.path + ("?" + query if query else "")


def _fingerprint(user: User) -> str:
    return hashlib.sha256(str(user.password_hash).encode()).hexdigest()


def _available(user: User | None) -> bool:
    return (
        user is not None
        and getattr(user, "deleted_at", None) is None
        and str(user.account_state or "") not in {"deleted", "disabled", "suspended", "blocked"}
    )


def issue_code(user_id: int, target: str, purpose: str) -> dict:
    target = normalize_target(target, purpose)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    code = secrets.token_urlsafe(32)
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        if user is None or not _available(user):
            raise ValueError("Handoff unavailable")
        # Bound storage growth; codes have no durable audit or business value.
        session.execute(delete(BrowserHandoffCode).where(BrowserHandoffCode.expires_at <= now))
        session.add(
            BrowserHandoffCode(
                code_hash=hashlib.sha256(code.encode()).hexdigest(),
                user_id=user.id,
                credential_fingerprint=_fingerprint(user),
                purpose=purpose,
                target=target,
                expires_at=now + timedelta(seconds=TTL_SECONDS),
            )
        )
        session.commit()
    return {
        "code": code,
        "target": target,
        "purpose": purpose,
        "expires_in": TTL_SECONDS,
    }


def consume_code(code: str, target: str, purpose: str) -> User:
    target = normalize_target(target, purpose)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise ValueError("Handoff expired or invalid")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_session_factory()() as session:
        # The predicate and mutation are one DB operation. Independent workers
        # cannot both redeem a code, including on PostgreSQL and SQLite.
        row = session.execute(
            update(BrowserHandoffCode)
            .where(
                BrowserHandoffCode.code_hash == hashlib.sha256(code.encode()).hexdigest(),
                BrowserHandoffCode.target == target,
                BrowserHandoffCode.purpose == purpose,
                BrowserHandoffCode.consumed_at.is_(None),
                BrowserHandoffCode.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(
                BrowserHandoffCode.user_id,
                BrowserHandoffCode.credential_fingerprint,
            )
        ).first()
        if row is None:
            raise ValueError("Handoff expired or invalid")
        user = session.get(User, row.user_id)
        valid = (
            user is not None
            and _available(user)
            and secrets.compare_digest(_fingerprint(user), row.credential_fingerprint)
        )
        session.commit()
        if user is None or not valid:
            raise ValueError("Handoff expired or invalid")
        session.refresh(user)
        session.expunge(user)
        return user
