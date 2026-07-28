"""Para merge-worker failure details that should keep the rejected branch mutable."""

from __future__ import annotations

_POST_DISPATCH_PREFIX = "post-dispatch-check-failed:"

# merge_worker.mjs throws these when GitHub label API fails; branch code is unchanged.
_BRANCH_PRESERVING_EXACT = frozenset(
    {
        "hold-merge-label-failed-before-review",
        "hold-merge-label-remove-failed-after-review",
    }
)


def is_post_dispatch_merge_failure_detail(detail: str) -> bool:
    return str(detail or "").strip().lower().startswith(_POST_DISPATCH_PREFIX)


def is_branch_preserving_para_merge_failure_detail(detail: str) -> bool:
    """True when merge-worker failed without invalidating the candidate branch delta."""

    text = str(detail or "").strip().lower()
    if is_post_dispatch_merge_failure_detail(text):
        return True
    if text in _BRANCH_PRESERVING_EXACT:
        return True
    return any(token in text for token in _BRANCH_PRESERVING_EXACT)


def resume_from_clean_baseline_for_para_merge(reason: str, detail: str) -> bool:
    if reason == "para_merge_conflict" and is_branch_preserving_para_merge_failure_detail(detail):
        return False
    return True


__all__ = [
    "is_branch_preserving_para_merge_failure_detail",
    "is_post_dispatch_merge_failure_detail",
    "resume_from_clean_baseline_for_para_merge",
]
