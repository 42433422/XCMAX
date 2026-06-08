"""工作区路径工具。

Phase 3 从 ``app.legacy.workspace`` 迁入,API 保持不变。
"""

from __future__ import annotations

import os
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
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid path") from e
    return target


__all__ = [
    "workspace_root",
    "traditional_workspace_root",
    "traditional_resolve_path",
    "resolve_safe_workspace_relpath",
]
