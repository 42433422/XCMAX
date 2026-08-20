# mypy: disable-error-code="union-attr, valid-type"
"""Self-maintenance runtime status rendering phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _runtime_status_phase_01(state):
    bounded_limit = max(1, min(int(state["limit"] or 80), 300))
    state["evidence_scan_limit"] = max(
        bounded_limit,
        max(
            100,
            min(
                _facade()._env_int(
                    "MODSTORE_SELF_MAINTENANCE_EVIDENCE_SCAN_LIMIT",
                    _facade().DEFAULT_EVIDENCE_SCAN_LIMIT,
                ),
                20000,
            ),
        ),
    )
    ledger_rows = _facade()._read_ledger(limit=state["evidence_scan_limit"])
    state["rows"] = ledger_rows[-bounded_limit:]
    state["evidence_window_days"] = max(
        1,
        min(
            _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_WINDOW_DAYS",
                _facade().DEFAULT_EVIDENCE_WINDOW_DAYS,
            ),
            90,
        ),
    )
    state["evidence_run_limit"] = max(
        1,
        min(
            _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_RUN_LIMIT",
                _facade().DEFAULT_EVIDENCE_RUN_LIMIT,
            ),
            64,
        ),
    )
    milestone_source_rows = _facade()._select_recent_milestone_rows(
        ledger_rows,
        window_days=state["evidence_window_days"],
        run_limit=state["evidence_run_limit"],
        row_limit=_facade().DEFAULT_EVIDENCE_ROW_LIMIT,
    )
    state["memory"] = _facade()._load_loop_memory()
    started: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    terminal: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    state["steps_by_run"]: _facade().Dict[
        str, _facade().List[_facade().Dict[str, _facade().Any]]
    ] = {}
    for row in state["rows"]:
        state["run_id"] = str(row.get("run_id") or "")
        if not state["run_id"]:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[state["run_id"]] = row
        elif phase in {"complete", "skip"}:
            terminal[state["run_id"]] = row
        elif phase == "step":
            state["steps_by_run"].setdefault(state["run_id"], []).append(row)
    state["open_run_ids"] = [
        state["run_id"] for state["run_id"] in started if state["run_id"] not in terminal
    ]
    state["latest_complete"] = None
    state["latest_skip"] = None
    for row in reversed(state["rows"]):
        phase = str(row.get("phase") or "")
        if state["latest_complete"] is None and phase == "complete":
            state["latest_complete"] = row
        if state["latest_skip"] is None and phase == "skip":
            state["latest_skip"] = row
        if state["latest_complete"] is not None and state["latest_skip"] is not None:
            break
    try:
        state["gate"] = _facade().should_run_self_maintenance_loop(force=False)
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("failed to evaluate self-maintenance runtime gate")
        state["gate"] = {"should_run": False, "reason": "gate_error", "error": str(exc)}
    state["trigger"] = _facade().cron_trigger_for_self_maintenance()
    state["open_items"] = (
        state["memory"].get("open_items")
        if isinstance(state["memory"].get("open_items"), list)
        else []
    )
    state["recent_runs"] = (
        state["memory"].get("recent_runs")
        if isinstance(state["memory"].get("recent_runs"), list)
        else []
    )
    try:
        from modstore_server.duty_roster import all_planned_employee_ids

        planned_employee_ids = set(all_planned_employee_ids())
    except RECOVERABLE_ERRORS:
        planned_employee_ids = set()

    def _participant_id(value: _facade().Any) -> str:
        text = str(value or "").strip()
        if not text or "-" not in text:
            return ""
        if planned_employee_ids and text not in planned_employee_ids:
            return ""
        return text

    def _participant_role(employee_id: str, row: _facade().Dict[str, _facade().Any]) -> str:
        explicit = str(row.get("role") or row.get("loop_role") or "").strip().lower()
        if explicit:
            return explicit
        step = str(row.get("step") or row.get("stage") or "").strip().lower()
        if step in {"scout", "detect", "detect_signal", "signal"}:
            return "scout"
        if step in {"write", "writer", "fix", "repair", "implement"}:
            return "fix"
        if step in {"review", "reviewer"}:
            return "review"
        if step in {"qa", "verify", "validator", "test"}:
            return "qa"
        by_employee = {
            "workflow-automator": "scout",
            "intake-dispatcher": "scout",
            "task-router-officer": "scout",
            "vibe-coding-maintainer": "fix",
            "code-validator": "review",
            "sandbox-tester": "qa",
            "test-qa-runner": "qa",
            "quality-validator": "qa",
            "self-checker": "verify",
            "host-checker": "ops",
        }
        return by_employee.get(employee_id, "worker")

    def _participant_role_label(role: str) -> str:
        return {
            "scout": "侦察",
            "fix": "修复",
            "review": "评审",
            "qa": "QA",
            "verify": "验证",
            "ops": "运维",
            "worker": "员工",
        }.get(role, role or "员工")

    def _participant_stage(row: _facade().Dict[str, _facade().Any]) -> str:
        for key in ("step", "stage", "role", "phase", "status"):
            text = str(row.get(key) or "").strip()
            if text:
                return text
        return "loop"

    def _participant_stage_label(stage: str) -> str:
        return {
            "start": "开始",
            "step": "步骤",
            "write": "写代码",
            "writer": "写代码",
            "fix": "修复",
            "review": "评审",
            "qa": "QA",
            "complete": "完成",
            "skip": "跳过",
            "failed": "失败",
            "success": "成功",
        }.get(stage, stage)

    state["participants_by_id"]: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}

    def _add_participant(
        employee_id: str, row: _facade().Dict[str, _facade().Any], source: str
    ) -> None:
        state["emp_id"] = _participant_id(employee_id)
        if not state["emp_id"]:
            return
        cur = state["participants_by_id"].setdefault(
            state["emp_id"],
            {
                "employee_id": state["emp_id"],
                "role": _participant_role(state["emp_id"], row),
                "role_label": _participant_role_label(_participant_role(state["emp_id"], row)),
                "stages": [],
                "stage_labels": [],
                "sources": [],
                "latest_at": None,
                "run_ids": [],
            },
        )
        stage = _participant_stage(row)
        if stage not in cur["stages"]:
            cur["stages"].append(stage)
        stage_label = _participant_stage_label(stage)
        if stage_label not in cur["stage_labels"]:
            cur["stage_labels"].append(stage_label)
        if source not in cur["sources"]:
            cur["sources"].append(source)
        state["run_id"] = str(row.get("run_id") or "").strip()
        if state["run_id"] and state["run_id"] not in cur["run_ids"]:
            cur["run_ids"].append(state["run_id"])
        observed_at = _facade()._ledger_row_timestamp(row)
        at = observed_at.isoformat() if observed_at is not None else ""
        if at and (not cur["latest_at"] or at > str(cur["latest_at"])):
            cur["latest_at"] = at

    def _collect_participants(value: _facade().Any, source: str) -> None:
        if isinstance(value, dict):
            for key in (
                "employee_id",
                "employeeId",
                "emp_id",
                "empId",
                "actor",
                "assignee",
                "worker_id",
                "role_employee_id",
            ):
                if key in value:
                    _add_participant(str(value.get(key) or ""), value, source)
            for key in (
                "steps",
                "nodes",
                "result",
                "employee_results",
                "reports",
                "items",
            ):
                if key in value:
                    _collect_participants(value.get(key), source)
        elif isinstance(value, list):
            for state["item"] in value:
                _collect_participants(state["item"], source)

    _collect_participants(state["rows"], "ledger")
    _collect_participants(state["steps_by_run"], "open_run_steps")
    _collect_participants(state["memory"].get("last_run"), "memory.last_run")
    _collect_participants(state["recent_runs"], "memory.recent_runs")

    def _timeline_label(row: _facade().Dict[str, _facade().Any]) -> str:
        phase = str(row.get("phase") or "").strip()
        step = str(row.get("step") or "").strip()
        if phase == "start":
            return "开始"
        if step:
            return _participant_stage_label(step)
        if phase == "complete":
            action = str(row.get("action") or "").strip()
            if action == "auto_merged_low_risk":
                return "自动合并"
            return "完成"
        if phase == "skip":
            return "跳过"
        return phase or "事件"

    def _timeline_item(
        row: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        employee_id = _participant_id(
            row.get("employee_id")
            or row.get("employeeId")
            or row.get("emp_id")
            or row.get("actor")
            or row.get("assignee")
        )
        role = _participant_role(employee_id, row) if employee_id else ""
        qa = row.get("qa") if isinstance(row.get("qa"), dict) else None
        review = row.get("review") if isinstance(row.get("review"), dict) else None
        if qa is None and str(row.get("step") or "").strip() == "qa":
            qa = _facade()._structured_report_from_step(row, _facade().STRUCTURED_QA_MARKER)
        if review is None and str(row.get("step") or "").strip() == "review":
            review = _facade()._structured_report_from_step(row, _facade().STRUCTURED_REVIEW_MARKER)
        return {
            "run_id": str(row.get("run_id") or "").strip(),
            "phase": str(row.get("phase") or "").strip(),
            "step": str(row.get("step") or "").strip(),
            "label": _timeline_label(row),
            "employee_id": employee_id,
            "role": role,
            "role_label": _participant_role_label(role) if role else "",
            "status": str(
                row.get("status") or row.get("action") or row.get("reason") or ""
            ).strip(),
            "created_at": (
                observed_at.isoformat()
                if (observed_at := _facade()._ledger_row_timestamp(row)) is not None
                else ""
            ),
            "para_task_id": str(row.get("para_task_id") or "").strip(),
            "branch": str(row.get("branch") or row.get("target_branch") or "").strip(),
            "qa_verdict": str(qa.get("verdict") or "").strip() if qa else "",
            "qa_blocking_findings": qa.get("blocking_findings") if qa else [],
            "qa_tested_commands": qa.get("tested_commands") if qa else [],
            "qa_target_branch_available": qa.get("target_branch_available") if qa else None,
            "qa_risk_class": str(qa.get("risk_class") or "").strip() if qa else "",
            "review_verdict": str(review.get("verdict") or "").strip() if review else "",
            "review_max_severity": str(review.get("max_severity") or "").strip() if review else "",
            "review_findings": review.get("findings") if review else [],
            "review_blocking_findings": review.get("blocking_findings") if review else [],
            "review_dimensions": review.get("dimensions") if review else {},
            "reason": str(row.get("reason") or "").strip(),
            "triggered_by": str(row.get("triggered_by") or "").strip(),
            "force": row.get("force") if isinstance(row.get("force"), bool) else None,
        }

    def _milestone_item(
        row: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        state["item"] = _timeline_item(row)
        for key in (
            "action",
            "catalog_readback_verified",
            "deployment_state",
            "dry_run",
            "environment",
            "event",
            "event_type",
            "final_status",
            "force",
            "identity_verified",
            "installability_verified",
            "market_catalog_item_id",
            "market_listing_verified",
            "merge_sha",
            "ok",
            "package_id",
            "package_sha256",
            "runtime_contract_verified",
            "source_commit_sha",
            "stored_filename",
            "strategic_council_receipt_id",
            "strategic_council_verified",
            "triggered_by",
            "version",
            "workflow_run_id",
        ):
            if key in row:
                state["item"][key] = row.get(key)
        return state["item"]

    state["milestone_rows"] = [_milestone_item(row) for row in milestone_source_rows]
    timelines_by_run: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = {}
    for row in state["rows"]:
        state["run_id"] = str(row.get("run_id") or "").strip()
        if not state["run_id"]:
            continue
        timelines_by_run.setdefault(state["run_id"], []).append(_timeline_item(row))
    state["run_timelines"] = [
        {
            "run_id": state["run_id"],
            "open": state["run_id"] in state["open_run_ids"],
            "items": items,
        }
        for (state["run_id"], items) in timelines_by_run.items()
    ][-12:]

    def _department_employee_ids(
        dept: _facade().Dict[str, _facade().Any],
    ) -> _facade().List[str]:
        ids: _facade().List[str] = []
        direct = dept.get("ids")
        if isinstance(direct, list):
            ids.extend(
                (
                    str(state["item"]).strip()
                    for state["item"] in direct
                    if str(state["item"]).strip()
                )
            )
        subzones = dept.get("subzones")
        if isinstance(subzones, dict):
            for subzone in subzones.values():
                if not isinstance(subzone, dict):
                    continue
                sub_ids = subzone.get("ids")
                if isinstance(sub_ids, list):
                    ids.extend(
                        (
                            str(state["item"]).strip()
                            for state["item"] in sub_ids
                            if str(state["item"]).strip()
                        )
                    )
        return list(dict.fromkeys(ids))

    def _department_lookup() -> _facade().Dict[str, _facade().Dict[str, str]]:
        out: _facade().Dict[str, _facade().Dict[str, str]] = {}
        for dept_key, dept in _facade().SIX_LINE_DEPARTMENTS.items():
            if not isinstance(dept, dict):
                continue
            dept_label = str(dept.get("label") or dept_key)
            for state["emp_id"] in _department_employee_ids(dept):
                out.setdefault(
                    state["emp_id"],
                    {"department_key": dept_key, "department_label": dept_label},
                )
        return out

    from modstore_server.self_maintenance_roster_alignment import (
        _build_roster_alignment,
    )

    state["roster_alignment"] = _build_roster_alignment(
        state, all_planned_employee_ids, _department_employee_ids
    )
    try:
        planned_ids_for_participants = set(all_planned_employee_ids())
    except RECOVERABLE_ERRORS:
        planned_ids_for_participants = set()
    try:
        deployed_ids_for_participants = set(_facade().duty_employee_records().keys())
    except RECOVERABLE_ERRORS:
        deployed_ids_for_participants = set()
    departments_by_employee = _department_lookup()
    for state["emp_id"], participant in state["participants_by_id"].items():
        in_roster = state["emp_id"] in planned_ids_for_participants
        deployed = state["emp_id"] in deployed_ids_for_participants
        dept = departments_by_employee.get(state["emp_id"], {})
        participant["roster_status"] = "in_roster" if in_roster else "out_of_roster"
        participant["roster_label"] = "编制内" if in_roster else "非编制"
        participant["duty_registered"] = deployed
        participant["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
        participant["department_key"] = dept.get("department_key", "")
        participant["department_label"] = dept.get("department_label", "")
    for timeline in state["run_timelines"]:
        items = timeline.get("items") if isinstance(timeline, dict) else None
        if not isinstance(items, list):
            continue
        for state["item"] in items:
            if not isinstance(state["item"], dict):
                continue
            state["emp_id"] = str(state["item"].get("employee_id") or "").strip()
            if not state["emp_id"]:
                continue
            in_roster = state["emp_id"] in planned_ids_for_participants
            deployed = state["emp_id"] in deployed_ids_for_participants
            dept = departments_by_employee.get(state["emp_id"], {})
            state["item"]["roster_status"] = "in_roster" if in_roster else "out_of_roster"
            state["item"]["roster_label"] = "编制内" if in_roster else "非编制"
            state["item"]["duty_registered"] = deployed
            state["item"]["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
            state["item"]["department_key"] = dept.get("department_key", "")
            state["item"]["department_label"] = dept.get("department_label", "")

    from modstore_server.self_maintenance_merge_decision_summary import (
        _merge_decision_summary,
    )

    state["merge_decision"] = _merge_decision_summary(
        state, state["memory"].get("last_policy_decision")
    )
    return None
