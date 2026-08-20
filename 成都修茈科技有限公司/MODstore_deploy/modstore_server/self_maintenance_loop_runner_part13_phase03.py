"""Self-maintenance runtime status rendering phase."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _runtime_status_phase_03(state):
    latest_timestamp = _facade()._ledger_row_timestamp(state["rows"][-1]) if state["rows"] else None
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
        state["remediation"] = _contract_surface_remediation(surface, missing)
        contract_surface_readiness[surface] = {
            "ok": not missing,
            "required": requirements,
            "missing": missing,
            "action": state["remediation"]["action"],
            "title": state["remediation"]["title"],
            "detail": state["remediation"]["detail"],
            "severity": state["remediation"]["severity"],
            "target_surface": state["remediation"].get("target_surface") or surface,
            "target_view": state["remediation"].get("target_view") or "loop",
            "requires_admin": state["remediation"].get("requires_admin") is True,
            "executable": state["remediation"].get("executable") is True,
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

    def _contract_incident_priority(item: _facade().Dict[str, _facade().Any]) -> tuple:
        severity_rank = {"bad": 0, "warn": 1, "ok": 2}
        surface_rank = {
            "duty_roster_graph": 0,
            "self_evolution_loop_runtime": 1,
            "employee_space": 2,
        }
        return (
            severity_rank.get(str(state["item"].get("severity") or "unknown"), 9),
            0 if state["item"].get("executable") else 1,
            0 if state["item"].get("requires_admin") else 1,
            surface_rank.get(str(state["item"].get("surface") or ""), 9),
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
            {
                str(state["item"].get("surface"))
                for state["item"] in contract_surface_incidents
                if state["item"].get("surface")
            }
        ),
        "actions": sorted(
            {
                str(state["item"].get("action"))
                for state["item"] in contract_surface_incidents
                if state["item"].get("action")
            }
        ),
        "by_severity": {
            severity: sum(
                (
                    1
                    for state["item"] in contract_surface_incidents
                    if state["item"].get("severity") == severity
                )
            )
            for severity in sorted(
                {
                    str(state["item"].get("severity") or "unknown")
                    for state["item"] in contract_surface_incidents
                }
            )
        },
        "requires_admin_count": sum(
            (
                1
                for state["item"] in contract_surface_incidents
                if state["item"].get("requires_admin")
            )
        ),
        "executable_count": sum(
            (1 for state["item"] in contract_surface_incidents if state["item"].get("executable"))
        ),
        "admin_required": any(
            (
                bool(state["item"].get("requires_admin"))
                for state["item"] in contract_surface_incidents
            )
        ),
        "executable_available": any(
            (bool(state["item"].get("executable")) for state["item"] in contract_surface_incidents)
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
    from modstore_server.self_maintenance_runtime_status_result import (
        _build_runtime_status_result,
    )

    return _build_runtime_status_result(locals())
