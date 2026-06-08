"""管理员：员工任务执行指标（employee_execution_metrics）只读分页 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

from modstore_server.api.deps import require_admin
from modstore_server.models import EmployeeExecutionMetric, User, get_session_factory

router = APIRouter(prefix="/api/admin/employees", tags=["admin-employees"])

_TASK_MAX = 1024
_ERROR_MAX = 500


def _trunc(text: str | None, max_len: int) -> str:
    if text is None:
        return ""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


@router.get("/{employee_id}/execution-metrics")
def list_employee_execution_metrics(
    employee_id: str,
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: int | None = Query(None, description="按触发用户 id 过滤（可选）"),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """分页返回指定员工包的执行记录（任务摘要、耗时、状态等）。"""
    _ = _admin_user
    eid = (employee_id or "").strip()
    if not eid:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    sf = get_session_factory()
    with sf() as session:
        q = session.query(EmployeeExecutionMetric).filter(
            EmployeeExecutionMetric.employee_id == eid
        )
        if user_id is not None and user_id > 0:
            q = q.filter(EmployeeExecutionMetric.user_id == int(user_id))

        total_cq = session.query(func.count(EmployeeExecutionMetric.id)).filter(
            EmployeeExecutionMetric.employee_id == eid
        )
        if user_id is not None and user_id > 0:
            total_cq = total_cq.filter(EmployeeExecutionMetric.user_id == int(user_id))
        total = int(total_cq.scalar() or 0)

        rows = q.order_by(EmployeeExecutionMetric.id.desc()).offset(offset).limit(limit).all()

        items = [
            {
                "id": r.id,
                "user_id": r.user_id,
                "task": _trunc(r.task, _TASK_MAX),
                "status": r.status or "",
                "duration_ms": float(r.duration_ms or 0.0),
                "llm_tokens": int(r.llm_tokens or 0),
                "error": _trunc(r.error, _ERROR_MAX),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    return {"items": items, "total": total, "limit": limit, "offset": offset}
