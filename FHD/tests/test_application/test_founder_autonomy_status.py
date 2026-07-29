from __future__ import annotations

from datetime import UTC, datetime

from app.application.founder_autonomy_status import (
    build_founder_autonomy_snapshot,
    build_public_founder_autonomy_projection,
    write_public_founder_autonomy_projection,
)

NOW = datetime(2026, 7, 22, 4, 30, tzinfo=UTC)


def _dimensions(snapshot: dict) -> dict[str, dict]:
    return {row["id"]: row for row in snapshot["dimensions"]}


def _surfaces() -> dict[str, bool]:
    return {
        "founder_cockpit": True,
        "approval_center": True,
        "knowledge_base": True,
        "ai_employees": True,
        "goals": True,
        "loops": True,
    }


def _ready_workforce(count: int = 55) -> dict:
    return {
        "planned_count": count,
        "assigned_count": count,
        "proven_count": count,
        "shell_count": 0,
        "assignment_ratio": 1.0,
        "proof_ratio": 1.0,
        "workforce_ready": True,
    }


def _ready_customer_value(**overrides) -> dict:
    evidence = {
        "schema": "customer_value_evidence.v1",
        "value_ledger_ready": True,
        "source_available": True,
        "source_authoritative": True,
        "append_only_store_available": True,
        "verified_paid_count": 2,
        "verified_paid_amount_cents": 10000,
        "customer_goal_count": 10,
        "delivered_count": 9,
        "unproven_delivery_count": 0,
        "paid_delivery_count": 2,
        "paid_acceptance_count": 1,
        "production_value_verified": True,
        "outcome_verified": True,
        "customer_acceptance_verified": True,
        "excluded": {"test_record": 3, "internal_order": 1},
    }
    evidence.update(overrides)
    return evidence


def _ready_council(**overrides) -> dict:
    payload = {
        "ready": True,
        "verified_receipt_count": 1,
        "roles": {
            "persy": {"status": "grounded"},
            "para": {"status": "linked"},
            "retort": {"status": "aligned", "engine_available": True},
        },
        "latest_receipt": {
            "receipt_id": "council-1",
            "goal_id": "goal-1",
            "loop_run_id": "loop-1",
            "para_task_id": "para-1",
        },
        "retort_clarifications": {
            "ok": True,
            "open_count": 0,
            "critical_count": 0,
            "healthy": True,
        },
    }
    payload.update(overrides)
    return payload


def test_missing_evidence_is_not_reported_as_finished() -> None:
    snapshot = build_founder_autonomy_snapshot(generated_at=NOW)
    dims = _dimensions(snapshot)

    assert snapshot["overall_progress"] < 20
    assert dims["system"]["progress"] == 0
    assert dims["code"]["progress"] == 0
    assert dims["customer"]["progress"] == 0
    assert snapshot["truth_domains"]["local_runtime"]["available"] is False
    assert dims["code"]["remaining"] == 100


