"""Automated clean-base recovery for Retort scope-only clarifications."""

from __future__ import annotations

from typing import Any

RETORT_SCOPE_REASON = "retort_scope_too_large"


def retort_scope_only_clarification(value: Any) -> bool:
    """Return whether Retort only asks to reduce an oversized change."""

    gate = value if isinstance(value, dict) else {}
    clarification = gate.get("clarification") if isinstance(gate.get("clarification"), dict) else {}
    questions = clarification.get("questions")
    return bool(questions) and all(
        isinstance(question, dict)
        and str(question.get("reason") or "").strip() == "elevated_risk_or_large_diff"
        for question in questions
    )


def reconcile_retort_scope_remediations(memory: dict[str, Any]) -> dict[str, Any]:
    """Turn durable scope-only Retort holds into clean-base code remediation."""

    from modstore_server import self_maintenance_loop_runner as runner

    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
        memory["open_items"] = open_items
    existing_run_ids = {
        str(item.get("run_id") or "").strip()
        for item in open_items
        if isinstance(item, dict)
        and item.get("kind") == "automated_remediation"
        and str(item.get("reason") or "").strip() == RETORT_SCOPE_REASON
    }
    added_run_ids: list[str] = []
    for row in runner._read_ledger(limit=500):
        run_id = str(row.get("run_id") or "").strip()
        retort = row.get("retort_clarification")
        if (
            row.get("phase") != "complete"
            or str(row.get("status") or "").strip() != "failed"
            or str(row.get("error") or "").strip() != "retort_clarification_pending"
            or not run_id
            or run_id in existing_run_ids
            or not retort_scope_only_clarification(retort)
        ):
            continue
        branch = str(row.get("branch") or "").strip()
        para_task_id = str(row.get("para_task_id") or "").strip()
        if not branch or not para_task_id:
            continue
        changed_file_count = int(
            (retort if isinstance(retort, dict) else {}).get("changed_file_count") or 0
        )
        open_items.append(
            {
                "branch": branch,
                "created_at": runner._iso(runner._utc_now()),
                "detail": (
                    f"Retort requested risk acceptance for {changed_file_count} changed files; "
                    "rebuild the smallest valid fix from the clean base."
                ),
                "kind": "automated_remediation",
                "para_task_id": para_task_id,
                "reason": RETORT_SCOPE_REASON,
                "resume_from_clean_baseline": True,
                "run_id": run_id,
                "task_id": para_task_id,
            }
        )
        existing_run_ids.add(run_id)
        added_run_ids.append(run_id)
    if added_run_ids:
        memory["updated_at"] = runner._iso(runner._utc_now())
    return {
        "added": len(added_run_ids),
        "changed": bool(added_run_ids),
        "run_ids": added_run_ids,
    }


def retort_scope_remediation_prompt(resume_candidate: Any) -> str:
    """Render clean-base instructions without weakening the original veto."""

    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if (
        candidate.get("reason") != "resume_automated_remediation_candidate"
        or str(candidate.get("remediation_reason") or "") != RETORT_SCOPE_REASON
    ):
        return ""
    rejected_branch = str(candidate.get("branch") or "").strip()
    feedback = str(candidate.get("remediation_feedback") or "").strip()[:4000]
    return (
        "\n\n=== RETORT SCOPE REMEDIATION ===\n"
        "Retort did not approve the previous candidate because its change surface was too "
        "large for unattended review. Start from the configured clean base. Inspect the "
        "rejected branch only as read-only evidence, then reproduce only the smallest "
        "production fix and focused regression test. Do not copy its repository-wide "
        "formatting churn. The diff-scoped Black/isort commands below must pass without "
        "formatting unrelated historical files. "
        f"Rejected reference branch: {rejected_branch or '(missing)'}. "
        f"Exact scope feedback: {feedback or '(missing)'}"
    )
