"""Client idempotency keys for billed chat: one execution per key, replay when done.

A key in ``processing`` is owned by one handler. An expired claim may be taken
over, with its attempt fenced before external work and every later transition.
Only an unsettled attempt can run again: a completed key replays its receipt,
and a key interrupted while ``settling`` never reruns.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.db.llm_chat import LlmClientRequest

KEY_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{8,128}")
_STALE_GRACE_S = 60.0


def request_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def attempt_request_id(user_id: int, client_request_id: str, attempts: int) -> str:
    """Wallet idempotency is per attempt; a finished attempt never runs twice."""
    digest = hashlib.sha256(f"{user_id}:{client_request_id}".encode()).hexdigest()[:24]
    return f"cr-{digest}-{attempts}"


def _stale(row: LlmClientRequest, deadline_s: float) -> bool:
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated > timedelta(seconds=deadline_s + _STALE_GRACE_S)


def lookup(db: Session, user_id: int, client_request_id: str, deadline_s: float) -> str:
    row = (
        db.query(LlmClientRequest)
        .filter_by(user_id=user_id, client_request_id=client_request_id)
        .one_or_none()
    )
    if row is None:
        return "not_found"
    if row.state == "processing" and _stale(row, deadline_s):
        return "failed"
    return str(row.state)


def completed_receipt(db: Session, user_id: int, client_request_id: str, digest: str):
    """Read an already completed receipt without acquiring a new execution lease."""
    row = (
        db.query(LlmClientRequest)
        .filter_by(user_id=user_id, client_request_id=client_request_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None or row.state != "completed":
        return None
    if row.request_sha256 != digest:
        return "conflict", None
    return "replay", json.loads(row.done_json or "{}")


def existing_state(db: Session, user_id: int, client_request_id: str, digest: str) -> str:
    row = (
        db.query(LlmClientRequest)
        .filter_by(user_id=user_id, client_request_id=client_request_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        return "not_found"
    return str(row.state) if row.request_sha256 == digest else "conflict"


def begin(
    db: Session, user_id: int, client_request_id: str, digest: str, deadline_s: float
) -> tuple[str, Any]:
    """``("run", row)``, ``("replay", done)``, ``("processing", None)`` or ``("conflict", None)``."""
    # SQLite's FOR UPDATE is a no-op. Reuse the receipt lock to reserve the
    # writer and refresh stale ORM identities before handing out an attempt.
    row = lock_request(db, user_id, client_request_id)
    if row is None:
        row = LlmClientRequest(
            user_id=user_id,
            client_request_id=client_request_id,
            request_sha256=digest,
            attempts=1,
        )
        inspect(row).info["claimed_attempt"] = 1
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return "processing", None
        return "run", row
    if row.request_sha256 != digest:
        db.commit()
        return "conflict", None
    if row.state == "completed":
        done = json.loads(row.done_json or "{}")
        db.commit()
        return "replay", done
    if row.state != "failed" and not (row.state == "processing" and _stale(row, deadline_s)):
        # Callers may read the external wallet next; never hold the writer
        # while reconciling an attempt owned by another handler.
        db.commit()
        return "processing", None
    row.state = "processing"
    row.attempts = int(row.attempts or 1) + 1
    inspect(row).info["claimed_attempt"] = row.attempts
    row.updated_at = datetime.now(UTC)
    db.commit()
    return "run", row


def _lock_owned_attempt(db: Session, row: LlmClientRequest) -> LlmClientRequest:
    # Keep the begin-time generation outside ORM expiration. A stale handler
    # must not gain the new owner's attempt simply by refreshing its row.
    with db.no_autoflush:
        attempt = inspect(row).info.get("claimed_attempt")
        if attempt is None:
            attempt = row.attempts
        locked = lock_request(db, row.user_id, row.client_request_id)
    if locked is None or locked.attempts != attempt:
        db.rollback()
        raise HTTPException(409, {"message": "原模型请求执行权已转移", "state": "ownership_lost"})
    return locked


def mark_settling(db: Session, row: LlmClientRequest) -> None:
    row = _lock_owned_attempt(db, row)
    if row.state not in {"processing", "settling"}:
        db.rollback()
        raise HTTPException(409, "原模型请求已结束")
    row.state = "settling"
    row.updated_at = datetime.now(UTC)
    db.commit()


def confirmed_no_charge(db: Session, row: LlmClientRequest) -> None:
    """Allow the live handler to continue after a definitive rejection or wallet release."""
    row = _lock_owned_attempt(db, row)
    if row.state != "settling":
        db.rollback()
        raise HTTPException(409, "原模型请求不能释放")
    row.state = "processing"
    row.done_json = None
    row.updated_at = datetime.now(UTC)
    db.commit()


def prepare_settlement(db: Session, row: LlmClientRequest, receipt: dict[str, Any]) -> None:
    """Keep provider usage and the intended charge before contacting the wallet."""
    row = _lock_owned_attempt(db, row)
    if row.state not in {"processing", "settling"}:
        db.rollback()
        raise HTTPException(409, "原模型请求已结束")
    row.done_json = json.dumps({"pending_settlement": receipt}, ensure_ascii=False)
    row.state = "settling"
    row.updated_at = datetime.now(UTC)
    db.commit()


def lock_request(db: Session, user_id: int, client_request_id: str) -> LlmClientRequest | None:
    query = db.query(LlmClientRequest).filter_by(
        user_id=user_id, client_request_id=client_request_id
    )
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE. Reserve its writer before reading the state;
        # retain this lock through the usage rows and receipt's existing commit.
        query.update({LlmClientRequest.state: LlmClientRequest.state}, synchronize_session=False)
    return query.populate_existing().with_for_update().one_or_none()


def finish(db: Session, row: LlmClientRequest, done: dict[str, Any] | None) -> None:
    """Record the receipt, or an unsettled failure; ``settling`` and done keys never revert."""
    row = _lock_owned_attempt(db, row)
    if row.state == "completed" or (done is None and row.state == "settling"):
        db.commit()
        return
    row.state = "completed" if done is not None else "failed"
    row.done_json = json.dumps(done, ensure_ascii=False) if done is not None else None
    row.updated_at = datetime.now(UTC)
    db.commit()
