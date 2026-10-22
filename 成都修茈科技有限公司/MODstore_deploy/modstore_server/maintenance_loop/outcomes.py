"""Reconcile Para feedback and persist completed loop outcomes and knowledge."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import (
    self_evolution_knowledge,
    self_maintenance_para_merge_remediation,
    self_maintenance_retry,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config
from . import memory as memory_domain
from . import para_client, store


def _close_items_resolved_by_final(
    memory: Dict[str, Any],
    final: Dict[str, Any],
) -> Dict[str, Any]:
    decision = final.get("policy_decision")
    if not isinstance(decision, dict):
        decision = {}
    action = str(decision.get("action") or "")
    status = str(final.get("status") or "")
    if action not in {"auto_merged_low_risk", "auto_continue"} and status != "completed_merged":
        return {"closed_count": 0, "closed_items": []}
    run_ids: List[str] = []
    task_ids: List[str] = []
    branches: List[str] = []
    resume_candidate = final.get("resume_candidate")
    if isinstance(resume_candidate, dict):
        failed_run_id = str(resume_candidate.get("failed_run_id") or "").strip()
        if failed_run_id:
            run_ids.append(failed_run_id)
        para_task_id = str(resume_candidate.get("para_task_id") or "").strip()
        if para_task_id:
            task_ids.append(para_task_id)
        branch = str(resume_candidate.get("branch") or "").strip()
        if branch:
            branches.append(branch)
    run_id = str(final.get("run_id") or "").strip()
    if run_id:
        run_ids.append(run_id)
    para_task_id = str(final.get("para_task_id") or "").strip()
    if para_task_id:
        task_ids.append(para_task_id)
    branch = str(final.get("branch") or "").strip()
    if branch:
        branches.append(branch)
    return memory_domain._close_open_items_in_memory(
        memory,
        actor="self_maintenance_loop",
        branches=branches,
        resolution_reason=str(decision.get("reason") or status or "resolved_by_successful_loop"),
        run_ids=run_ids,
        task_ids=task_ids,
    )


def _reconcile_requested_merge_feedback(
    memory: Dict[str, Any],
    *,
    api_base: Optional[str] = None,
    task_fetcher: Optional[Any] = None,
) -> Dict[str, Any]:
    """Settle requested merges from Para without confusing request with success.

    ``completed_merge_requested`` remains open until Para reports a real merged
    SHA. Any terminal merge failure becomes an automated remediation item with
    the exact findings. The next code employee starts from the configured clean
    base and uses the rejected branch only as evidence, preventing retries from
    accumulating an ever-larger inherited diff.
    """
    base = (api_base or os.environ.get("MODSTORE_PARA_API_BASE") or "").strip()
    recent_runs = memory.get("recent_runs")
    open_items = memory.get("open_items")
    if not base or not isinstance(recent_runs, list):
        return {"changed": False, "merged": 0, "remediation_added": 0}
    if not isinstance(open_items, list):
        open_items = []
        memory["open_items"] = open_items
    fetcher = task_fetcher or para_client._fetch_para_task_state
    changed = False
    merged = 0
    remediation_added = 0
    checked_task_ids: set[str] = set()
    for run in reversed(recent_runs):
        if not isinstance(run, dict):
            continue
        if str(run.get("status") or "") != "completed_merge_requested":
            continue
        task_id = str(run.get("para_task_id") or "").strip()
        if not task_id or task_id in checked_task_ids:
            continue
        checked_task_ids.add(task_id)
        try:
            task = fetcher(base, task_id)
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to reconcile requested Para merge task_id=%s", task_id)
            continue
        task_status = str(task.get("status") or "").strip().lower()
        branch = str(run.get("branch") or "").strip()
        if task_status == "merged" and str(task.get("merge_commit_sha") or "").strip():
            merge_sha = str(task.get("merge_commit_sha") or "").strip()
            existing_receipt = run.get("merge_reconciliation")
            receipt = {
                "merge_commit_sha": merge_sha,
                "reconciled_at": config._iso(config._utc_now()),
                "status": "merged",
                "task_id": task_id,
            }
            if not (
                isinstance(existing_receipt, dict)
                and existing_receipt.get("status") == "merged"
                and (existing_receipt.get("task_id") == task_id)
                and (existing_receipt.get("merge_commit_sha") == merge_sha)
            ):
                run["merge_reconciliation"] = receipt
                changed = True
            closed = memory_domain._close_open_items_in_memory(
                memory,
                actor="para_merge_reconciler",
                branches=[branch],
                resolution_reason="para_reported_real_merge_sha",
                task_ids=[task_id],
            )
            if closed.get("closed_count"):
                changed = True
            merged += 1
            continue
        terminal_failure_statuses = {
            "cancelled",
            "dispatch_error",
            "dispatch_failed",
            "failed",
            "merge_conflict",
        }
        if task_status not in terminal_failure_statuses:
            continue
        conflict = task.get("merge_conflict")
        if not isinstance(conflict, dict):
            conflict = {}
        source = str(conflict.get("source") or "").strip()
        detail = str(
            conflict.get("detail")
            or task.get("fail_reason")
            or task.get("error")
            or f"Para merge task ended with status={task_status}"
        ).strip()[:4000]
        reason, item_kind, open_items, changed = (
            self_maintenance_para_merge_remediation.reconcile_para_merge_failure_state(
                memory, changed, detail, source, task_id, task_status
            )
        )
        existing_receipt = run.get("merge_reconciliation")
        receipt = {
            "detail": detail,
            "reconciled_at": config._iso(config._utc_now()),
            "source": source,
            "status": task_status,
            "task_id": task_id,
        }
        if not (
            isinstance(existing_receipt, dict)
            and existing_receipt.get("status") == task_status
            and (existing_receipt.get("task_id") == task_id)
            and (existing_receipt.get("source") == source)
            and (existing_receipt.get("detail") == detail)
        ):
            run["merge_reconciliation"] = receipt
            changed = True
        already_open = any(
            (
                isinstance(item, dict)
                and str(item.get("task_id") or item.get("para_task_id") or "") == task_id
                and (item.get("reason") == reason)
                and (item.get("kind") == item_kind)
                for item in open_items
            )
        )
        if not already_open:
            rejected_branch = str(conflict.get("branch_name") or branch).strip()
            resume_from_clean_baseline = (
                self_maintenance_para_merge_remediation.resume_from_clean_baseline_for_para_merge(
                    reason, detail
                )
            )
            veto_meta = (
                self_maintenance_para_merge_remediation.classify_para_merge_review_detail(detail)
                if source == "ai-review-veto"
                else {}
            )
            open_item: Dict[str, Any] = {
                "branch": rejected_branch,
                "created_at": config._iso(config._utc_now()),
                "detail": detail,
                "kind": item_kind,
                "para_task_id": task_id,
                "reason": reason,
                "rejected_branch": rejected_branch,
                "resume_from_clean_baseline": resume_from_clean_baseline,
                "review_feedback": detail if source == "ai-review-veto" else "",
                "run_id": str(run.get("run_id") or "").strip(),
                "source": source,
                "task_status": task_status,
                "task_id": task_id,
            }
            if source == "ai-review-veto":
                open_item["review_actionable_findings"] = veto_meta.get("actionable_code_findings")
                open_item["review_veto_branch_hint"] = veto_meta.get("branch_hint") or ""
                open_item["review_veto_code"] = veto_meta.get("veto_code") or ""
                if veto_meta.get("review_diff_chars") is not None:
                    open_item["review_diff_chars"] = veto_meta["review_diff_chars"]
            open_items.append(open_item)
            changed = True
            remediation_added += 1
    if changed:
        memory["open_items"] = (memory.get("open_items") or [])[-50:]
        memory["updated_at"] = config._iso(config._utc_now())
    return {
        "changed": changed,
        "merged": merged,
        "remediation_added": remediation_added,
    }


def _update_loop_memory(final: Dict[str, Any], gate: Dict[str, Any]) -> None:
    memory = store._load_loop_memory()
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
            existing["last_attempted_at"] = config._iso(config._utc_now())
            existing["steps"] = failed_steps
            existing["run_id"] = run_id
            if final.get("branch"):
                existing["branch"] = final.get("branch")
            if final.get("para_task_id"):
                existing["para_task_id"] = final.get("para_task_id")
        else:
            new_item = {
                "created_at": config._iso(config._utc_now()),
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
            "created_at": config._iso(config._utc_now()),
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
    self_maintenance_retry.close_successful_code_resume(
        memory, final, memory_domain._close_open_items_in_memory
    )
    resolution_record = _close_items_resolved_by_final(memory, final)
    knowledge_record = self_evolution_knowledge.record_loop_evolution_knowledge(final, gate)
    salvage_summary: Optional[Dict[str, Any]] = None
    try:
        para_task_id = final.get("para_task_id") or ""
        ws_root = os.environ.get(
            "DEVFLEET_WORKSPACE_ROOT",
            "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace",
        )
        para_workspace = Path(ws_root) / para_task_id if para_task_id else Path(ws_root)
        salvage_summary = self_evolution_knowledge.salvage_kb_from_workspace(
            para_workspace=para_workspace, run_id=final.get("run_id")
        )
        if salvage_summary and (
            salvage_summary.get("salvaged_fixes") or salvage_summary.get("salvaged_patterns")
        ):
            config.logger.info(
                "kb salvage run_id=%s salvaged_fixes=%s salvaged_patterns=%s",
                final.get("run_id"),
                salvage_summary.get("salvaged_fixes"),
                salvage_summary.get("salvaged_patterns"),
            )
        store._append_ledger(
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
                "timestamp": config._iso(config._utc_now()),
            }
        )
    except RECOVERABLE_ERRORS:
        config.logger.exception("kb salvage failed run_id=%s", final.get("run_id"))
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
        evict_summary = memory_domain._evict_loop_memory_items(memory, actor="auto")
    except RECOVERABLE_ERRORS:
        evict_summary = {"evicted_count": 0, "error": "evict_failed"}
        config.logger.exception("loop memory auto-evict failed run_id=%s", final.get("run_id"))
    memory.update(
        {
            "evicted_items": memory.get("evicted_items", [])[-config.LOOP_EVICT_MAX_ITEMS :],
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
            "updated_at": config._iso(config._utc_now()),
        }
    )
    store._write_loop_memory(memory)
