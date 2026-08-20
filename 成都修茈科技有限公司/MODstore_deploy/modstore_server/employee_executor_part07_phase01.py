"""Employee execution transaction phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _execute_employee_phase_01(state):
    state["pack"] = _facade().load_employee_pack_resolved(state["session"], state["employee_id"])
    state["manifest"], burn_in_eligibility = (state["pack"].get("manifest") or {}, {})
    reviewed_contract, reviewed_manifest = _facade()._trusted_system_duty_contract_execution(
        state["employee_id"], state["payload"], user_id=state["user_id"]
    )
    if reviewed_contract and reviewed_manifest:
        state["manifest"] = reviewed_manifest
        state["payload"]["_trusted_duty_contract_execution"] = True
        state["payload"]["work_contract"] = {
            "schema": "xcagi.duty_employee_work_contracts/v1",
            "employee_id": state["employee_id"],
            "mission": str(reviewed_contract.get("mission") or ""),
            "mode": str(reviewed_contract.get("mode") or ""),
            "risk_level": str(reviewed_contract.get("risk_level") or ""),
            "acceptance": list(reviewed_contract.get("acceptance") or []),
        }
    elif _facade()._flag_enabled(state["payload"].get("burn_in")) and _facade()._flag_enabled(
        state["payload"].get("burn_in_read_only")
    ):
        from modstore_server.duty_workforce_burnin import assess_burn_in_eligibility
        from modstore_server.duty_workforce_contracts import (
            load_reviewed_duty_manifest,
            workforce_contract_map,
        )

        state["manifest"] = load_reviewed_duty_manifest(state["employee_id"])
        reviewed_contract = workforce_contract_map().get(state["employee_id"]) or {}
        burn_in_eligibility = assess_burn_in_eligibility(
            state["employee_id"], reviewed_contract, state["manifest"]
        )
        if burn_in_eligibility.get("eligible") is not True:
            raise RuntimeError(
                "duty burn-in eligibility rejected: "
                + str(burn_in_eligibility.get("reason") or "unknown")
            )
        state["payload"]["work_contract"] = {
            "schema": "xcagi.duty_employee_work_contracts/v1",
            "employee_id": state["employee_id"],
            "mission": str(reviewed_contract.get("mission") or ""),
            "mode": str(reviewed_contract.get("mode") or ""),
            "risk_level": str(reviewed_contract.get("risk_level") or ""),
            "acceptance": list(reviewed_contract.get("acceptance") or []),
        }
    state["config"] = _facade().parse_employee_config_v2(state["manifest"])
    try:
        from modstore_server.employee_runtime_policy import apply_policy_to_config

        state["config"], state["runtime_policy"] = apply_policy_to_config(
            state["employee_id"], state["config"]
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug(
            "employee runtime policy apply failed employee_id=%s",
            state["employee_id"],
            exc_info=True,
        )
        state["runtime_policy"] = {}
    state["config"] = _facade().bind_reviewed_burn_in_handlers(state["config"], burn_in_eligibility)
    actions_section = state["config"].get("actions") or {}
    actions_inner = (
        actions_section.get("actions")
        if isinstance(actions_section.get("actions"), dict)
        else actions_section
    )
    state["handler_list"] = list((actions_inner or {}).get("handlers") or [])
    gate = _facade()._evaluate_employee_risk_gate(
        state["employee_id"], state["manifest"], state["handler_list"], state["payload"]
    )
    if not gate.get("ok"):
        state["duration_ms"] = round((_facade().time.perf_counter() - state["t0"]) * 1000, 3)
        state["session"].add(
            _facade().EmployeeExecutionMetric(
                user_id=_facade()._resolve_metric_user_id(state["session"], state["user_id"]),
                employee_id=state["employee_id"],
                task=_facade()._metric_task_preview(state["task"]),
                status="blocked_by_risk_gate",
                duration_ms=state["duration_ms"],
                llm_tokens=0,
            )
        )
        state["session"].commit()
        _facade().logger.info(
            "employee_execute_finish employee_id=%s user_id=%s status=blocked_by_risk_gate duration_ms=%s",
            state["employee_id"],
            state["user_id"],
            state["duration_ms"],
        )
        return (
            True,
            {
                "employee_id": state["employee_id"],
                "pack": {"id": state["pack"]["pack_id"], "version": state["pack"]["version"]},
                "duration_ms": state["duration_ms"],
                "result": {
                    "task": state["task"],
                    "handlers": state["handler_list"],
                    "outputs": [],
                    "summary": "blocked by risk middleware",
                    "risk_gate": gate,
                },
                "executed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                "llm_tokens": 0,
                "blocked_by_risk_gate": True,
                "runtime_policy": state["runtime_policy"] or None,
                "risk_level": gate.get("risk_level"),
            },
        )
    ctx = _facade().build_employee_context(state["employee_id"], state["payload"])
    state["perceived"] = _facade()._perception_real(
        state["config"].get("perception", {}), state["payload"], state["session"], state["user_id"]
    )
    try:
        from modstore_server.employee_perception_enricher import enrich_perception

        state["_project_root"] = (
            str(state["payload"].get("project_root") or "").strip()
            if isinstance(state["payload"], dict)
            else ""
        ) or _facade().os.environ.get("MODSTORE_REPO_ROOT", "")
        enrich_perception(
            employee_id=state["employee_id"],
            perceived=state["perceived"] if isinstance(state["perceived"], dict) else {},
            config=state["config"],
            session=state["session"],
            project_root=_facade().Path(state["_project_root"]) if state["_project_root"] else None,
            manifest=state["manifest"] if isinstance(state["manifest"], dict) else None,
        )
    except RECOVERABLE_ERRORS as _pe_exc:
        _facade().logger.debug(
            "perception_enricher failed employee_id=%s err=%s", state["employee_id"], _pe_exc
        )
    try:
        from modstore_server.employee_task_classifier import enrich_perception_with_classification

        enrich_perception_with_classification(
            employee_id=state["employee_id"],
            task=str(state["task"] or ""),
            perceived=state["perceived"] if isinstance(state["perceived"], dict) else {},
        )
    except RECOVERABLE_ERRORS as _tc_exc:
        _facade().logger.debug(
            "task_classifier failed employee_id=%s err=%s", state["employee_id"], _tc_exc
        )
    file_path_fast = (
        isinstance(state["payload"], dict)
        and str(state["payload"].get("file_path") or state["payload"].get("path") or "").strip()
    )
    state["direct_only"] = state["handler_list"] == ["direct_python"] and bool(
        file_path_fast
        or _facade()._deterministic_direct_input_ready(
            actions_inner if isinstance(actions_inner, dict) else {},
            state["payload"] if isinstance(state["payload"], dict) else {},
        )
        or (
            state["employee_id"] == "change-request-auditor"
            and str(state["payload"].get("handler") or "").strip() == "direct_python"
        )
    )
    if state["direct_only"]:
        state["memory"]: _facade().Dict[str, _facade().Any] = {}
        state["reasoning"] = {
            "input": dict(state["payload"]) if isinstance(state["payload"], dict) else {},
            "reasoning": "",
            "skipped_cognition": True,
        }
        state["recovery_meta"] = {}
    else:
        state["memory"] = _facade()._memory_real(
            state["config"].get("memory", {}), ctx, state["session"], state["user_id"]
        )
        (
            state["reasoning"],
            state["recovery_meta"],
        ) = _facade()._run_cognition_with_transient_retries(
            state["config"].get("cognition", {}),
            state["perceived"],
            state["memory"],
            state["session"],
            state["user_id"],
            employee_id=state["employee_id"],
            task=state["task"],
            bench_llm_override=state["bench_llm_override"],
        )
    state["reasoning"] = _facade()._merge_original_input_into_reasoning(
        state["reasoning"] if isinstance(state["reasoning"], dict) else {},
        state["payload"] if isinstance(state["payload"], dict) else {},
    )
    return (False, None)
