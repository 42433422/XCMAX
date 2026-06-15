from __future__ import annotations

from pathlib import Path


def attendance_workspace_root(base: Path) -> Path:
    p = (base / "attendance_workspace").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p
