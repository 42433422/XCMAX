"""Prompt fragments for branch-based self-maintenance remediation."""

from __future__ import annotations

from typing import Any

from .self_maintenance_para_merge_remediation import (
    para_merge_conflict_continues_on_rejected_branch,
)

__all__ = [
    "external_merge_remediation_prompt",
    "external_review_remediation_prompt",
    "para_merge_conflict_continues_on_rejected_branch",
    "qa_executor_retry_prompt",
]


def external_review_remediation_prompt(resume_candidate: Any) -> str:
    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_para_ai_review_rejection":
        return ""
    feedback = str(candidate.get("review_feedback") or "").strip()[:4000]
    rejected_branch = str(candidate.get("rejected_branch") or candidate.get("branch") or "").strip()
    from modstore_server.self_maintenance_policy import (
        classify_para_merge_review_detail,
        merge_review_veto_is_diff_too_large,
        merge_review_veto_is_indeterminate,
        normalize_merge_review_veto_code,
    )

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
    if merge_review_veto_is_indeterminate(veto_code):
        prompt += (
            "\n\n=== INDETERMINATE MERGE REVIEW VETO ===\n"
            "Merge-worker returned indeterminate-review (no parseable APPROVE/REJECT). "
            "Ship focused modstore_server production change plus regression tests; "
            "keep the diff small and avoid marker-only or KB-only deltas."
        )
    elif merge_review_veto_is_diff_too_large(veto_code):
        prompt += (
            "\n\n=== DIFF TOO LARGE MERGE REVIEW VETO ===\n"
            "PR git diff exceeded the Para merge-review budget (default 30000). "
            "Rebase, drop unrelated commits, keep modstore_server + focused tests only, "
            "and omit FHD/XCAGI/kb/* on this remediation branch until merge succeeds."
        )
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
    if continue_on_branch:
        strategy = (
            "The previous Para merge task failed during post-dispatch required-check polling, "
            "gh pr checks polling infrastructure (bot merge checks failed or unavailable), "
            "merge-worker hold-merge label infrastructure, or indeterminate AI review "
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
            "update-branch content conflicts with main). Start from the configured clean base. "
            "Use the rejected branch only as read-only evidence, then reproduce the smallest "
            "valid production fix and focused regression test; do not inherit or cherry-pick the "
            "whole rejected diff."
        )
    return (
        "\n\n=== EXTERNAL MERGE FAILURE REMEDIATION ===\n"
        f"{strategy} "
        f"Reason: {remediation_reason or '(missing)'}. "
        f"Rejected reference branch: {rejected_branch or '(missing)'}. "
        f"Exact failure detail: {feedback or '(missing)'}"
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
