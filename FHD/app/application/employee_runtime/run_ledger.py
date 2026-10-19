"""AI 员工执行持久审计（Run Ledger）。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.models.employee_run_log import EmployeeRunLog
from app.db.session import get_db
from app.infrastructure.tenant_scope import current_tenant_id, tenant_id_for_write

logger = logging.getLogger(__name__)


def _tenant_query(db, tid: int):
    """按显式租户谓词查询；无环境租户时不再叠加全局过滤（否则恒为 false）。"""
    query = db.query(EmployeeRunLog).filter(EmployeeRunLog.tenant_id == int(tid))
    if current_tenant_id() is None:
        return query.execution_options(skip_tenant_filter=True)
    return query


def create_employee_run_log(
    *,
    employee_id: str,
    input_payload: dict[str, Any] | None = None,
    tenant_id: int | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
) -> int:
    """写入执行台账；缺租户上下文时拒绝（``TenantScopeError``）。"""
    tid = tenant_id_for_write(tenant_id)
    with get_db() as db:
        row = EmployeeRunLog(
            employee_id=str(employee_id or "").strip(),
            tenant_id=tid,
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
    tenant_id: int | None = None,
) -> bool:
    """按租户归属结束台账；跨租户 / 缺租户时不改任何行。"""
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    if tid is None:
        logger.warning("拒绝结束执行台账 %s：缺少租户上下文", run_id)
        return False
    with get_db() as db:
        row = (
            _tenant_query(db, tid)
            .filter(EmployeeRunLog.id == int(run_id))
            .first()
        )
        if row is None:
            logger.warning("拒绝结束执行台账 %s：非当前租户数据", run_id)
            return False
        row.status = str(status or "failed")[:32]
        row.output_json = json.dumps(output or {}, ensure_ascii=False)
        row.error_text = str(error or "")[:4000]
        row.attempts = max(1, int(attempts))
        row.verified = 1 if verified else 0
        row.finished_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        return True


def list_employee_run_logs(
    employee_id: str, *, limit: int = 50, tenant_id: int | None = None
) -> list[dict[str, Any]]:
    """列出当前租户该员工的执行台账；缺租户时 fail-closed 返回空。"""
    eid = str(employee_id or "").strip()
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    if not eid or tid is None:
        return []
    with get_db() as db:
        rows = (
            _tenant_query(db, tid)
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
