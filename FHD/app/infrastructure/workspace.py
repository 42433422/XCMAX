"""工作区路径工具。

Phase 3 从 ``app.legacy.workspace`` 迁入,API 保持不变。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException


def workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()


def traditional_workspace_root() -> Path:
    base = workspace_root()
    tw = base / "traditional_workspace"
    tw.mkdir(parents=True, exist_ok=True)
    return tw


def traditional_resolve_path(rel: str) -> Path:
    base = traditional_workspace_root()
    raw = unquote(rel or "").strip().replace("\\", "/").lstrip("/")
    target = (base / raw).resolve() if raw else base
    base_prefix = base.as_posix().rstrip("/") + "/"
    if target != base and not target.as_posix().startswith(base_prefix):
        raise HTTPException(status_code=400, detail="invalid path")
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    return target


def resolve_safe_workspace_relpath(rel: str) -> Path:
    base = workspace_root()
    raw = unquote(rel or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        raise HTTPException(status_code=400, detail="missing path")
    target = (base / raw).resolve()
    base_prefix = base.as_posix().rstrip("/") + "/"
    if target != base and not target.as_posix().startswith(base_prefix):
        raise HTTPException(status_code=400, detail="invalid path")
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    return target


def resolve_existing_file_under_root(base: Path, rel: str) -> Path:
    """Resolve an existing regular file without passing untrusted text to filesystem APIs.

    Each user-controlled path component is matched against names returned by
    ``os.scandir``.  The path used for the next filesystem operation therefore
    always comes from the trusted directory listing, and symlink traversal is
    rejected at every level.
    """

    root = base.resolve()
    raw = unquote(rel or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or (len(raw) >= 3 and raw[1:3] == ":/"):
        raise ValueError("invalid path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid path")

    current = root
    for index, part in enumerate(parts):
        try:
            with os.scandir(current) as entries:
                entry = next((candidate for candidate in entries if candidate.name == part), None)
        except OSError as exc:
            raise FileNotFoundError(raw) from exc
        if entry is None or entry.is_symlink():
            raise FileNotFoundError(raw)
        is_last = index == len(parts) - 1
        if is_last:
            if not entry.is_file(follow_symlinks=False):
                raise FileNotFoundError(raw)
        elif not entry.is_dir(follow_symlinks=False):
            raise FileNotFoundError(raw)
        current = Path(entry.path)
    return current


def resolve_existing_workspace_file(rel: str) -> Path:
    return resolve_existing_file_under_root(workspace_root(), rel)


def allocate_generated_workspace_file(kind: str) -> Path:
    """Allocate a server-named workspace file for a fixed product use case."""

    specs = {
        "attendance-upload-xlsx": ("uploads", "attendance-upload-", ".xlsx"),
        "attendance-upload-xlsm": ("uploads", "attendance-upload-", ".xlsm"),
        "attendance-upload-xls": ("uploads", "attendance-upload-", ".xls"),
        "attendance-output": ("424", "attendance-output-", ".xlsx"),
        "attendance-export": ("attendance_exports", "attendance-export-", ".xlsx"),
    }
    spec = specs.get(kind)
    if spec is None:
        raise ValueError("unsupported workspace file kind")
    directory_name, prefix, suffix = spec
    directory = workspace_root() / directory_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}{uuid.uuid4().hex}{suffix}"


__all__ = [
    "workspace_root",
    "traditional_workspace_root",
    "traditional_resolve_path",
    "resolve_safe_workspace_relpath",
    "resolve_existing_file_under_root",
    "resolve_existing_workspace_file",
    "allocate_generated_workspace_file",
]
