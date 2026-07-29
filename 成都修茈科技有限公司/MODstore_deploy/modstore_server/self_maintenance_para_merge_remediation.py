"""Executable Para merge-worker failure classification for self-maintenance scheduling."""

from __future__ import annotations

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


__all__ = [
    "is_branch_preserving_para_merge_failure_detail",
    "operational_merge_reason_candidates",
    "para_merge_conflict_continues_on_rejected_branch",
    "resume_from_clean_baseline_for_para_merge",
]
