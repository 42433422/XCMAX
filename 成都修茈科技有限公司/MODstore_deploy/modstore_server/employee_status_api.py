"""员工任务状态看板 API。

GET /api/ops/employee-status  — 聚合每个员工的最近执行状态、pending CR 数量、事件积压数。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from modstore_server.api.deps import _get_current_user
from modstore_server.models import (
    CatalogItem,
    EmployeeChangeRequest,
    EmployeeExecutionMetric,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["ops"])


def _employee_status_summary() -> List[Dict[str, Any]]:
    sf = get_session_factory()
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)

    with sf() as session:
        employees = (
            session.query(CatalogItem)
            .filter(CatalogItem.artifact == "employee_pack")
            .order_by(CatalogItem.name.asc())
            .all()
        )

        result: List[Dict[str, Any]] = []
        for emp in employees:
            eid = str(emp.pkg_id or "")

            # 最近执行记录
            recent_metrics = (
                session.query(EmployeeExecutionMetric)
                .filter(
                    EmployeeExecutionMetric.employee_id == eid,
                    EmployeeExecutionMetric.created_at >= cutoff_7d,
                )
                .order_by(EmployeeExecutionMetric.created_at.desc())
                .limit(10)
                .all()
            )

            last_exec: Optional[Dict[str, Any]] = None
            if recent_metrics:
                m = recent_metrics[0]
                last_exec = {
                    "id": int(m.id),
                    "status": str(m.status or ""),
                    "task": str(m.task or "")[:200],
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "duration_ms": int(m.duration_ms or 0),
                }

            total_runs_7d = len(recent_metrics)
            success_runs_7d = sum(1 for m in recent_metrics if (m.status or "") == "success")

            # pending ChangeRequest 数量
            pending_cr_count = (
                session.query(EmployeeChangeRequest)
                .filter(
                    EmployeeChangeRequest.source_employee_id == eid,
                    EmployeeChangeRequest.status == "pending",
                )
                .count()
            )

            result.append(
                {
                    "employee_id": eid,
                    "name": str(emp.name or ""),
                    "description": str(emp.description or "")[:200],
                    "last_execution": last_exec,
                    "runs_7d": total_runs_7d,
                    "success_7d": success_runs_7d,
                    "pending_change_requests": int(pending_cr_count),
                    "health": (
                        "healthy"
                        if total_runs_7d == 0
                        else ("healthy" if success_runs_7d / total_runs_7d >= 0.8 else "degraded")
                    ),
                }
            )
        return result


@router.get("/employee-status", summary="员工任务状态看板")
async def get_employee_status(
    user: User = Depends(_get_current_user),
):
    """聚合所有员工的最近执行状态、pending ChangeRequest 数量和健康指标。"""
    data = _employee_status_summary()
    return {"ok": True, "employees": data, "total": len(data)}
