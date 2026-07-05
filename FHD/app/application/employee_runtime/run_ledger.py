"""AI 员工执行持久审计（Run Ledger）。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.models.employee_run_log import EmployeeRunLog
from app.db.session import get_db

logger = logging.getLogger(__name__)


def create_employee_run_log(
    *,
    employee_id: str,
    input_payload: dict[str, Any] | None = None,
    tenant_id: int | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
) -> int:
    with get_db() as db:
        row = EmployeeRunLog(
            employee_id=str(employee_id or "").strip(),
            tenant_id=tenant_id,
            session_id=(str(session_id).strip() if session_id else None),
            user_id=user_id,
            status="running",
            input_json=json.dumps(input_payload or {}, ensure_ascii=False),
        )
        db.add(row)
        db.flush()
        run_id = int(row.id)
        db.commit()
        return run_id


def finish_employee_run_log(
    run_id: int,
    *,
    status: str,
    output: dict[str, Any] | None = None,
    error: str = "",
    attempts: int = 1,
    verified: bool = False,
) -> None:
    with get_db() as db:
        row = db.get(EmployeeRunLog, int(run_id))
        if row is None:
            return
        row.status = str(status or "failed")[:32]
        row.output_json = json.dumps(output or {}, ensure_ascii=False)
        row.error_text = str(error or "")[:4000]
        row.attempts = max(1, int(attempts))
        row.verified = 1 if verified else 0
        row.finished_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()


def list_employee_run_logs(employee_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    eid = str(employee_id or "").strip()
    if not eid:
        return []
    with get_db() as db:
        rows = (
            db.query(EmployeeRunLog)
            .filter(EmployeeRunLog.employee_id == eid)
            .order_by(EmployeeRunLog.id.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [
            {
                "id": row.id,
                "employee_id": row.employee_id,
                "status": row.status,
                "attempts": row.attempts,
                "verified": bool(row.verified),
                "error": row.error_text,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "finished_at": row.finished_at.isoformat() if row.finished_at else "",
            }
            for row in rows
        ]