def test_complete_evidence_can_reach_the_target_band() -> None:
    rows = [
        {
            "run_id": "incident-1",
            "phase": "start",
            "status": "running",
            "triggered_by": "incident_event",
            "force": False,
        },
        {
            "run_id": "incident-1",
            "phase": "step",
            "step": "code",
            "status": "success",
            "triggered_by": "incident_event",
            "ok": True,
        },
        {"phase": "step", "step": "review", "status": "success", "ok": True},
        {
            "phase": "step",
            "step": "qa",
            "status": "success",
            "qa_verdict": "PASS",
            "ok": True,
        },
        {
            "run_id": "incident-1",
            "phase": "complete",
            "status": "completed_merged",
            "triggered_by": "incident_event",
        },
        {
            "run_id": "incident-1",
            "event": "deploy_dispatch",
            "environment": "production",
            "status": "accepted",
            "ok": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-101",
        },
        {
            "run_id": "incident-1",
            "event": "post_deploy_verified",
            "environment": "production",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-101",
        },
        {
            "run_id": "incident-1",
            "event": "incident_recovered_verified",
            "triggered_by": "incident_event",
            "status": "healthy",
            "ok": True,
        },
        {
            "run_id": "evolution-1",
            "phase": "start",
            "triggered_by": "proactive_signal",
            "force": False,
            "status": "running",
        },
        {
            "run_id": "evolution-1",
            "step": "code",
            "triggered_by": "proactive_signal",
            "status": "success",
            "ok": True,
        },
        {
            "run_id": "evolution-1",
            "step": "qa",
            "triggered_by": "proactive_signal",
            "status": "success",
            "ok": True,
        },
        {"event": "employee_pack_built", "status": "success", "ok": True},
        {
            "event_type": "modstore_deployment_verified",
            "environment": "production",
            "status": "verified",
            "ok": True,
            "dry_run": False,
            "catalog_readback_verified": True,
            "installability_verified": True,
            "runtime_contract_verified": True,
            "strategic_council_verified": True,
            "package_id": "evolved-capability",
            "version": "1.0.0",
            "package_sha256": "b" * 64,
        },
    ]
    runtime = {
        "ok": True,
        "cron": {"hour": 3, "minute": 0},
        "latest_event_at": NOW.isoformat(),
        "contract_status": {"global_ok": True},
        "active_gates": {"ok": True, "blocking_keys": []},
        "governance_gate": {"ok": True, "summary": {"health": "good"}},
        "current_gate": {
            "incident_count": 2,
            "proactive_task_count": 3,
            "runtime_provenance": {
                "ok": True,
                "source": "immutable_manifest",
                "reasons": [],
            },
        },
        "evolution_metrics_summary": {"history_count": 2},
        "kb_summary": {"fix_count": 3, "pattern_count": 2},
        "participants": [{"employee_id": "writer"}, {"employee_id": "reviewer"}],
        "run_timelines": [],
        "evidence": {
            "recent_rows": rows,
            "open_run_ids": [],
            "latest_complete": {"status": "completed_merged"},
        },
    }
    snapshot = build_founder_autonomy_snapshot(
        runtime=runtime,
        closure={
            "deliverable": True,
            "staffing": {"planned_count": 52, "registered_count": 52},
        },
        approvals={"local_pending": 0},
        knowledge={"success": True, "document_count": 8, "chunk_count": 80},
        goals={"total": 10, "closed": 9, "completion_rate": 0.9},
        finance={"success": True, "paid_count": 2, "paid_amount_cents": 10000},
        customer_value=_ready_customer_value(),
        autonomy_audit={
            "total": 100,
            "veto_rate": 3.0,
            "has_prohibited_miss": False,
            "prohibited_miss_evidence_status": "verified_clear",
            "posthoc_coverage_rate": 100.0,
            "source_authoritative": True,
            "append_only": True,
            "append_only_enforced": True,
            "veto_channel": {"available": True, "pending_count": 0},
        },
        employee_autonomy={"ok": True},
        employee_capability=_ready_workforce(),
        dead_letters={"ok": True, "unresolved_count": 0, "resolved_count": 4},
        strategic_decisions={"count": 0},
        strategic_council=_ready_council(),
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    dims = _dimensions(snapshot)

    assert snapshot["overall_progress"] >= 90
    assert all(row["progress"] >= 90 for row in dims.values())
    assert snapshot["attention"]["human_intervention_rare"] is True
    assert snapshot["live_summary"]["deploy_verified"] is True
    assert snapshot["truth_domains"]["production_value"]["available"] is True
    assert snapshot["live_summary"]["employee_workforce_ready"] is True
    assert snapshot["live_summary"]["dead_letters_healthy"] is True
    assert snapshot["live_summary"]["retort_clarifications_healthy"] is True


def test_retort_clarification_backlog_surfaces_in_attention() -> None:
    snapshot = build_founder_autonomy_snapshot(
        strategic_council=_ready_council(
            retort_clarifications={
                "ok": True,
                "open_count": 2,
                "critical_count": 1,
                "healthy": False,
            }
        ),
        generated_at=NOW,
    )
    kinds = {item["kind"] for item in snapshot["attention"]["items"]}
    assert "retort_clarification" in kinds
    assert snapshot["live_summary"]["retort_clarifications_open"] == 2
    assert snapshot["live_summary"]["retort_clarifications_critical"] == 1
    assert snapshot["live_summary"]["retort_clarifications_healthy"] is False
    assert snapshot["attention"]["human_intervention_rare"] is False


def test_runtime_holds_apply_hard_caps_and_surface_attention() -> None:
    runtime = {
        "ok": True,
        "cron": {"hour": 3},
        "latest_event_at": NOW.isoformat(),
        "contract_status": {"global_ok": True},
        "active_gates": {"ok": False, "blocking_keys": ["governance"]},
        "governance_gate": {
            "ok": False,
            "reason": "governance_audit_consecutive_failures",
            "summary": {"success_count": 7, "failure_count": 3},
        },
        "current_gate": {"incident_count": 2, "proactive_task_count": 3},
        "participants": [{"employee_id": "writer"}],
        "evolution_metrics_summary": {"history_count": 0},
        "evidence": {
            "open_run_ids": ["run-open"],
            "latest_complete": {"status": "completed_held_for_remediation"},
            "recent_rows": [
                {"step": "code", "status": "success", "ok": True},
                {"step": "review", "status": "success", "ok": True},
                {"step": "qa", "status": "success", "qa_verdict": "PASS", "ok": True},
                {"status": "completed_merged"},
                {
                    "event": "deploy_dispatch",
                    "environment": "production",
                    "status": "success",
                    "reason": "dry_run_skipped",
                    "ok": True,
                },
            ],
        },
    }
    snapshot = build_founder_autonomy_snapshot(
        runtime=runtime,
        closure={
            "deliverable": True,
            "staffing": {"planned_count": 52, "registered_count": 52},
        },
        approvals={"local_pending": 8},
        strategic_decisions={"count": 2},
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    dims = _dimensions(snapshot)

    assert dims["founder"]["progress"] <= 80
    assert dims["system"]["progress"] <= 60
    assert dims["code"]["progress"] <= 65
    assert dims["alignment"]["progress"] <= 65
    assert dims["fault"]["progress"] == 35
    assert dims["evolution"]["progress"] == 15
    assert snapshot["live_summary"]["real_deploy_dispatched"] is False
    assert snapshot["live_summary"]["deploy_attempted"] is True
    assert snapshot["attention"]["human_intervention_rare"] is False
    assert any(item["kind"] == "governance" for item in snapshot["attention"]["items"])


def test_planned_workforce_gap_changes_next_step_without_inflating_score() -> None:
    runtime = {
        "ok": True,
        "latest_event_at": NOW.isoformat(),
        "current_gate": {
            "proactive_task_count": 1,
            "proactive_signals": {
                "workforce_gap_count": 1,
                "workforce_gaps": [
                    {
                        "employee_id": "host-checker",
                        "remediation": {
                            "task_id": "workforce-gap-aaaaaaaaaaaaaaaa",
                            "target_files": ["FHD/mods/_employees/host-checker/manifest.json"],
                            "closure_event": "later_strict_burnin_receipt_accepted",
                            "auto_close": False,
                        },
                    }
                ],
                "candidates": [{"kind": "workforce_capability_gap"}],
            },
        },
        "evolution_metrics_summary": {"history_count": 1},
        "kb_summary": {"fix_count": 1, "pattern_count": 1},
        "evidence": {"recent_rows": [], "open_run_ids": []},
    }

    snapshot = build_founder_autonomy_snapshot(runtime=runtime, generated_at=NOW)
    evolution = _dimensions(snapshot)["evolution"]

    assert evolution["progress"] == 40
    assert evolution["next_gap"] == ("执行已生成的 1 个员工能力修复工单，并取得后续严格试运行回执")
    assert snapshot["live_summary"]["workforce_capability_gap_count"] == 1
    assert snapshot["live_summary"]["planned_workforce_remediations"] == 1


def test_retort_receipt_without_engine_does_not_pass_council_gates() -> None:
    council = _ready_council()
    council["roles"]["retort"]["engine_available"] = False

    snapshot = build_founder_autonomy_snapshot(
        strategic_council=council,
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    dims = _dimensions(snapshot)

    assert snapshot["live_summary"]["strategic_council_ready"] is False
    for dimension_id in ("founder", "evolution", "alignment"):
        assert "council" in {gate["key"] for gate in dims[dimension_id]["gaps"]}


def test_public_projection_is_sanitized_and_written_to_all_site_targets(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "ok": True,
            "latest_event_at": NOW.isoformat(),
            "active_gates": {"ok": False, "blocking_keys": ["secret-gate"]},
            "governance_gate": {"ok": False, "reason": "internal-reason"},
            "evidence": {"open_run_ids": ["private-run-id"]},
        },
        approvals={"local_pending": 1},
        customer_value=_ready_customer_value(verified_paid_amount_cents=999999),
        autonomy_audit={
            "source_authoritative": True,
            "append_only": True,
            "append_only_enforced": True,
            "total": 4,
            "allow_count": 3,
            "posthoc_conclusive_count": 2,
            "posthoc_uncovered_count": 1,
            "posthoc_coverage_rate": 66.67,
            "prohibited_miss_evidence_status": "unknown",
            "posthoc_uncovered_contracts": [
                {
                    "action": "daily_digest",
                    "source": "daily_digest.cron",
                    "count": 1,
                }
            ],
        },
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    public = build_public_founder_autonomy_projection(snapshot)
    body = str(public)

    assert public["schema"] == "xcagi.public_founder_autonomy/v1"
    assert len(public["dimensions"]) == 7
    assert public["proof"]["paid_value_verified"] is True
    assert public["proof"]["paid_delivery_verified"] is True
    assert public["proof"]["customer_acceptance_verified"] is True
    assert public["proof"]["runtime_provenance_ok"] is False
    assert public["proof"]["employee_workforce_ready"] is False
    assert public["proof"]["alignment_posthoc"] == {
        "status": "unknown",
        "coverage_rate": 66.67,
        "allow_count": 3,
        "conclusive_count": 2,
        "uncovered_count": 1,
        "uncovered_contracts": [
            {
                "action": "daily_digest",
                "source": "daily_digest.cron",
                "count": 1,
            }
        ],
    }
    assert "private-run-id" not in body
    assert "secret-gate" not in body
    assert "999999" not in body

    company = tmp_path / "成都修茈科技有限公司"
    market = company / "MODstore_deploy" / "market" / "public"
    live = tmp_path / "live-site"
    company.mkdir(parents=True)
    market.mkdir(parents=True)
    live.mkdir()
    monkeypatch.setenv("XCMAX_PUBLIC_SITE_LIVE_ROOTS", str(live))
    result = write_public_founder_autonomy_projection(snapshot, repo_root=tmp_path)

    assert result["ok"] is True
    assert len(result["written"]) == 3
    assert (company / "download-founder-autonomy.json").is_file()
    assert (market / "download-founder-autonomy.json").is_file()
    assert (live / "download-founder-autonomy.json").is_file()


def test_generic_finance_and_action_items_cannot_impersonate_customer_value() -> None:
    snapshot = build_founder_autonomy_snapshot(
        goals={"total": 99, "closed": 99, "completion_rate": 1.0},
        finance={"paid_count": 99, "paid_amount_cents": 999999},
        employee_capability=_ready_workforce(),
        generated_at=NOW,
    )
    customer = _dimensions(snapshot)["customer"]

    assert customer["progress"] == 10
    assert snapshot["live_summary"]["paid_count"] == 0
    assert snapshot["truth_domains"]["production_value"]["available"] is False


def test_untrusted_runtime_provenance_caps_founder_and_system_truth() -> None:
    runtime = {
        "ok": True,
        "cron": {"hour": 3},
        "latest_event_at": NOW.isoformat(),
        "contract_status": {"global_ok": True},
        "active_gates": {"ok": True, "blocking_keys": []},
        "governance_gate": {"ok": True},
        "current_gate": {
            "runtime_provenance": {
                "ok": False,
                "source": "git_checkout",
                "reasons": ["dirty_worktree", "head_sha_mismatch"],
            }
        },
        "participants": [{"employee_id": "writer"}],
        "evidence": {
            "open_run_ids": [],
            "latest_complete": {"run_id": "scheduler-run", "status": "completed"},
            "recent_rows": [
                {
                    "run_id": "scheduler-run",
                    "phase": "start",
                    "status": "running",
                    "triggered_by": "scheduler",
                    "force": False,
                },
                {
                    "run_id": "scheduler-run",
                    "step": "code",
                    "status": "success",
                    "ok": True,
                },
                {
                    "run_id": "scheduler-run",
                    "step": "review",
                    "status": "success",
                    "ok": True,
                },
                {
                    "run_id": "scheduler-run",
                    "step": "qa",
                    "status": "success",
                    "ok": True,
                },
                {
                    "run_id": "scheduler-run",
                    "phase": "complete",
                    "status": "completed",
                },
            ],
        },
    }
    snapshot = build_founder_autonomy_snapshot(
        runtime=runtime,
        closure={"staffing": {"planned_count": 55, "registered_count": 55}},
        goals={"total": 1},
        employee_capability=_ready_workforce(),
        strategic_council=_ready_council(),
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    dims = _dimensions(snapshot)

    assert dims["founder"]["progress"] <= 85
    assert dims["system"]["progress"] == 85
    assert snapshot["attention"]["human_intervention_rare"] is False
    assert snapshot["live_summary"]["runtime_provenance_ok"] is False
    assert snapshot["live_summary"]["runtime_provenance_reasons"] == [
        "dirty_worktree",
        "head_sha_mismatch",
    ]
    assert any(item["kind"] == "runtime_provenance" for item in snapshot["attention"]["items"])


def test_empty_authoritative_customer_ledger_only_proves_ledger_and_capacity() -> None:
    snapshot = build_founder_autonomy_snapshot(
        customer_value=_ready_customer_value(
            verified_paid_count=0,
            verified_paid_amount_cents=0,
            customer_goal_count=0,
            delivered_count=0,
            paid_delivery_count=0,
            production_value_verified=False,
            outcome_verified=False,
        ),
        employee_capability=_ready_workforce(),
        generated_at=NOW,
    )
    customer = _dimensions(snapshot)["customer"]

    assert customer["progress"] == 25
    assert {gate["key"] for gate in customer["evidence"]} == {
        "value_ledger",
        "capacity",
    }
    assert snapshot["live_summary"]["customer_value_ledger_ready"] is True


def test_unrelated_or_staging_only_deploy_receipts_do_not_prove_production() -> None:
    rows = [
        {
            "run_id": "run-a",
            "phase": "start",
            "status": "running",
            "triggered_by": "scheduler",
            "force": False,
        },
        {
            "run_id": "run-a",
            "event": "deploy_dispatch",
            "environment": "staging",
            "status": "accepted",
            "ok": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-a",
        },
        {
            "run_id": "run-b",
            "phase": "start",
            "status": "running",
            "triggered_by": "scheduler",
            "force": False,
        },
        {
            "run_id": "run-b",
            "event": "post_deploy_verified",
            "environment": "staging",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-b",
        },
    ]
    snapshot = build_founder_autonomy_snapshot(
        runtime={"evidence": {"recent_rows": rows}},
        generated_at=NOW,
    )

    assert snapshot["live_summary"]["real_deploy_dispatched"] is True
    assert snapshot["live_summary"]["verified_deploy_receipts"] == 0
    assert snapshot["live_summary"]["deploy_verified"] is False


def test_unknown_prohibited_miss_evidence_never_counts_as_verified_clear() -> None:
    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "contract_status": {"global_ok": True},
            "governance_gate": {"ok": True},
        },
        autonomy_audit={
            "total": 4,
            "veto_rate": 0.0,
            "has_prohibited_miss": None,
            "prohibited_miss_evidence_status": "unknown",
            "posthoc_coverage_rate": 0.0,
            "source_authoritative": True,
            "append_only": True,
            "append_only_enforced": True,
            "veto_channel": {"available": True, "pending_count": 0},
        },
        surfaces=_surfaces(),
        generated_at=NOW,
    )
    alignment = _dimensions(snapshot)["alignment"]
    passed = {gate["key"] for gate in alignment["evidence"]}

    assert "audit" in passed
    assert "veto" in passed
    assert "rare" in passed
    assert "prohibited" not in passed
    assert "self_policy" not in passed
    assert snapshot["live_summary"]["prohibited_miss_status"] == "unknown"


def test_strong_modstore_deployment_event_fields_prove_publish_gate() -> None:
    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "evidence": {
                "recent_rows": [
                    {
                        "event_type": "modstore_deployment_verified",
                        "environment": "production",
                        "final_status": "verified",
                        "deployment_state": "catalog_install_verified",
                        "ok": True,
                        "dry_run": False,
                        "catalog_readback_verified": True,
                        "installability_verified": True,
                        "runtime_contract_verified": True,
                        "strategic_council_verified": True,
                        "package_id": "evolved-capability",
                        "version": "1.0.0",
                        "package_sha256": "c" * 64,
                    }
                ]
            }
        },
        generated_at=NOW,
    )
    evolution = _dimensions(snapshot)["evolution"]

    assert "publish" in {gate["key"] for gate in evolution["evidence"]}


