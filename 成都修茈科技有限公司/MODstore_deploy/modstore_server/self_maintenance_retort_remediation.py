"""Automated clean-base recovery for Retort scope-only clarifications."""

from __future__ import annotations

import json
from typing import Any

RETORT_SCOPE_REASON = "retort_scope_too_large"
RETORT_SCOPE_MAX_FILES = 6
RETORT_SCOPE_MAX_CHANGED_LINES = 400
RETORT_SCOPE_MAX_DIFF_CHARS = 12_000
RETORT_SCOPE_EXCLUDED_PATHS = (
    ".github/workflows/",
    "FHD/XCAGI/kb/",
    "config/source_governance_baseline.json",
    "scripts/dev/source_governance.py",
    "self_maintenance_loop_status.py",
)


def _normalize_repo_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip().strip('"').strip("'")


def is_retort_scope_excluded_path(path: str) -> bool:
    """Return whether a changed path is forbidden during clean-base Retort retries."""

    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    for pattern in RETORT_SCOPE_EXCLUDED_PATHS:
        if pattern.endswith("/"):
            if normalized.startswith(pattern):
                return True
            continue
        if normalized == pattern or normalized.endswith("/" + pattern):
            return True
    return False


def retort_scope_remediation_contract() -> dict[str, Any]:
    """Return the deterministic diff budget for a clean-base Retort retry."""

    return {
        "base_ref": "origin/main",
        "excluded_paths": list(RETORT_SCOPE_EXCLUDED_PATHS),
        "max_changed_files": RETORT_SCOPE_MAX_FILES,
        "max_changed_lines": RETORT_SCOPE_MAX_CHANGED_LINES,
        "max_diff_chars": RETORT_SCOPE_MAX_DIFF_CHARS,
        "required_shape": "production root-cause files plus focused regression tests only",
    }


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
    contract = retort_scope_remediation_contract()
    return (
        "\n\n=== RETORT SCOPE REMEDIATION ===\n"
        "Retort did not approve the previous candidate because its change surface was too "
        "large for unattended review. Start from the current remote main fetched into "
        "`origin/main`; never continue, merge, rebase, or cherry-pick the rejected branch. "
        "Inspect that branch only as read-only evidence and select exactly one still-missing "
        "production root cause. Reproduce only that source fix and its focused regression "
        "tests. This retry intentionally overrides the generic KB-writing instruction: the "
        "previous workspace is already salvaged separately, so do not add KB, metrics, status, "
        "governance-baseline, workflow, generated, or documentation files to this branch. "
        "Before commit and again before reporting completion, run `git diff --name-only "
        "origin/main...HEAD`, `git diff --numstat origin/main...HEAD`, and "
        "`git diff origin/main...HEAD | wc -c`; all limits in "
        "RETORT_SCOPE_CONTRACT_JSON must pass. If the rejected fix is already on main, choose "
        "one bounded executable gap from current evidence instead of replaying historical "
        "commits or creating a marker-only change. The diff-scoped Black/isort commands below "
        "must pass without formatting unrelated historical files. "
        f"RETORT_SCOPE_CONTRACT_JSON: {json.dumps(contract, ensure_ascii=False, sort_keys=True)}. "
        f"Rejected reference branch: {rejected_branch or '(missing)'}. "
        f"Exact scope feedback: {feedback or '(missing)'}"
    )


__all__ = [
    "RETORT_SCOPE_REASON",
    "is_retort_scope_excluded_path",
    "reconcile_retort_scope_remediations",
    "retort_scope_only_clarification",
    "retort_scope_remediation_contract",
    "retort_scope_remediation_prompt",
]
