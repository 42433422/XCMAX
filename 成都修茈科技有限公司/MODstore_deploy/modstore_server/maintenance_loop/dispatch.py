"""Bounded employee retries; accepted asynchronous tasks are never duplicated."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from modstore_server import (
    employee_executor,
    self_maintenance_quality_gate,
    self_maintenance_remediation_prompts,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, para_client, results, review, store


def _loop_platform_bench_override() -> Optional[tuple]:
    """后台自维护/进化 loop 默认走平台派发：LLM 成本记平台密钥、不查/扣用户 ``llm_calls`` 配额。

    与 digest 产线一致——后台自治 loop 不该按「用户调用」计量。``_first_user_id()`` 返回的是
    第一个真实用户，挂到其月度配额上几小时就 ``403 配额不足: llm_calls``（生产实测疯跑 99.6%
    失败、进化引擎误把配额失败当 prompt 问题狂改的根因）。返回平台 bench (provider, model) 作为
    ``bench_llm_override`` → cognition ``use_platform_dispatch=True`` → 不经 require_llm_credit；
    ``user_id`` 仍透传给 RAG/指标。关闭（回退按用户配额）：``MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM=0``。
    """
    if not config._env_bool("MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM", True):
        return None
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        rp, rm = resolve_platform_bench_llm()
        if rp and rm:
            return (rp, rm)
    except RECOVERABLE_ERRORS:
        return None
    return None


def _execute_employee_task_with_retries(
    employee_id: str,
    task_text: str,
    input_data: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    retries = max(0, config._env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRIES", 2))
    delay_sec = max(
        1, config._env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRY_DELAY_SEC", 10)
    )
    attempts = retries + 1
    bench_override = _loop_platform_bench_override()
    result: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        device_wait = para_client._wait_for_para_device_online()
        if not device_wait.get("online"):
            config.logger.warning(
                "self-maintenance para device not online before dispatch attempt=%s/%s",
                attempt,
                attempts,
            )
        result = employee_executor.execute_employee_task(
            employee_id,
            task_text,
            input_data,
            user_id=user_id,
            bench_llm_override=bench_override,
        )
        if results._employee_result_ok(result):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        if attempt >= attempts or not results._is_transient_employee_dispatch_failure(
            result
        ):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        config.logger.warning(
            "self-maintenance employee step transient dispatch failure; retrying attempt=%s/%s",
            attempt,
            attempts,
        )
        time.sleep(delay_sec)
    result["self_maintenance_retry_attempts"] = attempts
    return result


def _run_step_with_inner_retries(
    *,
    employee_id: str,
    step_name: str,
    task_text: str,
    extra: Dict[str, Any],
    user_id: int,
    run_id: str,
) -> Tuple[
    Dict[str, Any],
    bool,
    str,
    Dict[str, Any],
    str,
    int,
    int,
]:
    """Run code fix retries or report protocol/infrastructure retries.

    Returns the final employee result plus retry counters. Intermediate attempts
    are recorded as ``phase=step_retry`` without polluting the final step list.
    """
    if step_name == "code":
        inner_max = max(
            1, config._env_int("MODSTORE_SELF_MAINTENANCE_CODE_FIX_RETRIES", 2) + 1
        )
        retry_kind = "code_fix"
    else:
        inner_max = max(
            1, config._env_int("MODSTORE_SELF_MAINTENANCE_MARKER_RETRIES", 2) + 1
        )
        retry_kind = "marker"
    marker = (
        config.STRUCTURED_REVIEW_MARKER
        if step_name == "review"
        else config.STRUCTURED_QA_MARKER
    )
    last_task_text = task_text
    result: Dict[str, Any] = {}
    ok = False
    failure_reason = ""
    para_meta: Dict[str, Any] = {}
    report_excerpt = ""
    code_fix_retry_rounds = 0
    marker_retry_rounds = 0
    for attempt in range(1, inner_max + 1):
        input_data = _base_para_input(extra)
        result = _execute_employee_task_with_retries(
            employee_id, last_task_text, input_data, user_id=user_id
        )
        ok = results._employee_result_ok(result)
        para_meta = results._extract_para_meta(result)
        report_excerpt = results._extract_report_excerpt(result)
        para_report_excerpt = para_client._fetch_para_task_report_excerpt(
            para_meta.get("task_id"), para_meta.get("subtask_id")
        )
        if para_report_excerpt:
            report_excerpt = (report_excerpt + "\n" + para_report_excerpt)[-10000:]
        failure_reason = (
            "" if ok else results._extract_failure_reason(result, para_meta)
        )
        is_final = attempt >= inner_max
        should_retry = False
        if not ok and (not is_final):
            if retry_kind == "code_fix" and (
                not results._is_accepted_para_wait_timeout(result)
            ):
                should_retry = True
        elif ok and retry_kind == "marker" and (not is_final):
            protocol_ok, protocol_reason = review._structured_protocol_ok(
                step_name, report_excerpt
            )
            if not protocol_ok:
                failure_reason = protocol_reason or "structured_protocol_invalid"
                should_retry = True
            elif step_name == "qa":
                qa_json = review._structured_report_from_step(
                    {"report_excerpt": report_excerpt}, config.STRUCTURED_QA_MARKER
                )
                if self_maintenance_quality_gate.qa_executor_infrastructure_unavailable(
                    qa_json
                ):
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
                "timestamp": config._iso(config._utc_now()),
            }
            store._append_ledger(trace_record)
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
            last_task_text = (
                self_maintenance_remediation_prompts.qa_executor_retry_prompt(
                    task_text, attempt, inner_max
                )
            )
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


def _base_para_input(
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "branch": os.environ.get("MODSTORE_PARA_BRANCH"),
        "device_id": os.environ.get("MODSTORE_PARA_DEVICE_ID"),
        "repo_url": os.environ.get("MODSTORE_PARA_REPO_URL"),
        "suppress_lifecycle_events": True,
        "wait_for_para": True,
        "wait_timeout_sec": config._env_int("MODSTORE_PARA_WAIT_TIMEOUT_SEC", 1800),
        "project_root": os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT")
        or "/root/XCMAX",
    }
    if extra:
        data.update(extra)
    return data