def test_time_bounded_milestones_survive_idle_feed_churn() -> None:
    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "evidence": {
                "recent_rows": [
                    {
                        "phase": "heartbeat",
                        "status": "heartbeat_idle",
                    }
                ],
                "milestone_rows": [
                    {
                        "run_id": "recent-work",
                        "phase": "start",
                        "status": "running",
                        "triggered_by": "scheduler",
                        "force": False,
                    },
                    {
                        "run_id": "recent-work",
                        "phase": "step",
                        "step": "code",
                        "status": "success",
                        "ok": True,
                    },
                    {
                        "run_id": "recent-work",
                        "phase": "step",
                        "step": "review",
                        "status": "success",
                        "ok": True,
                    },
                    {
                        "run_id": "recent-work",
                        "phase": "step",
                        "step": "qa",
                        "status": "success",
                        "ok": True,
                    },
                ],
                "milestone_window": {
                    "window_days": 30,
                    "selected_rows": 4,
                },
            }
        },
        generated_at=NOW,
    )
    code = _dimensions(snapshot)["code"]

    assert {gate["key"] for gate in code["evidence"]} == {
        "write",
        "review",
        "qa",
    }
    assert snapshot["live_summary"]["milestone_evidence_rows"] == 4
    assert snapshot["live_summary"]["milestone_evidence_window"]["window_days"] == 30


