"""Validate runtime surface contracts and construct the public status response."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from . import config, deployment, merge_policy, review, risk, store


def render_runtime_contract(state: Dict[str, Any]) -> Dict[str, Any]:
    latest_timestamp = store._ledger_row_timestamp(state["rows"][-1]) if state["rows"] else None
    latest_event_at = latest_timestamp.isoformat() if latest_timestamp is not None else None
    runtime_source = {
        "name": "self_maintenance_loop_runner",
        "runtime": "MODstore",
        "ledger": str(store.ledger_path()),
        "memory": str(store.loop_memory_path()),
        "governance_audit": str(store.governance_audit_path()),
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
        "surfaces": [
            "employee_space",
            "duty_roster_graph",
            "self_evolution_loop_runtime",
        ],
        "identity_dependencies": ["participants", "roster_alignment", "ui_bridge"],
        "gate_dependencies": [
            "active_gates",
            "governance_gate",
            "roster_alignment.gate",
            "merge_decision",
            "evolution_metrics_summary",
        ],
        "truth_dependencies": [
            "source",
            "evidence",
            "governance_audit",
            "run_timelines",
        ],
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
            bool(state["active_gates"].get("items"))
            if isinstance(state["active_gates"], dict)
            else False
        ),
        "governance_audit.summary": bool(state["governance_audit_summary"]),
        "governance_gate.summary": (
            bool(state["governance_gate_current"].get("summary"))
            if isinstance(state["governance_gate_current"], dict)
            else False
        ),
        "roster_alignment.gate": (
            bool(state["roster_alignment"].get("gate"))
            if isinstance(state["roster_alignment"], dict)
            else False
        ),
        "ui_bridge.employee_space": (
            bool(state["ui_bridge"].get("employee_space"))
            if isinstance(state["ui_bridge"], dict)
            else False
        ),
        "ui_bridge.duty_roster_graph": (
            bool(state["ui_bridge"].get("duty_roster_graph"))
            if isinstance(state["ui_bridge"], dict)
            else False
        ),
        "ui_bridge.governance_action": (
            bool(state["ui_bridge"].get("governance_action"))
            if isinstance(state["ui_bridge"], dict)
            else False
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

    def _contract_surface_remediation(surface: str, missing: List[str]) -> Dict[str, Any]:
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
            "created_at": state["generated_at"],
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

    def _contract_incident_priority(item: Dict[str, Any]) -> tuple:
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
                state["ui_bridge"].get("primary_employee_id")
                if isinstance(state["ui_bridge"], dict)
                else None
            ),
            "target_employee_ids": (
                state["ui_bridge"].get("target_employee_ids")
                if isinstance(state["ui_bridge"], dict)
                and isinstance(state["ui_bridge"].get("target_employee_ids"), list)
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
        "generated_at": state["generated_at"],
        "surfaces": runtime_contract["surfaces"],
        "gate_dependencies": runtime_contract["gate_dependencies"],
        "truth_dependencies": runtime_contract["truth_dependencies"],
    }

    return _build_runtime_status_result(
        state=state,
        runtime_contract=runtime_contract,
        contract_validation=contract_validation,
        contract_status=contract_status,
        runtime_source=runtime_source,
        latest_event_at=latest_event_at,
    )


def _build_runtime_status_result(
    *,
    state,
    runtime_contract,
    contract_validation,
    contract_status,
    runtime_source,
    latest_event_at,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "cron": {
            "hour": config._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3),
            "minute": config._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0),
            "timezone": os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai"),
            "trigger": str(state["trigger"]),
        },
        "current_gate": state["gate"],
        "schema_version": runtime_contract["schema_version"],
        "contract": runtime_contract,
        "contract_validation": contract_validation,
        "contract_status": contract_status,
        "source": runtime_source,
        "generated_at": state["generated_at"],
        "refreshed_at": state["generated_at"],
        "latest_event_at": latest_event_at,
        "evidence": {
            "ledger_path": str(store.ledger_path()),
            "memory_path": str(store.loop_memory_path()),
            "latest_complete": state["latest_complete"],
            "latest_skip": state["latest_skip"],
            "open_run_ids": state["open_run_ids"],
            "recent_rows": state["rows"][-20:],
            "milestone_rows": state["milestone_rows"],
            "milestone_window": {
                "window_days": state["evidence_window_days"],
                "scan_limit": state["evidence_scan_limit"],
                "run_limit": state["evidence_run_limit"],
                "row_limit": config.DEFAULT_EVIDENCE_ROW_LIMIT,
                "selected_rows": len(state["milestone_rows"]),
                "policy": "recent_meaningful_runs_excluding_heartbeat_skip_and_kb_salvage",
            },
            "steps_by_open_run": {
                run_id: state["steps_by_run"].get(run_id, []) for run_id in state["open_run_ids"]
            },
        },
        "participants": sorted(
            state["participants_by_id"].values(),
            key=lambda item: str(item.get("latest_at") or ""),
            reverse=True,
        )[:24],
        "run_timelines": state["run_timelines"],
        "roster_alignment": state["roster_alignment"],
        "ui_bridge": state["ui_bridge"],
        "active_gates": state["active_gates"],
        "governance_gate": state["governance_gate_current"],
        "governance_audit": {
            "path": str(store.governance_audit_path()),
            "summary": state["governance_audit_summary"],
            "recent": state["governance_audit"],
            "last": (state["governance_audit"][-1] if state["governance_audit"] else None),
        },
        "merge_decision": state["merge_decision"],
        "kb_summary": state["kb_summary"],
        "evolution_metrics_summary": state["evolution_metrics_summary"],
        "memory": {
            "updated_at": state["memory"].get("updated_at"),
            "last_policy_decision": state["memory"].get("last_policy_decision"),
            "last_run": state["memory"].get("last_run"),
            "open_items": state["open_items"][-20:],
            "recent_runs": state["recent_runs"][-20:],
            "run_count": state["memory"].get("run_count"),
        },
        "policy": {
            "auto_merge_low_risk": config._env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True
            ),
            "auto_merge_dynamic_low_risk": config._env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True
            ),
            "auto_merge_forbidden_globs": merge_policy._auto_merge_forbidden_globs(),
            "auto_merge_globs": merge_policy._allowed_auto_merge_globs(),
            "auto_merge_max_files": merge_policy._auto_merge_max_files(),
            "auto_merge_max_lines": merge_policy._auto_merge_max_lines(),
            "auto_merge_max_risk_score": risk._auto_merge_max_risk_score(),
            "auto_merge_min_safety_score_v2": risk._auto_merge_min_safety_score_v2(),
            "auto_merge_scoring_gate_v2": config._env_bool(
                "MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True
            ),
            "auto_merge_scope_globs": merge_policy._auto_merge_scope_globs(),
            "report_timeout_sec": config._env_int(
                "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
            ),
            "focused_test_command": review._focused_test_command(),
            "threshold": config._env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1),
            "cooldown_minutes": config._env_int("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360),
            "auto_dispatch_deploy": config._auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": deployment._auto_dispatch_deploy_envs(),
            "auto_dispatch_deploy_dry_run": config._env_flag_enabled(
                "MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"
            ),
        },
        "l4_closure": {
            "target": "L4",
            "auto_dispatch_deploy": config._auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": deployment._auto_dispatch_deploy_envs(),
            "half_closed_without_deploy": not config._auto_dispatch_deploy_enabled(),
            "open_items_count": len(state["open_items"][-20:]),
        },
    }
