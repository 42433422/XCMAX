"""Release-train history read projection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def list_history(
    history_directory: Path,
    *,
    limit: int,
    logger: logging.Logger,
) -> list[Dict[str, Any]]:
    jsonl_path = history_directory / "history.jsonl"
    if not jsonl_path.is_file():
        return []
    rows: list[Dict[str, Any]] = []
    try:
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = entry.get("state") or {}
            rows.append(
                {
                    "saved_at": entry.get("saved_at"),
                    "reason": entry.get("reason"),
                    "current": state.get("current"),
                    "day_index": state.get("day_index"),
                    "last_bump_at": state.get("last_bump_at"),
                    "last_bump_day": state.get("last_bump_day"),
                }
            )
    except RECOVERABLE_ERRORS:
        logger.exception("release_train: read history failed")
        return []
    rows.reverse()
    return rows[: max(1, int(limit))]
