# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
    LOOP_EVICT_MAX_ITEMS entries).  The returned private audit record must be
    emitted by the caller only after the updated memory is persisted.
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
    return {
        "_governance_audit_record": summary_record,
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "reasons": reasons,
    }


def _append_committed_eviction_audit(
    record: _facade().Optional[_facade().Dict[str, _facade().Any]],
) -> None:
    if not record:
        return
    try:
        _facade()._append_governance_audit(record)
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to write loop_evicted governance audit")


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
    audit_record = result.pop("_governance_audit_record", None)
    memory["updated_at"] = _facade()._iso(_facade()._utc_now())
    _facade()._write_loop_memory(memory)
    _append_committed_eviction_audit(audit_record)
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
            "DEVFLEET_WORKSPACE_ROOT",
            "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace",
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
    except RECOVERABLE_ERRORS:
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
    audit_record = None
    try:
        evict_summary = _facade()._evict_loop_memory_items(memory, actor="auto")
        audit_record = evict_summary.pop("_governance_audit_record", None)
    except RECOVERABLE_ERRORS:
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
    _append_committed_eviction_audit(audit_record)
