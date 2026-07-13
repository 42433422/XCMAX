"""Resolve user-referenced files by selecting entries from a trusted directory tree."""

from __future__ import annotations

import os
from pathlib import Path, PurePath


def existing_file_under(root: Path, raw_path: object) -> Path | None:
    """Return an existing file below ``root`` without opening a tainted path.

    The requested name is used only for comparison.  Every returned ``Path``
    originates from ``Path.iterdir()``, so the filesystem operation always
    follows a child selected from the trusted root rather than a constructed
    user path.
    """

    base = root.resolve()
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    requested = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(base, raw))
    try:
        if os.path.commonpath((str(base), requested)) != str(base):
            return None
    except ValueError:
        return None

    relative = os.path.relpath(requested, base)
    parts = PurePath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None

    current = base
    for index, part in enumerate(parts):
        try:
            match = next((entry for entry in current.iterdir() if entry.name == part), None)
        except OSError:
            return None
        if match is None:
            return None
        current = match
        if index < len(parts) - 1 and not current.is_dir():
            return None
    return current if current.is_file() else None


__all__ = ["existing_file_under"]
