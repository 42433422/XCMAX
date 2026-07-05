"""Resolve the local repo used by mobile relay development tasks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _is_git_workspace(root: str | Path) -> bool:
    try:
        return (Path(root).expanduser() / ".git").exists()
    except OSError:
        return False


def _inferred_xcmax_repo_root() -> str:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "FHD":
            repo = parent.parent
            if _is_git_workspace(repo):
                return str(repo)
    return ""


def resolve_verified_relay_workspace_root(context: dict[str, Any] | None = None) -> str:
    """Return a verified git repo root for operator-owned mobile relay tasks.

    Client supplied paths are only accepted after local verification. When older
    mobile builds do not send a path, source-tree runs infer the surrounding
    XCMAX checkout so Trae/Codex still execute against the real repo.
    """
    ctx = context if isinstance(context, dict) else {}
    candidates = (
        ctx.get("workspace_root"),
        os.environ.get("XCMAX_RELAY_WORKSPACE_ROOT"),
        os.environ.get("DEVFLEET_WORKSPACE_ROOT"),
        _inferred_xcmax_repo_root(),
    )
    for raw in candidates:
        root = str(raw or "").strip()
        if not root:
            continue
        path = Path(root).expanduser()
        if _is_git_workspace(path):
            return str(path)
    return ""


__all__ = ["resolve_verified_relay_workspace_root"]
