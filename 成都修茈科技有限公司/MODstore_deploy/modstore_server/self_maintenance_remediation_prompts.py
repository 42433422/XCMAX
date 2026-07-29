"""Prompt fragments for branch-based self-maintenance remediation."""

from __future__ import annotations

from typing import Any

_OPERATIONAL_MERGE_FAILURE_PREFIXES = (
    "post-dispatch-check-failed:",
    "indeterminate-review:",
    "bot merge checks failed or unavailable:",
)

# merge_worker.mjs throws these when GitHub label API fails; branch code is unchanged.
_BRANCH_PRESERVING_MERGE_WORKER_TOKENS = (
    "hold-merge-label-failed-before-review",
    "hold-merge-label-remove-failed-after-review",
)

# gh pr update-branch content conflicts: branch is behind/diverged from main; rebase on clean base.
_GIT_CONTENT_CONFLICT_MARKERS = ("cannot update pr branch due to conflicts",)


def _strip_error_prefix(text: str) -> str:
    lowered = text.strip().lower()
    if lowered.startswith("error:"):
        return text.strip()[6:].strip()
    return text.strip()


def _operational_merge_reason_candidates(detail: str) -> list[str]:
    """Yield reason payloads from merge_worker/Para merge_conflict.detail strings."""

    raw = str(detail or "").strip()
    if not raw:
        return []
    candidates: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        candidates.append(_strip_error_prefix(line))
        if ": " in line:
            tail = _strip_error_prefix(line.split(": ", 1)[1])
            if tail:
                candidates.append(tail)
    return candidates


def para_merge_conflict_continues_on_rejected_branch(detail: str) -> bool:
    """Operational merge failures where the branch fix should be continued, not rewritten."""

    for candidate in _operational_merge_reason_candidates(detail):
        lowered = candidate.lower()
        if any(marker in lowered for marker in _GIT_CONTENT_CONFLICT_MARKERS):
            return False
        if any(lowered.startswith(prefix) for prefix in _OPERATIONAL_MERGE_FAILURE_PREFIXES):
            return True
        if any(token in lowered for token in _BRANCH_PRESERVING_MERGE_WORKER_TOKENS):
            return True
    return False


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
