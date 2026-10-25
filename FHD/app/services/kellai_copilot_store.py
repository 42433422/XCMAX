"""Atomic JSON persistence for derived Kellai copilot artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def empty_store() -> dict[str, Any]:
    return {"version": 2, "drafts": {}, "follow_up_tasks": {}}


def read_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return empty_store()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store()
    return value if isinstance(value, dict) else empty_store()


def write_store(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
