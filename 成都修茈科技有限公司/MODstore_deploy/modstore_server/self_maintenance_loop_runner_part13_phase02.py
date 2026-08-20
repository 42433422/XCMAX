# mypy: disable-error-code="index"
"""Self-maintenance runtime status rendering phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _runtime_status_phase_02(state):
    try:
        kb_context = _facade().build_self_evolution_context(
            run_id="runtime_status",
            evaluation=state["gate"] if isinstance(state["gate"], dict) else {},
            memory=state["memory"] if isinstance(state["memory"], dict) else {},
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
        state["kb_summary"] = {
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
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("failed to build self-evolution KB runtime summary")
        state["kb_summary"] = {
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
    except RECOVERABLE_ERRORS as exc:
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
    state["evolution_metrics_summary"] = {
        "pause": bool(metrics_gate.get("pause")),
        "reason": metrics_gate.get("reason"),
        "history_count": metrics_gate.get("history_count"),
        "raw_history_count": metrics_gate.get("raw_history_count"),
        "verified_history_count": metrics_gate.get("verified_history_count"),
        "metrics_path": metrics_gate.get("metrics_path"),
        "windows": metric_windows[-2:],
    }
    state["governance_audit"] = _facade()._read_governance_audit(10)
    state["governance_audit_summary"] = _facade()._governance_audit_summary(
        state["governance_audit"]
    )
    state["governance_gate_current"] = {
        "ok": state["governance_audit_summary"].get("health") != "bad",
        "blocking": state["governance_audit_summary"].get("health") == "bad",
        "action": (
            "hold_for_governance_review"
            if state["governance_audit_summary"].get("health") == "bad"
            else "allow"
        ),
        "reason": (
            "governance_audit_consecutive_failures"
            if state["governance_audit_summary"].get("health") == "bad"
            else "governance_audit_healthy"
        ),
        "summary": state["governance_audit_summary"],
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }
    roster_gate_current = (
        state["roster_alignment"].get("gate")
        if isinstance(state["roster_alignment"].get("gate"), dict)
        else {}
    )
    active_gate_items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if state["gate"].get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": state["gate"].get("reason") or state["gate"].get("trigger_reason") or "",
            "detail": f"missing={state['gate'].get('missing_count', 0)} threshold={state['gate'].get('threshold', '')}",
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
            "status": state["governance_gate_current"].get("action"),
            "ok": state["governance_gate_current"].get("ok"),
            "blocking": state["governance_gate_current"].get("blocking"),
            "reason": state["governance_gate_current"].get("reason"),
            "detail": state["governance_gate_current"].get("policy"),
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if state["evolution_metrics_summary"].get("pause") else "allow",
            "ok": not bool(state["evolution_metrics_summary"].get("pause")),
            "blocking": bool(state["evolution_metrics_summary"].get("pause")),
            "reason": state["evolution_metrics_summary"].get("reason") or "",
            "detail": f"history={state['evolution_metrics_summary'].get('history_count', 0)}",
        },
    ]
    active_blocking_items = [item for item in active_gate_items if item.get("blocking")]
    state["active_gates"] = {
        "ok": not active_blocking_items,
        "blocking_count": len(active_blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in active_blocking_items],
        "items": active_gate_items,
    }

    def _ui_bridge_summary() -> _facade().Dict[str, _facade().Any]:
        gate_info = (
            state["roster_alignment"].get("gate")
            if isinstance(state["roster_alignment"].get("gate"), dict)
            else {}
        )
        remediation_info = (
            state["roster_alignment"].get("remediation")
            if isinstance(state["roster_alignment"].get("remediation"), dict)
            else {}
        )
        gate_action = str(gate_info.get("action") or "").strip()
        gate_reason = str(gate_info.get("reason") or "").strip()
        target_ids = [
            str(emp_id).strip()
            for emp_id in remediation_info.get("target_employee_ids") or []
            if str(emp_id).strip()
        ][:80]
        participant_count = len(state["participants_by_id"])
        open_count = len(state["open_run_ids"])
        governance_health = str(state["governance_audit_summary"].get("health") or "").strip()
        governance_consecutive = int(
            state["governance_audit_summary"].get("consecutive_failures") or 0
        )
        ui_state = "ready"
        tone = "ok"
        title = "编制与 Loop 已对齐"
        detail = "参与员工满足编制与上岗登记要求，员工空间可作为执行现场展示。"
        primary_surface = "employee_space"
        primary_view = "hub"
        primary_action = "observe_loop_workbench"
        next_actions = ["open_employee_space", "inspect_loop_timeline"]
        if gate_action == "hold":
            ui_state = "requires_duty_registration"
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
            ui_state = "requires_roster_isolation"
            tone = "bad"
            title = "Loop 混入非编制员工"
            detail = "检测到非编制 employee_id，必须在编制图谱隔离，不能进入上岗员工执行面。"
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "isolate_out_of_roster_participants"
            next_actions = ["inspect_out_of_roster_ids", "isolate_from_on_duty_views"]
        elif gate_action == "unknown":
            ui_state = "roster_source_error"
            tone = "warn"
            title = "编制/上岗数据源异常"
            detail = f"无法确认编制或上岗数据源：{gate_reason or 'unknown'}。"
            primary_surface = "duty_roster_graph"
            primary_view = "department"
            primary_action = "repair_roster_data_source"
            next_actions = ["inspect_roster_source", "repair_duty_registry"]
        elif governance_health == "bad":
            ui_state = "governance_degraded"
            tone = "bad"
            title = "治理动作连续失败"
            detail = f"最近治理动作连续失败 {governance_consecutive} 次；先在完整 Loop 查看治理审计，再恢复自动治理信任。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_governance_audit"
            next_actions = ["inspect_governance_audit", "review_failed_governance_actions"]
        elif not participant_count:
            ui_state = "waiting_for_loop_participants"
            tone = "warn"
            title = "等待 Loop 派发到员工"
            detail = "runtime 尚未暴露 employee_id/actor/assignee；员工空间暂时只能展示待派发工位。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_gate_and_evidence"
            next_actions = ["inspect_evidence_gate", "wait_for_participant_evidence"]
        elif open_count:
            ui_state = "running"
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
        elif ui_state == "governance_degraded":
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
            "state": ui_state,
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
            "governance_health": state["governance_audit_summary"],
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

    state["ui_bridge"] = _ui_bridge_summary()
    state["generated_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
    return None