def test_forced_history_cannot_inflate_unattended_code_progress() -> None:
    forced_rows = [
        {
            "run_id": "forced-run",
            "phase": "start",
            "status": "running",
            "triggered_by": "gha-force-self-maintenance",
            "force": True,
        },
        *[
            {
                "run_id": "forced-run",
                "phase": "step",
                "step": step,
                "status": "success",
                "ok": True,
            }
            for step in ("code", "review", "qa")
        ],
        {
            "run_id": "forced-run",
            "phase": "complete",
            "status": "completed_merged",
        },
        {
            "run_id": "forced-run",
            "event": "deploy_dispatch",
            "environment": "production",
            "status": "accepted",
            "ok": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-forced",
        },
        {
            "run_id": "forced-run",
            "event": "post_deploy_verified",
            "environment": "production",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
            "merge_sha": "a" * 40,
            "workflow_run_id": "workflow-forced",
        },
    ]
    autonomous_rows = [
        {
            "run_id": "scheduler-run",
            "phase": "start",
            "status": "running",
            "triggered_by": "scheduler",
            "force": False,
        },
        *[
            {
                "run_id": "scheduler-run",
                "phase": "step",
                "step": step,
                "status": "success",
                "ok": True,
            }
            for step in ("code", "review", "qa")
        ],
        {
            "run_id": "scheduler-run",
            "phase": "complete",
            "status": "completed_merge_requested",
        },
    ]

    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "evidence": {
                "recent_rows": [*forced_rows, *autonomous_rows],
                "latest_complete": forced_rows[4],
                "open_run_ids": [],
            }
        },
        generated_at=NOW,
    )
    code = _dimensions(snapshot)["code"]

    assert code["progress"] == 45
    assert {gate["key"] for gate in code["evidence"]} == {"write", "review", "qa"}
    assert snapshot["live_summary"]["real_deploy_dispatched"] is False
    assert snapshot["live_summary"]["deploy_verified"] is False
    assert snapshot["live_summary"]["latest_autonomous_complete_status"] == (
        "completed_merge_requested"
    )


