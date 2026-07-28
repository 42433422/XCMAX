"""Close post-dispatch merge remediations whose branch delta is already on main."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_POST_DISPATCH_PREFIX = "post-dispatch-check-failed:"
_FAILED_CHECKS_RE = re.compile(r"checks=([^\s]+)", re.IGNORECASE)


def parse_post_dispatch_failed_checks(detail: str) -> List[str]:
    """Extract required-check names from merge-worker post-dispatch detail."""

    text = str(detail or "").strip()
    if not text.lower().startswith(_POST_DISPATCH_PREFIX):
        return []
    match = _FAILED_CHECKS_RE.search(text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def is_post_dispatch_merge_failure_detail(detail: str) -> bool:
    return str(detail or "").strip().lower().startswith(_POST_DISPATCH_PREFIX)


def resume_from_clean_baseline_for_para_merge(reason: str, detail: str) -> bool:
    """Whether remediation must restart from the clean base instead of the rejected branch."""

    if reason == "para_merge_conflict" and is_post_dispatch_merge_failure_detail(detail):
        return False
    return True


def attach_post_dispatch_remediation_fields(remediation_item: Dict[str, Any], detail: str) -> None:
    """Record failed required-check names on a new automated_remediation open item."""

    if not is_post_dispatch_merge_failure_detail(detail):
        return
    failed_checks = parse_post_dispatch_failed_checks(detail)
    if failed_checks:
        remediation_item["failed_post_dispatch_checks"] = failed_checks


def copy_failed_post_dispatch_checks_to_candidate(
    candidate: Dict[str, Any], item: Dict[str, Any]
) -> None:
    failed_checks = item.get("failed_post_dispatch_checks")
    if isinstance(failed_checks, list) and failed_checks:
        candidate["failed_post_dispatch_checks"] = [
            str(name).strip() for name in failed_checks if str(name).strip()
        ]


def _default_git_is_ancestor(ancestor: str, descendant: str) -> bool:
    repo_root = Path(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT") or "/root/XCMAX"
    ).expanduser()
    if not ancestor or not descendant:
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def rejected_branch_delta_absorbed_by_main(
    branch: str,
    *,
    base_branch: str,
    remote_branch_head: Callable[[str, str], Optional[str]],
    is_ancestor: Optional[Callable[[str, str], bool]] = None,
) -> bool:
    """Return True when ``branch`` tip is already contained in ``base_branch`` tip."""

    rejected = str(branch or "").strip()
    base = str(base_branch or "").strip()
    if not rejected or not base:
        return False
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_head = remote_branch_head(repo_url, base)
    branch_head = remote_branch_head(repo_url, rejected)
    if not base_head or not branch_head:
        return False
    if branch_head == base_head:
        return True
    ancestor_check = is_ancestor or _default_git_is_ancestor
    return ancestor_check(branch_head, base_head)


def reconcile_superseded_post_dispatch_remediations(
    memory: Dict[str, Any],
    *,
    base_branch: Optional[str] = None,
    remote_branch_head: Optional[Callable[[str, str], Optional[str]]] = None,
    is_ancestor: Optional[Callable[[str, str], bool]] = None,
) -> Dict[str, Any]:
    """Close para_merge_conflict items whose rejected branch is already on main."""

    from modstore_server import self_maintenance_loop_runner as runner

    open_items = memory.get("open_items")
    if not isinstance(open_items, list) or not open_items:
        return {"changed": False, "closed_count": 0, "closed_branches": []}

    base = str(base_branch or os.environ.get("MODSTORE_PARA_BRANCH") or "main").strip()
    head_resolver = remote_branch_head or runner._remote_branch_head
    closed_branches: List[str] = []
    for item in list(open_items):
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "automated_remediation":
            continue
        if str(item.get("reason") or "") != "para_merge_conflict":
            continue
        if item.get("resume_from_clean_baseline") is not False:
            continue
        detail = str(item.get("detail") or "")
        if not is_post_dispatch_merge_failure_detail(detail):
            continue
        branch = str(item.get("branch") or item.get("rejected_branch") or "").strip()
        if not branch:
            continue
        if not rejected_branch_delta_absorbed_by_main(
            branch,
            base_branch=base,
            remote_branch_head=head_resolver,
            is_ancestor=is_ancestor,
        ):
            continue
        task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        resolution = runner._close_open_items_in_memory(
            memory,
            actor="post_dispatch_remediation_reconciler",
            branches=[branch],
            resolution_reason="remediation_delta_already_on_main",
            run_ids=[run_id] if run_id else None,
            task_ids=[task_id] if task_id else None,
        )
        if resolution.get("closed_count"):
            closed_branches.append(branch)

    return {
        "changed": bool(closed_branches),
        "closed_branches": closed_branches,
        "closed_count": len(closed_branches),
    }
