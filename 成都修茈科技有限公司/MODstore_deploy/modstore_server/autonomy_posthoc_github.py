"""Fail-closed GitHub evidence for historical self-maintenance merges."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

import httpx

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,244}$")
_SUCCESSFUL_CHECK_CONCLUSIONS = frozenset({"neutral", "skipped", "success"})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def _safe_branch(value: Any) -> str:
    branch = str(value or "").strip()
    if (
        not _BRANCH.fullmatch(branch)
        or branch.startswith(("/", "."))
        or branch.endswith(("/", ".", ".lock"))
        or ".." in branch
        or "@{" in branch
        or "//" in branch
    ):
        return ""
    return branch


def _repository() -> str:
    value = str(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_GITHUB_REPOSITORY")
        or os.environ.get("GITHUB_REPOSITORY")
        or "42433422/XCMAX"
    ).strip()
    return value if _REPOSITORY.fullmatch(value) else ""


def _timeout_seconds() -> float:
    raw = str(os.environ.get("MODSTORE_GITHUB_EVIDENCE_TIMEOUT_SEC") or "15").strip()
    try:
        return max(3.0, min(float(raw), 30.0))
    except ValueError:
        return 15.0


def _default_fetch_json(path: str, params: dict[str, str] | None = None) -> Any:
    token = str(
        os.environ.get("MODSTORE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    ).strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "xcmax-autonomy-posthoc-auditor",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(
        base_url="https://api.github.com",
        headers=headers,
        timeout=_timeout_seconds(),
        trust_env=False,
    ) as client:
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.json()


def _merge_scope_verdict(files: Any) -> dict[str, Any]:
    if not isinstance(files, list) or not files:
        return {"ok": False, "reason": "github_pr_files_missing"}
    from modstore_server.self_maintenance_merge_policy import (
        absolute_forbidden_globs,
        file_matches_any_glob,
        forbidden_globs,
        max_files,
        max_lines,
        normalize_repo_path,
        scope_globs,
    )

    file_limit = max_files()
    if len(files) > file_limit:
        return {"ok": False, "reason": "github_pr_file_limit_exceeded"}
    allowed_scope = scope_globs()
    absolute_forbidden = absolute_forbidden_globs()
    forbidden = forbidden_globs()
    normalized_files: list[str] = []
    line_changes = 0
    for item in files:
        if not isinstance(item, dict):
            return {"ok": False, "reason": "github_pr_file_record_invalid"}
        filename = normalize_repo_path(item.get("filename"))
        if not filename or item.get("patch") is None:
            return {"ok": False, "reason": "github_pr_file_diff_incomplete"}
        if file_matches_any_glob(filename, absolute_forbidden):
            return {"ok": False, "reason": "github_pr_absolute_forbidden_scope"}
        if file_matches_any_glob(filename, forbidden):
            return {"ok": False, "reason": "github_pr_forbidden_scope"}
        if not file_matches_any_glob(filename, allowed_scope):
            return {"ok": False, "reason": "github_pr_outside_low_risk_scope"}
        try:
            additions = int(item.get("additions"))
            deletions = int(item.get("deletions"))
        except (TypeError, ValueError):
            return {"ok": False, "reason": "github_pr_line_stats_invalid"}
        if additions < 0 or deletions < 0:
            return {"ok": False, "reason": "github_pr_line_stats_invalid"}
        line_changes += additions + deletions
        normalized_files.append(filename)
    if line_changes > max_lines():
        return {"ok": False, "reason": "github_pr_line_limit_exceeded"}
    scope_digest = hashlib.sha256(
        json.dumps(
            {
                "files": sorted(normalized_files),
                "line_changes": line_changes,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "file_count": len(normalized_files),
        "line_changes": line_changes,
        "scope_digest": scope_digest,
    }


def verify_github_self_maintenance_merge(
    *,
    branch: str,
    base_branch: str,
    allowed_at: datetime,
    expected_merge_sha: str = "",
    fetch_json: Callable[[str, dict[str, str] | None], Any] | None = None,
) -> dict[str, Any]:
    """Verify one historical merge action from durable GitHub state.

    This proves only that the guarded low-risk merge occurred safely. Production
    deployment identity remains a separate release contract.
    """

    repository = _repository()
    safe_head = _safe_branch(branch)
    safe_base = _safe_branch(base_branch)
    expected_sha = str(expected_merge_sha or "").strip().lower()
    if not repository:
        return {"ok": False, "reason": "github_repository_invalid"}
    if not safe_head or not safe_base:
        return {"ok": False, "reason": "github_branch_invalid"}
    if expected_sha and not _SHA.fullmatch(expected_sha):
        return {"ok": False, "reason": "github_expected_merge_sha_invalid"}
    fetch = fetch_json or _default_fetch_json
    owner = repository.split("/", 1)[0]

    try:
        pulls = fetch(
            f"/repos/{repository}/pulls",
            {
                "head": f"{owner}:{safe_head}",
                "per_page": "20",
                "state": "all",
            },
        )
    except Exception:  # noqa: BLE001 - evidence outage must remain unknown
        return {"ok": False, "reason": "github_pull_evidence_unavailable"}
    candidates = []
    if isinstance(pulls, list):
        for pull in pulls:
            if not isinstance(pull, dict):
                continue
            head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
            base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
            merged_at = _timestamp(pull.get("merged_at"))
            if (
                str(head.get("ref") or "") == safe_head
                and str(base.get("ref") or "") == safe_base
                and str(pull.get("state") or "").lower() == "closed"
                and merged_at is not None
                and merged_at >= _utc(allowed_at)
            ):
                candidates.append(pull)
    if len(candidates) != 1:
        return {"ok": False, "reason": "github_merged_pull_not_unique"}

    pull = candidates[0]
    try:
        pull_number = int(pull.get("number"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "github_pull_number_invalid"}
    try:
        pull = fetch(f"/repos/{repository}/pulls/{pull_number}", None)
    except Exception:  # noqa: BLE001 - evidence outage must remain unknown
        return {"ok": False, "reason": "github_pull_detail_unavailable"}
    if not isinstance(pull, dict):
        return {"ok": False, "reason": "github_pull_detail_invalid"}
    try:
        detail_number = int(pull.get("number"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "github_pull_detail_invalid"}
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
    merged_at = _timestamp(pull.get("merged_at"))
    if (
        detail_number != pull_number
        or str(head.get("ref") or "") != safe_head
        or str(base.get("ref") or "") != safe_base
        or pull.get("merged") is not True
        or merged_at is None
        or merged_at < _utc(allowed_at)
    ):
        return {"ok": False, "reason": "github_pull_detail_contradiction"}
    merge_sha = str(pull.get("merge_commit_sha") or "").strip().lower()
    head_sha = str(head.get("sha") or "").strip().lower()
    try:
        changed_files = int(pull.get("changed_files"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "github_pull_file_count_invalid"}
    if not _SHA.fullmatch(merge_sha) or not _SHA.fullmatch(head_sha):
        return {"ok": False, "reason": "github_pull_sha_invalid"}
    if expected_sha and expected_sha != merge_sha:
        return {"ok": False, "reason": "github_merge_sha_contradiction"}
    if changed_files < 1 or changed_files > 100:
        return {"ok": False, "reason": "github_pull_file_count_invalid"}

    try:
        files = fetch(
            f"/repos/{repository}/pulls/{pull_number}/files",
            {"per_page": "100"},
        )
        checks = fetch(
            f"/repos/{repository}/commits/{head_sha}/check-runs",
            {"filter": "latest", "per_page": "100"},
        )
        comparison = fetch(
            (
                f"/repos/{repository}/compare/"
                f"{quote(merge_sha, safe='')}...{quote(safe_base, safe='')}"
            ),
            None,
        )
    except Exception:  # noqa: BLE001 - evidence outage must remain unknown
        return {"ok": False, "reason": "github_merge_evidence_unavailable"}
    if not isinstance(files, list) or len(files) != changed_files:
        return {"ok": False, "reason": "github_pr_files_incomplete"}
    scope = _merge_scope_verdict(files)
    if not scope.get("ok"):
        return scope

    if not isinstance(checks, dict):
        return {"ok": False, "reason": "github_check_runs_invalid"}
    check_runs = checks.get("check_runs")
    try:
        check_count = int(checks.get("total_count"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "github_check_runs_invalid"}
    if (
        not isinstance(check_runs, list)
        or check_count < 1
        or check_count > 100
        or len(check_runs) != check_count
    ):
        return {"ok": False, "reason": "github_check_runs_incomplete"}
    for check in check_runs:
        if (
            not isinstance(check, dict)
            or str(check.get("status") or "").lower() != "completed"
            or str(check.get("conclusion") or "").lower() not in _SUCCESSFUL_CHECK_CONCLUSIONS
        ):
            return {"ok": False, "reason": "github_check_run_not_successful"}

    if not isinstance(comparison, dict):
        return {"ok": False, "reason": "github_main_ancestry_invalid"}
    merge_base = (
        comparison.get("merge_base_commit")
        if isinstance(comparison.get("merge_base_commit"), dict)
        else {}
    )
    if (
        str(comparison.get("status") or "").lower() not in {"ahead", "identical"}
        or str(merge_base.get("sha") or "").lower() != merge_sha
    ):
        return {"ok": False, "reason": "github_merge_not_in_base_ancestry"}

    return {
        "ok": True,
        "verdict": "no_prohibited_miss",
        "evidence_ref": (
            f"github-pr:{pull_number}:merged:{merge_sha[:12]}"
            f"+checks:{check_count}+scope:{str(scope['scope_digest'])[:24]}"
        ),
        "reason": "github_merged_pr_scope_checks_and_ancestry_verified",
    }


__all__ = ["verify_github_self_maintenance_merge"]
