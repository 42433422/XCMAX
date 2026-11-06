"""Retry, approval, crash and idempotency decisions shared by task writers."""

from __future__ import annotations

import json
import random
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.task_lifecycle.machine import (
    DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds,
)

RETRYABLE_CODES = frozenset({"timeout", "upstream_unavailable", "rate_limited"})
_DDL = """
CREATE TABLE IF NOT EXISTS task_lifecycle_records (
    module TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    body_json TEXT NOT NULL,
    PRIMARY KEY (module, tenant_id, task_id)
)
"""
_IDEMPOTENCY = """
CREATE TABLE IF NOT EXISTS task_lifecycle_idempotency (
    module TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    task_id TEXT NOT NULL,
    PRIMARY KEY (module, tenant_id, idem_key)
)
"""


class TaskLifecycleError(ValueError):
    """A writer asked for a retry, approval or idempotency outcome the machine refuses."""


def jittered_delay(retry_number: int, *, jitter_ratio: float, rng: random.Random) -> float:
    """Delay(n) = min(1 * 2^(n-1), 30), then symmetric jitter."""
    base = retry_delay_seconds(retry_number)
    ratio = max(0.0, float(jitter_ratio))
    if ratio == 0:
        return base
    return max(0.0, base + rng.uniform(-base * ratio, base * ratio))


def failure_retries(
    attempts: int, error_code: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS
) -> bool:
    return error_code in RETRYABLE_CODES and int(attempts) < int(max_attempts)


def empty_body() -> dict[str, Any]:
    return {
        "effects": [],
        "approver": "",
        "approval_requested_at": "",
        "history": [],
        "available_at": "",
    }


def remember(
    body: dict[str, Any], *, at: str, source: str, target: str, code: str, actor: str
) -> None:
    history = body.setdefault("history", [])
    history.append(
        {
            "at": at,
            "from": source,
            "to": target,
            "code": code,
            "actor": actor,
        }
    )


def approval_actor_allowed(body: dict[str, Any], actor: str) -> bool:
    approver = str(body.get("approver") or "")
    if not str(actor or "").strip():
        return False
    return not approver or approver == actor


class MemoryBook:
    """In-process lifecycle log for the in-memory queue."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.idem: dict[tuple[str, str, str], tuple[str, str]] = {}

    def get(self, module: str, tenant: str, task_id: str) -> dict[str, Any]:
        return self.rows.setdefault((module, tenant, task_id), empty_body())

    def put(self, module: str, tenant: str, task_id: str, body: dict[str, Any]) -> None:
        self.rows[(module, tenant, task_id)] = body

    def claim_key(self, module: str, tenant: str, key: str, fingerprint: str, task_id: str) -> str:
        slot = (module, tenant, key)
        current = self.idem.get(slot)
        if current is None:
            self.idem[slot] = (fingerprint, task_id)
            return ""
        if current[0] != fingerprint:
            raise TaskLifecycleError("幂等键与已有任务内容冲突")
        return current[1]


class SessionBook:
    """Lifecycle log stored in the same database as the task row."""

    def __init__(self, db: Session) -> None:
        self._db = db
        db.execute(text(_DDL))
        db.execute(text(_IDEMPOTENCY))

    def get(self, module: str, tenant: str, task_id: str) -> dict[str, Any]:
        row = self._db.execute(
            text(
                "SELECT body_json FROM task_lifecycle_records "
                "WHERE module=:m AND tenant_id=:t AND task_id=:id"
            ),
            {"m": module, "t": tenant, "id": task_id},
        ).first()
        if row is None:
            return empty_body()
        loaded = json.loads(row[0])
        return loaded if isinstance(loaded, dict) else empty_body()

    def put(self, module: str, tenant: str, task_id: str, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
        self._db.execute(
            text(
                "INSERT INTO task_lifecycle_records(module, tenant_id, task_id, body_json) "
                "VALUES (:m, :t, :id, :body) "
                "ON CONFLICT(module, tenant_id, task_id) DO UPDATE SET body_json=:body"
            ),
            {"m": module, "t": tenant, "id": task_id, "body": payload},
        )

    def claim_key(self, module: str, tenant: str, key: str, fingerprint: str, task_id: str) -> str:
        row = self._db.execute(
            text(
                "SELECT fingerprint, task_id FROM task_lifecycle_idempotency "
                "WHERE module=:m AND tenant_id=:t AND idem_key=:k"
            ),
            {"m": module, "t": tenant, "k": key},
        ).first()
        if row is None:
            self._db.execute(
                text(
                    "INSERT INTO task_lifecycle_idempotency"
                    "(module, tenant_id, idem_key, fingerprint, task_id) "
                    "VALUES (:m, :t, :k, :f, :id)"
                ),
                {"m": module, "t": tenant, "k": key, "f": fingerprint, "id": task_id},
            )
            return ""
        if str(row[0]) != fingerprint:
            raise TaskLifecycleError("幂等键与已有任务内容冲突")
        return str(row[1])
