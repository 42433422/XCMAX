"""工作区 Excel 路径解析。

Phase 3B 从 ``app.legacy.attendance_paths`` 吸收。
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_workspace_excel(rel_path: str) -> Path:
    base = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    raw = (rel_path or "").replace("\\", "/").lstrip("/")
    p = (base / raw).resolve()
    p.relative_to(base)
    return p


__all__ = ["resolve_workspace_excel"]
