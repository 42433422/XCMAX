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
_TASK_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SUCCESSFUL_CHECK_CONCLUSIONS = frozenset({"neutral", "skipped", "success"})
_GENERATED_MERGE_REQUIRED_CHECKS = frozenset(
    {
        "release-verify",
        "review",
        "security-scan",
    }
)


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


def _generated_para_merge_contract_verdict(
    *,
    pull: dict[str, Any],
    checks: list[dict[str, Any]],
    expected_task_id: str,
    branch: str,
    base_branch: str,
) -> dict[str, Any]:
    """Bind an out-of-legacy-scope merge to the guarded Para PR contract."""

    task_id = str(expected_task_id or "").strip()
    if not _TASK_ID.fullmatch(task_id):
        return {"ok": False, "reason": "github_para_task_id_invalid"}
    body = str(pull.get("body") or "")
    required_markers = (
        "## Para 自动派工产物",
        f"**任务 ID**: {task_id}",
        f"**工作分支**: `{branch}`",
        f"**目标分支**: `{base_branch}`",
        "本 PR 由 merge-worker 自动创建",
        "AI review APPROVE",
        "`risk:r0`",
        "`hold-merge`",
        "`github-actions[bot]`",
    )
    if any(marker not in body for marker in required_markers):
        return {"ok": False, "reason": "github_para_generated_contract_missing"}

    labels = pull.get("labels") if isinstance(pull.get("labels"), list) else []
    label_names = {
        str(label.get("name") or "").strip().lower() for label in labels if isinstance(label, dict)
    }
    if "risk:r0" not in label_names or "hold-merge" in label_names:
        return {"ok": False, "reason": "github_para_merge_labels_invalid"}
    merged_by = pull.get("merged_by") if isinstance(pull.get("merged_by"), dict) else {}
    if str(merged_by.get("login") or "").strip().lower() != "github-actions[bot]":
        return {"ok": False, "reason": "github_para_merge_actor_invalid"}

    successful_action_checks = {
        str(check.get("name") or "").strip()
        for check in checks
        if isinstance(check, dict)
        and str(check.get("status") or "").lower() == "completed"
        and str(check.get("conclusion") or "").lower() == "success"
        and str(
            (check.get("app") if isinstance(check.get("app"), dict) else {}).get("slug") or ""
        ).lower()
        == "github-actions"
    }
    missing_checks = sorted(_GENERATED_MERGE_REQUIRED_CHECKS - successful_action_checks)
    if missing_checks:
        return {
            "ok": False,
            "reason": "github_para_required_checks_missing",
            "missing_checks": missing_checks,
        }

    contract_digest = hashlib.sha256(
        json.dumps(
            {
                "base_branch": base_branch,
                "branch": branch,
                "labels": sorted(label_names),
                "merge_actor": "github-actions[bot]",
                "required_checks": sorted(_GENERATED_MERGE_REQUIRED_CHECKS),
                "task_id": task_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "contract_digest": contract_digest,
        "reason": "github_para_generated_merge_contract_verified",
    }


def _merge_scope_verdict(
    files: Any,
    *,
    allow_generated_contract: bool = False,
) -> dict[str, Any]:
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
        if not allow_generated_contract and file_matches_any_glob(filename, forbidden):
            return {"ok": False, "reason": "github_pr_forbidden_scope"}
        if not allow_generated_contract and not file_matches_any_glob(filename, allowed_scope):
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
                "contract": (
                    "generated_para_merge" if allow_generated_contract else "legacy_low_risk_scope"
                ),
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
        "scope_mode": (
            "generated_para_merge" if allow_generated_contract else "legacy_low_risk_scope"
        ),
        "scope_digest": scope_digest,
    }


def verify_github_self_maintenance_merge(
    *,
    branch: str,
    base_branch: str,
    allowed_at: datetime,
    expected_merge_sha: str = "",
    expected_task_id: str = "",
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

    generated_contract = _generated_para_merge_contract_verdict(
        pull=pull,
        checks=check_runs,
        expected_task_id=expected_task_id,
        branch=safe_head,
        base_branch=safe_base,
    )
    scope = _merge_scope_verdict(
        files,
        allow_generated_contract=generated_contract.get("ok") is True,
    )
    if not scope.get("ok"):
        if (
            str(expected_task_id or "").strip()
            and scope.get("reason")
            in {
                "github_pr_forbidden_scope",
                "github_pr_outside_low_risk_scope",
            }
            and not generated_contract.get("ok")
        ):
            return generated_contract
        return scope

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

    generated_digest = str(generated_contract.get("contract_digest") or "")
    evidence_ref = (
        f"github-pr:{pull_number}:merged:{merge_sha[:12]}"
        f"+checks:{check_count}+scope:{str(scope['scope_digest'])[:24]}"
    )
    reason = "github_merged_pr_scope_checks_and_ancestry_verified"
    if generated_contract.get("ok") is True:
        evidence_ref += f"+para-contract:{generated_digest[:24]}"
        reason = "github_generated_para_merge_checks_and_ancestry_verified"
    return {
        "ok": True,
        "verdict": "no_prohibited_miss",
        "evidence_ref": evidence_ref,
        "reason": reason,
    }


def verify_github_self_maintenance_veto(
    *,
    branch: str,
    base_branch: str,
    fetch_json: Callable[[str, dict[str, str] | None], Any] | None = None,
) -> dict[str, Any]:
    """Verify that the exact branch remains unmerged behind an explicit veto."""

    repository = _repository()
    safe_head = _safe_branch(branch)
    safe_base = _safe_branch(base_branch)
    if not repository:
        return {"ok": False, "reason": "github_repository_invalid"}
    if not safe_head or not safe_base:
        return {"ok": False, "reason": "github_branch_invalid"}
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
            if str(head.get("ref") or "") == safe_head and str(base.get("ref") or "") == safe_base:
                candidates.append(pull)
    if len(candidates) != 1:
        return {"ok": False, "reason": "github_pull_not_unique"}
    try:
        pull_number = int(candidates[0].get("number"))
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
    labels = pull.get("labels") if isinstance(pull.get("labels"), list) else []
    label_names = {
        str(label.get("name") or "").strip().lower() for label in labels if isinstance(label, dict)
    }
    if (
        detail_number != pull_number
        or str(head.get("ref") or "") != safe_head
        or str(base.get("ref") or "") != safe_base
        or pull.get("merged") is not False
        or _timestamp(pull.get("merged_at")) is not None
    ):
        return {"ok": False, "reason": "github_unmerged_pull_contradiction"}
    if "hold-merge" not in label_names:
        return {"ok": False, "reason": "github_explicit_veto_missing"}
    return {
        "ok": True,
        "evidence_ref": f"github-pr:{pull_number}:unmerged:veto:hold-merge",
        "reason": "github_unmerged_pull_explicitly_vetoed",
    }


__all__ = [
    "verify_github_self_maintenance_merge",
    "verify_github_self_maintenance_veto",
]
