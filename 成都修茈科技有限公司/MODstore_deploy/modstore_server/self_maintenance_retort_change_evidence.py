"""Bounded change-path evidence for the self-maintenance Retort preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from modstore_server.operational_errors import BOUNDARY_ERRORS


def _github_repository_identity(repo_url: str) -> Optional[Tuple[str, str]]:
    """Return the owner/repository pair for a GitHub transport URL."""

    raw = str(repo_url or "").strip()
    if not raw:
        return None
    host = ""
    path = ""
    if raw.startswith("git@") and ":" in raw:
        host_path = raw.split("@", 1)[1]
        host, path = host_path.split(":", 1)
    else:
        parsed = urlparse(raw)
        host = str(parsed.hostname or "")
        path = parsed.path
    if host.lower() != "github.com":
        return None
    parts = [part for part in str(path or "").strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not owner or not repo or any(" " in value for value in (owner, repo)):
        return None
    return owner, repo


def github_compare_changed_files(*, repo_url: str, base_branch: str, branch: str) -> List[str]:
    """Fetch GitHub's server-side compare paths as a bounded diff fallback.

    A response capped by GitHub at 300 paths remains safe: downstream policy
    treats a large diff as non-auto-mergeable.
    """

    identity = _github_repository_identity(repo_url)
    if identity is None:
        raise RuntimeError("github_compare_repository_unavailable")
    owner, repo = identity
    compare = f"{quote(base_branch, safe='')}...{quote(branch, safe='')}"
    request = Request(
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/compare/{compare}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xcmax-self-maintenance",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API host
        payload = json.loads(response.read().decode("utf-8"))
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        raise RuntimeError("github_compare_files_missing")
    return [
        str(item.get("filename") or "").strip()
        for item in files[:300]
        if isinstance(item, dict) and str(item.get("filename") or "").strip()
    ]


def resolve_retort_change_evidence(
    *,
    run_id: str,
    branch: str,
    repo_url: str,
    base_branch: str,
    memory: Dict[str, Any],
    workspace_root: Path,
    changed_files_for_branch: Callable[[Path], List[str]],
    cleanup_workspace: Callable[[Path], bool],
) -> Dict[str, Any]:
    """Resolve path evidence without turning transport loss into a human hold."""

    target = str(branch or "").strip()
    changed_files: List[str] = []
    source = "none"
    errors: List[str] = []
    if target and repo_url and base_branch:
        workspace = workspace_root / "retort-review-gate" / str(run_id or "run")
        try:
            changed_files = changed_files_for_branch(workspace)
            source = "git_diff"
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - fall back to GitHub/memory evidence
            errors.append(f"git_diff:{type(exc).__name__}")
        finally:
            cleanup_workspace(workspace)
        if not changed_files and errors:
            try:
                changed_files = github_compare_changed_files(
                    repo_url=repo_url,
                    base_branch=base_branch,
                    branch=target,
                )
                source = "github_compare"
            except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - fall back to memory hints
                source = "unavailable"
                errors.append(f"github_compare:{type(exc).__name__}")
    elif target:
        errors.append("git_diff:configuration_missing")
        source = "unavailable"

    if not changed_files:
        memory_files = memory.get("changed_files") if isinstance(memory, dict) else None
        if isinstance(memory_files, list):
            changed_files = [str(item).strip() for item in memory_files if str(item).strip()][:80]
            if changed_files:
                source = "memory"

    result: Dict[str, Any] = {
        "changed_files": changed_files,
        "errors": errors,
        "source": source,
    }
    if target and not changed_files:
        result["skip_reason"] = (
            "gate_change_evidence_unavailable" if errors else "gate_no_changed_files"
        )
    return result
