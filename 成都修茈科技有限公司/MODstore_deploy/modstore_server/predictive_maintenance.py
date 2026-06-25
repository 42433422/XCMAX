"""Predictive maintenance from self-evolution KB time series."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

WINDOW_DAYS = 30


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _kb_fixes_dir() -> Path:
    try:
        from modstore_server.self_evolution_knowledge import kb_root

        return kb_root() / "fixes"
    except Exception:
        return Path.home() / "Desktop" / "XCMAX" / "FHD" / "XCAGI" / "kb" / "fixes"


def _parse_time(value: Any, fallback_path: Path) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return datetime.now(timezone.utc)


def _incident_class(payload: Dict[str, Any]) -> str:
    text = " ".join(
        str(payload.get(k) or "") for k in ("symptom", "root_cause", "fix_diff")
    ).lower()
    buckets = {
        "auth": ("auth", "jwt", "csrf", "token", "credential", "permission"),
        "email": ("smtp", "imap", "email", "mail", "邮件"),
        "scheduler": ("scheduler", "cron", "apscheduler", "heartbeat", "launchd"),
        "android": ("adb", "android", "emulator", "p-app"),
        "database": ("sqlite", "postgres", "database", "db", "migration"),
        "employee": ("employee", "para", "task", "worker", "员工"),
        "release": ("release", "deploy", "slo", "rollback", "canary"),
        "kb": ("kb", "rag", "redisvl", "knowledge", "fixes"),
    }
    for name, terms in buckets.items():
        if any(term in text for term in terms):
            return name
    tokens = re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]{2,}", text)
    return tokens[0][:32] if tokens else "unknown"


def _load_fix_events() -> List[Dict[str, Any]]:
    directory = _kb_fixes_dir()
    if not directory.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        created = _parse_time(payload.get("created_at"), path)
        rows.append(
            {
                "class": _incident_class(payload),
                "created_at": created,
                "path": str(path),
                "symptom": str(payload.get("symptom") or "")[:500],
            }
        )
    return rows


def forecast_next_24h(*, window_days: int = WINDOW_DAYS) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(window_days or WINDOW_DAYS)))
    events = [row for row in _load_fix_events() if row["created_at"] >= cutoff]
    by_class: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in events:
        by_class[str(row["class"])].append(row)
    forecasts: List[Dict[str, Any]] = []
    for cls, rows in by_class.items():
        rows.sort(key=lambda item: item["created_at"])
        count = len(rows)
        if count <= 0:
            continue
        gaps_hours: List[float] = []
        for prev, cur in zip(rows, rows[1:]):
            gaps_hours.append(
                max(0.0, (cur["created_at"] - prev["created_at"]).total_seconds() / 3600.0)
            )
        avg_gap = sum(gaps_hours) / len(gaps_hours) if gaps_hours else float(window_days * 24)
        last_age = max(0.0, (now - rows[-1]["created_at"]).total_seconds() / 3600.0)
        frequency_score = min(1.0, count / max(1.0, window_days / 3.0))
        due_score = min(1.0, last_age / max(1.0, avg_gap))
        confidence = round(min(0.95, 0.35 + frequency_score * 0.35 + due_score * 0.25), 3)
        eta_hours = max(1.0, avg_gap - last_age)
        forecasts.append(
            {
                "class": cls,
                "confidence": confidence,
                "count": count,
                "eta_hours": round(eta_hours, 2),
                "last_seen_at": rows[-1]["created_at"].isoformat(),
                "sample_symptom": rows[-1].get("symptom"),
            }
        )
    forecasts.sort(
        key=lambda item: (float(item["confidence"]), -float(item["eta_hours"])), reverse=True
    )
    return {
        "forecast_horizon_hours": 24,
        "generated_at": now.isoformat(),
        "history_count": len(events),
        "ok": True,
        "predictions": forecasts[:10],
        "window_days": window_days,
    }


def run_predictive_maintenance_once() -> Dict[str, Any]:
    forecast = forecast_next_24h()
    path = _runtime_dir() / "predictive_maintenance_forecast.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(forecast, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    threshold = float(os.environ.get("MODSTORE_PREDICTIVE_MAINTENANCE_CONFIDENCE", "0.7"))
    emitted = False
    top = forecast.get("predictions", [{}])[0] if forecast.get("predictions") else {}
    if isinstance(top, dict) and float(top.get("confidence") or 0.0) >= threshold:
        try:
            from modstore_server.incident_bus import publish_unified_incident

            emitted = publish_unified_incident(
                event_type="on_error",
                fingerprint=f"predictive:{top.get('class')}:{int(time.time() // 86400)}",
                payload={"prediction": top, "forecast": forecast},
                priority=70,
                scope="predictive_maintenance",
                source="predictive_maintenance",
                summary=(
                    f"预测维护：未来 24h 可能出现 {top.get('class')} 类 incident，"
                    f"confidence={top.get('confidence')}"
                ),
            )
        except Exception:
            emitted = False
    return {**forecast, "emitted_incident": emitted, "forecast_path": str(path)}


__all__ = ["forecast_next_24h", "run_predictive_maintenance_once"]
