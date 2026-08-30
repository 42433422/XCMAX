"""Executable Para merge-worker failure classification for self-maintenance scheduling."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .self_maintenance_policy import (
    is_auxiliary_self_maintenance_evidence_path,
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
_PR_CLOSED_WITHOUT_MERGE_MARKERS = ("closed without merge",)
# merge_worker.mjs throws when update-branch leaves zero PR changed files.
_CHANGED_FILES_EMPTY_MARKERS = ("changed-files-empty",)
_MANUAL_MERGE_VETO_TOKEN = "manual-veto-active:"
_MODSTORE_SERVER_SCOPE = "成都修茈科技有限公司/MODstore_deploy/modstore_server/"
_ABSORPTION_ELIGIBLE_REASONS = frozenset(
    {
        "para_ai_review_rejected",
        "para_merge_conflict",
    }
)


def retain_newest_open_items(items: Any, *, limit: int = 50) -> list[Dict[str, Any]]:
    """Retain the newest valid open items by created_at, independent of list order."""

    if limit <= 0 or not isinstance(items, list):
        return []
    indexed_items = [(index, item) for index, item in enumerate(items) if isinstance(item, dict)]

    def recency(entry: tuple[int, Dict[str, Any]]) -> tuple[int, datetime, int]:
        index, item = entry
        try:
            created_at = datetime.fromisoformat(
                str(item.get("created_at") or "").replace("Z", "+00:00")
            )
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return 1, created_at.astimezone(UTC), index
        except ValueError:
            return 0, datetime.min.replace(tzinfo=UTC), index

    return [item for _, item in sorted(indexed_items, key=recency)[-limit:]]


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


def reconcile_para_merge_failure_state(
    memory: Dict[str, Any],
    changed: bool,
    detail: str,
    source: str,
    task_id: str,
    task_status: str,
) -> tuple[str, str, list[Dict[str, Any]], bool]:
    """Classify a merge failure and migrate a same-task manual veto atomically."""

    manual_veto = _MANUAL_MERGE_VETO_TOKEN in str(detail or "").lower()
    if manual_veto:
        reason = "manual_merge_veto_active"
    elif source == "ai-review-veto":
        reason = "para_ai_review_rejected"
    elif task_status == "merge_conflict":
        reason = "para_merge_conflict"
    else:
        reason = "para_merge_task_failed"
    item_kind = "human_strategy_approval" if manual_veto else "automated_remediation"

    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    stale_same_task = manual_veto and any(
        isinstance(item, dict)
        and str(item.get("task_id") or item.get("para_task_id") or "") == task_id
        and (item.get("kind") != item_kind or item.get("reason") != reason)
        for item in open_items
    )
    if not stale_same_task:
        return reason, item_kind, open_items, changed

    closed_at = datetime.now(UTC).isoformat()
    kept_items: list[Dict[str, Any]] = []
    newly_closed: list[Dict[str, Any]] = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        item_task_id = str(item.get("task_id") or item.get("para_task_id") or "")
        if item_task_id == task_id:
            newly_closed.append(
                {
                    "actor": "para_merge_reconciler",
                    "closed_at": closed_at,
                    "original_item": item,
                    "resolution_reason": "reclassified_as_manual_merge_veto_active",
                }
            )
        else:
            kept_items.append(item)
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []
    memory["open_items"] = retain_newest_open_items(kept_items)
    memory["closed_items"] = (closed_items + newly_closed)[-200:]
    memory["updated_at"] = closed_at
    return reason, item_kind, memory["open_items"], True


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

    normalized = str(reason or "").strip()
    if normalized == "para_ai_review_rejected":
        # AI review vetoes always restart from the clean base unless merge-worker
        # already proved the rejected branch has no remaining executable delta.
        if is_changed_files_empty_detail(detail) or is_pr_closed_without_merge_detail(detail):
            return False
        return True
    if normalized.startswith("para_merge_") and (
        is_branch_preserving_para_merge_failure_detail(detail)
        or is_changed_files_empty_detail(detail)
        or is_pr_closed_without_merge_detail(detail)
    ):
        return False
    return True


def is_pr_closed_without_merge_detail(detail: str) -> bool:
    """True when merge-worker closed the PR without landing a merge commit."""

    for candidate in operational_merge_reason_candidates(detail):
        lowered = candidate.lower()
        if any(marker in lowered for marker in _PR_CLOSED_WITHOUT_MERGE_MARKERS):
            return True
    return False


def is_changed_files_empty_detail(detail: str) -> bool:
    """True when merge-worker found zero PR changed files after update-branch."""

    for candidate in operational_merge_reason_candidates(detail):
        lowered = candidate.lower()
        if any(marker in lowered for marker in _CHANGED_FILES_EMPTY_MARKERS):
            return True
    return False


def is_update_branch_content_conflict_detail(detail: str) -> bool:
    """True when gh pr update-branch failed due to content conflicts with main."""

    for candidate in operational_merge_reason_candidates(detail):
        lowered = candidate.lower()
        if any(marker in lowered for marker in _GIT_CONTENT_CONFLICT_MARKERS):
            return True
    return False


def para_merge_resume_pins_rejected_branch(item: Mapping[str, Any]) -> bool:
    """Whether a para_merge remediation should continue on the rejected branch."""

    if not isinstance(item, Mapping):
        return False
    # Explicit clean-baseline restart must win over branch-preserving detail heuristics
    # (stale open_items may still carry resume_from_clean_baseline=True).
    if item.get("resume_from_clean_baseline"):
        return False
    detail = str(item.get("detail") or "")
    if (
        is_changed_files_empty_detail(detail)
        or is_pr_closed_without_merge_detail(detail)
        or is_update_branch_content_conflict_detail(detail)
    ):
        return False
    return is_branch_preserving_para_merge_failure_detail(detail)


def _normalize_repo_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip().strip('"').strip("'")


def _is_production_modstore_server_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized.startswith(_MODSTORE_SERVER_SCOPE):
        return False
    return not is_auxiliary_self_maintenance_evidence_path(normalized)


def _default_repo_root() -> Optional[Path]:
    from modstore_server.runtime_provenance import resolve_runtime_repo_root

    return resolve_runtime_repo_root()


def _default_run_git(repo_root: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _branch_remote_ref(branch: str, *, prefix: str = "origin/") -> str:
    normalized = str(branch or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("refs/") or normalized.startswith("origin/"):
        return normalized
    return f"{prefix}{normalized}"


def rejected_branch_production_delta_absorbed_by_main(
    rejected_branch: str,
    *,
    base_ref: str = "origin/main",
    repo_root: Optional[Path] = None,
    run_git: Optional[Callable[..., tuple[int, str, str]]] = None,
) -> Dict[str, Any]:
    """Return whether rejected-branch production deltas are already on the base ref.

      Uses one batched two-dot name-only diff across the modstore_server scope
    instead of per-file diffs to avoid N+1 git calls per open_item.
    """

    branch_ref = _branch_remote_ref(rejected_branch)
    if not branch_ref:
        return {"absorbed": False, "reason": "missing_rejected_branch"}

    root = repo_root or _default_repo_root()
    if root is None:
        return {"absorbed": False, "reason": "repo_root_unavailable"}

    git_runner = run_git or _default_run_git
    scope_path = f"{_MODSTORE_SERVER_SCOPE.rstrip('/')}/"
    diff_rc, diff_out, diff_err = git_runner(
        root,
        "diff",
        "--name-only",
        base_ref,
        branch_ref,
        "--",
        scope_path,
    )
    if diff_rc != 0:
        return {
            "absorbed": False,
            "reason": "git_diff_name_only_failed",
            "stderr": diff_err[:300],
        }

    remaining_paths = [
        _normalize_repo_path(path)
        for path in (diff_out or "").splitlines()
        if _is_production_modstore_server_path(path)
    ]
    if remaining_paths:
        return {
            "absorbed": False,
            "base_ref": base_ref,
            "branch_ref": branch_ref,
            "reason": "rejected_branch_production_delta_present",
            "remaining_paths": remaining_paths,
        }

    three_dot_rc, three_dot_out, _ = git_runner(
        root,
        "diff",
        "--name-only",
        f"{base_ref}...{branch_ref}",
        "--",
        scope_path,
    )
    scoped_paths = []
    if three_dot_rc == 0:
        scoped_paths = [
            _normalize_repo_path(path)
            for path in (three_dot_out or "").splitlines()
            if _is_production_modstore_server_path(path)
        ]
    reason = (
        "no_rejected_branch_production_delta"
        if not scoped_paths
        else "rejected_branch_production_delta_absorbed_by_main"
    )
    return {
        "absorbed": True,
        "base_ref": base_ref,
        "branch_ref": branch_ref,
        "reason": reason,
        "scoped_paths": scoped_paths,
    }


def reconcile_absorbed_para_merge_remediations(
    memory: Dict[str, Any],
    *,
    base_branch: str = "main",
    repo_root: Optional[Path] = None,
    run_git: Optional[Callable[..., tuple[int, str, str]]] = None,
) -> Dict[str, Any]:
    """Close para_merge_conflict holds when main already has the production fix."""

    from modstore_server import self_maintenance_loop_runner as runner

    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        return {"changed": False, "closed_count": 0, "closed_task_ids": []}

    base_ref = f"origin/{(base_branch or 'main').strip() or 'main'}"
    closed_task_ids: list[str] = []
    assessment_cache: Dict[str, Dict[str, Any]] = {}
    for item in list(open_items):
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "automated_remediation":
            continue
        if str(item.get("reason") or "").strip() not in _ABSORPTION_ELIGIBLE_REASONS:
            continue
        detail = str(item.get("detail") or "")
        empty_files = is_changed_files_empty_detail(detail)
        closed_without_merge = is_pr_closed_without_merge_detail(detail)
        update_branch_conflict = is_update_branch_content_conflict_detail(detail)
        branch_preserving_infra = is_branch_preserving_para_merge_failure_detail(detail)
        if (
            not empty_files
            and not closed_without_merge
            and not update_branch_conflict
            and not branch_preserving_infra
        ):
            continue
        rejected_branch = str(item.get("rejected_branch") or item.get("branch") or "").strip()
        cache_key = f"{base_ref}\0{rejected_branch}"
        if cache_key not in assessment_cache:
            assessment_cache[cache_key] = rejected_branch_production_delta_absorbed_by_main(
                rejected_branch,
                base_ref=base_ref,
                repo_root=repo_root,
                run_git=run_git,
            )
        assessment = assessment_cache[cache_key]
        if not assessment.get("absorbed"):
            continue
        task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        resolution = runner._close_open_items_in_memory(
            memory,
            actor="para_merge_absorption_reconciler",
            branches=[rejected_branch],
            resolution_reason="rejected_branch_production_delta_absorbed_by_main",
            task_ids=[task_id] if task_id else None,
        )
        if resolution.get("closed_count"):
            closed_task_ids.append(task_id)
            memory.setdefault("absorbed_para_merge_reconciliations", []).append(
                {
                    "assessment": assessment,
                    "closed_at": runner._iso(runner._utc_now()),
                    "rejected_branch": rejected_branch,
                    "task_id": task_id,
                }
            )

    if closed_task_ids:
        memory["updated_at"] = runner._iso(runner._utc_now())
    return {
        "changed": bool(closed_task_ids),
        "closed_count": len(closed_task_ids),
        "closed_task_ids": closed_task_ids,
    }


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
    "is_changed_files_empty_detail",
    "is_pr_closed_without_merge_detail",
    "is_update_branch_content_conflict_detail",
    "para_merge_resume_pins_rejected_branch",
    "operational_merge_reason_candidates",
    "para_merge_conflict_continues_on_rejected_branch",
    "reconcile_absorbed_para_merge_remediations",
    "rejected_branch_production_delta_absorbed_by_main",
    "resume_candidate_from_para_ai_review_item",
    "resume_from_clean_baseline_for_para_merge",
]
