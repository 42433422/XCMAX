# mypy: disable-error-code="no-any-return"
"""Final self-maintenance runtime status response builder."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _build_runtime_status_result(context):
    return {
        "ok": True,
        "cron": {
            "hour": _facade()._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3),
            "minute": _facade()._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0),
            "timezone": _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai"),
            "trigger": str(context["state"]["trigger"]),
        },
        "current_gate": context["state"]["gate"],
        "schema_version": context["runtime_contract"]["schema_version"],
        "contract": context["runtime_contract"],
        "contract_validation": context["contract_validation"],
        "contract_status": context["contract_status"],
        "source": context["runtime_source"],
        "generated_at": context["state"]["generated_at"],
        "refreshed_at": context["state"]["generated_at"],
        "latest_event_at": context["latest_event_at"],
        "evidence": {
            "ledger_path": str(_facade().ledger_path()),
            "memory_path": str(_facade().loop_memory_path()),
            "latest_complete": context["state"]["latest_complete"],
            "latest_skip": context["state"]["latest_skip"],
            "open_run_ids": context["state"]["open_run_ids"],
            "recent_rows": context["state"]["rows"][-20:],
            "milestone_rows": context["state"]["milestone_rows"],
            "milestone_window": {
                "window_days": context["state"]["evidence_window_days"],
                "scan_limit": context["state"]["evidence_scan_limit"],
                "run_limit": context["state"]["evidence_run_limit"],
                "row_limit": _facade().DEFAULT_EVIDENCE_ROW_LIMIT,
                "selected_rows": len(context["state"]["milestone_rows"]),
                "policy": "recent_meaningful_runs_excluding_heartbeat_skip_and_kb_salvage",
            },
            "steps_by_open_run": {
                context["state"]["run_id"]: context["state"]["steps_by_run"].get(
                    context["state"]["run_id"], []
                )
                for context["state"]["run_id"] in context["state"]["open_run_ids"]
            },
        },
        "participants": sorted(
            context["state"]["participants_by_id"].values(),
            key=lambda item: str(context["state"]["item"].get("latest_at") or ""),
            reverse=True,
        )[:24],
        "run_timelines": context["state"]["run_timelines"],
        "roster_alignment": context["state"]["roster_alignment"],
        "ui_bridge": context["state"]["ui_bridge"],
        "active_gates": context["state"]["active_gates"],
        "governance_gate": context["state"]["governance_gate_current"],
        "governance_audit": {
            "path": str(_facade().governance_audit_path()),
            "summary": context["state"]["governance_audit_summary"],
            "recent": context["state"]["governance_audit"],
            "last": (
                context["state"]["governance_audit"][-1]
                if context["state"]["governance_audit"]
                else None
            ),
        },
        "merge_decision": context["state"]["merge_decision"],
        "kb_summary": context["state"]["kb_summary"],
        "evolution_metrics_summary": context["state"]["evolution_metrics_summary"],
        "memory": {
            "updated_at": context["state"]["memory"].get("updated_at"),
            "last_policy_decision": context["state"]["memory"].get("last_policy_decision"),
            "last_run": context["state"]["memory"].get("last_run"),
            "open_items": context["state"]["open_items"][-20:],
            "recent_runs": context["state"]["recent_runs"][-20:],
            "run_count": context["state"]["memory"].get("run_count"),
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
            "open_items_count": len(context["state"]["open_items"][-20:]),
        },
    }
