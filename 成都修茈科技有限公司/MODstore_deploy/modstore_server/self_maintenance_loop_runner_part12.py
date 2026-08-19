# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _evict_loop_memory_items(
    memory: _facade().Dict[str, _facade().Any],
    *,
    actor: str = "auto",
    note: str = "",
    admin_user_id: _facade().Optional[_facade().Any] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Evict stale open_items so the loop can resume fresh runs.

    Rules (checked in order, first match wins):
      - any item with created_at > 7d  → evict (reason=aged_out_7d)
      - failed_steps item with created_at > 24h AND retry_count >= 3
        → evict (reason=stuck_24h_retry_3)
    Evicted items are appended to memory["evicted_items"] (capped at the last
    LOOP_EVICT_MAX_ITEMS entries) and a ``loop_evicted`` governance audit
    record is written so the action is visible in the governance UI.
    Returns a summary dict; never raises.
    """
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    evicted_items = memory.get("evicted_items")
    if not isinstance(evicted_items, list):
        evicted_items = []
    now = _facade()._utc_now()
    kept: _facade().List[_facade().Dict[str, _facade().Any]] = []
    newly_evicted: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        created_dt = _facade()._parse_iso(item.get("created_at"))
        age_seconds = (now - created_dt).total_seconds() if created_dt else 0.0
        retry_count = int(item.get("retry_count") or 0)
        kind = str(item.get("kind") or "")
        evict_reason = ""
        if age_seconds >= _facade().LOOP_EVICT_AGE_OUT_SECONDS:
            evict_reason = "aged_out_7d"
        elif (
            kind == "failed_steps"
            and age_seconds >= _facade().LOOP_EVICT_STUCK_AGE_SECONDS
            and (retry_count >= _facade().LOOP_EVICT_STUCK_RETRY_THRESHOLD)
        ):
            evict_reason = "stuck_24h_retry_3"
        if evict_reason:
            evicted_entry: _facade().Dict[str, _facade().Any] = {
                "actor": actor,
                "evicted_at": _facade()._iso(now),
                "evict_reason": evict_reason,
                "original_item": item,
            }
            if note:
                evicted_entry["note"] = str(note)[:1000]
            if admin_user_id is not None:
                evicted_entry["admin_user_id"] = admin_user_id
            newly_evicted.append(evicted_entry)
        else:
            kept.append(item)
    memory["open_items"] = kept
    memory["evicted_items"] = (evicted_items + newly_evicted)[-_facade().LOOP_EVICT_MAX_ITEMS :]
    if not newly_evicted:
        return {
            "evicted_count": 0,
            "evicted_items": [],
            "reasons": {"aged_out_7d": 0, "stuck_24h_retry_3": 0},
        }
    reasons = {
        "aged_out_7d": sum(
            (1 for entry in newly_evicted if entry["evict_reason"] == "aged_out_7d")
        ),
        "stuck_24h_retry_3": sum(
            (1 for entry in newly_evicted if entry["evict_reason"] == "stuck_24h_retry_3")
        ),
    }
    summary_record = {
        "action": "loop_evicted",
        "actor": actor,
        "admin_user_id": admin_user_id,
        "created_at": _facade()._iso(now),
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "note": str(note or "")[:1000],
        "ok": True,
        "reasons": reasons,
        "source": "self_maintenance_loop_runner",
        "status": "evicted",
    }
    try:
        _facade()._append_governance_audit(summary_record)
    except Exception:
        _facade().logger.exception("failed to write loop_evicted governance audit")
    return {"evicted_count": len(newly_evicted), "evicted_items": newly_evicted, "reasons": reasons}


def evict_loop_memory_items(
    *,
    actor: str = "manual",
    note: str = "",
    admin_user_id: _facade().Optional[_facade().Any] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Manually evict stale loop-memory open_items (veto channel).

    Exposed via POST /api/xcmax/admin/loop/memory/evict for human override when
    the loop is stuck resuming long-failed runs.
    """
    memory = _facade()._load_loop_memory()
    result = _facade()._evict_loop_memory_items(
        memory, actor=actor, note=note, admin_user_id=admin_user_id
    )
    memory["updated_at"] = _facade()._iso(_facade()._utc_now())
    _facade()._write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(_facade().loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }


