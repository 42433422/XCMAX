"""Queue only uncertain autonomous decisions for human review."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def queue_path() -> Path:
    raw = (os.environ.get("MODSTORE_AUTONOMOUS_UNCERTAINTY_QUEUE") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / "autonomous_uncertainty_queue.jsonl"


def _fingerprint(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _recent_fingerprints(limit: int = 300) -> set[str]:
    path = queue_path()
    if not path.exists():
        return set()
    rows: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(line)
    except OSError:
        return set()
    out = set()
    for line in rows[-limit:]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        fp = str(data.get("fingerprint") or "").strip()
        if fp:
            out.add(fp)
    return out


def enqueue_uncertain_item(
    *,
    context: Dict[str, Any],
    decision: Dict[str, Any],
    reason: str,
    source: str = "self_maintenance_loop",
) -> Dict[str, Any]:
    """Append a deduplicated uncertainty item.

    This is the Phase-D replacement for sending every merge to daily approval:
    humans see only blocked or low-confidence decisions.
    """

    if (
        os.environ.get("MODSTORE_AUTONOMOUS_UNCERTAINTY_QUEUE_ENABLED") or "1"
    ).strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {"queued": False, "reason": "disabled"}
    item = {
        "context": context,
        "decision": decision,
        "reason": reason,
        "schema_version": 1,
        "source": source,
        "ts": time.time(),
    }
    item["fingerprint"] = _fingerprint(
        {
            "branch": context.get("branch"),
            "reason": reason,
            "run_id": context.get("run_id"),
            "task_id": context.get("para_task_id"),
        }
    )
    if item["fingerprint"] in _recent_fingerprints():
        return {"fingerprint": item["fingerprint"], "queued": False, "reason": "duplicate"}
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return {"fingerprint": item["fingerprint"], "path": str(path), "queued": True}


__all__ = ["enqueue_uncertain_item", "queue_path"]
