"""AI 员工执行持久审计（Run Ledger）。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.models.employee_run_log import EmployeeRunLog
from app.db.session import get_db
from app.domain.task_lifecycle.adapters import (
    LegacyTransitionError,
    assert_legacy_transition,
    canonicalize,
)

logger = logging.getLogger(__name__)


def create_employee_run_log(
    *,
    employee_id: str,
    input_payload: dict[str, Any] | None = None,
    tenant_id: int | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
) -> int:
    tenant_id = _require_tenant(tenant_id)
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
    tenant_id: int | None = None,
    output: dict[str, Any] | None = None,
    error: str = "",
    attempts: int = 1,
    verified: bool = False,
    error_code: str = "",
    approver: str = "",
    jitter_ratio: float = 0.2,
) -> None:
    tenant_id = _require_tenant(tenant_id)
    with get_db() as db:
        from app.domain.task_lifecycle.control import (
            SessionBook,
            failure_retries,
            jittered_delay,
            remember,
        )

        row = db.get(EmployeeRunLog, int(run_id))
        if row is None or row.tenant_id != tenant_id:
            return
        current = row.status or "running"
        target = str(status or "failed")
        book = SessionBook(db)
        body = book.get("employee", str(tenant_id), str(run_id))
        if target == "failed" and error_code == "timeout" and not failure_retries(
            int(attempts), error_code or ""
        ):
            target = "timed_out"
        scheduled = target == "failed" and failure_retries(int(attempts), error_code or "")
        try:
            assert_legacy_transition("employee", current, "failed" if scheduled else target)
        except LegacyTransitionError as exc:
            raise ValueError(str(exc)) from exc
        if (
            not scheduled
            and canonicalize("employee", current) == canonicalize("employee", target)
            and current != "running"
        ):
            return
        if target == "awaiting_approval":
            body["approver"] = str(approver or body.get("approver") or "")
            body["approval_requested_at"] = datetime.now(UTC).isoformat()
        if scheduled:
            import random
            from datetime import timedelta

            delay = jittered_delay(
                int(attempts), jitter_ratio=jitter_ratio, rng=random.Random(run_id)
            )
            target = "pending"
            body["available_at"] = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
            attempts = int(attempts) + 1
        row.status = target[:32]
        remember(
            body,
            at=datetime.now(UTC).isoformat() if scheduled else "",
            source=current,
            target=target,
            code=error_code,
            actor=str(tenant_id),
        )
        book.put("employee", str(tenant_id), str(run_id), body)
        row.output_json = json.dumps(output or {}, ensure_ascii=False)
        row.error_text = str(error or "")[:4000]
        row.attempts = max(1, int(attempts))
        row.verified = 1 if verified else 0
        row.finished_at = (
            None
            if row.status in {"unknown", "pending", "accepted", "running", "awaiting_approval"}
            else datetime.now(UTC).replace(tzinfo=None)
        )
        db.commit()


def employee_lifecycle(run_id: int, *, tenant_id: int) -> dict[str, Any]:
    tenant_id = _require_tenant(tenant_id)
    with get_db() as db:
        from app.domain.task_lifecycle.control import SessionBook

        row = db.get(EmployeeRunLog, int(run_id))
        if row is None or row.tenant_id != tenant_id:
            return {}
        return SessionBook(db).get("employee", str(tenant_id), str(run_id))


def decide_employee_run_log(
    run_id: int,
    *,
    tenant_id: int,
    decision: str,
    actor: str,
) -> None:
    tenant_id = _require_tenant(tenant_id)
    with get_db() as db:
        from app.domain.task_lifecycle.control import (
            SessionBook,
            TaskLifecycleError,
            approval_actor_allowed,
            remember,
        )

        row = db.get(EmployeeRunLog, int(run_id))
        if row is None or row.tenant_id != tenant_id:
            return
        book = SessionBook(db)
        body = book.get("employee", str(tenant_id), str(run_id))
        if not approval_actor_allowed(body, actor):
            raise ValueError("无权审批该任务")
        target = {"approve": "pending", "reject": "rejected"}.get(decision)
        if target is None:
            raise ValueError("未知审批决定")
        current = row.status or "running"
        try:
            assert_legacy_transition("employee", current, target)
        except (LegacyTransitionError, TaskLifecycleError) as exc:
            raise ValueError(str(exc)) from exc
        row.status = target
        row.finished_at = None if target == "pending" else datetime.now(UTC).replace(tzinfo=None)
        remember(
            body,
            at=datetime.now(UTC).isoformat(),
            source=current,
            target=target,
            code=decision,
            actor=actor,
        )
        book.put("employee", str(tenant_id), str(run_id), body)
        db.commit()


def request_employee_approval(run_id: int, *, tenant_id: int, approver: str) -> None:
    tenant_id = _require_tenant(tenant_id)
    with get_db() as db:
        from app.domain.task_lifecycle.control import SessionBook

        row = db.get(EmployeeRunLog, int(run_id))
        if row is None or row.tenant_id != tenant_id:
            return
        book = SessionBook(db)
        body = book.get("employee", str(tenant_id), str(run_id))
        body["approver"] = approver
        body["approval_requested_at"] = datetime.now(UTC).isoformat()
        book.put("employee", str(tenant_id), str(run_id), body)
        db.commit()
    finish_employee_run_log(
        run_id, tenant_id=tenant_id, status="awaiting_approval", error="approval_requested"
    )


def expire_employee_approvals(*, tenant_id: int, timeout_seconds: float) -> int:
    tenant_id = _require_tenant(tenant_id)
    now = datetime.now(UTC)
    expired = 0
    with get_db() as db:
        from app.domain.task_lifecycle.control import SessionBook, remember

        rows = (
            db.query(EmployeeRunLog)
            .filter(
                EmployeeRunLog.tenant_id == tenant_id,
                EmployeeRunLog.status == "awaiting_approval",
            )
            .all()
        )
        book = SessionBook(db)
        for row in rows:
            body = book.get("employee", str(tenant_id), str(row.id))
            started = str(body.get("approval_requested_at") or "")
            if not started:
                continue
            age = (now - datetime.fromisoformat(started)).total_seconds()
            if age < timeout_seconds:
                continue
            current = row.status
            row.status = "rejected"
            row.error_text = "approval_timeout"
            row.finished_at = now.replace(tzinfo=None)
            remember(
                body,
                at=now.isoformat(),
                source=current,
                target="rejected",
                code="approval_timeout",
                actor="",
            )
            book.put("employee", str(tenant_id), str(row.id), body)
            expired += 1
        db.commit()
    return expired


def list_employee_run_logs(
    employee_id: str, *, tenant_id: int | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    tenant_id = _require_tenant(tenant_id)
    eid = str(employee_id or "").strip()
    if not eid:
        return []
    with get_db() as db:
        rows = (
            db.query(EmployeeRunLog)
            .filter(EmployeeRunLog.employee_id == eid, EmployeeRunLog.tenant_id == tenant_id)
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


def _require_tenant(tenant_id: int | None) -> int:
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("employee run requires a trusted tenant")
    return tenant_id