def test_scheduler_automated_remediation_counts_exact_deploy_chain() -> None:
    run_id = "automated-remediation-run"
    merge_sha = "b" * 40
    workflow_run_id = "workflow-automated-remediation"
    rows = [
        {
            "run_id": run_id,
            "phase": "start",
            "status": "running",
            "triggered_by": "automated_remediation",
            "force": False,
        },
        *[
            {
                "run_id": run_id,
                "phase": "step",
                "step": step,
                "status": "success",
                "ok": True,
            }
            for step in ("code", "review", "qa")
        ],
        {
            "run_id": run_id,
            "phase": "complete",
            "status": "completed_merge_requested",
        },
        {
            "run_id": run_id,
            "phase": "deployment",
            "event": "deploy_dispatch",
            "environment": "production",
            "status": "accepted",
            "ok": True,
            "merge_sha": merge_sha,
            "workflow_run_id": workflow_run_id,
        },
        {
            "run_id": run_id,
            "phase": "deployment",
            "event": "post_deploy_verified",
            "environment": "production",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
            "merge_sha": merge_sha,
            "workflow_run_id": workflow_run_id,
        },
        {
            "run_id": run_id,
            "phase": "merge",
            "event": "merge_completed",
            "environment": "production",
            "status": "completed_merged",
            "ok": True,
            "merge_sha": merge_sha,
            "workflow_run_id": workflow_run_id,
        },
    ]

    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "evidence": {
                "milestone_rows": rows,
                "latest_complete": rows[4],
                "open_run_ids": [],
            }
        },
        generated_at=NOW,
    )
    code = _dimensions(snapshot)["code"]

    assert code["progress"] == 100
    assert {gate["key"] for gate in code["evidence"]} == {
        "write",
        "review",
        "qa",
        "merge",
        "dispatch",
        "verify",
    }
    assert snapshot["live_summary"]["latest_autonomous_complete_status"] == (
        "completed_merge_requested"
    )
    assert snapshot["live_summary"]["real_deploy_dispatched"] is True
    assert snapshot["live_summary"]["deploy_verified"] is True


