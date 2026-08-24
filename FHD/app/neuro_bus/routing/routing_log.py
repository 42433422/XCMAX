"""Append-only routing decision log for offline training."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.utils.path_io.ai_runtime_artifacts import mutable_ai_artifact_path


def _default_log_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    source_default = root / "resources" / "routing_policies" / "routing_decisions.jsonl"
    path = mutable_ai_artifact_path(
        "routing_policies/routing_decisions.jsonl",
        source_fallback=source_default,
    )
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    return path


def append_routing_decision(
    trace_id: str | None,
    features: list[float],
    action: str,
    latency_ms: float,
    outcome: str,
    reward: float | None = None,
    extra: dict[str, Any] | None = None,
    sla_hit: bool | None = None,
    success: bool | None = None,
) -> None:
    row = {
        "ts": time.time(),
        "trace_id": trace_id,
        "features": features,
        "action": action,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "reward": reward,
        "extra": extra or {},
        "sla_hit": sla_hit,
        "success": success,
    }
    path = Path(os.environ.get("XCAGI_ROUTING_LOG_PATH", str(_default_log_path())))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
