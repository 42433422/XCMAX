"""Transactional acceptance, leases and append-only correlation events."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.db.mac_control import MacControlEvent, MacControlTask
from modstore_server.eventing.db_outbox import enqueue

TERMINAL = {"execution_completed", "failed", "cancelled"}


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def event(db: Session, task: MacControlTask, state: str, detail: dict) -> None:
    key = digest([task.id, task.attempt_id, state, detail])
    if db.query(MacControlEvent).filter_by(event_key=key).first():
        return
    db.add(
        MacControlEvent(
            event_key=key,
            task_id=task.id,
            attempt_id=task.attempt_id,
            state=state,
            payload_json=encoded(detail),
            created_at=time.time(),
        )
    )
    if state in {"failed", "awaiting_approval", "cancelled"}:
        enqueue(
            db,
            "mac_control.attention",
            task.id,
            {"task_id": task.id, "state": state},
            event_id=key,
        )


def accept(db: Session, *, actor: str, key: str, request: dict) -> MacControlTask:
    if not actor or not key or len(key) > 128:
        raise ValueError("需要有效的身份与稳定请求标识")
    checksum = digest(request)
    existing = db.query(MacControlTask).filter_by(actor=actor, request_key=key).first()
    if existing:
        if existing.request_digest != checksum:
            raise ValueError("相同请求标识不能提交不同内容")
        return existing
    now = time.time()
    task = MacControlTask(
        id=uuid.uuid4().hex,
        actor=actor,
        request_key=key,
        request_digest=checksum,
        request_json=encoded(request),
        state="queued",
        reason="",
        para_task_id="",
        device_id="",
        attempt_id="",
        lease_until=0,
        snapshot_json="{}",
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
            event(db, task, "queued", {"source": request.get("source", "admin")})
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(MacControlTask).filter_by(actor=actor, request_key=key).one()
        if existing.request_digest != checksum:
            raise ValueError("相同请求标识不能提交不同内容") from None
        return existing
    return task


def acquire(db: Session, task_id: str, now: float | None = None) -> MacControlTask | None:
    now = time.time() if now is None else now
    changed = (
        db.query(MacControlTask)
        .filter(
            MacControlTask.id == task_id,
            MacControlTask.lease_until < now,
            MacControlTask.state.notin_(TERMINAL),
        )
        .update({"lease_until": now + 120}, synchronize_session=False)
    )
    db.commit()
    db.expire_all()
    return db.get(MacControlTask, task_id) if changed else None


def transition(
    db: Session,
    task: MacControlTask,
    state: str,
    reason: str = "",
    snapshot: dict | None = None,
) -> None:
    task.state, task.reason, task.updated_at = state, reason, time.time()
    if snapshot is not None:
        task.snapshot_json = encoded(snapshot)
    event(
        db,
        task,
        state,
        {
            "reason": reason,
            "para_task_id": task.para_task_id,
            "snapshot": snapshot or {},
        },
    )
    db.commit()


def view(task: MacControlTask) -> dict:
    return {
        "id": task.id,
        "state": task.state,
        "reason": task.reason,
        "request": json.loads(task.request_json),
        "para_task_id": task.para_task_id,
        "device_id": task.device_id,
        "attempt_id": task.attempt_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "execution": json.loads(task.snapshot_json),
        "delivery": {"status": "not_verified", "source": "customer_delivery_receipts"},
    }
