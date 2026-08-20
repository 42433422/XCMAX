# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.employee_executor_part07_phase01 import _execute_employee_phase_01
from modstore_server.employee_executor_part07_phase02 import _execute_employee_phase_02
from modstore_server.employee_executor_part07_phase03 import _execute_employee_phase_03
from modstore_server.employee_executor_part07_phase04 import _execute_employee_phase_04
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def execute_employee_task(
    employee_id: str,
    task: str,
    input_data: _facade().Dict[str, _facade().Any] = None,
    user_id: int = 0,
    *,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    t0 = _facade().time.perf_counter()
    payload = dict(input_data or {})
    payload.pop("_trusted_duty_contract_execution", None)
    detail_log = _facade()._executor_detail_log_enabled()
    recovery_meta: _facade().Dict[str, _facade().Any] = {}
    _facade().logger.info(
        "employee_execute_start employee_id=%s user_id=%s task_len=%s",
        employee_id,
        user_id,
        len(task or ""),
    )
    sem = _facade()._get_executor_semaphore()
    if sem:
        sem.acquire()
    try:
        sf = _facade().get_session_factory()
        with sf() as session:
            try:
                state = {
                    "detail_log": detail_log,
                    "bench_llm_override": bench_llm_override,
                    "employee_id": employee_id,
                    "input_data": input_data,
                    "payload": payload,
                    "recovery_meta": recovery_meta,
                    "session": session,
                    "t0": t0,
                    "task": task,
                    "user_id": user_id,
                }
                phase_done, phase_result = _execute_employee_phase_01(state)
                if phase_done:
                    return phase_result
                phase_done, phase_result = _execute_employee_phase_02(state)
                if phase_done:
                    return phase_result
                phase_done, phase_result = _execute_employee_phase_03(state)
                if phase_done:
                    return phase_result
                phase_done, phase_result = _execute_employee_phase_04(state)
                if phase_done:
                    return phase_result
            except RECOVERABLE_ERRORS as e:
                state["duration_ms"] = round(
                    (_facade().time.perf_counter() - state["t0"]) * 1000, 3
                )
                err_text = str(e)
                failure_kind = _facade().classify_failure_kind(err_text)
                state["session"].add(
                    _facade().EmployeeExecutionMetric(
                        user_id=_facade()._resolve_metric_user_id(
                            state["session"], state["user_id"]
                        ),
                        employee_id=state["employee_id"],
                        task=_facade()._metric_task_preview(state["task"]),
                        status="failed",
                        duration_ms=state["duration_ms"],
                        llm_tokens=0,
                        error=err_text,
                        failure_kind=failure_kind,
                    )
                )
                state["session"].commit()
                if failure_kind == _facade().FAILURE_KIND_QUOTA:
                    _facade().logger.warning(
                        "employee_execute_finish employee_id=%s user_id=%s status=failed failure_kind=quota duration_ms=%s error=%s (配额/计费失败，非 prompt 问题，不应触发自进化 prompt 重写)",
                        state["employee_id"],
                        state["user_id"],
                        state["duration_ms"],
                        err_text[:400],
                    )
                else:
                    _facade().logger.info(
                        "employee_execute_finish employee_id=%s user_id=%s status=failed failure_kind=%s duration_ms=%s error=%s",
                        state["employee_id"],
                        state["user_id"],
                        failure_kind or "unknown",
                        state["duration_ms"],
                        err_text[:400],
                    )
                if not _facade()._flag_enabled(state["payload"].get("suppress_lifecycle_events")):
                    try:
                        from modstore_server.notification_service import (
                            notify_employee_execution_done,
                        )

                        if state["user_id"]:
                            notify_employee_execution_done(
                                state["user_id"], state["employee_id"], state["task"], "failed"
                            )
                    except RECOVERABLE_ERRORS:
                        pass
                try:
                    from modstore_server.models_project_context import record_execution_outcome

                    record_execution_outcome(
                        employee_id=state["employee_id"],
                        task=state["task"],
                        input_data=state["payload"] if isinstance(state["payload"], dict) else {},
                        outcome={"error": str(e)},
                        status="failed",
                    )
                except RECOVERABLE_ERRORS:
                    pass
                state["suppress_lifecycle_events"] = isinstance(state["payload"], dict) and str(
                    state["payload"].get("suppress_lifecycle_events") or ""
                ).strip().lower() in {"1", "true", "yes", "on"}
                if not state["suppress_lifecycle_events"]:
                    try:
                        from modstore_server.services.change_signal import emit_task_lifecycle_event

                        emit_task_lifecycle_event(
                            state["employee_id"], state["task"], status="failed", error=str(e)
                        )
                    except RECOVERABLE_ERRORS:
                        pass
                raise
    finally:
        if sem:
            sem.release()


def get_employee_status(employee_id: str) -> _facade().Dict[str, _facade().Any]:
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().EmployeeExecutionMetric)
            .filter(_facade().EmployeeExecutionMetric.employee_id == employee_id)
            .order_by(_facade().EmployeeExecutionMetric.id.desc())
            .limit(100)
            .all()
        )
        ok = len([r for r in rows if r.status == "success"])
        return {
            "status": "active",
            "employee_id": employee_id,
            "execution_stats": {
                "total_executions": len(rows),
                "success_count": ok,
                "failed_count": len(rows) - ok,
                "success_rate": ok / len(rows) * 100.0 if rows else 0,
            },
            "last_execution": rows[0].created_at.isoformat() if rows else None,
        }
