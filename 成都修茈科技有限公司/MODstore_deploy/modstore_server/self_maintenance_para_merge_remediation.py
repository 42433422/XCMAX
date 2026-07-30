"""Executable Para merge-worker failure classification for self-maintenance scheduling."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .self_maintenance_policy import (
    normalize_merge_review_veto_code,
    parse_merge_review_diff_char_count,
)
from .self_maintenance_remediation_lineage import normalize_automated_remediation_reason

_INDETERMINATE_MERGE_REVIEW_CODES = frozenset({"indeterminate-review", "indeterminate_review"})
_DIFF_TOO_LARGE_MERGE_REVIEW_CODE = "diff-too-large"

_OPERATIONAL_MERGE_FAILURE_PREFIXES = (
    "post-dispatch-check-failed:",
    "indeterminate-review:",
    "bot merge checks failed or unavailable:",
)

# merge_worker.mjs throws these when GitHub label API fails; branch code is unchanged.
_BRANCH_PRESERVING_MERGE_WORKER_TOKENS = (
    "hold-merge-label-failed-before-review",
    "hold-merge-label-remove-failed-after-review",
    "risk-label-failed-after-review",
)

# gh pr update-branch content conflicts: branch is behind/diverged from main; rebase on clean base.
_GIT_CONTENT_CONFLICT_MARKERS = ("cannot update pr branch due to conflicts",)


def _strip_error_prefix(text: str) -> str:
    lowered = text.strip().lower()
    if lowered.startswith("error:"):
        return text.strip()[6:].strip()
    return text.strip()


def operational_merge_reason_candidates(detail: str) -> list[str]:
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


def is_branch_preserving_para_merge_failure_detail(detail: str) -> bool:
    """True when merge-worker failed without invalidating the candidate branch delta."""

    return para_merge_conflict_continues_on_rejected_branch(detail)


def para_merge_conflict_continues_on_rejected_branch(detail: str) -> bool:
    """Operational merge failures where the branch fix should be continued, not rewritten."""

    for candidate in operational_merge_reason_candidates(detail):
        lowered = candidate.lower()
        if any(marker in lowered for marker in _GIT_CONTENT_CONFLICT_MARKERS):
            return False
        if any(lowered.startswith(prefix) for prefix in _OPERATIONAL_MERGE_FAILURE_PREFIXES):
            return True
        if any(token in lowered for token in _BRANCH_PRESERVING_MERGE_WORKER_TOKENS):
            return True
    return False


def resume_from_clean_baseline_for_para_merge(reason: str, detail: str) -> bool:
    """Whether automated remediation must restart from the configured clean base."""

    if reason == "para_merge_conflict" and is_branch_preserving_para_merge_failure_detail(detail):
        return False
    return True


def resume_candidate_from_para_ai_review_item(
    memory: Dict[str, Any],
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a code-resume candidate for Para merge-worker AI review vetoes."""

    reason = normalize_automated_remediation_reason(memory, item)
    if reason != "para_ai_review_rejected":
        return None
    branch = str(item.get("branch") or "").strip()
    para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
    if not branch or not para_task_id:
        return None
    feedback = str(item.get("review_feedback") or item.get("detail") or "")[:4000]
    veto_meta = classify_para_merge_review_detail(feedback)
    return {
        "branch": branch,
        "failed_run_id": str(item.get("run_id") or "").strip(),
        "failed_steps": ["code"],
        "para_task_id": para_task_id,
        "reason": "resume_para_ai_review_rejection",
        "rejected_branch": branch,
        "review_actionable_findings": veto_meta.get("actionable_code_findings"),
        "review_feedback": feedback,
        "review_veto_branch_hint": veto_meta.get("branch_hint") or "",
        "review_veto_code": str(item.get("review_veto_code") or veto_meta.get("veto_code") or ""),
    }


def classify_para_merge_review_detail(detail: str) -> Dict[str, Any]:
    """Normalize Para merge-worker veto detail for loop remediation."""

    text = str(detail or "").strip()[:4000]
    lowered = text.lower()
    branch_hint = ""
    veto_code = ""
    if ":" in text:
        left, _, right = text.partition(":")
        left = left.strip()
        right = right.strip().lower()
        if "/" in left and right:
            branch_hint = left
            veto_code = normalize_merge_review_veto_code(right)
    if not veto_code:
        for marker in _INDETERMINATE_MERGE_REVIEW_CODES:
            if marker in lowered:
                veto_code = marker
                break
        if not veto_code and _DIFF_TOO_LARGE_MERGE_REVIEW_CODE in lowered:
            veto_code = _DIFF_TOO_LARGE_MERGE_REVIEW_CODE
    else:
        veto_code = normalize_merge_review_veto_code(veto_code)
    actionable_code_findings = bool(
        text
        and veto_code not in _INDETERMINATE_MERGE_REVIEW_CODES
        and veto_code != _DIFF_TOO_LARGE_MERGE_REVIEW_CODE
        and re.search(r"\bREJECT\s*:", text, re.IGNORECASE)
    )
    review_diff_chars = parse_merge_review_diff_char_count(text)
    return {
        "actionable_code_findings": actionable_code_findings,
        "branch_hint": branch_hint,
        "detail": text,
        "review_diff_chars": review_diff_chars,
        "veto_code": veto_code,
    }


__all__ = [
    "classify_para_merge_review_detail",
    "is_branch_preserving_para_merge_failure_detail",
    "operational_merge_reason_candidates",
    "para_merge_conflict_continues_on_rejected_branch",
    "resume_candidate_from_para_ai_review_item",
    "resume_from_clean_baseline_for_para_merge",
]
