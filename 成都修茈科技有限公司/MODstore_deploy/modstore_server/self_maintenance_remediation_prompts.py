"""Prompt fragments for branch-based self-maintenance remediation."""

from __future__ import annotations

import json
from typing import Any

from .self_maintenance_para_merge_remediation import (
    classify_para_merge_review_detail,
    is_changed_files_empty_detail,
    para_merge_conflict_continues_on_rejected_branch,
)
from .self_maintenance_policy import normalize_merge_review_veto_code

_INDETERMINATE_MERGE_REVIEW_CODES = frozenset({"indeterminate-review", "indeterminate_review"})
_DIFF_TOO_LARGE_MERGE_REVIEW_CODE = "diff-too-large"

__all__ = [
    "external_merge_remediation_prompt",
    "external_review_remediation_prompt",
    "para_merge_conflict_continues_on_rejected_branch",
    "qa_executor_retry_prompt",
    "structured_report_remediation_prompt",
]


def _indeterminate_merge_review_remediation_hint() -> str:
    return (
        "\n\n=== INDETERMINATE MERGE REVIEW VETO ===\n"
        "The merge-worker reported indeterminate-review: Trae and MiniMax did not emit a "
        "parseable APPROVE/REJECT verdict on the prior PR diff. This is not a dimensional "
        "code-defect list. Remediation must be executable and reviewable:\n"
        "1) Do not re-land duplicate KB/tests-only deltas when the production fix already "
        "exists on the canonical base branch.\n"
        "2) Ship a focused modstore_server production change plus regression tests that "
        "make indeterminate vetoes classifiable in loop memory (this branch).\n"
        "3) Keep the diff small and free of marker-only or status-only files so the "
        "independent merge reviewer can emit a strict verdict."
    )


def _diff_too_large_merge_review_remediation_hint() -> str:
    return (
        "\n\n=== DIFF TOO LARGE MERGE REVIEW VETO ===\n"
        "The merge-worker reported diff-too-large: the PR git diff exceeded the Para "
        "merge-review character budget (default 30000, same as merge_worker.mjs). "
        "Remediation must shrink the branch before re-requesting merge:\n"
        "1) Rebase onto the current integration base and drop unrelated merge commits "
        "(for example generated workflow or desktop feed deltas not part of this fix).\n"
        "2) Keep modstore_server production changes plus focused tests; do not land "
        "FHD/XCAGI/kb/* paths on this remediation branch (auto-merge blocks KB while "
        "a diff-too-large open_item is active).\n"
        "3) Confirm git diff character count stays under the budget before merge request."
    )


def external_review_remediation_prompt(resume_candidate: Any) -> str:
    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_para_ai_review_rejection":
        return ""
    feedback = str(candidate.get("review_feedback") or "").strip()[:4000]
    rejected_branch = str(candidate.get("rejected_branch") or candidate.get("branch") or "").strip()
    veto_code = normalize_merge_review_veto_code(
        str(
            candidate.get("review_veto_code")
            or classify_para_merge_review_detail(feedback).get("veto_code")
            or ""
        )
    )
    prompt = (
        "\n\n=== EXTERNAL MERGE REVIEW REMEDIATION ===\n"
        "The independent Para merge reviewer vetoed the previous candidate. "
        "Your current isolated work branch starts from the configured clean base, not from "
        "the rejected branch. Treat the rejected branch as read-only reference and reproduce "
        "only the smallest production fix needed to address the original symptom and every "
        "finding below; do not inherit or cherry-pick the whole rejected diff. "
        "Do not weaken safety gates or merely rewrite comments. "
        "After the fix, run the mandatory policy suite, commit, and push the current work branch. "
        f"Rejected reference branch: {rejected_branch or '(missing)'}. "
        f"Exact reviewer findings: {feedback or '(missing feedback: fail closed and inspect the parent diff)'}"
    )
    if veto_code in _INDETERMINATE_MERGE_REVIEW_CODES:
        prompt += _indeterminate_merge_review_remediation_hint()
    elif veto_code == _DIFF_TOO_LARGE_MERGE_REVIEW_CODE:
        prompt += _diff_too_large_merge_review_remediation_hint()
    return prompt


