"""Account-scoped private draft storage, always outside a source checkout."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def require_private_directory(path: Path) -> Path:
    """Reject source-tree destinations, including symlink aliases into a checkout."""
    resolved = path.expanduser().resolve()
    if any(_git_checkout(parent) for parent in (resolved, *resolved.parents)):
        raise ValueError("private business data must be stored outside a Git checkout")
    return resolved


def draft_asset_directory(*, user_id: int, session_id: str, repo_root: Path | None = None) -> Path:
    """Resolve a draft without creating or deleting anything.

    ``repo_root`` remains a compatibility seam for isolated callers, but it must
    be an external data directory. Production uses MODSTORE_RUNTIME_DIR.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise ValueError("user_id must be a positive integer")
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("invalid draft session_id")
    if repo_root is not None:
        runtime = require_private_directory(Path(repo_root)) / "var"
    else:
        configured = os.environ.get("MODSTORE_RUNTIME_DIR", "").strip()
        runtime = require_private_directory(
            Path(configured) if configured else Path(tempfile.gettempdir()) / "modstore_runtime"
        )
    current = runtime
    for component in ("employee_draft_assets", str(user_id), session_id):
        current = current / component
        if current.is_symlink():
            raise ValueError("draft storage must not contain symlink components")
    require_private_directory(current)
    return current


def reset_draft_directory(path: Path) -> None:
    """Replace only a previously validated draft; never follow a linked draft."""
    require_private_directory(path)
    if path.is_symlink():
        raise ValueError("draft storage must not be a symlink")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=False)


def _git_checkout(path: Path) -> bool:
    marker = path / ".git"
    if marker.is_dir():
        return (marker / "HEAD").is_file()
    return marker.is_file() and marker.read_text(encoding="utf-8").startswith("gitdir: ")
