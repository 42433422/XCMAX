# ruff: noqa
"""Runtime-status read model extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def get_self_maintenance_runtime_status(limit: int = 80) -> _facade().Dict[str, _facade().Any]:
    """Return the runtime-consumed self-maintenance loop state.

    This is the read side for the loop. It intentionally consumes the same
    ledger, memory and gate functions used by the scheduler instead of relying
    on a marker file committed by an employee branch.
    """
    bounded_limit = max(1, min(int(limit or 80), 300))
    evidence_scan_limit = max(
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
    ledger_rows = _facade()._read_ledger(limit=evidence_scan_limit)
    rows = ledger_rows[-bounded_limit:]
    evidence_window_days = max(
        1,
        min(
            _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_WINDOW_DAYS",
                _facade().DEFAULT_EVIDENCE_WINDOW_DAYS,
            ),
            90,
        ),
    )
    evidence_run_limit = max(
        1,
        min(
            _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_RUN_LIMIT", _facade().DEFAULT_EVIDENCE_RUN_LIMIT
            ),
            64,
        ),
    )
    milestone_source_rows = _facade()._select_recent_milestone_rows(
        ledger_rows,
        window_days=evidence_window_days,
        run_limit=evidence_run_limit,
        row_limit=_facade().DEFAULT_EVIDENCE_ROW_LIMIT,
    )
    memory = _facade()._load_loop_memory()
    started: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    terminal: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    steps_by_run: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[run_id] = row
        elif phase in {"complete", "skip"}:
            terminal[run_id] = row
        elif phase == "step":
            steps_by_run.setdefault(run_id, []).append(row)
    open_run_ids = [run_id for run_id in started if run_id not in terminal]
    latest_complete = None
    latest_skip = None
    for row in reversed(rows):
        phase = str(row.get("phase") or "")
        if latest_complete is None and phase == "complete":
            latest_complete = row
        if latest_skip is None and phase == "skip":
            latest_skip = row
        if latest_complete is not None and latest_skip is not None:
            break
    try:
        gate = _facade().should_run_self_maintenance_loop(force=False)
    except Exception as exc:
        _facade().logger.exception("failed to evaluate self-maintenance runtime gate")
        gate = {"should_run": False, "reason": "gate_error", "error": str(exc)}
    trigger = _facade().cron_trigger_for_self_maintenance()
    open_items = memory.get("open_items") if isinstance(memory.get("open_items"), list) else []
    recent_runs = memory.get("recent_runs") if isinstance(memory.get("recent_runs"), list) else []
    try:
        from modstore_server.duty_roster import all_planned_employee_ids

        planned_employee_ids = set(all_planned_employee_ids())
    except Exception:
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

    participants_by_id: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}

    def _add_participant(
        employee_id: str, row: _facade().Dict[str, _facade().Any], source: str
    ) -> None:
        emp_id = _participant_id(employee_id)
        if not emp_id:
            return
        cur = participants_by_id.setdefault(
            emp_id,
            {
                "employee_id": emp_id,
                "role": _participant_role(emp_id, row),
                "role_label": _participant_role_label(_participant_role(emp_id, row)),
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
        run_id = str(row.get("run_id") or "").strip()
        if run_id and run_id not in cur["run_ids"]:
            cur["run_ids"].append(run_id)
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
            for key in ("steps", "nodes", "result", "employee_results", "reports", "items"):
                if key in value:
                    _collect_participants(value.get(key), source)
        elif isinstance(value, list):
            for item in value:
                _collect_participants(item, source)

    _collect_participants(rows, "ledger")
    _collect_participants(steps_by_run, "open_run_steps")
    _collect_participants(memory.get("last_run"), "memory.last_run")
    _collect_participants(recent_runs, "memory.recent_runs")

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
        row: _facade().Dict[str, _facade().Any]
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
        row: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        item = _timeline_item(row)
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
                item[key] = row.get(key)
        return item

    milestone_rows = [_milestone_item(row) for row in milestone_source_rows]
    timelines_by_run: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        timelines_by_run.setdefault(run_id, []).append(_timeline_item(row))
    run_timelines = [
        {"run_id": run_id, "open": run_id in open_run_ids, "items": items}
        for (run_id, items) in timelines_by_run.items()
    ][-12:]

    def _department_employee_ids(dept: _facade().Dict[str, _facade().Any]) -> _facade().List[str]:
        ids: _facade().List[str] = []
        direct = dept.get("ids")
        if isinstance(direct, list):
            ids.extend((str(item).strip() for item in direct if str(item).strip()))
        subzones = dept.get("subzones")
        if isinstance(subzones, dict):
            for subzone in subzones.values():
                if not isinstance(subzone, dict):
                    continue
                sub_ids = subzone.get("ids")
                if isinstance(sub_ids, list):
                    ids.extend((str(item).strip() for item in sub_ids if str(item).strip()))
        return list(dict.fromkeys(ids))

    def _department_lookup() -> _facade().Dict[str, _facade().Dict[str, str]]:
        out: _facade().Dict[str, _facade().Dict[str, str]] = {}
        for dept_key, dept in _facade().SIX_LINE_DEPARTMENTS.items():
            if not isinstance(dept, dict):
                continue
            dept_label = str(dept.get("label") or dept_key)
            for emp_id in _department_employee_ids(dept):
                out.setdefault(emp_id, {"department_key": dept_key, "department_label": dept_label})
        return out

    def _roster_alignment_summary() -> _facade().Dict[str, _facade().Any]:
        try:
            planned_ids = set(all_planned_employee_ids())
        except Exception as exc:
            _facade().logger.exception("failed to load duty roster ids for self-maintenance status")
            planned_ids = set()
            load_error = str(exc)[:300]
        else:
            load_error = ""
        try:
            deployed_ids = set(_facade().duty_employee_records().keys())
        except Exception as exc:
            _facade().logger.exception(
                "failed to load duty employee registry for self-maintenance status"
            )
            deployed_ids = set()
            deployed_error = str(exc)[:300]
        else:
            deployed_error = ""
        participant_ids = sorted(participants_by_id.keys())
        in_roster_ids = [emp_id for emp_id in participant_ids if emp_id in planned_ids]
        out_of_roster_ids = [emp_id for emp_id in participant_ids if emp_id not in planned_ids]
        in_deployed_ids = [emp_id for emp_id in in_roster_ids if emp_id in deployed_ids]
        not_deployed_ids = [emp_id for emp_id in in_roster_ids if emp_id not in deployed_ids]
        in_roster_set = set(in_roster_ids)
        coverage: _facade().List[_facade().Dict[str, _facade().Any]] = []
        covered_ids: set[str] = set()
        for dept_key, dept in _facade().SIX_LINE_DEPARTMENTS.items():
            if not isinstance(dept, dict):
                continue
            dept_ids = [
                emp_id for emp_id in _department_employee_ids(dept) if emp_id in planned_ids
            ]
            hits = [emp_id for emp_id in dept_ids if emp_id in in_roster_set]
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
        ungrouped_ids = [emp_id for emp_id in in_roster_ids if emp_id not in covered_ids]
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
        remediation = {
            "action": "none",
            "title": "无需修复",
            "detail": "参与员工已满足编制与上岗登记要求。",
            "target_employee_ids": [],
        }
        if gate_action == "hold":
            remediation = {
                "action": "register_duty_employees",
                "title": "补登记上岗员工",
                "detail": "这些 employee_id 在编制基线内，但未出现在 duty_employee_registry.json；先完成上岗登记后再允许自维护自动放行。",
                "target_employee_ids": not_deployed_ids[:80],
                "registry": "duty_employee_registry.json",
                "suggested_entrypoint": "yuangon_onboard_admin_api",
            }
        elif gate_action == "isolate":
            remediation = {
                "action": "isolate_out_of_roster_participants",
                "title": "隔离非编制参与者",
                "detail": "这些 employee_id 不属于管理端编制基线，不能作为上岗员工进入自维护 loop 自动放行。",
                "target_employee_ids": out_of_roster_ids[:80],
                "policy": "store/catalog employees must stay outside duty loop auto-merge",
            }
        elif gate_action == "wait":
            remediation = {
                "action": "wait_for_participant_evidence",
                "title": "等待参与员工证据",
                "detail": "runtime 尚未暴露 employee_id/actor/assignee；需要 ledger 或 run timeline 回写参与员工。",
                "target_employee_ids": [],
            }
        elif gate_action == "unknown":
            remediation = {
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
            "remediation": remediation,
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

    roster_alignment = _roster_alignment_summary()
    try:
        planned_ids_for_participants = set(all_planned_employee_ids())
    except Exception:
        planned_ids_for_participants = set()
    try:
        deployed_ids_for_participants = set(_facade().duty_employee_records().keys())
    except Exception:
        deployed_ids_for_participants = set()
    departments_by_employee = _department_lookup()
    for emp_id, participant in participants_by_id.items():
        in_roster = emp_id in planned_ids_for_participants
        deployed = emp_id in deployed_ids_for_participants
        dept = departments_by_employee.get(emp_id, {})
        participant["roster_status"] = "in_roster" if in_roster else "out_of_roster"
        participant["roster_label"] = "编制内" if in_roster else "非编制"
        participant["duty_registered"] = deployed
        participant["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
        participant["department_key"] = dept.get("department_key", "")
        participant["department_label"] = dept.get("department_label", "")
    for timeline in run_timelines:
        items = timeline.get("items") if isinstance(timeline, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            emp_id = str(item.get("employee_id") or "").strip()
            if not emp_id:
                continue
            in_roster = emp_id in planned_ids_for_participants
            deployed = emp_id in deployed_ids_for_participants
            dept = departments_by_employee.get(emp_id, {})
            item["roster_status"] = "in_roster" if in_roster else "out_of_roster"
            item["roster_label"] = "编制内" if in_roster else "非编制"
            item["duty_registered"] = deployed
            item["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
            item["department_key"] = dept.get("department_key", "")
            item["department_label"] = dept.get("department_label", "")

    def _score_summary(value: _facade().Any) -> _facade().Dict[str, _facade().Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "score": value.get("score"),
            "max_allowed": value.get("max_allowed"),
            "min_allowed": value.get("min_allowed"),
            "reason": value.get("reason"),
            "source": value.get("source"),
            "available": value.get("available"),
            "passed": value.get("passed"),
        }

    def _merge_decision_summary(value: _facade().Any) -> _facade().Dict[str, _facade().Any]:
        if not isinstance(value, dict):
            return {}
        risk_v1 = _score_summary(value.get("risk_score"))
        safety_v2 = _score_summary(value.get("safety_score_v2"))
        safety_v3 = _score_summary(value.get("safety_score_v3"))
        qa = value.get("qa") if isinstance(value.get("qa"), dict) else {}
        review = value.get("review") if isinstance(value.get("review"), dict) else {}
        final = value.get("final") if isinstance(value.get("final"), dict) else {}
        roster_gate = value.get("roster_gate") if isinstance(value.get("roster_gate"), dict) else {}
        governance_gate = (
            value.get("governance_gate") if isinstance(value.get("governance_gate"), dict) else {}
        )
        active_gates = (
            value.get("active_gates") if isinstance(value.get("active_gates"), dict) else {}
        )
        evolution_gate = (
            value.get("evolution_gate") if isinstance(value.get("evolution_gate"), dict) else {}
        )
        return {
            "action": str(value.get("action") or "").strip(),
            "reason": str(value.get("reason") or "").strip(),
            "ok": value.get("ok"),
            "active_gates": active_gates,
            "evolution_gate": evolution_gate,
            "risk_score_v1": risk_v1,
            "safety_score_v2": safety_v2,
            "safety_score_v3": safety_v3,
            "roster_gate": roster_gate,
            "governance_gate": governance_gate,
            "qa_verdict": str(qa.get("verdict") or "").strip(),
            "review_max_severity": str(review.get("max_severity") or "").strip(),
            "branch": str(
                value.get("branch")
                or value.get("target_branch")
                or final.get("branch")
                or final.get("target_branch")
                or ""
            ).strip(),
            "para_task_id": str(
                value.get("para_task_id") or final.get("para_task_id") or ""
            ).strip(),
        }

    merge_decision = _merge_decision_summary(memory.get("last_policy_decision"))
    try:
        kb_context = _facade().build_self_evolution_context(
            run_id="runtime_status",
            evaluation=gate if isinstance(gate, dict) else {},
            memory=memory if isinstance(memory, dict) else {},
        )
        kb_search = (
            kb_context.get("kb_search") if isinstance(kb_context.get("kb_search"), dict) else {}
        )
        fix_hits = (
            kb_context.get("fix_knowledge_hits")
            if isinstance(kb_context.get("fix_knowledge_hits"), list)
            else []
        )
        pattern_hits = (
            kb_context.get("pattern_hits")
            if isinstance(kb_context.get("pattern_hits"), list)
            else []
        )
        inventory = (
            kb_context.get("inventory") if isinstance(kb_context.get("inventory"), dict) else {}
        )
        kb_summary = {
            "fix_count": int(inventory.get("fix_count") or 0),
            "pattern_count": int(inventory.get("pattern_count") or 0),
            "total": int(inventory.get("total") or 0),
            "invalid_count": int(inventory.get("invalid_count") or 0),
            "kb_root": kb_context.get("kb_root"),
            "engine": kb_search.get("engine"),
            "fix_hit_count": kb_search.get("fix_hit_count", len(fix_hits)),
            "pattern_hit_count": kb_search.get("pattern_hit_count", len(pattern_hits)),
            "redisvl_status": kb_search.get("redisvl_status"),
            "top_fix_hits": [
                {
                    "symptom": str(
                        item.get("symptom") or item.get("summary") or item.get("id") or ""
                    )[:180],
                    "root_cause": str(item.get("root_cause") or "")[:180],
                    "fix_diff": str(item.get("fix_diff") or "")[:2000],
                    "executable_template": (
                        item.get("executable_template")
                        if isinstance(item.get("executable_template"), dict)
                        else {}
                    ),
                    "required_tests": (
                        item.get("executable_template", {}).get("required_tests")
                        if isinstance(item.get("executable_template"), dict)
                        and isinstance(
                            item.get("executable_template", {}).get("required_tests"), list
                        )
                        else []
                    ),
                    "rollback_plan": (
                        str(item.get("executable_template", {}).get("rollback_plan") or "")[:1000]
                        if isinstance(item.get("executable_template"), dict)
                        else ""
                    ),
                    "path": item.get("_path"),
                }
                for item in fix_hits[:3]
                if isinstance(item, dict)
            ],
            "top_pattern_hits": [
                {
                    "pattern": str(
                        item.get("pattern") or item.get("summary") or item.get("id") or ""
                    )[:180],
                    "summary": str(item.get("summary") or "")[:180],
                    "applicability": str(
                        item.get("applicability") or item.get("applicability_check") or ""
                    )[:1000],
                    "patch_strategy": str(item.get("patch_strategy") or "")[:1000],
                    "path": item.get("_path"),
                }
                for item in pattern_hits[:3]
                if isinstance(item, dict)
            ],
        }
    except Exception as exc:
        _facade().logger.exception("failed to build self-evolution KB runtime summary")
        kb_summary = {
            "error": str(exc)[:500],
            "fix_count": 0,
            "fix_hit_count": 0,
            "invalid_count": 0,
            "pattern_count": 0,
            "pattern_hit_count": 0,
            "redisvl_status": {"ready": False, "error": str(exc)[:300]},
            "total": 0,
        }
    metrics_gate = {}
    try:
        metrics_gate = _facade().evolution_metrics_gate()
    except Exception as exc:
        _facade().logger.exception("failed to build evolution metrics summary")
        metrics_gate = {
            "pause": False,
            "reason": "metrics_gate_error",
            "error": str(exc)[:500],
            "windows": [],
            "history_count": 0,
        }
    metric_windows = (
        metrics_gate.get("windows") if isinstance(metrics_gate.get("windows"), list) else []
    )
    evolution_metrics_summary = {
        "pause": bool(metrics_gate.get("pause")),
        "reason": metrics_gate.get("reason"),
        "history_count": metrics_gate.get("history_count"),
        "raw_history_count": metrics_gate.get("raw_history_count"),
        "verified_history_count": metrics_gate.get("verified_history_count"),
        "metrics_path": metrics_gate.get("metrics_path"),
        "windows": metric_windows[-2:],
    }
    governance_audit = _facade()._read_governance_audit(10)
    governance_audit_summary = _facade()._governance_audit_summary(governance_audit)
    governance_gate_current = {
        "ok": governance_audit_summary.get("health") != "bad",
        "blocking": governance_audit_summary.get("health") == "bad",
        "action": (
            "hold_for_governance_review"
            if governance_audit_summary.get("health") == "bad"
            else "allow"
        ),
        "reason": (
            "governance_audit_consecutive_failures"
            if governance_audit_summary.get("health") == "bad"
            else "governance_audit_healthy"
        ),
        "summary": governance_audit_summary,
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }
    roster_gate_current = (
        roster_alignment.get("gate") if isinstance(roster_alignment.get("gate"), dict) else {}
    )
    active_gate_items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if gate.get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": gate.get("reason") or gate.get("trigger_reason") or "",
            "detail": f"missing={gate.get('missing_count', 0)} threshold={gate.get('threshold', '')}",
        },
        {
            "key": "roster",
            "label": "Roster Gate",
            "status": roster_gate_current.get("action") or "unknown",
            "ok": roster_gate_current.get("ok") is not False,
            "blocking": bool(roster_gate_current.get("blocking")),
            "reason": roster_gate_current.get("reason") or "",
            "detail": roster_gate_current.get("policy") or "",
        },
        {
            "key": "governance",
            "label": "Governance Gate",
            "status": governance_gate_current.get("action"),
            "ok": governance_gate_current.get("ok"),
            "blocking": governance_gate_current.get("blocking"),
            "reason": governance_gate_current.get("reason"),
            "detail": governance_gate_current.get("policy"),
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if evolution_metrics_summary.get("pause") else "allow",
            "ok": not bool(evolution_metrics_summary.get("pause")),
            "blocking": bool(evolution_metrics_summary.get("pause")),
            "reason": evolution_metrics_summary.get("reason") or "",
            "detail": f"history={evolution_metrics_summary.get('history_count', 0)}",
        },
    ]
    active_blocking_items = [item for item in active_gate_items if item.get("blocking")]
    active_gates = {
        "ok": not active_blocking_items,
        "blocking_count": len(active_blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in active_blocking_items],
        "items": active_gate_items,
    }

    def _ui_bridge_summary() -> _facade().Dict[str, _facade().Any]:
        gate_info = (
            roster_alignment.get("gate") if isinstance(roster_alignment.get("gate"), dict) else {}
        )
        remediation_info = (
            roster_alignment.get("remediation")
            if isinstance(roster_alignment.get("remediation"), dict)
            else {}
        )
        gate_action = str(gate_info.get("action") or "").strip()
        gate_reason = str(gate_info.get("reason") or "").strip()
        target_ids = [
            str(emp_id).strip()
            for emp_id in remediation_info.get("target_employee_ids") or []
            if str(emp_id).strip()
        ][:80]
        participant_count = len(participants_by_id)
        open_count = len(open_run_ids)
        governance_health = str(governance_audit_summary.get("health") or "").strip()
        governance_consecutive = int(governance_audit_summary.get("consecutive_failures") or 0)
        state = "ready"
        tone = "ok"
        title = "编制与 Loop 已对齐"
        detail = "参与员工满足编制与上岗登记要求，员工空间可作为执行现场展示。"
        primary_surface = "employee_space"
        primary_view = "hub"
        primary_action = "observe_loop_workbench"
        next_actions = ["open_employee_space", "inspect_loop_timeline"]
        if gate_action == "hold":
            state = "requires_duty_registration"
            tone = "bad"
            title = "编制员工未登记上岗"
            detail = (
                "Loop 参与者命中编制基线但未完成 duty registry 上岗登记，必须先在编制图谱补登记。"
            )
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "register_duty_employees"
            next_actions = ["register_duty_employees", "refresh_self_maintenance_status"]
        elif gate_action == "isolate":
            state = "requires_roster_isolation"
            tone = "bad"
            title = "Loop 混入非编制员工"
            detail = "检测到非编制 employee_id，必须在编制图谱隔离，不能进入上岗员工执行面。"
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "isolate_out_of_roster_participants"
            next_actions = ["inspect_out_of_roster_ids", "isolate_from_on_duty_views"]
        elif gate_action == "unknown":
            state = "roster_source_error"
            tone = "warn"
            title = "编制/上岗数据源异常"
            detail = f"无法确认编制或上岗数据源：{gate_reason or 'unknown'}。"
            primary_surface = "duty_roster_graph"
            primary_view = "department"
            primary_action = "repair_roster_data_source"
            next_actions = ["inspect_roster_source", "repair_duty_registry"]
        elif governance_health == "bad":
            state = "governance_degraded"
            tone = "bad"
            title = "治理动作连续失败"
            detail = f"最近治理动作连续失败 {governance_consecutive} 次；先在完整 Loop 查看治理审计，再恢复自动治理信任。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_governance_audit"
            next_actions = ["inspect_governance_audit", "review_failed_governance_actions"]
        elif not participant_count:
            state = "waiting_for_loop_participants"
            tone = "warn"
            title = "等待 Loop 派发到员工"
            detail = "runtime 尚未暴露 employee_id/actor/assignee；员工空间暂时只能展示待派发工位。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_gate_and_evidence"
            next_actions = ["inspect_evidence_gate", "wait_for_participant_evidence"]
        elif open_count:
            state = "running"
            tone = "run"
            title = "上岗员工正在执行 Loop"
            detail = f"{participant_count} 个员工参与，{open_count} 个 run 未闭环；员工空间展示执行现场，编制图谱展示准入。"
            primary_surface = "employee_space"
            primary_view = "hub"
            primary_action = "observe_active_workers"
            next_actions = ["open_employee_space", "inspect_run_timeline"]
        governance_action = {
            "id": primary_action,
            "label": "观察 Loop 状态",
            "status": "informational",
            "surface": primary_surface,
            "view": primary_view,
            "executable": False,
            "target_employee_ids": target_ids,
            "requires_admin": False,
            "allowed_surfaces": [primary_surface],
            "method": "",
            "endpoint_hint": "",
            "refresh_after": ["self_maintenance_status"],
        }
        if gate_action == "hold":
            governance_action.update(
                {
                    "id": "register_duty_employees",
                    "label": "补登记上岗员工",
                    "status": "requires_action",
                    "surface": "duty_roster_graph",
                    "view": "loop",
                    "executable": True,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                    "method": "POST",
                    "endpoint_hint": "/api/admin/yuangon-onboard/run",
                    "refresh_after": ["duty_roster_graph", "self_maintenance_status"],
                }
            )
        elif gate_action == "isolate":
            governance_action.update(
                {
                    "id": "isolate_out_of_roster_participants",
                    "label": "隔离非编制参与者",
                    "status": "enforced",
                    "surface": "duty_roster_graph",
                    "view": "loop",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph", "self_evolution_loop"],
                    "method": "gate",
                    "endpoint_hint": "self_maintenance_roster_gate",
                    "refresh_after": ["self_maintenance_status"],
                }
            )
        elif gate_action == "unknown":
            governance_action.update(
                {
                    "id": "repair_roster_data_source",
                    "label": "修复编制/上岗数据源",
                    "status": "requires_human_review",
                    "surface": "duty_roster_graph",
                    "view": "department",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                }
            )
        elif state == "governance_degraded":
            governance_action.update(
                {
                    "id": "inspect_governance_audit",
                    "label": "复核治理审计",
                    "status": "requires_human_review",
                    "surface": "self_evolution_loop",
                    "view": "loop",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                    "method": "audit",
                    "endpoint_hint": "governance_audit.summary",
                    "review_endpoint_hint": "/api/ops/self-maintenance/governance-review",
                    "refresh_after": ["self_maintenance_status"],
                }
            )
        return {
            "state": state,
            "tone": tone,
            "title": title,
            "detail": detail,
            "primary_surface": primary_surface,
            "primary_view": primary_view,
            "primary_action": primary_action,
            "primary_employee_id": target_ids[0] if target_ids else "",
            "target_employee_ids": target_ids,
            "gate_action": gate_action,
            "gate_reason": gate_reason,
            "isolation_enforced": gate_action == "isolate",
            "blocked_employee_ids": target_ids if gate_action == "isolate" else [],
            "isolation_reason": gate_reason if gate_action == "isolate" else "",
            "isolation_policy": "out_of_roster_participants_are_never_treated_as_on_duty_workers",
            "governance_action": governance_action,
            "governance_health": governance_audit_summary,
            "next_actions": next_actions,
            "handoff_path": [
                {"surface": "self_evolution_loop", "role": "runtime_overview", "view": "loop"},
                {
                    "surface": "duty_roster_graph",
                    "role": "governance_surface",
                    "view": primary_view,
                },
                {
                    "surface": "employee_space",
                    "role": "execution_surface",
                    "employee_id": target_ids[0] if target_ids else "",
                },
            ],
            "employee_space": {
                "role": "execution_surface",
                "title": title if primary_surface == "employee_space" else "员工空间只展示执行现场",
                "detail": (
                    detail
                    if primary_surface == "employee_space"
                    else "补登记、隔离、数据源修复统一在编制图谱处理，避免工位页绕过上岗门禁。"
                ),
                "cta": "看执行现场" if primary_surface == "employee_space" else "去编制图谱处理",
            },
            "duty_roster_graph": {
                "role": "governance_surface",
                "title": title,
                "detail": detail,
                "cta": "执行治理动作" if primary_surface == "duty_roster_graph" else "查看编制准入",
            },
        }

    ui_bridge = _ui_bridge_summary()
    generated_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    latest_timestamp = _facade()._ledger_row_timestamp(rows[-1]) if rows else None
    latest_event_at = latest_timestamp.isoformat() if latest_timestamp is not None else None
    runtime_source = {
        "name": "self_maintenance_loop_runner",
        "runtime": "MODstore",
        "ledger": str(_facade().ledger_path()),
        "memory": str(_facade().loop_memory_path()),
        "governance_audit": str(_facade().governance_audit_path()),
    }
    runtime_contract = {
        "schema_version": "self_maintenance_runtime.v1",
        "required_top_level": [
            "schema_version",
            "source",
            "generated_at",
            "refreshed_at",
            "evidence",
            "participants",
            "run_timelines",
            "roster_alignment",
            "ui_bridge",
            "active_gates",
            "governance_gate",
            "governance_audit",
            "merge_decision",
        ],
        "surfaces": ["employee_space", "duty_roster_graph", "self_evolution_loop_runtime"],
        "identity_dependencies": ["participants", "roster_alignment", "ui_bridge"],
        "gate_dependencies": [
            "active_gates",
            "governance_gate",
            "roster_alignment.gate",
            "merge_decision",
            "evolution_metrics_summary",
        ],
        "truth_dependencies": ["source", "evidence", "governance_audit", "run_timelines"],
        "required_nested": [
            "active_gates.items",
            "governance_audit.summary",
            "governance_gate.summary",
            "roster_alignment.gate",
            "ui_bridge.employee_space",
            "ui_bridge.duty_roster_graph",
            "ui_bridge.governance_action",
        ],
    }
    runtime_top_level_keys = {
        "ok",
        "cron",
        "current_gate",
        "schema_version",
        "contract",
        "contract_validation",
        "source",
        "generated_at",
        "refreshed_at",
        "latest_event_at",
        "evidence",
        "participants",
        "run_timelines",
        "roster_alignment",
        "ui_bridge",
        "active_gates",
        "governance_gate",
        "governance_audit",
        "merge_decision",
        "kb_summary",
        "evolution_metrics_summary",
        "memory",
    }
    contract_missing_fields = [
        field
        for field in runtime_contract["required_top_level"]
        if field not in runtime_top_level_keys
    ]
    contract_nested_presence = {
        "active_gates.items": (
            bool(active_gates.get("items")) if isinstance(active_gates, dict) else False
        ),
        "governance_audit.summary": bool(governance_audit_summary),
        "governance_gate.summary": (
            bool(governance_gate_current.get("summary"))
            if isinstance(governance_gate_current, dict)
            else False
        ),
        "roster_alignment.gate": (
            bool(roster_alignment.get("gate")) if isinstance(roster_alignment, dict) else False
        ),
        "ui_bridge.employee_space": (
            bool(ui_bridge.get("employee_space")) if isinstance(ui_bridge, dict) else False
        ),
        "ui_bridge.duty_roster_graph": (
            bool(ui_bridge.get("duty_roster_graph")) if isinstance(ui_bridge, dict) else False
        ),
        "ui_bridge.governance_action": (
            bool(ui_bridge.get("governance_action")) if isinstance(ui_bridge, dict) else False
        ),
    }
    contract_missing_nested = [
        path
        for path in runtime_contract["required_nested"]
        if not contract_nested_presence.get(path)
    ]
    contract_surface_requirements = {
        "employee_space": [
            "participants",
            "run_timelines",
            "roster_alignment.gate",
            "ui_bridge.employee_space",
            "ui_bridge.governance_action",
        ],
        "duty_roster_graph": [
            "roster_alignment.gate",
            "ui_bridge.duty_roster_graph",
            "ui_bridge.governance_action",
            "governance_gate.summary",
            "governance_audit.summary",
        ],
        "self_evolution_loop_runtime": [
            "active_gates.items",
            "merge_decision",
            "evolution_metrics_summary",
            "governance_gate.summary",
            "governance_audit.summary",
        ],
    }

    def _contract_dependency_present(name: str) -> bool:
        if "." in name:
            return bool(contract_nested_presence.get(name))
        return name in runtime_top_level_keys

    def _contract_surface_remediation(
        surface: str, missing: _facade().List[str]
    ) -> _facade().Dict[str, _facade().Any]:
        if not missing:
            return {
                "action": "observe",
                "title": "Surface contract ready",
                "detail": "All required runtime dependencies for this surface are present.",
                "severity": "ok",
                "target_surface": surface,
                "target_view": "loop",
                "requires_admin": False,
                "executable": False,
            }
        if surface == "employee_space":
            if "participants" in missing or "run_timelines" in missing:
                return {
                    "action": "wait_for_employee_ledger",
                    "title": "Wait for employee work-order evidence",
                    "detail": "Employee space needs participants and run_timelines before it can prove real loop work.",
                    "severity": "warn",
                    "target_surface": "self_evolution_loop_runtime",
                    "target_view": "loop",
                    "requires_admin": False,
                    "executable": False,
                }
            return {
                "action": "open_duty_roster_graph",
                "title": "Resolve employee governance dependencies",
                "detail": "Employee space is read-only for governance; fix roster/ui_bridge dependencies in duty roster graph.",
                "severity": "bad",
                "target_surface": "duty_roster_graph",
                "target_view": "loop",
                "requires_admin": True,
                "executable": False,
            }
        if surface == "duty_roster_graph":
            if "governance_audit.summary" in missing or "governance_gate.summary" in missing:
                return {
                    "action": "inspect_governance_audit",
                    "title": "Inspect governance audit contract",
                    "detail": "Duty roster graph needs governance gate and audit summaries before it can execute admin decisions.",
                    "severity": "bad",
                    "target_surface": "duty_roster_graph",
                    "target_view": "loop",
                    "requires_admin": True,
                    "executable": True,
                }
            return {
                "action": "repair_roster_contract",
                "title": "Repair roster governance contract",
                "detail": "Duty roster graph needs roster_alignment.gate and ui_bridge governance action dependencies.",
                "severity": "bad",
                "target_surface": "duty_roster_graph",
                "target_view": "loop",
                "requires_admin": True,
                "executable": True,
            }
        return {
            "action": "inspect_runtime_contract",
            "title": "Inspect full loop runtime contract",
            "detail": "Full loop panel needs active gates, merge decision, metrics, and governance summaries.",
            "severity": "bad",
            "target_surface": "self_evolution_loop_runtime",
            "target_view": "loop",
            "requires_admin": False,
            "executable": False,
        }

    contract_surface_readiness = {}
    for surface, requirements in contract_surface_requirements.items():
        missing = [name for name in requirements if not _contract_dependency_present(name)]
        remediation = _contract_surface_remediation(surface, missing)
        contract_surface_readiness[surface] = {
            "ok": not missing,
            "required": requirements,
            "missing": missing,
            "action": remediation["action"],
            "title": remediation["title"],
            "detail": remediation["detail"],
            "severity": remediation["severity"],
            "target_surface": remediation.get("target_surface") or surface,
            "target_view": remediation.get("target_view") or "loop",
            "requires_admin": remediation.get("requires_admin") is True,
            "executable": remediation.get("executable") is True,
        }
    contract_surface_incidents = [
        {
            "id": f"contract:{surface}",
            "source": "contract_validation",
            "schema_version": runtime_contract["schema_version"],
            "created_at": generated_at,
            "surface": surface,
            "severity": readiness.get("severity") or "bad",
            "action": readiness.get("action") or "inspect_runtime_contract",
            "title": readiness.get("title") or "Surface contract blocked",
            "detail": readiness.get("detail") or "Surface runtime dependencies are missing.",
            "target_surface": readiness.get("target_surface") or surface,
            "target_view": readiness.get("target_view") or "loop",
            "requires_admin": readiness.get("requires_admin") is True,
            "executable": readiness.get("executable") is True,
            "missing": readiness.get("missing") or [],
            "required": readiness.get("required") or [],
        }
        for (surface, readiness) in contract_surface_readiness.items()
        if isinstance(readiness, dict) and (not readiness.get("ok"))
    ]

    def _contract_incident_priority(item: _facade().Dict[str, _facade().Any]) -> tuple:
        severity_rank = {"bad": 0, "warn": 1, "ok": 2}
        surface_rank = {
            "duty_roster_graph": 0,
            "self_evolution_loop_runtime": 1,
            "employee_space": 2,
        }
        return (
            severity_rank.get(str(item.get("severity") or "unknown"), 9),
            0 if item.get("executable") else 1,
            0 if item.get("requires_admin") else 1,
            surface_rank.get(str(item.get("surface") or ""), 9),
        )

    contract_primary_incident = (
        sorted(contract_surface_incidents, key=_contract_incident_priority)[0]
        if contract_surface_incidents
        else None
    )
    contract_surface_incident_summary = {
        "status": "blocked" if contract_surface_incidents else "clear",
        "total": len(contract_surface_incidents),
        "surfaces": sorted(
            {str(item.get("surface")) for item in contract_surface_incidents if item.get("surface")}
        ),
        "actions": sorted(
            {str(item.get("action")) for item in contract_surface_incidents if item.get("action")}
        ),
        "by_severity": {
            severity: sum(
                (1 for item in contract_surface_incidents if item.get("severity") == severity)
            )
            for severity in sorted(
                {str(item.get("severity") or "unknown") for item in contract_surface_incidents}
            )
        },
        "requires_admin_count": sum(
            (1 for item in contract_surface_incidents if item.get("requires_admin"))
        ),
        "executable_count": sum(
            (1 for item in contract_surface_incidents if item.get("executable"))
        ),
        "admin_required": any(
            (bool(item.get("requires_admin")) for item in contract_surface_incidents)
        ),
        "executable_available": any(
            (bool(item.get("executable")) for item in contract_surface_incidents)
        ),
        "primary_incident": contract_primary_incident,
        "primary_action": (
            contract_primary_incident.get("action")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
        "primary_surface": (
            contract_primary_incident.get("surface")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
        "primary_target_surface": (
            contract_primary_incident.get("target_surface")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
    }
    contract_global_ok = not contract_missing_fields
    contract_all_surfaces_ok = not contract_surface_incidents
    contract_status_blocked = not contract_global_ok or not contract_all_surfaces_ok
    contract_status_detail = (
        f"Runtime contract top-level required fields are missing: {', '.join(contract_missing_fields[:6])}."
        if contract_missing_fields
        else (
            contract_primary_incident.get("detail")
            if isinstance(contract_primary_incident, dict)
            else "All runtime contract surfaces are ready."
        )
    )
    contract_status = {
        "state": "blocked" if contract_status_blocked else "trusted",
        "tone": "bad" if contract_status_blocked else "ok",
        "label": "Contract blocked" if contract_status_blocked else "Contract trusted",
        "detail": contract_status_detail,
        "global_ok": contract_global_ok,
        "all_surfaces_ok": contract_all_surfaces_ok,
        "primary_action": contract_surface_incident_summary.get("primary_action"),
        "primary_surface": contract_surface_incident_summary.get("primary_surface"),
        "primary_target_surface": contract_surface_incident_summary.get("primary_target_surface"),
        "surface_incident_total": contract_surface_incident_summary.get("total", 0),
        "admin_required": contract_surface_incident_summary.get("admin_required", False),
        "executable_available": contract_surface_incident_summary.get(
            "executable_available", False
        ),
        "primary_route": {
            "surface": contract_surface_incident_summary.get("primary_target_surface")
            or contract_surface_incident_summary.get("primary_surface")
            or "self_evolution_loop_runtime",
            "view": (
                contract_primary_incident.get("target_view")
                if isinstance(contract_primary_incident, dict)
                else "loop"
            ),
            "action": contract_surface_incident_summary.get("primary_action") or "observe",
            "requires_admin": contract_surface_incident_summary.get("admin_required", False),
            "executable": contract_surface_incident_summary.get("executable_available", False),
            "employee_id": (
                ui_bridge.get("primary_employee_id") if isinstance(ui_bridge, dict) else None
            ),
            "target_employee_ids": (
                ui_bridge.get("target_employee_ids")
                if isinstance(ui_bridge, dict)
                and isinstance(ui_bridge.get("target_employee_ids"), list)
                else []
            ),
            "label": (
                "Open governance surface"
                if contract_surface_incident_summary.get("primary_target_surface")
                == "duty_roster_graph"
                else (
                    "Open employee surface"
                    if contract_surface_incident_summary.get("primary_target_surface")
                    == "employee_space"
                    else "Open full loop"
                )
            ),
            "detail": (
                "Admin governance action is available on the target surface."
                if contract_surface_incident_summary.get("executable_available")
                else "Navigate to the target surface for inspection; no direct action is executed here."
            ),
        },
    }
    contract_validation = {
        "ok": contract_global_ok and contract_all_surfaces_ok,
        "global_ok": contract_global_ok,
        "all_surfaces_ok": contract_all_surfaces_ok,
        "schema_version": runtime_contract["schema_version"],
        "required_count": len(runtime_contract["required_top_level"]),
        "missing_fields": contract_missing_fields,
        "required_nested_count": len(runtime_contract["required_nested"]),
        "missing_nested": contract_missing_nested,
        "surface_readiness": contract_surface_readiness,
        "surface_incidents": contract_surface_incidents,
        "surface_incident_summary": contract_surface_incident_summary,
        "contract_status": contract_status,
        "generated_at": generated_at,
        "surfaces": runtime_contract["surfaces"],
        "gate_dependencies": runtime_contract["gate_dependencies"],
        "truth_dependencies": runtime_contract["truth_dependencies"],
    }
    return {
        "ok": True,
        "cron": {
            "hour": _facade()._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3),
            "minute": _facade()._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0),
            "timezone": _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai"),
            "trigger": str(trigger),
        },
        "current_gate": gate,
        "schema_version": runtime_contract["schema_version"],
        "contract": runtime_contract,
        "contract_validation": contract_validation,
        "contract_status": contract_status,
        "source": runtime_source,
        "generated_at": generated_at,
        "refreshed_at": generated_at,
        "latest_event_at": latest_event_at,
        "evidence": {
            "ledger_path": str(_facade().ledger_path()),
            "memory_path": str(_facade().loop_memory_path()),
            "latest_complete": latest_complete,
            "latest_skip": latest_skip,
            "open_run_ids": open_run_ids,
            "recent_rows": rows[-20:],
            "milestone_rows": milestone_rows,
            "milestone_window": {
                "window_days": evidence_window_days,
                "scan_limit": evidence_scan_limit,
                "run_limit": evidence_run_limit,
                "row_limit": _facade().DEFAULT_EVIDENCE_ROW_LIMIT,
                "selected_rows": len(milestone_rows),
                "policy": "recent_meaningful_runs_excluding_heartbeat_skip_and_kb_salvage",
            },
            "steps_by_open_run": {run_id: steps_by_run.get(run_id, []) for run_id in open_run_ids},
        },
        "participants": sorted(
            participants_by_id.values(),
            key=lambda item: str(item.get("latest_at") or ""),
            reverse=True,
        )[:24],
        "run_timelines": run_timelines,
        "roster_alignment": roster_alignment,
        "ui_bridge": ui_bridge,
        "active_gates": active_gates,
        "governance_gate": governance_gate_current,
        "governance_audit": {
            "path": str(_facade().governance_audit_path()),
            "summary": governance_audit_summary,
            "recent": governance_audit,
            "last": governance_audit[-1] if governance_audit else None,
        },
        "merge_decision": merge_decision,
        "kb_summary": kb_summary,
        "evolution_metrics_summary": evolution_metrics_summary,
        "memory": {
            "updated_at": memory.get("updated_at"),
            "last_policy_decision": memory.get("last_policy_decision"),
            "last_run": memory.get("last_run"),
            "open_items": open_items[-20:],
            "recent_runs": recent_runs[-20:],
            "run_count": memory.get("run_count"),
        },
        "policy": {
            "auto_merge_low_risk": _facade()._env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True
            ),
            "auto_merge_dynamic_low_risk": _facade()._env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True
            ),
            "auto_merge_forbidden_globs": _facade()._auto_merge_forbidden_globs(),
            "auto_merge_globs": _facade()._allowed_auto_merge_globs(),
            "auto_merge_max_files": _facade()._auto_merge_max_files(),
            "auto_merge_max_lines": _facade()._auto_merge_max_lines(),
            "auto_merge_max_risk_score": _facade()._auto_merge_max_risk_score(),
            "auto_merge_min_safety_score_v2": _facade()._auto_merge_min_safety_score_v2(),
            "auto_merge_scoring_gate_v2": _facade()._env_bool(
                "MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True
            ),
            "auto_merge_scope_globs": _facade()._auto_merge_scope_globs(),
            "report_timeout_sec": _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
            ),
            "focused_test_command": _facade()._focused_test_command(),
            "threshold": _facade()._env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1),
            "cooldown_minutes": _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360
            ),
            "auto_dispatch_deploy": _facade()._auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": _facade()._auto_dispatch_deploy_envs(),
            "auto_dispatch_deploy_dry_run": _facade()._env_flag_enabled(
                "MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"
            ),
        },
        "l4_closure": {
            "target": "L4",
            "auto_dispatch_deploy": _facade()._auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": _facade()._auto_dispatch_deploy_envs(),
            "half_closed_without_deploy": not _facade()._auto_dispatch_deploy_enabled(),
            "open_items_count": len(open_items[-20:]),
        },
    }
