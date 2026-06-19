"""Autonomous release strategy selection from SLO signals."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _load_runtime_slo() -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_SLO_METRICS_FILE") or "").strip()
    path = Path(raw).expanduser() if raw else _runtime_dir() / "slo_metrics.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _payload_slo(payload: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("slo", "slo_metrics", "metrics"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _metric(metrics: Dict[str, Any], name: str, default: float) -> float:
    try:
        return float(metrics.get(name, default))
    except (TypeError, ValueError):
        return default


def _release_related(event_type: str, payload: Dict[str, Any]) -> bool:
    text = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=False).lower()
    return any(token in text for token in ("deploy", "release", "canary", "rollback", "slo", "smoke", "发布", "灰度", "回滚"))


def build_adaptive_release_plan(*, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {**_load_runtime_slo(), **_payload_slo(payload)}
    try:
        priority = int(payload.get("priority")) if payload.get("priority") is not None else 50
    except (TypeError, ValueError):
        priority = 50
    error_rate = _metric(metrics, "error_rate", 0.0)
    p95_ms = _metric(metrics, "p95_ms", 0.0)
    availability = _metric(metrics, "availability", 1.0)
    saturation = max(
        _metric(metrics, "cpu", 0.0),
        _metric(metrics, "memory", 0.0),
        _metric(metrics, "queue_saturation", 0.0),
    )
    bad_slo = (
        error_rate >= _env_float("MODSTORE_SLO_ERROR_RATE_ROLLBACK", 0.03)
        or (p95_ms > 0 and p95_ms >= _env_float("MODSTORE_SLO_P95_MS_ROLLBACK", 2500.0))
        or availability <= _env_float("MODSTORE_SLO_AVAILABILITY_ROLLBACK", 0.995)
    )
    needs_scale = saturation >= _env_float("MODSTORE_SLO_AUTOSCALE_SATURATION", 0.82)
    related = _release_related(event_type, payload)
    if related and (bad_slo or priority >= 95):
        action = "rollback"
        strategy = "rollback"
    elif related and needs_scale:
        action = "autoscale"
        strategy = "canary"
    elif related and priority >= 85:
        action = "gray_hold"
        strategy = "blue_green"
    elif related:
        action = "gray_hold"
        strategy = "rolling"
    elif needs_scale:
        action = "autoscale"
        strategy = "scale_only"
    else:
        action = "observe"
        strategy = "observe"
    return {
        "action": action,
        "bad_slo": bad_slo,
        "metrics": metrics,
        "needs_scale": needs_scale,
        "priority": priority,
        "release_related": related,
        "schema_version": 1,
        "slo_thresholds": {
            "availability_rollback": _env_float("MODSTORE_SLO_AVAILABILITY_ROLLBACK", 0.995),
            "autoscale_saturation": _env_float("MODSTORE_SLO_AUTOSCALE_SATURATION", 0.82),
            "error_rate_rollback": _env_float("MODSTORE_SLO_ERROR_RATE_ROLLBACK", 0.03),
            "p95_ms_rollback": _env_float("MODSTORE_SLO_P95_MS_ROLLBACK", 2500.0),
        },
        "source": "phase_d_adaptive_release_controller",
        "strategy": strategy,
        "ts": time.time(),
    }


__all__ = ["build_adaptive_release_plan"]
