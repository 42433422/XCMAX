"""Append-only routing decision log for offline training."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir


def _is_frozen_runtime() -> bool:
    """Return whether the module is running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def _runtime_data_root() -> Path | None:
    """Resolve the writable root for runtime routing telemetry.

    A packaged XCAGI backend lives below ``Contents/Resources``.  That path is
    part of the signed application and must never receive append-only runtime
    data.  Electron normally supplies ``XCAGI_DATA_DIR``; the frozen fallback
    also uses the platform application-data directory if that variable is
    unexpectedly absent.
    """
    raw = (os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if _is_frozen_runtime():
        return Path(get_app_data_dir()).expanduser().resolve()
    return None


def _default_log_path() -> Path:
    runtime_root = _runtime_data_root()
    if runtime_root is not None:
        d = runtime_root / "logs" / "routing_policies"
    else:
        # Preserve the source-tree default for local development and offline
        # training, where no desktop data root is configured.
        root = Path(__file__).resolve().parents[3]
        d = root / "resources" / "routing_policies"
    d.mkdir(parents=True, exist_ok=True)
    return d / "routing_decisions.jsonl"


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