def test_fault_loop_cannot_mix_repair_and_recovery_across_run_ids() -> None:
    snapshot = build_founder_autonomy_snapshot(
        runtime={
            "current_gate": {"incident_count": 2},
            "participants": [{"employee_id": "log-monitor-incident"}],
            "evidence": {
                "recent_rows": [
                    {
                        "run_id": "incident-repair",
                        "phase": "start",
                        "triggered_by": "incident_event",
                        "force": False,
                        "status": "running",
                    },
                    {
                        "run_id": "incident-repair",
                        "phase": "step",
                        "step": "code",
                        "status": "success",
                        "ok": True,
                    },
                    {
                        "run_id": "incident-other",
                        "phase": "complete",
                        "triggered_by": "incident_event",
                        "status": "completed_merged",
                    },
                    {
                        "run_id": "incident-other",
                        "event": "incident_recovered_verified",
                        "status": "healthy",
                        "ok": True,
                    },
                ]
            },
        },
        generated_at=NOW,
    )
    fault = _dimensions(snapshot)["fault"]

    assert fault["progress"] == 60
    assert {gate["key"] for gate in fault["evidence"]} == {
        "sense",
        "triage",
        "repair",
    }
    assert {gate["key"] for gate in fault["gaps"]} >= {"complete", "verify"}
