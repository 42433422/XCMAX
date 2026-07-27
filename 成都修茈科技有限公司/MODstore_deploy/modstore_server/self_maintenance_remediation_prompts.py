"""Prompt fragments for branch-based self-maintenance remediation."""

from __future__ import annotations

from typing import Any


def external_review_remediation_prompt(resume_candidate: Any) -> str:
    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_para_ai_review_rejection":
        return ""
    feedback = str(candidate.get("review_feedback") or "").strip()[:4000]
    rejected_branch = str(candidate.get("rejected_branch") or candidate.get("branch") or "").strip()
    return (
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


def external_merge_remediation_prompt(resume_candidate: Any) -> str:
    candidate = resume_candidate if isinstance(resume_candidate, dict) else {}
    if candidate.get("reason") != "resume_automated_remediation_candidate" or not str(
        candidate.get("remediation_reason") or ""
    ).startswith("para_merge_"):
        return ""
    rejected_branch = str(candidate.get("branch") or "").strip()
    remediation_reason = str(candidate.get("remediation_reason") or "").strip()
    feedback = str(candidate.get("remediation_feedback") or "").strip()[:4000]
    return (
        "\n\n=== EXTERNAL MERGE FAILURE REMEDIATION ===\n"
        "The previous Para merge task ended in a terminal failure. Start from the configured "
        "clean base. Use the rejected branch only as read-only evidence, then reproduce the "
        "smallest valid production fix and focused regression test; do not inherit or cherry-pick "
        "the whole rejected diff. "
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
