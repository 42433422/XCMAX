# mypy: disable-error-code="union-attr, valid-type"
"""Duty-roster alignment builder for self-maintenance status."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _build_roster_alignment(
    state, all_planned_employee_ids, department_employee_ids
) -> _facade().Dict[str, _facade().Any]:
    try:
        planned_ids = set(all_planned_employee_ids())
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("failed to load duty roster ids for self-maintenance status")
        planned_ids = set()
        load_error = str(exc)[:300]
    else:
        load_error = ""
    try:
        deployed_ids = set(_facade().duty_employee_records().keys())
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception(
            "failed to load duty employee registry for self-maintenance status"
        )
        deployed_ids = set()
        deployed_error = str(exc)[:300]
    else:
        deployed_error = ""
    participant_ids = sorted(state["participants_by_id"].keys())
    in_roster_ids = [
        state["emp_id"] for state["emp_id"] in participant_ids if state["emp_id"] in planned_ids
    ]
    out_of_roster_ids = [
        state["emp_id"] for state["emp_id"] in participant_ids if state["emp_id"] not in planned_ids
    ]
    in_deployed_ids = [
        state["emp_id"] for state["emp_id"] in in_roster_ids if state["emp_id"] in deployed_ids
    ]
    not_deployed_ids = [
        state["emp_id"] for state["emp_id"] in in_roster_ids if state["emp_id"] not in deployed_ids
    ]
    in_roster_set = set(in_roster_ids)
    coverage: _facade().List[_facade().Dict[str, _facade().Any]] = []
    covered_ids: set[str] = set()
    for dept_key, dept in _facade().SIX_LINE_DEPARTMENTS.items():
        if not isinstance(dept, dict):
            continue
        dept_ids = [
            state["emp_id"]
            for state["emp_id"] in department_employee_ids(dept)
            if state["emp_id"] in planned_ids
        ]
        hits = [state["emp_id"] for state["emp_id"] in dept_ids if state["emp_id"] in in_roster_set]
        if not hits:
            continue
        covered_ids.update(hits)
        coverage.append(
            {
                "key": dept_key,
                "label": str(dept.get("label") or dept_key),
                "count": len(hits),
                "total": len(dept_ids),
                "ids": hits,
            }
        )
    ungrouped_ids = [
        state["emp_id"] for state["emp_id"] in in_roster_ids if state["emp_id"] not in covered_ids
    ]
    if ungrouped_ids:
        coverage.append(
            {
                "key": "ungrouped",
                "label": "未归组",
                "count": len(ungrouped_ids),
                "total": len(ungrouped_ids),
                "ids": ungrouped_ids,
            }
        )
    status = "clean"
    if load_error:
        status = "unknown"
    elif out_of_roster_ids:
        status = "mixed"
    elif not_deployed_ids:
        status = "not_deployed"
    elif not in_roster_ids:
        status = "empty"
    gate_action = "allow"
    gate_reason = "all_participants_are_in_duty_roster"
    gate_blocking = False
    if load_error:
        gate_action = "unknown"
        gate_reason = "duty_roster_load_error"
    elif deployed_error:
        gate_action = "unknown"
        gate_reason = "duty_employee_registry_load_error"
    elif out_of_roster_ids:
        gate_action = "isolate"
        gate_reason = "out_of_roster_participants_detected"
        gate_blocking = True
    elif not_deployed_ids:
        gate_action = "hold"
        gate_reason = "in_roster_but_not_registered_duty_employee"
        gate_blocking = True
    elif not participant_ids:
        gate_action = "wait"
        gate_reason = "no_loop_participants_detected"
    state["remediation"] = {
        "action": "none",
        "title": "无需修复",
        "detail": "参与员工已满足编制与上岗登记要求。",
        "target_employee_ids": [],
    }
    if gate_action == "hold":
        state["remediation"] = {
            "action": "register_duty_employees",
            "title": "补登记上岗员工",
            "detail": "这些 employee_id 在编制基线内，但未出现在 duty_employee_registry.json；先完成上岗登记后再允许自维护自动放行。",
            "target_employee_ids": not_deployed_ids[:80],
            "registry": "duty_employee_registry.json",
            "suggested_entrypoint": "yuangon_onboard_admin_api",
        }
    elif gate_action == "isolate":
        state["remediation"] = {
            "action": "isolate_out_of_roster_participants",
            "title": "隔离非编制参与者",
            "detail": "这些 employee_id 不属于管理端编制基线，不能作为上岗员工进入自维护 loop 自动放行。",
            "target_employee_ids": out_of_roster_ids[:80],
            "policy": "store/catalog employees must stay outside duty loop auto-merge",
        }
    elif gate_action == "wait":
        state["remediation"] = {
            "action": "wait_for_participant_evidence",
            "title": "等待参与员工证据",
            "detail": "runtime 尚未暴露 employee_id/actor/assignee；需要 ledger 或 run timeline 回写参与员工。",
            "target_employee_ids": [],
        }
    elif gate_action == "unknown":
        state["remediation"] = {
            "action": "repair_roster_data_source",
            "title": "修复编制/上岗数据源",
            "detail": gate_reason,
            "target_employee_ids": [],
        }
    return {
        "status": status,
        "planned_count": len(planned_ids),
        "participant_count": len(participant_ids),
        "in_roster_count": len(in_roster_ids),
        "out_of_roster_count": len(out_of_roster_ids),
        "deployed_count": len(deployed_ids),
        "in_deployed_count": len(in_deployed_ids),
        "not_deployed_count": len(not_deployed_ids),
        "in_roster_ids": in_roster_ids[:80],
        "out_of_roster_ids": out_of_roster_ids[:80],
        "in_deployed_ids": in_deployed_ids[:80],
        "not_deployed_ids": not_deployed_ids[:80],
        "department_coverage": coverage,
        "source": "duty_roster.py:SIX_LINE_DEPARTMENTS",
        "error": load_error or deployed_error,
        "remediation": state["remediation"],
        "gate": {
            "ok": not gate_blocking and (not load_error) and (not deployed_error),
            "blocking": gate_blocking,
            "action": gate_action,
            "reason": gate_reason,
            "policy": "only_registered_duty_roster_participants_can_be_visualized_as_on_duty",
            "out_of_roster_action": "isolate_from_on_duty_views",
            "not_deployed_action": "hold_for_duty_employee_registration",
        },
    }
