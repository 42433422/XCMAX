"""Client idempotency keys for billed chat: one execution per key, replay when done.

A key in ``processing`` is owned by one live handler; the handler is bounded by the
chat deadline, so a row older than that died with its process and may run again.
Only an unsettled attempt can run again: a completed key always replays its receipt,
and a key interrupted while ``settling`` is reported as such and never reruns.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

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


def begin(
    db: Session, user_id: int, client_request_id: str, digest: str, deadline_s: float
) -> tuple[str, Any]:
    """``("run", row)``, ``("replay", done)``, ``("processing", None)`` or ``("conflict", None)``."""
    row = (
        db.query(LlmClientRequest)
        .filter_by(user_id=user_id, client_request_id=client_request_id)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        row = LlmClientRequest(
            user_id=user_id, client_request_id=client_request_id, request_sha256=digest
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return "processing", None
        return "run", row
    if row.request_sha256 != digest:
        return "conflict", None
    if row.state == "completed":
        return "replay", json.loads(row.done_json or "{}")
    if row.state == "settling" or (row.state == "processing" and not _stale(row, deadline_s)):
        return "processing", None
    row.state = "processing"
    row.attempts = int(row.attempts or 1) + 1
    row.updated_at = datetime.now(UTC)
    db.commit()
    return "run", row


def mark_settling(db: Session, row: LlmClientRequest) -> None:
    row.state = "settling"
    row.updated_at = datetime.now(UTC)
    db.commit()


def finish(db: Session, row: LlmClientRequest, done: dict[str, Any] | None) -> None:
    """Record the receipt, or an unsettled failure; ``settling`` and done keys never revert."""
    if done is None and row.state in {"completed", "settling"}:
        return
    row.state = "completed" if done is not None else "failed"
    row.done_json = json.dumps(done, ensure_ascii=False) if done is not None else None
    row.updated_at = datetime.now(UTC)
    db.commit()
