"""Durable 30/90-day operating metrics for autonomous actions."""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.domain.autonomy.audit_log import summarize_autonomy_audit

_FHD_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_METRICS_PATH = _FHD_ROOT / "metrics" / "autonomy-metrics.jsonl"
_DEFAULT_BOUNDARIES_PATH = _FHD_ROOT / "config" / "autonomy_boundaries.yaml"
_LOCK = threading.RLock()
UTC = timezone.utc  # noqa: UP017 - shared module must import on Python 3.10


def _runtime_dir() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
    if not raw:
        raw = (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _FHD_ROOT / "metrics"


def _metrics_jsonl_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_METRICS_LOG_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / _DEFAULT_METRICS_PATH.name


def _boundaries_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_BOUNDARIES_PATH") or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_BOUNDARIES_PATH


def autonomy_boundary_review_status(*, now: datetime | None = None) -> dict[str, Any]:
    """Return the code-owned quarterly autonomy-boundary review status."""

    path = _boundaries_path()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("autonomy boundaries root must be an object")
        revision = max(0, int(raw.get("boundary_revision") or 0))
        cadence_days = max(1, int(raw.get("review_cadence_days") or 90))
        reviewed_raw = raw.get("last_reviewed_at")
        if isinstance(reviewed_raw, datetime):
            reviewed_at = reviewed_raw.date()
        elif isinstance(reviewed_raw, date):
            reviewed_at = reviewed_raw
        else:
            reviewed_at = date.fromisoformat(str(reviewed_raw or ""))
        next_review_at = reviewed_at + timedelta(days=cadence_days)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        due = current.astimezone(UTC).date() >= next_review_at
        return {
            "boundary_revision": revision,
            "last_reviewed_at": reviewed_at.isoformat(),
            "review_cadence_days": cadence_days,
            "next_review_at": next_review_at.isoformat(),
            "review_due": due,
            "status": "due" if due else "current",
        }
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return {
            "boundary_revision": 0,
            "last_reviewed_at": None,
            "review_cadence_days": 90,
            "next_review_at": None,
            "review_due": True,
            "status": "invalid",
            "error": str(exc),
        }


def evaluate_autonomy_window(
    days: int,
    *,
    include_synthetic: bool = False,
    summary: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate a 30/90-day operating window without claiming early success."""

    if days not in {30, 90}:
        raise ValueError("autonomy operating window must be 30 or 90 days")
    result = dict(
        summary or summarize_autonomy_audit(days=days, include_synthetic=include_synthetic)
    )
    observed = float(result.get("observed_days") or 0.0)
    veto_rate = float(result.get("veto_rate") or 0.0)
    total = int(result.get("total") or 0)
    complete = total > 0 and observed >= days
    boundary_review = autonomy_boundary_review_status(now=now)

    if result.get("has_prohibited_miss"):
        status = "failed"
        reason = "BLOCKED action execution evidence requires immediate incident review"
        recommendation = "incident_review"
    elif not complete:
        status = "collecting"
        reason = f"observed {observed:.2f}/{days} days"
        recommendation = "collect"
    elif veto_rate > 10.0:
        status = "needs_tuning"
        reason = "veto rate above 10%; review whether medium-risk boundaries are too strict"
        recommendation = "review_medium_risk_boundaries"
    elif days >= 90 and veto_rate < 1.0:
        status = "needs_tuning"
        reason = "veto rate below 1%; audit for missed or under-classified risk"
        recommendation = "audit_under_classification"
    elif days >= 90 and boundary_review["review_due"]:
        status = "needs_review"
        reason = "quarterly autonomy boundary review is due"
        recommendation = "review_boundaries"
    elif days >= 90 and 1.0 <= veto_rate <= 5.0:
        status = "passed"
        reason = "90-day veto rate is within 1-5%"
        recommendation = "continue"
    elif 30 <= days < 90 and veto_rate <= 5.0:
        status = "passed"
        reason = "30-day veto rate is at most 5%"
        recommendation = "continue"
    else:
        status = "needs_tuning"
        reason = "veto rate is outside the target window"
        recommendation = "review_risk_thresholds"
    return {
        **result,
        "status": status,
        "status_reason": reason,
        "recommendation": recommendation,
        "complete": complete,
        "boundary_review": boundary_review,
    }


def record_autonomy_metrics_snapshots(
    *,
    windows: tuple[int, ...] = (30, 90),
    include_synthetic: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Append at most one immutable snapshot per UTC day/window/cohort."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    snapshot_at = current.isoformat()
    snapshot_date = current.date().isoformat()
    cohort = "all" if include_synthetic else "operational"
    path = _metrics_jsonl_path()

    with _LOCK:
        existing: dict[tuple[str, int, str], dict[str, Any]] = {}
        if path.is_file():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        item = json.loads(line)
                        if not isinstance(item, dict):
                            continue
                        key = (
                            str(item.get("snapshot_date") or ""),
                            int(item.get("window_days") or 0),
                            str(item.get("cohort") or ""),
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    existing[key] = item
            except OSError:
                existing = {}

        results: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for window in windows:
            if int(window) not in {30, 90}:
                raise ValueError("autonomy snapshot windows must contain only 30 or 90")
            key = (snapshot_date, int(window), cohort)
            report = evaluate_autonomy_window(
                int(window), include_synthetic=include_synthetic, now=current
            )
            record = {**report, "snapshot_at": snapshot_at, "snapshot_date": snapshot_date}
            if key in existing:
                results.append(
                    {
                        **record,
                        "recorded": False,
                        "recorded_snapshot_at": existing[key].get("snapshot_at"),
                    }
                )
                continue
            pending.append(record)
            results.append({**record, "recorded": True})

        if pending:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                for record in pending:
                    stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return results


__all__ = [
    "autonomy_boundary_review_status",
    "evaluate_autonomy_window",
    "record_autonomy_metrics_snapshots",
]
