"""工作区路径工具。

Phase 3 从 ``app.legacy.workspace`` 迁入,API 保持不变。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

from fastapi import HTTPException


def workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()


def traditional_workspace_root() -> Path:
    base = workspace_root()
    tw = base / "traditional_workspace"
    tw.mkdir(parents=True, exist_ok=True)
    return tw


_MAX_URL_DECODE_PASSES = 5


def _fully_unquote_path(value: str) -> str:
    """Decode nested URL escaping so a later layer cannot reveal traversal."""
    current = value
    for _ in range(_MAX_URL_DECODE_PASSES):
        decoded = unquote(current)
        if decoded == current:
            return current
        current = decoded
    if unquote(current) != current:
        raise HTTPException(status_code=400, detail="invalid path")
    return current


def _safe_relative_parts(rel: str, *, allow_empty: bool) -> tuple[str, ...]:
    raw = _fully_unquote_path(str(rel or "").strip()).replace("\\", "/")
    if not raw:
        if allow_empty:
            return ()
        raise HTTPException(status_code=400, detail="missing path")
    if "\x00" in raw or raw.startswith("/") or PureWindowsPath(raw).drive:
        raise HTTPException(status_code=400, detail="invalid path")
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise HTTPException(status_code=400, detail="invalid path")
    candidate = PurePosixPath(raw)
    parts = candidate.parts
    if candidate.is_absolute() or tuple(raw_parts) != parts:
        raise HTTPException(status_code=400, detail="invalid path")
    return parts


def _confined_path(base: Path, parts: tuple[str, ...]) -> Path:
    # Components are rejected before touching the filesystem; resolve plus the
    # ancestry check also prevents an in-workspace symlink from escaping.
    try:
        target = base.joinpath(*parts).resolve(strict=False)  # lgtm[py/path-injection]
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    return target


def traditional_resolve_path(rel: str) -> Path:
    base = traditional_workspace_root()
    return _confined_path(base, _safe_relative_parts(rel, allow_empty=True))


def resolve_safe_workspace_relpath(rel: str) -> Path:
    base = workspace_root()
    return _confined_path(base, _safe_relative_parts(rel, allow_empty=False))


def resolve_safe_workspace_file(rel: str) -> Path:
    """Resolve an existing regular file confined to the configured workspace."""
    target = resolve_safe_workspace_relpath(rel)
    if not target.is_file():  # lgtm[py/path-injection]
        raise FileNotFoundError(f"workspace file not found: {rel}")
    return target


def read_safe_workspace_file(rel: str, *, max_bytes: int) -> tuple[Path, bytes]:
    """Read at most ``max_bytes`` from a workspace-confined regular file."""
    target = resolve_safe_workspace_file(rel)
    limit = max(0, int(max_bytes))
    with target.open("rb") as stream:  # lgtm[py/path-injection]
        return target, stream.read(limit)


__all__ = [
    "workspace_root",
    "traditional_workspace_root",
    "traditional_resolve_path",
    "resolve_safe_workspace_relpath",
    "resolve_safe_workspace_file",
    "read_safe_workspace_file",
]
