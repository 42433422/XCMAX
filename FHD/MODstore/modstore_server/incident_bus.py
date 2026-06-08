"""事件轨 incident 队列（MODstore 侧）。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_QUEUE_NAME = "six_line_incident_bus.jsonl"


def _queue_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    data = root / "data" / "six_line"
    data.mkdir(parents=True, exist_ok=True)
    return data / _QUEUE_NAME


def enqueue(entry: dict[str, Any]) -> dict[str, Any]:
    row = dict(entry)
    row.setdefault("at", datetime.now(timezone.utc).isoformat())
    row.setdefault("state", "pending")
    path = _queue_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("incident_bus enqueue %s %s", row.get("event_type"), row.get("priority"))
    return row


def pending_count() -> int:
    path = _queue_path()
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def recent(limit: int = 20) -> list[dict[str, Any]]:
    path = _queue_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
