"""应用版本 SSOT（与 pyproject.toml [project].version 对齐）。"""

from __future__ import annotations

__version__ = "10.0.0"


def get_version() -> str:
    return __version__
