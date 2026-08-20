# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _run_self_maintenance_loop_unlocked(
    *,
    triggered_by: str = "manual",
    force: bool = False,
    reason: _facade().Optional[str] = None,
    remediation_context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Run the real employee maintenance chain when gates allow it."""
    _facade().reconcile_stale_self_maintenance_runs(exclusive_lease_reacquired=True)
    run_id = str(_facade().uuid.uuid4())
    started_at = _facade()._utc_now()
    gate = _facade().should_run_self_maintenance_loop(force=force, triggered_by=triggered_by)
    _facade().ensure_clean_baseline()
    if not gate.get("should_run"):
        record = {
            "created_at": _facade()._iso(started_at),
            "force": force,
            "gate": gate,
            "phase": "skip",
            "reason": reason,
            "run_id": run_id,
            "status": f"skipped_{gate.get('reason')}",
            "triggered_by": triggered_by,
        }
        record.update(_facade()._remediation_lineage_fields(remediation_context))
        _facade()._append_ledger(record)
        return record
    user_id = _facade()._self_maintenance_actor_user_id()
    loop_memory = _facade()._load_loop_memory()
    merge_reconciliation = _facade()._reconcile_requested_merge_feedback(loop_memory)
    retort_scope_reconciliation = _facade()._reconcile_retort_scope_remediations(loop_memory)
    absorbed_merge_reconciliation = _facade()._reconcile_absorbed_para_merge_remediations(
        loop_memory,
        base_branch=_facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main",
    )
    if (
        merge_reconciliation.get("changed")
        or retort_scope_reconciliation.get("changed")
        or absorbed_merge_reconciliation.get("changed")
    ):
        _facade()._write_loop_memory(loop_memory)
    resume_candidate = (
        _facade()._resume_candidate_from_remediation_context(loop_memory, remediation_context)
        if remediation_context
        else _facade()._resume_review_qa_candidate(loop_memory)
    )
    if remediation_context and resume_candidate is None:
        record = _facade()._unavailable_remediation_context_record(
            created_at=_facade()._iso(started_at),
            force=force,
            gate=gate,
            remediation_context=remediation_context,
            run_id=run_id,
            triggered_by=triggered_by,
        )
        _facade()._append_ledger(record)
        return record
    start_record = {
        "created_at": _facade()._iso(started_at),
        "force": force,
        "gate": gate,
        "memory_path": str(_facade().loop_memory_path()),
        "phase": "start",
        "reason": reason,
        "run_id": run_id,
        "started_at": _facade()._iso(started_at),
        "status": "running",
        "triggered_by": triggered_by,
        "user_id": user_id,
        "runtime_provenance": gate.get("runtime_provenance"),
    }
    start_record.update(_facade()._remediation_lineage_fields(remediation_context))
    if any(merge_reconciliation.values()):
        start_record["merge_reconciliation"] = merge_reconciliation
    if retort_scope_reconciliation.get("changed"):
        start_record["retort_scope_reconciliation"] = retort_scope_reconciliation
    if absorbed_merge_reconciliation.get("changed"):
        start_record["absorbed_para_merge_reconciliation"] = absorbed_merge_reconciliation
    if resume_candidate:
        start_record["resume_candidate"] = resume_candidate
    _facade()._append_ledger(start_record)
    steps: _facade().List[_facade().Dict[str, _facade().Any]] = []
    plan = []
    steps_to_run = _facade()._resume_steps(resume_candidate)
    para_task_id, code_branch = _facade()._resume_dispatch_context(resume_candidate, steps_to_run)
    if "code" in steps_to_run:
        code_extra: _facade().Dict[str, _facade().Any] = {
            "allow_medium_risk": True,
            "skip_path_guard": True,
        }
        if resume_candidate and resume_candidate.get("continue_existing_code_task"):
            code_extra["branch"] = code_branch
        plan.append(
            (
                "vibe-coding-maintainer",
                "code",
                _facade()._code_task_text(run_id, gate, loop_memory, resume_candidate),
                code_extra,
            )
        )
    if "review" in steps_to_run:
        plan.append(
            (
                "change-request-auditor",
                "review",
                "",
                {
                    "allow_medium_risk": True,
                    "report_only": True,
                    "skip_path_guard": True,
                    "wait_timeout_sec": _facade()._env_int(
                        "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                    ),
                },
            )
        )
    if "qa" in steps_to_run:
        plan.append(
            (
                "test-qa-runner",
                "qa",
                "",
                {
                    "allow_medium_risk": True,
                    "report_only": True,
                    "wait_timeout_sec": _facade()._env_int(
                        "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                    ),
                },
            )
        )
    try:
        for employee_id, step_name, task_text, extra in plan:
            if step_name == "review":
                task_text = _facade()._review_task_text(run_id, code_branch, loop_memory)
            elif step_name == "qa":
                task_text = _facade()._qa_task_text(run_id, code_branch, loop_memory)
            if para_task_id and step_name == "code":
                extra = {**extra, "para_task_id": para_task_id}
            elif para_task_id:
                extra = {
                    **extra,
                    "review_base_branch": _facade().os.environ.get("MODSTORE_PARA_BRANCH"),
                    "review_repo_url": _facade().os.environ.get("MODSTORE_PARA_REPO_URL"),
                    "review_target_branch": code_branch,
                    "review_target_para_task_id": para_task_id,
                }
            remediation_base_branch = (
                str(extra.get("branch") or "").strip() if step_name == "code" else ""
            )
            if step_name == "review":
                retort_gate = _facade()._evaluate_retort_clarification_before_review(
                    run_id=run_id,
                    branch=code_branch,
                    para_task_id=str(para_task_id or ""),
                    memory=loop_memory,
                )
                if retort_gate.get("blocked"):
                    scope_only = _facade()._retort_scope_only_clarification(retort_gate)
                    step_record = {
                        "employee_id": employee_id,
                        "error": str(retort_gate.get("reason") or "retort_clarification_pending"),
                        "ok": False,
                        "para": {},
                        "phase": "step",
                        "report_excerpt": "",
                        "run_id": run_id,
                        "status": "completed_held_for_remediation" if scope_only else "failed",
                        "step": step_name,
                        "timestamp": _facade()._iso(_facade()._utc_now()),
                        "retort_clarification": retort_gate,
                    }
                    steps.append(step_record)
                    _facade()._append_ledger(step_record)
                    final = {
                        "branch": code_branch,
                        "completed_at": _facade()._iso(_facade()._utc_now()),
                        "error": str(retort_gate.get("reason") or "retort_clarification_pending"),
                        "failed_step": step_name,
                        "para_task_id": para_task_id,
                        "phase": "complete",
                        "run_id": run_id,
                        "started_at": _facade()._iso(started_at),
                        "status": "failed",
                        "steps": steps,
                        "triggered_by": triggered_by,
                        "retort_clarification": retort_gate,
                    }
                    if resume_candidate:
                        final["resume_candidate"] = resume_candidate
                    if scope_only:
                        final["policy_decision"] = {
                            "action": "hold_for_automated_remediation",
                            "detail": "Retort requires a smaller clean-base patch before unattended review.",
                            "reason": _facade().RETORT_SCOPE_REASON,
                            "resume_from_clean_baseline": True,
                        }
                    else:
                        final["policy_decision"] = _facade()._decide_post_loop_policy(
                            branch=code_branch,
                            gate=gate,
                            para_task_id=para_task_id,
                            run_id=run_id,
                            status="failed",
                            steps=steps,
                        )
                    _facade()._append_ledger(final)
                    _facade()._update_loop_memory(final, gate)
                    return final
            (
                result,
                ok,
                failure_reason,
                para_meta,
                report_excerpt,
                code_fix_retry_rounds,
                marker_retry_rounds,
            ) = _facade()._run_step_with_inner_retries(
                employee_id=employee_id,
                step_name=step_name,
                task_text=task_text,
                extra=extra,
                user_id=user_id,
                run_id=run_id,
            )
            if para_meta.get("task_id") and para_task_id is None:
                para_task_id = str(para_meta["task_id"])
            if step_name == "code" and para_meta.get("branch"):
                code_branch = str(para_meta["branch"])
            branch_delivery_validation: _facade().Optional[_facade().Dict[str, _facade().Any]] = (
                None
            )
            if step_name == "code" and ok and remediation_base_branch:
                branch_delivery_validation = _facade()._validate_remediation_branch_delivery(
                    base_branch=remediation_base_branch,
                    delivered_branch=str(code_branch or ""),
                )
                if not branch_delivery_validation.get("ok"):
                    ok = False
                    failure_reason = str(branch_delivery_validation.get("reason") or "")
            step_record = {
                "employee_id": employee_id,
                "error": failure_reason,
                "ok": ok,
                "para": para_meta,
                "phase": "step",
                "report_excerpt": report_excerpt,
                "retry_attempts": result.get("self_maintenance_retry_attempts"),
                "code_fix_retry_rounds": code_fix_retry_rounds,
                "marker_retry_rounds": marker_retry_rounds,
                "run_id": run_id,
                "status": "success" if ok else "failed",
                "step": step_name,
                "timestamp": _facade()._iso(_facade()._utc_now()),
            }
            if branch_delivery_validation is not None:
                step_record["branch_delivery_validation"] = branch_delivery_validation
            steps.append(step_record)
            _facade()._append_ledger(step_record)
            if not ok:
                final = {
                    "branch": code_branch,
                    "completed_at": _facade()._iso(_facade()._utc_now()),
                    "error": failure_reason,
                    "failed_step": step_name,
                    "para_task_id": para_task_id,
                    "phase": "complete",
                    "run_id": run_id,
                    "started_at": _facade()._iso(started_at),
                    "status": "failed",
                    "steps": steps,
                    "triggered_by": triggered_by,
                }
                if resume_candidate:
                    final["resume_candidate"] = resume_candidate
                final["policy_decision"] = _facade()._decide_post_loop_policy(
                    branch=code_branch,
                    gate=gate,
                    para_task_id=para_task_id,
                    run_id=run_id,
                    status="failed",
                    steps=steps,
                )
                _facade()._append_ledger(final)
                _facade()._update_loop_memory(final, gate)
                return final
            if step_name == "code" and ok and code_branch:
                try:
                    early_kb = _facade()._early_kb_validation_for_branch(
                        run_id=run_id, branch=code_branch
                    )
                except RECOVERABLE_ERRORS:
                    _facade().logger.exception(
                        "early KB validation crashed for branch=%s run_id=%s; skipping",
                        code_branch,
                        run_id,
                    )
                    early_kb = {"ok": True, "reason": "early_kb_validation_crashed"}
                if (
                    isinstance(early_kb, dict)
                    and (not early_kb.get("ok"))
                    and (early_kb.get("reason") == "kb_json_schema_validation_failed")
                    and isinstance(early_kb.get("kb_validation"), dict)
                ):
                    _facade().logger.warning(
                        "early KB schema validation failed for branch=%s run_id=%s; rejecting and retrying code step",
                        code_branch,
                        run_id,
                    )
                    return _facade()._reject_and_retry_kb_schema_failure(
                        run_id=run_id,
                        branch=code_branch,
                        para_task_id=para_task_id,
                        kb_validation=early_kb["kb_validation"],
                        steps=steps,
                        gate=gate,
                        triggered_by=triggered_by,
                        started_at=started_at,
                    )
        policy_decision = _facade()._decide_post_loop_policy(
            branch=code_branch,
            gate=gate,
            para_task_id=para_task_id,
            run_id=run_id,
            status="completed",
            steps=steps,
        )
        final_status = "completed"
        if policy_decision.get("action") == "auto_merged_low_risk":
            final_status = "completed_merged"
        elif policy_decision.get("action") == "auto_merge_requested_low_risk":
            final_status = "completed_merge_requested"
        elif policy_decision.get("action") == "hold_for_automated_remediation":
            final_status = "completed_held_for_remediation"
        final = {
            "branch": code_branch,
            "completed_at": _facade()._iso(_facade()._utc_now()),
            "para_task_id": para_task_id,
            "phase": "complete",
            "policy_decision": policy_decision,
            "run_id": run_id,
            "started_at": _facade()._iso(started_at),
            "status": final_status,
            "steps": steps,
            "triggered_by": triggered_by,
        }
        if resume_candidate:
            final["resume_candidate"] = resume_candidate
        _facade()._append_ledger(final)
        _facade()._update_loop_memory(final, gate)
        return final
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("self-maintenance loop failed")
        final = {
            "branch": code_branch,
            "completed_at": _facade()._iso(_facade()._utc_now()),
            "error": str(exc),
            "para_task_id": para_task_id,
            "phase": "complete",
            "run_id": run_id,
            "started_at": _facade()._iso(started_at),
            "status": "failed",
            "steps": steps,
            "triggered_by": triggered_by,
        }
        if resume_candidate:
            final["resume_candidate"] = resume_candidate
        final["policy_decision"] = _facade()._decide_post_loop_policy(
            branch=code_branch,
            gate=gate,
            para_task_id=para_task_id,
            run_id=run_id,
            status="failed",
            steps=steps,
        )
        _facade()._append_ledger(final)
        _facade()._update_loop_memory(final, gate)
        return final


@_facade().platform_llm_scoped
def run_self_maintenance_loop(
    *,
    triggered_by: str = "manual",
    force: bool = False,
    reason: _facade().Optional[str] = None,
    remediation_context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Run one maintenance transaction under an OS-backed exclusive lease."""
    with _facade()._exclusive_loop_lease() as acquired:
        if acquired:
            return _facade()._run_self_maintenance_loop_unlocked(
                triggered_by=triggered_by,
                force=force,
                reason=reason,
                remediation_context=remediation_context,
            )
        run_id = str(_facade().uuid.uuid4())
        record = {
            "created_at": _facade()._iso(_facade()._utc_now()),
            "force": force,
            "phase": "skip",
            "reason": reason,
            "run_id": run_id,
            "status": "skipped_active_lease",
            "triggered_by": triggered_by,
        }
        record.update(_facade()._remediation_lineage_fields(remediation_context))
        _facade()._append_ledger(record)
        return record
