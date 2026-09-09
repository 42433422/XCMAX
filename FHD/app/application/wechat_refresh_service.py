"""Durable refresh outbox. A request is complete only after the collector's receipt."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models.wechat_refresh import WechatRefreshRequest as Record

ACTIONS = frozenset({"refresh_contact_cache", "refresh_messages_cache"})


def _open_session():
    from app.db import HostSessionLocal

    return HostSessionLocal()


def _view(row: Record, now: float) -> dict[str, Any]:
    state = row.state
    if state in {"pending", "running", "paused", "pausing"} and row.expires_at <= now:
        state = "expired"
    return {
        "request_id": row.request_id,
        "action": row.action,
        "state": state,
        "completed": state == "completed",
        "receipt": json.loads(row.receipt_json),
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }


def request_refresh(tenant_id: int, actor_id: str, action: str, request_key: str) -> dict[str, Any]:
    if tenant_id <= 0 or not actor_id or action not in ACTIONS or not request_key:
        raise ValueError("invalid refresh scope or action")
    request_id = hashlib.sha256(
        json.dumps([tenant_id, actor_id, request_key], ensure_ascii=False).encode()
    ).hexdigest()
    now = time.time()
    with _open_session() as session:
        row = session.get(Record, request_id)
        if row is None:
            row = Record(
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                created_at=now,
                expires_at=now + 900,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                row = session.get(Record, request_id)
                if row is None:
                    raise
        if row.action != action:
            raise ValueError("refresh request key already used for another action")
        if row.state in {"paused", "pausing"} and row.expires_at > now:
            session.execute(
                update(Record)
                .where(Record.request_id == request_id, Record.state.in_(["paused", "pausing"]))
                .values(state=case((Record.state == "pausing", "running"), else_="pending"))
            )
            session.commit()
            session.refresh(row)
        return _view(row, now)


def control_refresh(tenant_id: int, actor_id: str, request_id: str, action: str) -> None:
    if action not in {"pause", "cancel"}:
        raise ValueError("invalid refresh control")
    # A running collector cannot be stopped remotely. Pause prevents unclaimed
    # work; cancel invalidates its receipt without claiming to undo collection.
    states = (
        ["pending", "running"] if action == "pause" else ["pending", "running", "paused", "pausing"]
    )
    with _open_session() as session:
        session.execute(
            update(Record)
            .where(
                Record.request_id == request_id,
                Record.tenant_id == tenant_id,
                Record.actor_id == actor_id,
                Record.state.in_(states),
            )
            .values(
                state=case((Record.state == "running", "pausing"), else_="paused")
                if action == "pause"
                else "cancelled"
            )
        )
        session.commit()


def get_refresh(tenant_id: int, actor_id: str, request_id: str) -> dict[str, Any] | None:
    with _open_session() as session:
        row = session.get(Record, request_id)
        if row is None or row.tenant_id != tenant_id or row.actor_id != actor_id:
            return None
        return _view(row, time.time())


def claim_refresh(tenant_id: int) -> dict[str, Any] | None:
    if tenant_id <= 0:
        raise ValueError("positive tenant_id required")
    now = time.time()
    eligible = (
        Record.tenant_id == tenant_id,
        Record.expires_at > now,
        or_(Record.state == "pending", (Record.state == "running") & (Record.lease_until <= now)),
    )
    with _open_session() as session:
        request_id = session.scalar(
            select(Record.request_id).where(*eligible).order_by(Record.created_at).limit(1)
        )
        if request_id is None:
            return None
        token = uuid.uuid4().hex
        changed = session.execute(
            update(Record)
            .where(Record.request_id == request_id, *eligible)
            .values(state="running", lease_token=token, lease_until=now + 300)
        ).rowcount
        session.commit()
        if changed != 1:
            return None
        row = session.get(Record, request_id)
        assert row is not None
        return {"request_id": request_id, "action": row.action, "lease_token": token}


def finish_refresh(
    tenant_id: int, request_id: str, lease_token: str, receipt: dict[str, Any]
) -> bool:
    if tenant_id <= 0 or not lease_token or not isinstance(receipt.get("success"), bool):
        raise ValueError("invalid refresh receipt")
    # Keep only execution evidence, never raw contact/message bodies or filesystem secrets.
    summary: dict[str, Any] = {"success": receipt["success"]}
    for key in ("contacts", "inserted", "skipped", "collected_contacts"):
        value = receipt.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            summary[key] = value
    success = receipt["success"] is True
    summary["error_code"] = "" if success else "collector_failed"
    now = time.time()
    encoded = json.dumps(summary, sort_keys=True)
    with _open_session() as session:
        changed = session.execute(
            update(Record)
            .where(
                Record.request_id == request_id,
                Record.tenant_id == tenant_id,
                Record.state.in_(["running", "pausing"]),
                Record.lease_token == lease_token,
                Record.lease_until > now,
                Record.expires_at > now,
            )
            .values(state="completed" if success else "failed", receipt_json=encoded)
        ).rowcount
        session.commit()
        if changed == 1:
            return True
        row = session.get(Record, request_id)
        return bool(
            row is not None
            and row.tenant_id == tenant_id
            and row.lease_token == lease_token
            and row.state in {"completed", "failed"}
            and row.receipt_json == encoded
        )
