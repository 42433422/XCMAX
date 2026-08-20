# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _execute_employee_task_with_retries(
    employee_id: str,
    task_text: str,
    input_data: _facade().Dict[str, _facade().Any],
    *,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    retries = max(0, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRIES", 2))
    delay_sec = max(1, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRY_DELAY_SEC", 10))
    attempts = retries + 1
    bench_override = _facade()._loop_platform_bench_override()
    result: _facade().Dict[str, _facade().Any] = {}
    for attempt in range(1, attempts + 1):
        device_wait = _facade()._wait_for_para_device_online()
        if not device_wait.get("online"):
            _facade().logger.warning(
                "self-maintenance para device not online before dispatch employee=%s attempt=%s/%s detail=%s",
                employee_id,
                attempt,
                attempts,
                device_wait,
            )
        result = _facade().execute_employee_task(
            employee_id,
            task_text,
            input_data,
            user_id=user_id,
            bench_llm_override=bench_override,
        )
        if _facade()._employee_result_ok(result):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        if attempt >= attempts or not _facade()._is_transient_employee_dispatch_failure(result):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        _facade().logger.warning(
            "self-maintenance employee step transient dispatch failure; retrying employee=%s attempt=%s/%s",
            employee_id,
            attempt,
            attempts,
        )
        _facade().time.sleep(delay_sec)
    result["self_maintenance_retry_attempts"] = attempts
    return result


def _run_step_with_inner_retries(
    *,
    employee_id: str,
    step_name: str,
    task_text: str,
    extra: _facade().Dict[str, _facade().Any],
    user_id: int,
    run_id: str,
) -> _facade().Tuple[
    _facade().Dict[str, _facade().Any],
    bool,
    str,
    _facade().Dict[str, _facade().Any],
    str,
    int,
    int,
]:
    """Run code fix retries or report protocol/infrastructure retries.

    Returns the final employee result plus retry counters. Intermediate attempts
    are recorded as ``phase=step_retry`` without polluting the final step list.
    """
    if step_name == "code":
        inner_max = max(1, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_CODE_FIX_RETRIES", 2) + 1)
        retry_kind = "code_fix"
    else:
        inner_max = max(1, _facade()._env_int("MODSTORE_SELF_MAINTENANCE_MARKER_RETRIES", 2) + 1)
        retry_kind = "marker"
    marker = (
        _facade().STRUCTURED_REVIEW_MARKER
        if step_name == "review"
        else _facade().STRUCTURED_QA_MARKER
    )
    last_task_text = task_text
    result: _facade().Dict[str, _facade().Any] = {}
    ok = False
    failure_reason = ""
    para_meta: _facade().Dict[str, _facade().Any] = {}
    report_excerpt = ""
    code_fix_retry_rounds = 0
    marker_retry_rounds = 0
    for attempt in range(1, inner_max + 1):
        input_data = _facade()._base_para_input(extra)
        result = _facade()._execute_employee_task_with_retries(
            employee_id, last_task_text, input_data, user_id=user_id
        )
        ok = _facade()._employee_result_ok(result)
        para_meta = _facade()._extract_para_meta(result)
        report_excerpt = _facade()._extract_report_excerpt(result)
        para_report_excerpt = _facade()._fetch_para_task_report_excerpt(
            para_meta.get("task_id"), para_meta.get("subtask_id")
        )
        if para_report_excerpt:
            report_excerpt = (report_excerpt + "\n" + para_report_excerpt)[-10000:]
        failure_reason = "" if ok else _facade()._extract_failure_reason(result, para_meta)
        is_final = attempt >= inner_max
        should_retry = False
        if not ok and (not is_final):
            if retry_kind == "code_fix" and (not _facade()._is_accepted_para_wait_timeout(result)):
                should_retry = True
        elif ok and retry_kind == "marker" and (not is_final):
            protocol_ok, protocol_reason = _facade()._structured_protocol_ok(
                step_name, report_excerpt
            )
            if not protocol_ok:
                failure_reason = protocol_reason or "structured_protocol_invalid"
                should_retry = True
            elif step_name == "qa":
                qa_json = _facade()._structured_report_from_step(
                    {"report_excerpt": report_excerpt}, _facade().STRUCTURED_QA_MARKER
                )
                if _facade()._qa_executor_infrastructure_unavailable(qa_json):
                    failure_reason = "structured_qa_executor_unavailable"
                    should_retry = True
        if not is_final and should_retry:
            trace_record = {
                "employee_id": employee_id,
                "error": failure_reason,
                "inner_attempt": attempt,
                "ok": ok,
                "para": para_meta,
                "phase": "step_retry",
                "report_excerpt": report_excerpt,
                "retry_attempts": result.get("self_maintenance_retry_attempts"),
                "run_id": run_id,
                "status": "success" if ok else "failed",
                "step": step_name,
                "timestamp": _facade()._iso(_facade()._utc_now()),
            }
            _facade()._append_ledger(trace_record)
        if not should_retry:
            break
        if retry_kind == "code_fix":
            last_task_text = (
                task_text
                + f"\n\n=== PREVIOUS ATTEMPT FAILED (inner round {attempt}/{inner_max - 1}) ===\n"
                + f"failure_reason: {failure_reason}\n"
                + "MANDATORY: Address the failure reason above. Re-run the failing "
                + "command locally, fix until it passes, then deliver again. Do not "
                + "report completion unless the previously failing command now exits 0."
            )
            code_fix_retry_rounds = attempt
        elif failure_reason == "structured_qa_executor_unavailable":
            last_task_text = _facade().qa_executor_retry_prompt(task_text, attempt, inner_max)
            marker_retry_rounds = attempt
        else:
            last_task_text = (
                task_text
                + f"\n\n=== PREVIOUS REPORT PROTOCOL REJECTED (inner round {attempt}/{inner_max - 1}) ===\n"
                + f"required_marker: {marker}\n"
                + f"protocol_error: {failure_reason or 'missing_or_invalid_structured_json'}\n"
                + "Re-emit exactly one JSON object after the marker. "
                + "For review, dimensions.security / business_logic / performance are mandatory "
                + "with status pass|fail|n/a and findings lists. "
                + "Do not summarize — output the full protocol JSON."
            )
            marker_retry_rounds = attempt
    return (
        result,
        ok,
        failure_reason,
        para_meta,
        report_excerpt,
        code_fix_retry_rounds,
        marker_retry_rounds,
    )
