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


def _trusted_workspace_match(raw: Any, trusted_root: Path) -> str:
    """Return trusted_root when raw text exactly names the trusted checkout."""
    candidate = str(raw or "").strip()
    if not candidate or "\x00" in candidate:
        return ""
    candidate = candidate.rstrip("/\\")
    trusted = trusted_root.resolve()
    allowed = {str(trusted), trusted.as_posix()}
    try:
        home_relative = trusted.relative_to(Path.home().resolve())
        allowed.add(f"~/{home_relative.as_posix()}")
    except ValueError:
        pass
    if candidate in allowed:
        return str(trusted)
    return ""


def resolve_verified_relay_workspace_root(context: dict[str, Any] | None = None) -> str:
    """Return a verified git repo root for operator-owned mobile relay tasks.

    Client supplied paths are not trusted as arbitrary filesystem paths. They
    are only accepted when they textually match the locally inferred XCMAX
    checkout; the returned path is derived from that trusted checkout, not from
    client input. When older mobile builds do not send a path, source-tree runs
    infer the surrounding XCMAX checkout so Trae/Codex still execute against the
    real repo.
    """
    ctx = context if isinstance(context, dict) else {}
    inferred = _inferred_xcmax_repo_root()
    if not inferred:
        return ""
    trusted_root = Path(inferred)
    candidates = (
        ctx.get("workspace_root"),
        os.environ.get("XCMAX_RELAY_WORKSPACE_ROOT"),
        os.environ.get("DEVFLEET_WORKSPACE_ROOT"),
        inferred,
    )
    for raw in candidates:
        path = _trusted_workspace_match(raw, trusted_root)
        if path and _is_git_workspace(path):
            return path
    return ""


__all__ = ["resolve_verified_relay_workspace_root"]
