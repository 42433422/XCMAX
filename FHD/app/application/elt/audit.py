"""Append-only audit rows for ETL upload, cleaning, confirmation, submit and failure.

Records share the process-wide ``ai_action_audit`` table and commit with the
business transaction that made the operation durable.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.elt.service_support import utcnow


def record_elt_audit(
    db: Session,
    *,
    actor: int | None,
    action: str,
    payload: dict[str, Any],
) -> None:
    """Insert one complete audit record. Caller commits."""
    occurred_at = utcnow().isoformat()
    body = {
        "actor_user_id": actor,
        "occurred_at": occurred_at,
        "operation": action,
        **payload,
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) > 4000:
        kept = (
            "actor_user_id",
            "occurred_at",
            "operation",
            "outcome",
            "run_id",
            "upload_id",
            "error_code",
        )
        encoded = json.dumps(
            {key: body[key] for key in kept if key in body},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    _ensure_table(db)
    json_payload = db.get_bind().dialect.name == "postgresql"
    statement = (
        "INSERT INTO ai_action_audit (created_at, actor, action, payload) "
        "VALUES (:created_at, :actor, :action, CAST(:payload AS jsonb))"
        if json_payload
        else "INSERT INTO ai_action_audit (created_at, actor, action, payload) "
        "VALUES (:created_at, :actor, :action, :payload)"
    )
    db.execute(
        text(statement),
        {
            "created_at": occurred_at,
            "actor": None if actor is None else str(actor),
            "action": action[:200],
            "payload": encoded,
        },
    )


def note_interrupted(db: Session, run: Any) -> None:
    """Mark a dead execution interrupted and keep a partial submit timestamp."""
    run.status = "interrupted"
    run.stage = "interrupted"
    run.error_code = "ELT_EXECUTION_INTERRUPTED"
    run.error_message = "上次执行被意外中断，请重新预演或重试"
    if int(run.executed_rows or 0) and run.executed_at is None:
        run.executed_at = utcnow()
    record_elt_audit(
        db,
        actor=run.owner_user_id,
        action="elt_exception",
        payload={
            "run_id": run.id,
            "upload_id": run.upload_id,
            "target_type": run.target_type,
            "file_sha256": run.file_sha256,
            "outcome": "interrupted",
            "error_code": run.error_code,
            "executed_rows": int(run.executed_rows or 0),
            "executed_at": run.executed_at.isoformat() if run.executed_at else None,
        },
    )


def _ensure_table(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        ddl = """
        CREATE TABLE IF NOT EXISTS ai_action_audit (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actor TEXT,
            action TEXT NOT NULL,
            payload JSONB
        )
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS ai_action_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            actor TEXT,
            action TEXT NOT NULL,
            payload TEXT
        )
        """
    db.execute(text(ddl))
