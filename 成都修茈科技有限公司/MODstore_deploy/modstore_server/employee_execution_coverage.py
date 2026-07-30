"""Employee receipt coverage with explicit capability/production semantics."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_

from modstore_server.models import EmployeeExecutionMetric, get_session_factory

_BURN_IN_TASK_PREFIX = "[duty-burn-in:"
_SUCCESS_STATUSES = ("success", "completed")


def _roster_receipts(rows: list[tuple[Any, Any]], planned: set[str]) -> list[dict[str, str]]:
    receipts = [
        {"employee_id": str(employee_id), "latest_success_at": created_at.isoformat()}
        for employee_id, created_at in rows
        if str(employee_id or "") in planned and created_at is not None
    ]
    receipts.sort(key=lambda item: item["employee_id"])
    return receipts


def build_execution_coverage(
    *,
    planned: set[str],
    assignment: dict[str, Any],
    window_hours: int,
    production_window_hours: int,
) -> dict[str, Any]:
    """Separate safe burn-in capability from non-burn-in production duty."""

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=window_hours)
    production_cutoff = now - timedelta(hours=production_window_hours)
    sf = get_session_factory()
    with sf() as session:
        capability_rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.max(EmployeeExecutionMetric.created_at),
            )
            .filter(
                EmployeeExecutionMetric.status.in_(_SUCCESS_STATUSES),
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .all()
        )
        burn_in_rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.max(EmployeeExecutionMetric.created_at),
            )
            .filter(
                EmployeeExecutionMetric.status.in_(_SUCCESS_STATUSES),
                EmployeeExecutionMetric.created_at >= cutoff,
                EmployeeExecutionMetric.task.like(f"{_BURN_IN_TASK_PREFIX}%"),
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .all()
        )
        production_rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.max(EmployeeExecutionMetric.created_at),
            )
            .filter(
                EmployeeExecutionMetric.status.in_(_SUCCESS_STATUSES),
                EmployeeExecutionMetric.created_at >= production_cutoff,
                or_(
                    EmployeeExecutionMetric.task.is_(None),
                    ~EmployeeExecutionMetric.task.like(f"{_BURN_IN_TASK_PREFIX}%"),
                ),
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .all()
        )

    receipts = _roster_receipts(capability_rows, planned)
    burn_in_receipts = _roster_receipts(burn_in_rows, planned)
    production_receipts = _roster_receipts(production_rows, planned)
    planned_count = len(planned)
    assigned_required = math.ceil(planned_count * 0.95) if planned_count else 0
    proven_required = math.ceil(planned_count * 0.80) if planned_count else 0

    def _ready(proven_count: int) -> bool:
        return bool(planned_count) and all(
            (
                int(assignment.get("assigned_count") or 0) >= assigned_required,
                proven_count >= proven_required,
                int(assignment.get("shell_count") or 0) == 0,
            )
        )

    from modstore_server.services.llm import resolve_platform_bench_llm

    bench_provider, bench_model = resolve_platform_bench_llm()
    return {
        "ok": True,
        "window_hours": window_hours,
        "cutoff": cutoff.isoformat(),
        "production_window_hours": production_window_hours,
        "production_cutoff": production_cutoff.isoformat(),
        "planned_count": planned_count,
        **assignment,
        "proven_count": len(receipts),
        "burn_in_proven_count": len(burn_in_receipts),
        "production_proven_count": len(production_receipts),
        "assignment_required_count": assigned_required,
        "proof_required_count": proven_required,
        "production_proof_required_count": proven_required,
        "assignment_ratio": (
            round(int(assignment.get("assigned_count") or 0) / planned_count, 4)
            if planned_count
            else 0.0
        ),
        "proof_ratio": round(len(receipts) / planned_count, 4) if planned_count else 0.0,
        "burn_in_proof_ratio": (
            round(len(burn_in_receipts) / planned_count, 4) if planned_count else 0.0
        ),
        "production_proof_ratio": (
            round(len(production_receipts) / planned_count, 4) if planned_count else 0.0
        ),
        "workforce_ready": _ready(len(receipts)),
        "production_workforce_ready": _ready(len(production_receipts)),
        "receipt_policy": {
            "capability": "successful roster receipt within window_hours; may include burn-in",
            "burn_in": f"task starts with {_BURN_IN_TASK_PREFIX}",
            "production": "successful roster receipt excluding duty burn-in task markers",
        },
        "employee_ids": [item["employee_id"] for item in receipts],
        "receipts": receipts,
        "burn_in_employee_ids": [item["employee_id"] for item in burn_in_receipts],
        "burn_in_receipts": burn_in_receipts,
        "production_employee_ids": [item["employee_id"] for item in production_receipts],
        "production_receipts": production_receipts,
        "platform_llm": {
            "configured": bool(bench_provider and bench_model),
            "provider": bench_provider,
            "model": bench_model,
        },
    }


__all__ = ["build_execution_coverage"]
