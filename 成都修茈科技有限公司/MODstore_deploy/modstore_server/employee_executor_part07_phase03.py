"""Employee execution transaction phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _execute_employee_phase_03(state):
    state["duration_ms"] = round((_facade().time.perf_counter() - state["t0"]) * 1000, 3)
    state["llm_tokens"] = (
        0 if state["direct_only"] else _facade()._extract_token_count(state["reasoning"])
    )
    state["handler_ok"] = _facade()._handlers_execution_ok(
        state["result"] if isinstance(state["result"], dict) else {}
    )
    burn_in_acceptance: _facade().Dict[str, _facade().Any] = {}
    if _facade()._flag_enabled(state["payload"].get("burn_in")):
        try:
            burn_in_deadline = float(state["payload"].get("burn_in_deadline_epoch") or 0)
        except (TypeError, ValueError):
            burn_in_deadline = 0.0
        if burn_in_deadline > 0 and _facade().time.time() > burn_in_deadline:
            burn_in_acceptance = {"passed": False, "reasons": ["orchestration_deadline_exceeded"]}
        else:
            try:
                from modstore_server.duty_workforce_burnin import validate_burn_in_execution_result

                burn_in_acceptance = validate_burn_in_execution_result(
                    {"result": state["result"] if isinstance(state["result"], dict) else {}}
                )
            except RECOVERABLE_ERRORS as exc:
                burn_in_acceptance = {
                    "passed": False,
                    "reasons": [f"acceptance_gate_error:{type(exc).__name__}"],
                }
        if isinstance(state["result"], dict):
            state["result"]["burn_in_acceptance"] = burn_in_acceptance
        if burn_in_acceptance.get("passed") is not True:
            state["handler_ok"] = False
    state["exec_status"] = (
        "success"
        if state["handler_ok"]
        else "burnin_rejected" if burn_in_acceptance else "handler_failed"
    )
    if state["handler_ok"]:
        metric_error = ""
    elif burn_in_acceptance:
        metric_error = "burn-in acceptance: " + ";".join(
            (str(item) for item in burn_in_acceptance.get("reasons") or [])
        )
    else:
        metric_error = _facade()._handler_failure_detail(
            state["result"] if isinstance(state["result"], dict) else {}
        )
    metric_failure_kind = ""
    _pg = state["result"].get("path_guard") if isinstance(state["result"], dict) else None
    if isinstance(_pg, dict) and _pg.get("checked") and (not _pg.get("ok")):
        state["exec_status"] = "blocked_by_path_guard"
        violations = _pg.get("violations") or []
        vstr = "; ".join(
            (
                f"{v.get('path', '')}({v.get('reason', '')})"
                for v in violations[:5]
                if isinstance(v, dict)
            )
        )
        metric_error = f"path_guard violations: {vstr}"[:500]
        metric_failure_kind = "path_guard_violation"
        state["handler_ok"] = False
    try:
        from modstore_server.employee_human_report import build_human_report

        _human_report = build_human_report(
            employee_id=state["employee_id"],
            task=state["task"],
            reasoning=state["reasoning"] if isinstance(state["reasoning"], dict) else {},
            result=state["result"] if isinstance(state["result"], dict) else {},
            duration_ms=state["duration_ms"],
            llm_tokens=state["llm_tokens"],
            exec_status=state["exec_status"],
            perceived=state["perceived"] if isinstance(state["perceived"], dict) else None,
            memory=state["memory"] if isinstance(state["memory"], dict) else None,
            cognition_error=(
                str(state["reasoning"].get("error") or "")
                if isinstance(state["reasoning"], dict)
                else ""
            ),
        )
        if isinstance(state["result"], dict):
            state["result"]["human_report"] = _human_report
    except RECOVERABLE_ERRORS as _hr_exc:
        _facade().logger.debug(
            "build_human_report failed employee_id=%s err=%s", state["employee_id"], _hr_exc
        )
    if not state["handler_ok"]:
        state["cog_err"] = (
            str(state["reasoning"].get("error") or "").strip()
            if isinstance(state["reasoning"], dict)
            else ""
        )
        cog_status = (
            state["reasoning"].get("status") if isinstance(state["reasoning"], dict) else None
        )
        metric_failure_kind = _facade().classify_failure_kind(
            state["cog_err"] or metric_error, cog_status
        )
        if state["cog_err"]:
            metric_error = f"{metric_error}; cognition_error={state['cog_err'][:500]}"
    state["session"].add(
        _facade().EmployeeExecutionMetric(
            user_id=_facade()._resolve_metric_user_id(state["session"], state["user_id"]),
            employee_id=state["employee_id"],
            task=_facade()._metric_task_preview(state["task"]),
            status=state["exec_status"],
            duration_ms=state["duration_ms"],
            llm_tokens=state["llm_tokens"],
            error=metric_error,
            failure_kind=metric_failure_kind,
        )
    )
    state["session"].commit()
    return (False, None)