def _update_loop_memory(
    final: _facade().Dict[str, _facade().Any], gate: _facade().Dict[str, _facade().Any]
) -> None:
    memory = _facade()._load_loop_memory()
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        recent_runs = []
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []
    memory["closed_items"] = closed_items
    decision = final.get("policy_decision") or {}
    steps = final.get("steps") if isinstance(final.get("steps"), list) else []
    failed_steps = [step.get("step") for step in steps if not step.get("ok")]
    if failed_steps:
        run_id = final.get("run_id")
        existing_idx = None
        for idx, item in enumerate(open_items):
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and (item.get("run_id") == run_id)
            ):
                existing_idx = idx
                break
        if existing_idx is None and isinstance(final.get("resume_candidate"), dict):
            failed_run_id = str(
                final.get("resume_candidate", {}).get("failed_run_id") or ""
            ).strip()
            if failed_run_id:
                for idx, item in enumerate(open_items):
                    if (
                        isinstance(item, dict)
                        and item.get("kind") == "failed_steps"
                        and (item.get("run_id") == failed_run_id)
                    ):
                        existing_idx = idx
                        break
        if existing_idx is None and failed_steps == ["code"]:
            for idx, item in reversed(list(enumerate(open_items))):
                if (
                    isinstance(item, dict)
                    and item.get("kind") == "failed_steps"
                    and (item.get("steps") == ["code"])
                    and (not item.get("branch"))
                    and (not item.get("task_id"))
                    and (not item.get("para_task_id"))
                ):
                    existing_idx = idx
                    break
        if existing_idx is None:
            branch = str(final.get("branch") or "").strip()
            para_task_id = str(final.get("para_task_id") or "").strip()
            if branch or para_task_id:
                for idx, item in reversed(list(enumerate(open_items))):
                    if not (isinstance(item, dict) and item.get("kind") == "failed_steps"):
                        continue
                    item_branch = str(item.get("branch") or "").strip()
                    item_task_id = str(
                        item.get("para_task_id") or item.get("task_id") or ""
                    ).strip()
                    if (
                        branch
                        and item_branch == branch
                        or (para_task_id and item_task_id == para_task_id)
                    ):
                        existing_idx = idx
                        break
        if existing_idx is not None:
            existing = open_items[existing_idx]
            existing["retry_count"] = int(existing.get("retry_count") or 1) + 1
            existing["last_attempted_at"] = _facade()._iso(_facade()._utc_now())
            existing["steps"] = failed_steps
            existing["run_id"] = run_id
            if final.get("branch"):
                existing["branch"] = final.get("branch")
            if final.get("para_task_id"):
                existing["para_task_id"] = final.get("para_task_id")
        else:
            new_item = {
                "created_at": _facade()._iso(_facade()._utc_now()),
                "kind": "failed_steps",
                "retry_count": 1,
                "run_id": run_id,
                "steps": failed_steps,
            }
            if final.get("branch"):
                new_item["branch"] = final.get("branch")
            if final.get("para_task_id"):
                new_item["para_task_id"] = final.get("para_task_id")
            open_items.append(new_item)
    if decision.get("action") == "hold_for_automated_remediation":
        remediation_item = {
            "branch": final.get("branch"),
            "active_gates": decision.get("active_gates"),
            "created_at": _facade()._iso(_facade()._utc_now()),
            "evolution_gate": decision.get("evolution_gate"),
            "kind": "automated_remediation",
            "governance_gate": decision.get("governance_gate"),
            "reason": decision.get("reason"),
            "roster_gate": decision.get("roster_gate"),
            "run_id": final.get("run_id"),
            "task_id": final.get("para_task_id"),
        }
        if decision.get("detail"):
            remediation_item["detail"] = decision.get("detail")
        structured_gate = decision.get("structured_gate")
        if isinstance(structured_gate, dict):
            remediation_item["structured_gate"] = structured_gate
        if decision.get("resume_from_clean_baseline"):
            remediation_item["resume_from_clean_baseline"] = True
        open_items.append(remediation_item)
    memory["open_items"] = open_items
    _facade().close_successful_code_resume(memory, final, _facade()._close_open_items_in_memory)
    resolution_record = _facade()._close_items_resolved_by_final(memory, final)
    knowledge_record = _facade().record_loop_evolution_knowledge(final, gate)
    salvage_summary: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    try:
        para_task_id = final.get("para_task_id") or ""
        ws_root = _facade().os.environ.get(
            "DEVFLEET_WORKSPACE_ROOT", "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace"
        )
        para_workspace = (
            _facade().Path(ws_root) / para_task_id if para_task_id else _facade().Path(ws_root)
        )
        salvage_summary = _facade().salvage_kb_from_workspace(
            para_workspace=para_workspace, run_id=final.get("run_id")
        )
        if salvage_summary and (
            salvage_summary.get("salvaged_fixes") or salvage_summary.get("salvaged_patterns")
        ):
            _facade().logger.info(
                "kb salvage run_id=%s salvaged_fixes=%s salvaged_patterns=%s",
                final.get("run_id"),
                salvage_summary.get("salvaged_fixes"),
                salvage_summary.get("salvaged_patterns"),
            )
        _facade()._append_ledger(
            {
                "phase": "kb_salvage",
                "run_id": final.get("run_id"),
                "para_task_id": final.get("para_task_id"),
                "salvaged_fixes": salvage_summary.get("salvaged_fixes") if salvage_summary else 0,
                "salvaged_patterns": (
                    salvage_summary.get("salvaged_patterns") if salvage_summary else 0
                ),
                "skipped": salvage_summary.get("skipped") if salvage_summary else 0,
                "workspace": salvage_summary.get("workspace") if salvage_summary else None,
                "timestamp": _facade()._iso(_facade()._utc_now()),
            }
        )
    except Exception:
        _facade().logger.exception("kb salvage failed run_id=%s", final.get("run_id"))
    recent_runs.append(
        {
            "action": decision.get("action"),
            "active_gates": decision.get("active_gates"),
            "branch": final.get("branch"),
            "completed_at": final.get("completed_at"),
            "evolution_gate_pause": (
                decision.get("evolution_gate", {}).get("pause")
                if isinstance(decision.get("evolution_gate"), dict)
                else None
            ),
            "evolution_gate_reason": (
                decision.get("evolution_gate", {}).get("reason")
                if isinstance(decision.get("evolution_gate"), dict)
                else None
            ),
            "gate_reason": gate.get("reason"),
            "governance_gate_action": (
                decision.get("governance_gate", {}).get("action")
                if isinstance(decision.get("governance_gate"), dict)
                else None
            ),
            "governance_gate_reason": (
                decision.get("governance_gate", {}).get("reason")
                if isinstance(decision.get("governance_gate"), dict)
                else None
            ),
            "governance_gate_health": (
                decision.get("governance_gate", {}).get("summary", {}).get("health")
                if isinstance(decision.get("governance_gate"), dict)
                and isinstance(decision.get("governance_gate", {}).get("summary"), dict)
                else None
            ),
            "para_task_id": final.get("para_task_id"),
            "roster_gate_action": (
                decision.get("roster_gate", {}).get("action")
                if isinstance(decision.get("roster_gate"), dict)
                else None
            ),
            "roster_gate_reason": (
                decision.get("roster_gate", {}).get("reason")
                if isinstance(decision.get("roster_gate"), dict)
                else None
            ),
            "roster_gate_out_of_roster_ids": (
                decision.get("roster_gate", {}).get("out_of_roster_ids")
                if isinstance(decision.get("roster_gate"), dict)
                and isinstance(decision.get("roster_gate", {}).get("out_of_roster_ids"), list)
                else []
            ),
            "roster_gate_not_deployed_ids": (
                decision.get("roster_gate", {}).get("not_deployed_ids")
                if isinstance(decision.get("roster_gate"), dict)
                and isinstance(decision.get("roster_gate", {}).get("not_deployed_ids"), list)
                else []
            ),
            "run_id": final.get("run_id"),
            "status": final.get("status"),
            "structured_gate": (
                decision.get("structured_gate")
                if isinstance(decision.get("structured_gate"), dict)
                else None
            ),
            "kb_salvage": salvage_summary,
        }
    )
    try:
        evict_summary = _facade()._evict_loop_memory_items(memory, actor="auto")
    except Exception:
        evict_summary = {"evicted_count": 0, "error": "evict_failed"}
        _facade().logger.exception("loop memory auto-evict failed run_id=%s", final.get("run_id"))
    memory.update(
        {
            "evicted_items": memory.get("evicted_items", [])[-_facade().LOOP_EVICT_MAX_ITEMS :],
            "last_evict_summary": evict_summary,
            "last_gate": gate,
            "last_knowledge_record": knowledge_record,
            "last_policy_decision": decision,
            "last_resolution_record": resolution_record,
            "last_run": recent_runs[-1],
            "open_items": memory.get("open_items", [])[-50:],
            "closed_items": memory.get("closed_items", [])[-200:],
            "recent_runs": recent_runs[-20:],
            "run_count": int(memory.get("run_count") or 0) + 1,
            "updated_at": _facade()._iso(_facade()._utc_now()),
        }
    )
    _facade()._write_loop_memory(memory)


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
    (para_task_id, code_branch) = _facade()._resume_dispatch_context(resume_candidate, steps_to_run)
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
                    base_branch=remediation_base_branch, delivered_branch=str(code_branch or "")
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
                except Exception:
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
    except Exception as exc:
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


