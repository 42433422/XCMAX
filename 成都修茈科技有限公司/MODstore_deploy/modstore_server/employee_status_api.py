"""员工任务状态看板 API。

GET /api/ops/employee-status  — 聚合每个员工的最近执行状态、pending CR 数量、事件积压数。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func

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
    cutoff_7d = datetime.now(UTC) - timedelta(days=7)

    with sf() as session:
        employees = (
            session.query(CatalogItem)
            .filter(CatalogItem.artifact == "employee_pack")
            .order_by(CatalogItem.name.asc())
            .all()
        )

        if not employees:
            return []
        # Preserve the dashboard's existing latest-ten-in-seven-days window.
        # Rank once for the catalog instead of issuing two queries per employee.
        employee_ids = session.query(CatalogItem.pkg_id).filter(
            CatalogItem.artifact == "employee_pack"
        )
        metric = EmployeeExecutionMetric
        ranked = (
            session.query(
                metric.employee_id,
                metric.id,
                metric.status,
                func.substr(metric.task, 1, 200).label("task"),
                metric.created_at,
                metric.duration_ms,
                func.row_number()
                .over(
                    partition_by=metric.employee_id,
                    order_by=(metric.created_at.desc(), metric.id.desc()),
                )
                .label("position"),
            )
            .filter(
                metric.employee_id.in_(employee_ids),
                metric.created_at >= cutoff_7d,
            )
            .subquery()
        )
        metrics_by_employee = defaultdict(list)
        for item in (
            session.query(ranked).filter(ranked.c.position <= 10).order_by(ranked.c.position)
        ):
            metrics_by_employee[item.employee_id].append(item)
        pending_by_employee = dict(
            session.query(EmployeeChangeRequest.source_employee_id, func.count())
            .filter(
                EmployeeChangeRequest.source_employee_id.in_(employee_ids),
                EmployeeChangeRequest.status == "pending",
            )
            .group_by(EmployeeChangeRequest.source_employee_id)
            .all()
        )
        result: List[Dict[str, Any]] = []
        for emp in employees:
            eid = str(emp.pkg_id or "")
            recent_metrics = metrics_by_employee[eid]

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

            result.append(
                {
                    "employee_id": eid,
                    "name": str(emp.name or ""),
                    "description": str(emp.description or "")[:200],
                    "last_execution": last_exec,
                    "runs_7d": total_runs_7d,
                    "success_7d": success_runs_7d,
                    "pending_change_requests": int(pending_by_employee.get(eid, 0)),
                    "health": (
                        "healthy"
                        if total_runs_7d == 0
                        else ("healthy" if success_runs_7d / total_runs_7d >= 0.8 else "degraded")
                    ),
                }
            )
        return result


@router.get("/employee-status", summary="员工任务状态看板")
def get_employee_status(
    user: User = Depends(_get_current_user),
):
    """聚合所有员工的最近执行状态、pending ChangeRequest 数量和健康指标。"""
    data = _employee_status_summary()
    return {"ok": True, "employees": data, "total": len(data)}