def external_merge_remediation_prompt(resume_candidate: Any) -> str:
    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_automated_remediation_candidate" or not str(
        candidate.get("remediation_reason") or ""
    ).startswith("para_merge_"):
        return ""
    rejected_branch = str(candidate.get("branch") or "").strip()
    remediation_reason = str(candidate.get("remediation_reason") or "").strip()
    feedback = str(candidate.get("remediation_feedback") or "").strip()[:4000]
    continue_on_branch = bool(candidate.get("continue_existing_code_task"))
    if remediation_reason == "para_merge_conflict" and is_changed_files_empty_detail(feedback):
        strategy = (
            "merge-worker reported changed-files-empty after gh pr update-branch, so the PR "
            "exposes zero scoped changed files. Compare the rejected branch against main; if "
            "every modstore_server production delta is already on main, update loop status with "
            "NO_ACTION instead of rewriting from the clean baseline or making marker-only edits."
        )
    elif continue_on_branch:
        strategy = (
            "The previous Para merge task failed during post-dispatch required-check polling, "
            "gh pr checks polling infrastructure (bot merge checks failed or unavailable), "
            "merge-worker hold-merge or risk-label infrastructure, or indeterminate AI review "
            "infrastructure, after the candidate branch already passed earlier gates. Continue on "
            "the rejected "
            "branch as the mutable base: diff it against main, keep the existing production fix "
            "when already present on main, and only add the smallest delta still missing. Do not "
            "restart from the clean baseline or reimplement an already-merged fix. If every "
            "executable gap is already on main, update loop status with NO_ACTION instead of "
            "marker-only edits."
        )
    else:
        strategy = (
            "The previous Para merge task ended in a terminal failure (including gh pr "
            "update-branch content conflicts with main or PR closed without merge). Start from "
            "the configured clean base. Use the rejected branch only as read-only evidence, then "
            "reproduce the smallest valid production fix and focused regression test; do not "
            "inherit or cherry-pick the whole rejected diff. If every executable gap from the "
            "rejected branch is already on main (for example superseded by another merged PR), "
            "update loop status with NO_ACTION instead of marker-only edits."
        )
    return (
        "\n\n=== EXTERNAL MERGE FAILURE REMEDIATION ===\n"
        f"{strategy} "
        f"Reason: {remediation_reason or '(missing)'}. "
        f"Rejected reference branch: {rejected_branch or '(missing)'}. "
        f"Exact failure detail: {feedback or '(missing)'}"
    )


def _matched_structured_remediation_open_item(
    memory: Any,
    resume_candidate: dict[str, Any],
) -> dict[str, Any] | None:
    open_items = memory.get("open_items") if isinstance(memory, dict) else None
    if not isinstance(open_items, list):
        return None
    selected_branch = str(resume_candidate.get("branch") or "").strip()
    selected_run_id = str(resume_candidate.get("failed_run_id") or "").strip()
    selected_task_id = str(resume_candidate.get("para_task_id") or "").strip()
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") != "automated_remediation":
            continue
        reason = str(item.get("reason") or "").strip()
        if not (reason.startswith("structured_review_") or reason.startswith("structured_qa_")):
            continue
        item_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if (
            (selected_branch and str(item.get("branch") or "").strip() == selected_branch)
            or (selected_run_id and str(item.get("run_id") or "").strip() == selected_run_id)
            or (selected_task_id and item_task_id == selected_task_id)
        ):
            return item
    return None


def structured_report_remediation_prompt(memory: Any, resume_candidate: Any) -> str:
    """Surface report-only review/QA blocking findings for code remediation."""

    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_automated_remediation_candidate":
        return ""
    matched_item = _matched_structured_remediation_open_item(memory, candidate)
    hold_reason = str((matched_item or {}).get("reason") or "").strip()
    if not hold_reason.startswith("structured_review_") and not hold_reason.startswith(
        "structured_qa_"
    ):
        return ""
    structured_gate = (
        matched_item.get("structured_gate")
        if isinstance(matched_item, dict) and isinstance(matched_item.get("structured_gate"), dict)
        else None
    )
    if structured_gate is None:
        decision = memory.get("last_policy_decision") if isinstance(memory, dict) else {}
        structured_gate = decision.get("structured_gate") if isinstance(decision, dict) else None
    if not isinstance(structured_gate, dict):
        return ""
    review = (
        structured_gate.get("review") if isinstance(structured_gate.get("review"), dict) else {}
    )
    qa = structured_gate.get("qa") if isinstance(structured_gate.get("qa"), dict) else {}
    review_blocking = review.get("blocking_findings")
    qa_blocking = qa.get("blocking_findings")
    failed_dimensions = structured_gate.get("failed_dimensions")
    evidence = {
        "failed_dimensions": failed_dimensions if isinstance(failed_dimensions, list) else [],
        "hold_reason": hold_reason,
        "qa_blocking_findings": qa_blocking if isinstance(qa_blocking, list) else [],
        "qa_verdict": str(qa.get("verdict") or "").strip(),
        "review_blocking_findings": (review_blocking if isinstance(review_blocking, list) else []),
        "review_max_severity": str(review.get("max_severity") or "").strip(),
    }
    return (
        "\n\n=== STRUCTURED REVIEW/QA REMEDIATION ===\n"
        "The independent report-only review/QA employee blocked the previous loop with "
        f"hold reason `{hold_reason}`. Address every blocking finding below with the "
        "smallest production fix plus focused regression tests. Do not weaken safety "
        "gates, submit marker-only deltas, or fabricate review/QA evidence. "
        f"Structured gate evidence: {json.dumps(evidence, ensure_ascii=False, sort_keys=True)}"
    )


def qa_executor_retry_prompt(task_text: str, attempt: int, inner_max: int) -> str:
    return (
        task_text
        + f"\n\n=== PREVIOUS QA EXECUTOR UNAVAILABLE (inner round {attempt}/{inner_max - 1}) ===\n"
        "The previous report proved that the shell/command execution backend was unavailable; "
        "it did not prove a code or test failure. Start a fresh report-only QA attempt and "
        "actually run the required target-branch commands. Do not reuse invented exit codes "
        "or the previous FAIL payload. If the backend is still unavailable, report it truthfully."
    )
