"""Git workspace, branch identity, diff and knowledge-file validation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import self_evolution_knowledge, self_maintenance_merge_policy
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config


def _run_cmd(
    args: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 120,
) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{output}")
    return output


def _cleanup_merge_workspace(workspace: Path) -> bool:
    """Remove one ephemeral merge workspace without widening the delete scope."""
    root = (config._runtime_dir() / config.DEFAULT_MERGE_WORKSPACE_ROOT).resolve()
    candidate = workspace.resolve()
    if candidate == root or root not in candidate.parents:
        config.logger.error("refusing to clean merge workspace outside root: %s", candidate)
        return False
    try:
        shutil.rmtree(candidate)
    except FileNotFoundError:
        return True
    except OSError:
        config.logger.exception("failed to clean merge workspace: %s", candidate)
        return False
    return True


def _para_repository_candidates(repo_url: str) -> List[str]:
    """Return authenticated Para transport first, then the public origin.

    Production Para branches are created by devices that do not share the
    scheduler's interactive HTTPS credentials.  ``MODSTORE_PARA_BARE_REPO``
    is therefore the durable transport contract and may be either a local
    bare path or an SSH URL.  The public origin remains a fail-soft fallback.
    """
    repositories: List[str] = []
    for candidate in (
        os.environ.get("MODSTORE_PARA_BARE_REPO", "").strip(),
        str(repo_url or "").strip(),
    ):
        if candidate and candidate not in repositories:
            repositories.append(candidate)
    return repositories


def _remote_branch_head(repo_url: str, branch: str) -> Optional[str]:
    """Resolve a Para branch head without mutating a workspace."""
    if not repo_url or not branch:
        return None
    for repository in _para_repository_candidates(repo_url):
        try:
            proc = subprocess.run(
                ["git", "ls-remote", "--heads", repository, f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        line = next(
            (item.strip() for item in (proc.stdout or "").splitlines() if item.strip()),
            "",
        )
        sha = line.split(None, 1)[0] if line else ""
        if re.fullmatch("[0-9a-fA-F]{40,64}", sha):
            return sha.lower()
    return None


def _validate_remediation_branch_delivery(
    *, base_branch: str, delivered_branch: str
) -> Dict[str, Any]:
    """Require a resumed code employee to advance its isolated work branch."""
    if not base_branch:
        return {"ok": True, "reason": "not_score_remediation"}
    if not delivered_branch:
        return {"ok": False, "reason": "missing_delivered_branch"}
    if delivered_branch == base_branch:
        return {
            "ok": False,
            "reason": "remediation_wrote_to_immutable_base_branch",
            "base_branch": base_branch,
            "delivered_branch": delivered_branch,
        }
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_head = _remote_branch_head(repo_url, base_branch)
    delivered_head = _remote_branch_head(repo_url, delivered_branch)
    if not delivered_head:
        return {
            "ok": False,
            "reason": "delivered_branch_head_unavailable",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
        }
    if base_head and delivered_head == base_head:
        return {
            "ok": False,
            "reason": "remediation_branch_not_advanced",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
            "delivered_head": delivered_head,
        }
    return {
        "ok": True,
        "reason": "remediation_branch_advanced",
        "base_branch": base_branch,
        "base_head": base_head,
        "delivered_branch": delivered_branch,
        "delivered_head": delivered_head,
    }


def _changed_files_for_branch(
    *, repo_url: str, base_branch: str, branch: str, workspace: Path
) -> List[str]:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists() and (not _cleanup_merge_workspace(workspace)):
        raise RuntimeError(f"stale merge workspace cleanup failed: {workspace}")
    clone_errors: List[str] = []
    cloned_from = ""
    for repository in _para_repository_candidates(repo_url):
        if workspace.exists() and (not _cleanup_merge_workspace(workspace)):
            raise RuntimeError(f"failed clone workspace cleanup: {workspace}")
        try:
            _run_cmd(
                [
                    "git",
                    "clone",
                    "--no-tags",
                    "--filter=blob:none",
                    "--no-checkout",
                    repository,
                    str(workspace),
                ],
                timeout=300,
            )
        except RECOVERABLE_ERRORS as exc:
            clone_errors.append(f"{type(exc).__name__}:{str(exc)[:300]}")
            continue
        cloned_from = repository
        break
    if not cloned_from:
        raise RuntimeError(
            "unable to clone Para repository through configured transports: "
            + "; ".join(clone_errors)
        )
    _run_cmd(["git", "fetch", "origin", base_branch], cwd=workspace, timeout=180)
    _fetch_branch = subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    branch_ref = f"origin/{branch}" if _fetch_branch.returncode == 0 else None
    if not branch_ref:
        bare_repo = os.environ.get(
            "MODSTORE_PARA_BARE_REPO",
            "/Users/a4243342/XCMAX-runtime/devfleet-bare.git",
        ).strip()
        if bare_repo:
            _sp_run = subprocess.run(
                ["git", "fetch", bare_repo, branch],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if _sp_run.returncode == 0:
                _run_cmd(
                    [
                        "git",
                        "update-ref",
                        f"refs/remotes/origin/{branch}",
                        "FETCH_HEAD",
                    ],
                    cwd=workspace,
                )
                branch_ref = f"origin/{branch}"
                config.logger.info(
                    "auto_merge: fetched branch %s from Para bareRepo %s",
                    branch,
                    bare_repo,
                )
    if not branch_ref:
        config.logger.warning(
            "auto_merge: branch %s not on remote or bareRepo — Para may not have pushed it",
            branch,
        )
        return []
    diff = _run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            f"origin/{base_branch}...{branch_ref}",
        ],
        cwd=workspace,
    )
    return [line.strip() for line in diff.splitlines() if line.strip()]


def _diff_numstat_for_branch(*, base_branch: str, branch: str, workspace: Path) -> Dict[str, Any]:
    diff = _run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--numstat",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
    )
    total_additions = 0
    total_deletions = 0
    binary_files: List[str] = []
    per_file: Dict[str, Dict[str, int]] = {}
    for raw_line in diff.splitlines():
        parts = raw_line.split("\t", 2)
        if len(parts) != 3:
            continue
        added_raw, deleted_raw, file_name = parts
        file_name = file_name.strip()
        if added_raw == "-" or deleted_raw == "-":
            binary_files.append(file_name)
            continue
        try:
            additions = int(added_raw)
            deletions = int(deleted_raw)
        except ValueError:
            binary_files.append(file_name)
            continue
        total_additions += additions
        total_deletions += deletions
        per_file[file_name] = {"additions": additions, "deletions": deletions}
    return {
        "additions": total_additions,
        "binary_files": binary_files,
        "changed_files": sorted(set(per_file) | set(binary_files)),
        "deletions": total_deletions,
        "files": per_file,
        "line_changes": total_additions + total_deletions,
        "source": "git_diff_numstat",
    }


def _kb_json_kind_for_repo_path(file_name: str) -> Optional[str]:
    normalized = _normalize_repo_path(file_name)
    if normalized.startswith("FHD/XCAGI/kb/fixes/") and normalized.endswith(".json"):
        return "fixes"
    if normalized.startswith("FHD/XCAGI/kb/patterns/") and normalized.endswith(".json"):
        return "patterns"
    return None


def _validate_kb_json_changes_for_auto_merge(
    *, branch: str, files: List[str], workspace: Path
) -> Dict[str, Any]:
    checked: List[str] = []
    errors: List[Dict[str, str]] = []
    for file_name in files:
        kind = _kb_json_kind_for_repo_path(file_name)
        if not kind:
            continue
        normalized = _normalize_repo_path(file_name)
        checked.append(normalized)
        try:
            raw = _run_cmd(
                [
                    "git",
                    "-c",
                    "core.quotePath=false",
                    "show",
                    f"origin/{branch}:{normalized}",
                ],
                cwd=workspace,
                timeout=60,
            )
            payload = json.loads(raw)
            self_evolution_knowledge.validate_kb_payload(kind, payload)
        except RECOVERABLE_ERRORS as exc:
            errors.append({"error": str(exc)[:500], "file": normalized, "kind": kind})
    if errors:
        return {
            "checked": checked,
            "errors": errors,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    return {
        "checked": checked,
        "ok": True,
        "reason": "kb_json_schema_valid" if checked else "no_kb_json_changes",
    }


def _normalize_repo_path(file_name: str) -> str:
    return self_maintenance_merge_policy.normalize_repo_path(file_name)


def _diff_stats_changed_files_consistency(
    files: List[str], diff_stats: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(diff_stats, dict) or diff_stats.get("source") != "git_diff_numstat":
        return {
            "ok": True,
            "reason": "diff_stats_consistency_not_enforced_for_legacy_input",
        }
    expected = {_normalize_repo_path(file_name) for file_name in files if file_name}
    stats_changed = diff_stats.get("changed_files")
    if not isinstance(stats_changed, list):
        file_stats = diff_stats.get("files") if isinstance(diff_stats.get("files"), dict) else {}
        if not isinstance(file_stats, dict):
            file_stats = {}
        binary_files = (
            diff_stats.get("binary_files")
            if isinstance(diff_stats.get("binary_files"), list)
            else []
        )
        if not isinstance(binary_files, list):
            binary_files = []
        stats_changed = list(file_stats.keys()) + binary_files
    actual = {_normalize_repo_path(str(file_name)) for file_name in stats_changed if str(file_name)}
    missing_from_numstat = sorted(expected - actual)
    extra_in_numstat = sorted(actual - expected)
    if missing_from_numstat or extra_in_numstat:
        return {
            "expected_name_only_files": sorted(expected),
            "extra_in_numstat": extra_in_numstat,
            "missing_from_numstat": missing_from_numstat,
            "numstat_files": sorted(actual),
            "ok": False,
            "reason": "changed_files_diff_stats_mismatch",
        }
    return {
        "checked_files": sorted(expected),
        "ok": True,
        "reason": "changed_files_diff_stats_match",
    }


def _file_matches_any_glob(file_name: str, globs: List[str]) -> bool:
    return self_maintenance_merge_policy.file_matches_any_glob(file_name, globs)


def _files_match_allowed_globs(files: List[str], globs: List[str]) -> bool:
    if not files:
        return False
    for file_name in files:
        if not _file_matches_any_glob(file_name, globs):
            return False
    return True
