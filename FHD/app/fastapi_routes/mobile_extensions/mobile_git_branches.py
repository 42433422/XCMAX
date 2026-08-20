"""Git branch discovery used by mobile AI group dispatch."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.fastapi_routes.mobile_extensions.models import AiGroupMessageBody
from app.utils.operational_errors import RECOVERABLE_ERRORS


def clean_mobile_git_branch(raw: Any) -> str:
    branch = str(raw or "").strip()
    for prefix in ("refs/heads/", "refs/remotes/", "origin/"):
        if branch.startswith(prefix):
            branch = branch.removeprefix(prefix)
    branch = re.sub(r"[^A-Za-z0-9._/-]+", "-", branch)[:180].strip("/.")
    if not branch or branch in {"HEAD", "origin/HEAD", ".", ".."}:
        return ""
    if ".." in branch or "//" in branch or "@{" in branch or branch.endswith(".lock"):
        return ""
    return branch


def branch_context_from_body(body: AiGroupMessageBody) -> str:
    context_raw = getattr(body, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    return clean_mobile_git_branch(
        getattr(body, "branch_context", "")
        or getattr(body, "branch", "")
        or context.get("branch_context")
        or context.get("branch")
    )


def git_repo_root() -> Path | None:
    candidates: list[Path] = []
    for key in (
        "XCMAX_REPO_ROOT",
        "FHD_REPO_ROOT",
        "DEVFLEET_REPO_ROOT",
        "CODEX_WORKSPACE",
        "WORKSPACE_ROOT",
    ):
        value = str(os.environ.get(key) or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    candidates.append(Path.cwd())
    candidates.extend(Path(__file__).resolve().parents)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            roots = [candidate, *candidate.parents] if candidate.exists() else [candidate]
        except RuntimeError:
            roots = [candidate]
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            if (root / ".git").exists():
                return root
    return None


def _git_no_prompt_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "true")
    return env


def sort_mobile_git_branches(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    branches = list(rows)
    branches.sort(
        key=lambda item: (
            not bool(item.get("current")),
            0 if item.get("name") in {"main", "master"} else 1,
            str(item.get("name") or "").lower(),
        )
    )
    return branches[:200]


def git_branches_from_repo(repo: Path) -> list[dict[str, Any]]:
    current = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_git_no_prompt_env(),
            check=False,
        )
        if result.returncode == 0:
            current = clean_mobile_git_branch(result.stdout)
    except RECOVERABLE_ERRORS:
        current = ""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads",
                "refs/remotes/origin",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=_git_no_prompt_env(),
            check=False,
        )
    except RECOVERABLE_ERRORS:
        return []
    if result.returncode != 0:
        return []
    branches: dict[str, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        raw = line.strip()
        if not raw or raw == "origin/HEAD":
            continue
        remote = raw.startswith("origin/")
        name = clean_mobile_git_branch(raw)
        if not name:
            continue
        row = branches.setdefault(name, {"name": name, "current": False, "remote": False})
        row["current"] = bool(row["current"] or name == current)
        row["remote"] = bool(row["remote"] or remote)
    return sort_mobile_git_branches(branches.values())


def git_branches_from_remote() -> list[dict[str, Any]]:
    remote_url = str(
        os.environ.get("XCMAX_GIT_REMOTE_URL")
        or os.environ.get("FHD_GIT_REMOTE_URL")
        or "https://github.com/42433422/XCMAX.git"
    ).strip()
    if not remote_url:
        return []
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote_url],
            capture_output=True,
            text=True,
            timeout=15,
            env=_git_no_prompt_env(),
            check=False,
        )
    except RECOVERABLE_ERRORS:
        return []
    if result.returncode != 0:
        return []
    branches: dict[str, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        if "refs/heads/" not in line:
            continue
        name = clean_mobile_git_branch(line.rsplit("refs/heads/", 1)[-1])
        if name:
            branches[name] = {"name": name, "current": False, "remote": True}
    return sort_mobile_git_branches(branches.values())
