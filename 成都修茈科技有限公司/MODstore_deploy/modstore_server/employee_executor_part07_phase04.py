"""Employee execution transaction phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _execute_employee_phase_04(state):
    if not state["handler_ok"]:
        state["suppress_lifecycle_events"] = isinstance(state["payload"], dict) and str(
            state["payload"].get("suppress_lifecycle_events") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not state["suppress_lifecycle_events"]:
            try:
                from modstore_server.notification_service import notify_employee_execution_done

                notify_employee_execution_done(
                    state["user_id"], state["employee_id"], state["task"], state["exec_status"]
                )
            except RECOVERABLE_ERRORS:
                pass
        return (
            True,
            {
                "employee_id": state["employee_id"],
                "pack": {"id": state["pack"]["pack_id"], "version": state["pack"]["version"]},
                "duration_ms": state["duration_ms"],
                "result": state["result"],
                "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                "llm_tokens": state["llm_tokens"],
                "handler_failed": True,
                "runtime_policy": state["runtime_policy"] or None,
            },
        )
    if state["recovery_meta"].get("recovered"):
        try:
            from modstore_server.services.change_signal import emit_execution_recovery_event

            emit_execution_recovery_event(
                state["employee_id"],
                state["task"],
                recovery_action=str(
                    state["recovery_meta"].get("recovery_action") or "cognition_retry"
                ),
                success=True,
                original_error=str(state["recovery_meta"].get("original_error") or ""),
                attempts=int(state["recovery_meta"].get("attempts") or 0),
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.debug("emit_execution_recovery_event failed", exc_info=True)
    if _facade()._flag_enabled(state["payload"].get("suppress_change_requests")):
        cr_bridge = {
            "ok": True,
            "suppressed": True,
            "reason": "read_only_burn_in",
            "change_request_ids": [],
        }
    else:
        cr_bridge = _facade()._auto_wrap_execution_result_to_change_requests(
            state["employee_id"],
            state["user_id"],
            state["payload"] if isinstance(state["payload"], dict) else {},
            state["result"] if isinstance(state["result"], dict) else {},
        )
    if isinstance(state["result"], dict):
        state["result"]["change_request_bridge"] = cr_bridge
        cids = (
            cr_bridge.get("change_request_ids")
            if isinstance(cr_bridge.get("change_request_ids"), list)
            else []
        )
        if cids:
            normalized_cids: _facade().List[int] = []
            for x in cids:
                try:
                    _cid = int(x or 0)
                except (TypeError, ValueError):
                    _cid = 0
                if _cid > 0:
                    normalized_cids.append(_cid)
            state["result"]["change_request_ids"] = normalized_cids
    if not _facade()._flag_enabled(state["payload"].get("suppress_lifecycle_events")):
        try:
            from modstore_server.notification_service import notify_employee_execution_done

            notify_employee_execution_done(
                state["user_id"], state["employee_id"], state["task"], "success"
            )
        except RECOVERABLE_ERRORS:
            pass
    try:
        from modstore_server.models_project_context import record_execution_outcome

        record_execution_outcome(
            employee_id=state["employee_id"],
            task=state["task"],
            input_data=state["payload"] if isinstance(state["payload"], dict) else {},
            outcome=state["result"] if isinstance(state["result"], dict) else {},
            status="success",
        )
    except RECOVERABLE_ERRORS:
        pass
    state["suppress_lifecycle_events"] = isinstance(state["payload"], dict) and str(
        state["payload"].get("suppress_lifecycle_events") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not state["suppress_lifecycle_events"]:
        try:
            from modstore_server.services.change_signal import (
                emit_signal_on_execution_complete,
                emit_task_lifecycle_event,
            )

            emit_signal_on_execution_complete(
                state["employee_id"],
                state["task"],
                {"status": "success", "result": state["result"]},
            )
            emit_task_lifecycle_event(
                state["employee_id"],
                state["task"],
                status="success",
                result={"result": state["result"]},
            )
        except RECOVERABLE_ERRORS:
            pass
    state["cog_err"] = ""
    if isinstance(state["reasoning"], dict):
        state["cog_err"] = str(state["reasoning"].get("error") or "").strip()
    rex = ""
    if isinstance(state["reasoning"], dict):
        rex = str(state["reasoning"].get("reasoning") or "").strip()[:4000]
    cog_attempts = (
        int(state["recovery_meta"].get("attempts") or 1)
        if state["recovery_meta"].get("recovered")
        else 1
    )
    if state["detail_log"]:
        _facade().logger.info(
            "employee_execute_finish employee_id=%s user_id=%s status=success duration_ms=%s llm_tokens=%s cognition_attempts=%s handlers=%s",
            state["employee_id"],
            state["user_id"],
            state["duration_ms"],
            state["llm_tokens"],
            cog_attempts,
            ",".join(state["handler_list"]),
        )
    else:
        _facade().logger.info(
            "employee_execute_finish employee_id=%s user_id=%s status=success duration_ms=%s llm_tokens=%s cognition_attempts=%s",
            state["employee_id"],
            state["user_id"],
            state["duration_ms"],
            state["llm_tokens"],
            cog_attempts,
        )
    return (
        True,
        {
            "employee_id": state["employee_id"],
            "pack": {"id": state["pack"]["pack_id"], "version": state["pack"]["version"]},
            "duration_ms": state["duration_ms"],
            "result": state["result"],
            "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            "llm_tokens": state["llm_tokens"],
            "runtime_policy": state["runtime_policy"] or None,
            "cognition_error": state["cog_err"] or None,
            "cognition_help": (
                "LLM 未返回有效内容。请检查 API Key、模型名、网络与平台余额。"
                if state["cog_err"]
                else None
            ),
            "reasoning_excerpt": rex or None,
            "change_request_ids": (
                state["result"].get("change_request_ids")
                if isinstance(state["result"], dict)
                and isinstance(state["result"].get("change_request_ids"), list)
                else []
            ),
        },
    )
    return (False, None)
