"""Tracked execution boundary for one scheduled employee duty."""

from __future__ import annotations

import importlib
from typing import Any


def _require_success(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("employee_cron_invalid_result")
    status = str(result.get("status") or "").strip().lower()
    if (
        result.get("ok") is False
        or result.get("handler_failed")
        or result.get("blocked_by_risk_gate")
        or status in {"failed", "handler_failed", "blocked_by_risk_gate"}
    ):
        raise RuntimeError(f"employee_cron_unsuccessful:{status or 'execution_failed'}")
    return result


def execute_employee_cron_duty(
    *,
    employee_id: str,
    task_brief: str,
    work_contract: dict[str, Any],
    schedule_source: str,
    project_root: str,
) -> dict[str, Any]:
    """Execute reviewed low/medium duty and write a success/failure runtime receipt."""

    employee_executor = importlib.import_module("modstore_server.employee_executor")
    from modstore_server.scheduler_runtime import track_job_run
    from modstore_server.services.llm import resolve_platform_bench_llm

    risk_level = str(work_contract.get("risk_level") or "medium").strip().lower()
    bench_provider, bench_model = resolve_platform_bench_llm()
    with track_job_run(f"employee_cron:{employee_id}"):
        if employee_id == "retention-officer":
            from modstore_server.file_retention_janitor import run_retention_janitor

            retention = run_retention_janitor(
                dry_run=True,
                notification_dry_run=True,
            )
            return _require_success(
                {
                    **retention,
                    "handler": "file_retention_janitor",
                    "summary": str(retention.get("report_md") or "")[:4000],
                    "read_only": True,
                    "side_effects": ["retention_audit_receipt"],
                }
            )
        input_data = {
            "trigger": "schedule",
            "schedule_source": schedule_source,
            "work_contract": {
                "schema": "xcagi.duty_employee_work_contracts/v1",
                "mode": str(work_contract.get("mode") or "execute"),
                "risk_level": risk_level,
                "acceptance": list(work_contract.get("acceptance") or []),
            },
            # The reviewed contract approves only low/medium unattended
            # duty. High-risk actions retain the existing approval/veto.
            "allow_medium_risk": risk_level in {"low", "medium"},
            "non_blocking_human_questions": True,
            "allow_high_risk_real_run": False,
            **({"project_root": project_root} if project_root else {}),
        }
        from modstore_server.employee_duty_input_resolver import (
            resolve_employee_duty_input,
        )

        resolved_input = resolve_employee_duty_input(employee_id)
        if resolved_input is not None:
            input_data.update(dict(resolved_input.get("input_data") or {}))
        result = _require_success(
            employee_executor.execute_employee_task(
                employee_id,
                task_brief,
                input_data,
                user_id=0,
                # Scheduled duty is a platform expense, independent of stale
                # provider/model names in an old employee manifest.
                bench_llm_override=(
                    (bench_provider, bench_model) if bench_provider and bench_model else None
                ),
            )
        )
        if resolved_input is not None:
            result["duty_input_receipt"] = dict(resolved_input.get("receipt") or {})
        return result


__all__ = ["execute_employee_cron_duty"]
