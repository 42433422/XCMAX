"""Reconcile durable merge receipts back into loop memory."""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _latest_completed_runs(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("phase") == "complete" and _text(row.get("run_id")):
            completed[_text(row.get("run_id"))] = row
    return completed


def _verified_merge_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = _text(row.get("run_id"))
        if (
            row.get("event") == "merge_completed"
            and row.get("ok") is True
            and _text(row.get("status")) == "completed_merged"
            and run_id
        ):
            verified[run_id] = row
    return verified


def reconcile_completed_loop_memory_from_ledger() -> dict[str, Any]:
    """Close superseded failures after an exact verified merge receipt.

    The merge/deploy callback is asynchronous, so the original loop transaction
    has already persisted ``completed_merge_requested``.  This reconciler runs
    before the scheduler selects another remediation and converts the durable
    ``merge_completed`` ledger receipt into memory closure.
    """

    from modstore_server import self_maintenance_loop_runner as runner

    rows = runner._read_ledger(limit=5000)
    memory = runner._load_loop_memory()
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        recent_runs = []
    raw_reconciliations = memory.get("completed_merge_reconciliations")
    reconciliation_history = (
        [_text(value) for value in raw_reconciliations if _text(value)]
        if isinstance(raw_reconciliations, list)
        else []
    )
    reconciled = set(reconciliation_history)
    completed_by_run = _latest_completed_runs(rows)
    verified_by_run = _verified_merge_rows(rows)
    closed_count = 0
    newly_reconciled: set[str] = set()
    updated_runs = 0

    for run_id, receipt in verified_by_run.items():
        if run_id in reconciled:
            continue
        completed = completed_by_run.get(run_id)
        if completed is None:
            continue
        resume = completed.get("resume_candidate")
        resume = resume if isinstance(resume, dict) else {}
        branches = [
            _text(receipt.get("branch")),
            _text(completed.get("branch")),
            _text(resume.get("branch")),
        ]
        run_ids = [run_id, _text(resume.get("failed_run_id"))]
        task_ids = [
            _text(receipt.get("para_task_id")),
            _text(completed.get("para_task_id")),
            _text(resume.get("para_task_id")),
        ]
        resolution = runner._close_open_items_in_memory(
            memory,
            actor="deployment_receipt_reconciler",
            branches=branches,
            resolution_reason="verified_merge_completed",
            run_ids=run_ids,
            task_ids=task_ids,
        )
        closed_count += int(resolution.get("closed_count") or 0)
        for recent in recent_runs:
            if not isinstance(recent, dict) or _text(recent.get("run_id")) != run_id:
                continue
            recent["status"] = "completed_merged"
            recent["merge_sha"] = _text(receipt.get("merge_sha"))
            recent["deployment_verified"] = True
            updated_runs += 1
        reconciled.add(run_id)
        newly_reconciled.add(run_id)

    if not newly_reconciled:
        return {
            "closed_count": 0,
            "reconciled_run_ids": [],
            "updated_runs": 0,
        }

    memory["recent_runs"] = recent_runs[-20:]
    memory["completed_merge_reconciliations"] = (reconciliation_history + sorted(newly_reconciled))[
        -200:
    ]
    runner._write_loop_memory(memory)
    return {
        "closed_count": closed_count,
        "reconciled_run_ids": sorted(newly_reconciled),
        "updated_runs": updated_runs,
    }
