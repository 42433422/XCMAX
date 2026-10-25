"""Fail-closed runtime provenance for autonomous maintenance and delivery.

The autonomy loop must never mutate or release code when the running checkout
cannot be tied to the intended clean commit.  Packaged/immutable releases may
not contain ``.git``; those deployments provide the same proof through build
environment variables.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_manifest() -> tuple[Optional[Path], Dict[str, Any]]:
    configured = (os.environ.get("MODSTORE_RELEASE_MANIFEST") or "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    runtime_root = (os.environ.get("MODSTORE_RUNTIME_ROOT") or "").strip()
    if runtime_root:
        candidates.append(Path(runtime_root).expanduser() / ".xcmax-runtime-provenance.json")
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return path.resolve(), payload
    return (candidates[0].resolve(), {}) if candidates else (None, {})


def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return result.returncode, (result.stdout or "").rstrip("\r\n")


def resolve_runtime_repo_root(explicit: Optional[str | Path] = None) -> Optional[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for key in ("MODSTORE_REPO_ROOT", "XCMAX_MONOREPO_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / ".git").exists():
            return candidate
    return None


def collect_runtime_provenance(
    *,
    repo_root: Optional[str | Path] = None,
    target_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Return an auditable, fail-closed source identity snapshot.

    A Git checkout is trusted only when it is clean, is on the intended branch,
    and its HEAD equals either the explicit expected SHA or the locally fetched
    ``origin/<target>`` ref.  An immutable package is trusted only when both the
    built SHA and expected SHA are present and equal.
    """

    target = str(target_branch or os.environ.get("MODSTORE_PARA_BRANCH") or "main").strip()
    expected = str(
        expected_sha
        or os.environ.get("MODSTORE_EXPECTED_GIT_SHA")
        or os.environ.get("XCAGI_EXPECTED_GIT_SHA")
        or ""
    ).strip()
    root = resolve_runtime_repo_root(repo_root)
    if root is None:
        built_sha = str(
            os.environ.get("MODSTORE_GIT_SHA")
            or os.environ.get("GIT_SHA")
            or os.environ.get("COMMIT_SHA")
            or ""
        ).strip()
        manifest_reasons: list[str] = []
        manifest_path, manifest = _runtime_manifest()
        manifest_sha = str(manifest.get("git_sha") or "").strip()
        verified_files: list[str] = []
        if not built_sha:
            manifest_reasons.append("missing_build_git_sha")
        if not expected:
            manifest_reasons.append("missing_expected_git_sha")
        if built_sha and expected and built_sha != expected:
            manifest_reasons.append("build_sha_mismatch")
        if manifest_path is not None:
            if not manifest:
                manifest_reasons.append("release_manifest_unavailable")
            elif not manifest_sha:
                manifest_reasons.append("release_manifest_missing_git_sha")
            elif manifest_sha not in {built_sha, expected}:
                manifest_reasons.append("release_manifest_sha_mismatch")
        file_hashes = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(file_hashes, dict) and manifest_path is not None:
            manifest_root = (
                Path(str(manifest.get("runtime_root") or manifest_path.parent))
                .expanduser()
                .resolve()
            )
            for relative, wanted in sorted(file_hashes.items()):
                candidate = (manifest_root / str(relative)).resolve()
                try:
                    candidate.relative_to(manifest_root)
                except ValueError:
                    manifest_reasons.append("release_manifest_path_escape")
                    continue
                try:
                    actual = _sha256(candidate)
                except OSError:
                    manifest_reasons.append(f"runtime_file_unavailable:{relative}")
                    continue
                if actual != str(wanted):
                    manifest_reasons.append(f"runtime_file_hash_mismatch:{relative}")
                    continue
                verified_files.append(str(relative))
        if os.environ.get("MODSTORE_DAILY_ENV_CLEANROOM") == "1":
            if not manifest:
                manifest_reasons.append("cleanroom_manifest_required")
            elif not isinstance(file_hashes, dict) or not file_hashes:
                manifest_reasons.append("cleanroom_file_hashes_required")
        return {
            "branch": target,
            "clean": None,
            "dirty_paths": [],
            "expected_sha": expected,
            "head_sha": built_sha,
            "manifest_path": str(manifest_path or ""),
            "manifest_sha": manifest_sha,
            "ok": not manifest_reasons,
            "reasons": manifest_reasons,
            "repo_root": "",
            "source": "immutable_manifest" if manifest else "immutable_environment",
            "target_sha": expected,
            "verified_files": verified_files,
        }

    _, head_sha = _git(root, "rev-parse", "HEAD")
    _, branch = _git(root, "branch", "--show-current")
    status_rc, status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    dirty_paths = [line[3:] for line in status.splitlines() if len(line) > 3]
    target_sha = expected
    if not target_sha and target:
        target_rc, resolved = _git(root, "rev-parse", f"refs/remotes/origin/{target}")
        if target_rc == 0:
            target_sha = resolved

    reasons: list[str] = []
    if not head_sha:
        reasons.append("missing_head_sha")
    if status_rc != 0:
        reasons.append("git_status_failed")
    elif dirty_paths:
        reasons.append("dirty_worktree")
    if not branch:
        reasons.append("detached_head")
    elif target and branch != target:
        reasons.append("branch_mismatch")
    if not target_sha:
        reasons.append("missing_target_sha")
    elif head_sha != target_sha:
        reasons.append("head_sha_mismatch")

    return {
        "branch": branch,
        "clean": status_rc == 0 and not dirty_paths,
        "dirty_paths": dirty_paths[:50],
        "expected_sha": expected,
        "head_sha": head_sha,
        "ok": not reasons,
        "reasons": reasons,
        "repo_root": str(root),
        "source": "git_checkout",
        "target_branch": target,
        "target_sha": target_sha,
    }


__all__ = ["collect_runtime_provenance", "resolve_runtime_repo_root"]