def cron_trigger_for_self_maintenance() -> _facade().CronTrigger:
    hour = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3)
    minute = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0)
    timezone_name = _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai")
    return _facade().CronTrigger(hour=hour, minute=minute, timezone=timezone_name)


def record_self_maintenance_heartbeat(
    *, triggered_by: str = "scheduler_heartbeat"
) -> _facade().Dict[str, _facade().Any]:
    """Append a side-effect-free liveness receipt for the outer loop.

    The full maintenance loop is intentionally daily and may be held by
    cooldown or governance.  A separate heartbeat proves the scheduler is
    still evaluating that gate without pretending code work was performed.
    """
    evaluation = _facade().should_run_self_maintenance_loop(force=False, triggered_by=triggered_by)
    provenance = (
        evaluation.get("runtime_provenance")
        if isinstance(evaluation.get("runtime_provenance"), dict)
        else {}
    )
    metrics_gate = (
        evaluation.get("evolution_metrics_gate")
        if isinstance(evaluation.get("evolution_metrics_gate"), dict)
        else {}
    )
    record = {
        "created_at": _facade()._iso(_facade()._utc_now()),
        "phase": "heartbeat",
        "run_id": f"heartbeat-{_facade().uuid.uuid4().hex[:16]}",
        "status": "heartbeat_ready" if evaluation.get("should_run") is True else "heartbeat_idle",
        "triggered_by": str(triggered_by or "scheduler_heartbeat")[:80],
        "gate": {
            "should_run": evaluation.get("should_run") is True,
            "reason": str(evaluation.get("reason") or "")[:160],
            "runtime_provenance_ok": provenance.get("ok") is True,
            "evolution_metrics_paused": metrics_gate.get("pause") is True,
        },
        "read_only": True,
        "side_effects": [],
    }
    _facade()._append_ledger(record)
    return record
