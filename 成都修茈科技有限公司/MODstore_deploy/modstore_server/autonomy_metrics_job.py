"""Daily production snapshot for the 30/90-day autonomy operating windows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path, evaluate_risk

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_ATTENTION_STATUSES = frozenset({"failed", "needs_review", "needs_tuning"})


def run_autonomy_metrics_snapshot(*, now: datetime | None = None) -> dict[str, Any]:
    """Record one idempotent production snapshot per UTC day and window."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    decision = evaluate_risk(
        "autonomy_metrics_snapshot",
        action_id=f"autonomy-metrics:{current.date().isoformat()}",
        source="autonomy_metrics.cron",
    )
    if not decision.allowed:
        return {
            "ok": False,
            "skipped": True,
            "reason": "autonomy_guard_blocked",
            "risk_decision": decision.to_dict(),
        }

    ensure_fhd_on_path()
    from app.domain.autonomy.operating_metrics import record_autonomy_metrics_snapshots

    snapshots = record_autonomy_metrics_snapshots(now=current)
    attention = [item for item in snapshots if item.get("status") in _ATTENTION_STATUSES]
    severity = (
        "critical"
        if any(item.get("status") == "failed" for item in attention)
        else ("warning" if attention else "info")
    )
    return {
        "ok": True,
        "skipped": False,
        "snapshot_date": current.date().isoformat(),
        "snapshots": snapshots,
        "alert": bool(attention),
        "severity": severity,
        "risk_decision": decision.to_dict(),
    }


__all__ = ["run_autonomy_metrics_snapshot"]
