"""Evidence-backed founder autonomy scorecard.

The scorecard deliberately treats source capability, local runtime evidence,
and deployed/value evidence as different truth domains.  Missing evidence is
scored as missing; it is never inferred from a route or a source file alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.founder_autonomy_alignment_summary import build_alignment_live_summary
from app.application.founder_autonomy_employee_summary import build_employee_live_summary
from app.application.founder_autonomy_primary_gates import build_primary_gate_sets
from app.application.founder_autonomy_projection import (
    build_public_founder_autonomy_projection,
    write_public_founder_autonomy_projection,
)
from app.application.founder_autonomy_resilience_gates import (
    build_resilience_gate_sets,
)
from app.application.founder_autonomy_support import (
    ScoreGate,
    _as_dict,
    _as_float,
    _as_int,
    _as_list,
    _build_attention_items,
    _build_dimensions,
    _correlated_deploy_evidence,
    _event_ok,
    _event_text,
    _first_number,
    _has_event,
    _is_strong_modstore_deployment,
    _latest_event_age_hours,
)


def build_founder_autonomy_snapshot(
    *,
    runtime: dict[str, Any] | None = None,
    closure: dict[str, Any] | None = None,
    approvals: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
    goals: dict[str, Any] | None = None,
    finance: dict[str, Any] | None = None,
    customer_value: dict[str, Any] | None = None,
    autonomy_audit: dict[str, Any] | None = None,
    employee_autonomy: dict[str, Any] | None = None,
    employee_capability: dict[str, Any] | None = None,
    dead_letters: dict[str, Any] | None = None,
    strategic_decisions: dict[str, Any] | None = None,
    strategic_council: dict[str, Any] | None = None,
    surfaces: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the seven-dimension founder scorecard from runtime evidence."""

    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    runtime = _as_dict(runtime)
    closure = _as_dict(closure)
    approvals = _as_dict(approvals)
    knowledge = _as_dict(knowledge)
    goals = _as_dict(goals)
    finance = _as_dict(finance)
    customer_value = _as_dict(customer_value)
    if isinstance(customer_value.get("data"), dict):
        customer_value = _as_dict(customer_value.get("data"))
    autonomy_audit = _as_dict(autonomy_audit)
    if isinstance(autonomy_audit.get("data"), dict):
        autonomy_audit = _as_dict(autonomy_audit.get("data"))
    employee_autonomy = _as_dict(employee_autonomy)
    employee_capability = _as_dict(employee_capability)
    dead_letters = _as_dict(dead_letters)
    strategic_decisions = _as_dict(strategic_decisions)
    strategic_council = _as_dict(strategic_council)
    if isinstance(strategic_council.get("data"), dict):
        strategic_council = _as_dict(strategic_council.get("data"))
    surfaces = _as_dict(surfaces)

    evidence = _as_dict(runtime.get("evidence"))
    rows = _as_list(evidence.get("recent_rows"))
    milestone_rows = _as_list(evidence.get("milestone_rows"))
    timelines = _as_list(runtime.get("run_timelines"))
    timeline_rows = [item for line in timelines for item in _as_list(_as_dict(line).get("items"))]
    all_rows = [
        *rows,
        *milestone_rows,
        *timeline_rows,
        *_as_list(_as_dict(runtime.get("governance_audit")).get("recent")),
    ]
    autonomous_triggers = {"incident_event", "proactive_signal", "scheduler"}
    autonomous_triggers.add("automated_remediation")
    autonomous_run_ids = {
        str(_as_dict(row).get("run_id") or "").strip()
        for row in all_rows
        if str(_as_dict(row).get("phase") or "").strip().lower() == "start"
        and _as_dict(row).get("force") is False
        and str(_as_dict(row).get("triggered_by") or "").strip().lower() in autonomous_triggers
        and str(_as_dict(row).get("run_id") or "").strip()
    }
    autonomy_rows = [
        row
        for row in all_rows
        if not str(_as_dict(row).get("run_id") or "").strip()
        or str(_as_dict(row).get("run_id") or "").strip() in autonomous_run_ids
    ]

    active_gates = _as_dict(runtime.get("active_gates"))
    governance_gate = _as_dict(runtime.get("governance_gate"))
    evolution_summary = _as_dict(runtime.get("evolution_metrics_summary"))
    current_gate = _as_dict(runtime.get("current_gate"))
    runtime_provenance = _as_dict(current_gate.get("runtime_provenance"))
    contract_status = _as_dict(runtime.get("contract_status"))
    latest_complete = _as_dict(evidence.get("latest_complete"))
    latest_autonomous_complete: dict[str, Any] = {}
    for row in reversed(autonomy_rows):
        item = _as_dict(row)
        if (
            str(item.get("phase") or "").strip().lower() == "complete"
            and str(item.get("run_id") or "").strip() in autonomous_run_ids
        ):
            latest_autonomous_complete = item
            break
    open_run_ids = [str(value) for value in _as_list(evidence.get("open_run_ids")) if str(value)]
    latest_age = _latest_event_age_hours(runtime, now)

    local_pending = _as_int(approvals.get("local_pending"))
    strategic_pending = _as_int(strategic_decisions.get("count"))
    pending_total = local_pending + strategic_pending
    knowledge_documents = _first_number(
        knowledge,
        (
            "documents",
            "document_count",
            "indexed_documents",
            "sources",
            "indexed_sources",
        ),
    )
    knowledge_chunks = _first_number(knowledge, ("chunks", "chunk_count", "indexed_chunks"))

    goals_total = _first_number(goals, ("total", "count", "goal_count", "items_total"))
    goals_closed = _first_number(
        goals,
        ("closed", "merged", "completed", "done", "closed_count", "completed_count"),
    )
    goal_completion_rate = _first_number(
        goals, ("completion_rate", "completed_rate", "close_rate", "success_rate")
    )
    if goal_completion_rate > 1:
        goal_completion_rate /= 100.0
    if not goal_completion_rate and goals_total:
        goal_completion_rate = min(1.0, goals_closed / goals_total)

    # Customer-value progress is intentionally isolated from the generic
    # finance summary and internal action items.  Only the authoritative,
    # append-only evidence contract may prove real payment or delivery.
    value_ledger_ready = all(
        (
            bool(customer_value.get("value_ledger_ready")),
            bool(customer_value.get("source_available")),
            bool(customer_value.get("source_authoritative")),
            bool(customer_value.get("append_only_store_available")),
        )
    )
    paid_count = _as_int(customer_value.get("verified_paid_count"))
    paid_amount = _as_int(customer_value.get("verified_paid_amount_cents"))
    customer_goals = _as_int(customer_value.get("customer_goal_count"))
    delivered_count = _as_int(customer_value.get("delivered_count"))
    unproven_delivery_count = _as_int(customer_value.get("unproven_delivery_count"))
    paid_delivery_count = _as_int(customer_value.get("paid_delivery_count"))
    paid_acceptance_count = _as_int(customer_value.get("paid_acceptance_count"))
    production_value_verified = bool(customer_value.get("production_value_verified")) and (
        paid_count > 0 or paid_amount > 0
    )
    outcome_verified = bool(customer_value.get("outcome_verified")) and paid_delivery_count > 0
    customer_acceptance_verified = (
        bool(customer_value.get("customer_acceptance_verified")) and paid_acceptance_count > 0
    )
    customer_value_excluded = _as_dict(customer_value.get("excluded"))

    audit_total = _as_int(autonomy_audit.get("total"))
    veto_rate = _as_float(autonomy_audit.get("veto_rate"))
    if 0 < veto_rate <= 1:
        veto_rate *= 100.0
    prohibited_miss_raw = autonomy_audit.get("has_prohibited_miss")
    prohibited_miss = prohibited_miss_raw is True
    prohibited_clear = prohibited_miss_raw is False
    audit_available = all(
        (
            bool(autonomy_audit.get("source_authoritative")),
            bool(autonomy_audit.get("append_only")),
            bool(autonomy_audit.get("append_only_enforced")),
        )
    )
    audit_has_rows = audit_available and audit_total > 0
    veto_channel = _as_dict(autonomy_audit.get("veto_channel"))
    veto_channel_available = bool(veto_channel.get("available"))
    veto_pending = _as_int(veto_channel.get("pending_count"))

    planned = _as_int(employee_capability.get("planned_count")) or _as_int(
        _as_dict(closure.get("staffing")).get("planned_count")
    )
    registered = _as_int(_as_dict(closure.get("staffing")).get("registered_count"))
    participants = _as_list(runtime.get("participants"))
    employee_dashboard_ok = bool(employee_autonomy) and not bool(employee_autonomy.get("error"))
    assigned_employees = _as_int(employee_capability.get("assigned_count"))
    proven_employees = _as_int(employee_capability.get("proven_count"))
    burn_in_proven_employees = _as_int(employee_capability.get("burn_in_proven_count"))
    production_proven_employees = _as_int(employee_capability.get("production_proven_count"))
    shell_employees = _as_int(employee_capability.get("shell_count"))
    workforce_ready = bool(employee_capability.get("workforce_ready"))
    production_workforce_ready = bool(employee_capability.get("production_workforce_ready"))
    workforce_assigned = bool(planned) and assigned_employees >= max(1, round(planned * 0.95))
    unresolved_dead_letters = _as_int(dead_letters.get("unresolved_count"))
    resolved_dead_letters = _as_int(dead_letters.get("resolved_count"))
    dead_letter_evidence = "unresolved_count" in dead_letters
    dead_letters_healthy = (
        dead_letter_evidence and bool(dead_letters.get("ok")) and unresolved_dead_letters == 0
    )

    cron_ok = bool(runtime.get("cron"))
    runtime_fresh = latest_age is not None and latest_age <= 6
    runtime_provenance_ok = runtime_provenance.get("ok") is True
    contract_trusted = bool(contract_status.get("global_ok"))
    gates_clear = bool(active_gates.get("ok"))
    governance_clear = bool(governance_gate.get("ok"))
    has_open_run = bool(open_run_ids)
    latest_completed = str(latest_autonomous_complete.get("status") or "").startswith("completed")
    latest_merged = "merged" in str(latest_autonomous_complete.get("status") or "").lower()

    wrote = _has_event(autonomy_rows, "code", "success")
    reviewed = _has_event(autonomy_rows, "review", "success")
    qa_passed = _has_event(autonomy_rows, "qa", "success") or _has_event(
        autonomy_rows, "qa", "pass"
    )
    merged = latest_merged or _has_event(autonomy_rows, "completed_merged")
    deploy_attempted = _has_event(autonomy_rows, "deploy_dispatch", require_ok=False)
    accepted_deploys, verified_deploys = _correlated_deploy_evidence(autonomy_rows)
    real_deploy_dispatched = bool(accepted_deploys)
    deploy_verified = any(
        str(row.get("environment") or "").lower() == "production" for row in verified_deploys
    )

    incident_count = _as_int(current_gate.get("incident_count"))
    incident_triggered = incident_count > 0 or _has_event(
        all_rows, "incident_event", require_ok=False
    )
    incident_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if "incident" in _event_text(row) and str(_as_dict(row).get("run_id") or "")
    }
    repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if _event_ok(row)
        and "code" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in incident_run_ids
    }
    completed_repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if str(_as_dict(row).get("status") or "") in {"completed_merged", "completed"}
        and str(_as_dict(row).get("run_id") or "") in repair_run_ids
    }
    verified_repair_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if _event_ok(row)
        and str(_as_dict(row).get("run_id") or "") in completed_repair_run_ids
        and any(token in _event_text(row) for token in ("verified", "recovered", "healthy"))
    }
    repair_started = bool(repair_run_ids)
    repair_completed = bool(completed_repair_run_ids)
    repair_verified = bool(verified_repair_run_ids)

    proactive_signals = _as_dict(current_gate.get("proactive_signals"))
    proactive_count = _as_int(current_gate.get("proactive_task_count"))
    proactive_detected = proactive_count > 0 or bool(_as_list(proactive_signals.get("candidates")))
    workforce_gaps = _as_list(proactive_signals.get("workforce_gaps"))
    workforce_gap_count = _as_int(proactive_signals.get("workforce_gap_count")) or len(
        workforce_gaps
    )
    planned_workforce_remediations = sum(
        1
        for raw_gap in workforce_gaps
        if str(_as_dict(raw_gap).get("employee_id") or "").strip()
        and str(_as_dict(_as_dict(raw_gap).get("remediation")).get("task_id") or "").strip()
        and bool(_as_list(_as_dict(_as_dict(raw_gap).get("remediation")).get("target_files")))
        and _as_dict(_as_dict(raw_gap).get("remediation")).get("closure_event")
        == "later_strict_burnin_receipt_accepted"
        and _as_dict(_as_dict(raw_gap).get("remediation")).get("auto_close") is False
    )
    evolution_implementation_gap = (
        f"执行已生成的 {planned_workforce_remediations} 个员工能力修复工单，"
        "并取得后续严格试运行回执"
        if planned_workforce_remediations > 0
        else "将能力缺口变成可执行实现"
    )
    evolution_history = _as_int(evolution_summary.get("history_count"))
    kb_summary = _as_dict(runtime.get("kb_summary"))
    reusable_knowledge = _first_number(kb_summary, ("fix_count", "pattern_count", "total")) > 0
    proactive_run_ids = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if any(token in _event_text(row) for token in ("proactive", "evolution"))
        and str(_as_dict(row).get("run_id") or "")
    }
    proactive_code_runs = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if _event_ok(row)
        and "code" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in proactive_run_ids
    }
    proactive_qa_runs = {
        str(_as_dict(row).get("run_id") or "")
        for row in autonomy_rows
        if _event_ok(row)
        and "qa" in _event_text(row)
        and str(_as_dict(row).get("run_id") or "") in proactive_run_ids
    }
    evolution_implemented = bool(proactive_code_runs & proactive_qa_runs)
    employee_pack_built = _has_event(autonomy_rows, "employee_pack", "built") or _has_event(
        autonomy_rows, "pack", "registered"
    )
    modstore_deployed = any(_is_strong_modstore_deployment(row) for row in autonomy_rows)
    council_roles = _as_dict(strategic_council.get("roles"))
    council_latest = _as_dict(strategic_council.get("latest_receipt"))
    retort_clarifications = _as_dict(strategic_council.get("retort_clarifications"))
    retort_open = _as_int(retort_clarifications.get("open_count"))
    retort_critical = _as_int(retort_clarifications.get("critical_count"))
    retort_healthy = (
        bool(retort_clarifications.get("healthy"))
        if "healthy" in retort_clarifications
        else retort_open == 0
    )
    council_ready = (
        bool(strategic_council.get("ready"))
        and all(
            _as_dict(council_roles.get(role)).get("status") == expected
            for role, expected in (
                ("persy", "grounded"),
                ("para", "linked"),
                ("retort", "aligned"),
            )
        )
        and _as_dict(council_roles.get("retort")).get("engine_available") is True
    )

    founder_gates, system_gates, customer_gates, code_gates = build_primary_gate_sets(locals())
    fault_gates, evolution_gates, alignment_gates = build_resilience_gate_sets(locals())

    dimensions = _build_dimensions(
        founder_gates=founder_gates,
        system_gates=system_gates,
        customer_gates=customer_gates,
        code_gates=code_gates,
        fault_gates=fault_gates,
        evolution_gates=evolution_gates,
        alignment_gates=alignment_gates,
        workforce_ready=workforce_ready,
        founder_workforce_ready=production_workforce_ready,
        pending_total=pending_total,
        governance_clear=governance_clear,
        runtime_provenance_ok=runtime_provenance_ok,
        gates_clear=gates_clear,
        paid_count=paid_count,
        paid_amount=paid_amount,
        deploy_verified=deploy_verified,
        repair_verified=repair_verified,
        modstore_deployed=modstore_deployed,
    )
    overall = round(sum(item["progress"] for item in dimensions) / len(dimensions))
    attention_items = _build_attention_items(
        local_pending=local_pending,
        strategic_pending=strategic_pending,
        governance_clear=governance_clear,
        governance_reason=str(governance_gate.get("reason") or ""),
        runtime_provenance_ok=runtime_provenance_ok,
        open_run_ids=open_run_ids,
        veto_pending=veto_pending,
        prohibited_miss=prohibited_miss,
        planned=planned,
        proven_employees=production_proven_employees,
        shell_employees=shell_employees,
        retort_open=retort_open,
        retort_critical=retort_critical,
    )

    return {
        "schema_version": "founder_autonomy_status.v1",
        "generated_at": now.isoformat(),
        "overall_progress": overall,
        "overall_remaining": 100 - overall,
        "target_state": "founder_strategic_only",
        "dimensions": dimensions,
        "attention": {
            "total": sum(_as_int(item.get("count")) for item in attention_items),
            "items": attention_items,
            "human_intervention_rare": pending_total <= 5
            and retort_open == 0
            and governance_clear
            and production_workforce_ready
            and runtime_provenance_ok,
        },
        "live_summary": {
            "runtime_ok": bool(runtime.get("ok")),
            "runtime_fresh": runtime_fresh,
            "runtime_provenance_ok": runtime_provenance_ok,
            "runtime_provenance_source": runtime_provenance.get("source"),
            "runtime_provenance_reasons": _as_list(runtime_provenance.get("reasons")),
            "latest_event_at": runtime.get("latest_event_at"),
            "latest_complete_status": latest_complete.get("status"),
            "latest_autonomous_complete_status": latest_autonomous_complete.get("status"),
            "autonomous_run_count": len(autonomous_run_ids),
            "open_run_ids": open_run_ids,
            "milestone_evidence_rows": len(milestone_rows),
            "milestone_evidence_window": _as_dict(evidence.get("milestone_window")),
            "active_gates_ok": gates_clear,
            "blocking_gate_keys": _as_list(active_gates.get("blocking_keys")),
            "governance_ok": governance_clear,
            "governance_summary": _as_dict(governance_gate.get("summary")),
            **build_employee_live_summary(employee_capability, locals()),
            "loop_participants": len(participants),
            "goals_total": int(goals_total),
            "goals_closed": int(goals_closed),
            "customer_goals": customer_goals,
            "customer_deliveries": delivered_count,
            "unproven_customer_deliveries": unproven_delivery_count,
            "paid_delivery_count": paid_delivery_count,
            "paid_acceptance_count": paid_acceptance_count,
            "customer_acceptance_verified": customer_acceptance_verified,
            "customer_value_ledger_ready": value_ledger_ready,
            "customer_value_excluded": customer_value_excluded,
            "knowledge_documents": int(knowledge_documents),
            "knowledge_chunks": int(knowledge_chunks),
            "workforce_capability_gap_count": workforce_gap_count,
            "planned_workforce_remediations": planned_workforce_remediations,
            "paid_count": int(paid_count),
            "paid_amount_cents": int(paid_amount),
            "production_value_verified": production_value_verified,
            "outcome_verified": outcome_verified,
            **build_alignment_live_summary(
                autonomy_audit,
                audit_available=audit_available,
                audit_total=audit_total,
                prohibited_miss=prohibited_miss,
                veto_rate=veto_rate,
            ),
            "veto_channel_available": veto_channel_available,
            "veto_pending": veto_pending,
            "deploy_attempted": deploy_attempted,
            "real_deploy_dispatched": real_deploy_dispatched,
            "deploy_verified": deploy_verified,
            "accepted_deploy_receipts": len(accepted_deploys),
            "verified_deploy_receipts": len(verified_deploys),
            "employee_autonomy_available": employee_dashboard_ok,
            "dead_letters_healthy": dead_letters_healthy,
            "unresolved_dead_letters": unresolved_dead_letters,
            "resolved_dead_letters": resolved_dead_letters,
            "strategic_council_ready": council_ready,
            "strategic_council_receipts": _as_int(strategic_council.get("verified_receipt_count")),
            "strategic_council_roles": council_roles,
            "strategic_council_latest": council_latest,
            "retort_clarifications_open": retort_open,
            "retort_clarifications_critical": retort_critical,
            "retort_clarifications_healthy": retort_healthy,
        },
        "truth_domains": {
            "source_capability": {"available": True, "label": "当前源码能力"},
            "local_runtime": {
                "available": bool(runtime.get("ok")),
                "label": "本机实际运行",
            },
            "deployment_runtime": {
                "available": real_deploy_dispatched or deploy_attempted,
                "label": "部署派发/验证",
            },
            "production_value": {
                "available": outcome_verified,
                "label": "真实客户付费与价值",
            },
        },
    }


__all__ = [
    "ScoreGate",
    "build_founder_autonomy_snapshot",
    "build_public_founder_autonomy_projection",
    "write_public_founder_autonomy_projection",
]
