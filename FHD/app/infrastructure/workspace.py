"""工作区路径工具。

Phase 3 从 ``legacy-layer.workspace`` 迁入,API 保持不变。
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
    base_text = os.path.realpath(os.path.abspath(base))
    target_text = os.path.realpath(os.path.abspath(os.path.join(base_text, raw)))
    base_prefix = base_text.rstrip(os.sep) + os.sep
    if target_text != base_text and not target_text.startswith(base_prefix):
        raise HTTPException(status_code=400, detail="invalid path")
    target = Path(target_text)
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    return target


def resolve_safe_workspace_relpath(rel: str, *, base: Path | None = None) -> Path:
    """Resolve below the default workspace or a verified server-selected root.

    An explicit ``base`` must be a canonical absolute root selected by the
    server, never a request-provided override. Such callers pass native relative
    paths: URL decoding or separator rewriting could validate a different file
    from the one their filesystem consumer uses.
    """
    if base is None:
        base = workspace_root()
        raw = unquote(rel or "").strip().replace("\\", "/").lstrip("/")
    else:
        raw = rel or ""
        relative = Path(raw)
        if not base.is_absolute() or relative.is_absolute() or relative.drive or "\x00" in raw:
            raise HTTPException(status_code=400, detail="invalid path")
    if not raw:
        raise HTTPException(status_code=400, detail="missing path")
    base_text = os.path.realpath(os.path.abspath(base))
    base_prefix = base_text.rstrip(os.sep) + os.sep
    lexical = os.path.abspath(os.path.join(base_text, raw))
    if lexical != base_text and not lexical.startswith(base_prefix):
        raise HTTPException(status_code=400, detail="invalid path")
    # Preserve native symlink/parent semantics after the lexical boundary check.
    target_text = os.path.realpath(os.path.join(base_text, raw))
    if target_text == base_text:
        target = Path(base_text)
    elif target_text.startswith(base_prefix):
        target = Path(target_text)
    else:
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
