# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _changed_files_for_branch(
    *, repo_url: str, base_branch: str, branch: str, workspace: _facade().Path
) -> _facade().List[str]:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists() and (not _facade()._cleanup_merge_workspace(workspace)):
        raise RuntimeError(f"stale merge workspace cleanup failed: {workspace}")
    clone_errors: _facade().List[str] = []
    cloned_from = ""
    for repository in _facade()._para_repository_candidates(repo_url):
        if workspace.exists() and (not _facade()._cleanup_merge_workspace(workspace)):
            raise RuntimeError(f"failed clone workspace cleanup: {workspace}")
        try:
            _facade()._run_cmd(
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
    _facade()._run_cmd(["git", "fetch", "origin", base_branch], cwd=workspace, timeout=180)
    _fetch_branch = _facade().subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    branch_ref = f"origin/{branch}" if _fetch_branch.returncode == 0 else None
    if not branch_ref:
        bare_repo = (
            _facade()
            .os.environ.get(
                "MODSTORE_PARA_BARE_REPO",
                "/Users/a4243342/XCMAX-runtime/devfleet-bare.git",
            )
            .strip()
        )
        if bare_repo:
            _sp_run = _facade().subprocess.run(
                ["git", "fetch", bare_repo, branch],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if _sp_run.returncode == 0:
                _facade()._run_cmd(
                    [
                        "git",
                        "update-ref",
                        f"refs/remotes/origin/{branch}",
                        "FETCH_HEAD",
                    ],
                    cwd=workspace,
                )
                branch_ref = f"origin/{branch}"
                _facade().logger.info(
                    "auto_merge: fetched branch %s from Para bareRepo %s",
                    branch,
                    bare_repo,
                )
    if not branch_ref:
        _facade().logger.warning(
            "auto_merge: branch %s not on remote or bareRepo — Para may not have pushed it",
            branch,
        )
        return []
    diff = _facade()._run_cmd(
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


def _diff_numstat_for_branch(
    *, base_branch: str, branch: str, workspace: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    diff = _facade()._run_cmd(
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
    binary_files: _facade().List[str] = []
    per_file: _facade().Dict[str, _facade().Dict[str, int]] = {}
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


def _kb_json_kind_for_repo_path(file_name: str) -> _facade().Optional[str]:
    normalized = _facade()._normalize_repo_path(file_name)
    if normalized.startswith("FHD/XCAGI/kb/fixes/") and normalized.endswith(".json"):
        return "fixes"
    if normalized.startswith("FHD/XCAGI/kb/patterns/") and normalized.endswith(".json"):
        return "patterns"
    return None


def _validate_kb_json_changes_for_auto_merge(
    *, branch: str, files: _facade().List[str], workspace: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    checked: _facade().List[str] = []
    errors: _facade().List[_facade().Dict[str, str]] = []
    for file_name in files:
        kind = _facade()._kb_json_kind_for_repo_path(file_name)
        if not kind:
            continue
        normalized = _facade()._normalize_repo_path(file_name)
        checked.append(normalized)
        try:
            raw = _facade()._run_cmd(
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
            payload = _facade().json.loads(raw)
            _facade().validate_kb_payload(kind, payload)
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
