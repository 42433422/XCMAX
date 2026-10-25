"""Reject path traversal in user-supplied relative paths."""
from __future__ import annotations

from pathlib import Path


def safe_join(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if root == candidate or root in candidate.parents:
        return candidate
    raise ValueError("path escapes root")
