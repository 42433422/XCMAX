"""Pure policy for resuming self-maintenance runs after infrastructure recovery."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


def _is_retryable_infrastructure_failure(error: Any) -> bool:
    """Return whether a terminal loop error is a transient Para transport outage."""

    normalized = str(error or "").strip().lower()
    if not normalized or "handler=para_delegate" not in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "device_online_wait_timeout",
            "server disconnected without sending a response",
            "connection reset by peer",
            "connection refused",
            "connect econnrefused",
            "设备未在线",
            "设备 mac 主设备 modstore bridge 未在线",
        )
    )


def pending_run_recovery(
    rows: Iterable[Mapping[str, Any]],
    triggered_by: str,
) -> Optional[Dict[str, Any]]:
    """Return a safe same-trigger cooldown bypass for the latest run.

    Interrupted runs and Para transport/device outages are recoverable.  Real
    code, review, QA, governance and delivery-validation failures are not.
    """

    latest_start: Optional[Mapping[str, Any]] = None
    terminal_by_run: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        phase = str(row.get("phase") or "").strip()
        if phase == "start":
            latest_start = row
        elif phase in {"complete", "skip"}:
            terminal_by_run[run_id] = row

    if latest_start is None:
        return None
    run_id = str(latest_start.get("run_id") or "").strip()
    terminal = terminal_by_run.get(run_id)
    if terminal is None:
        return None
    expected_trigger = str(latest_start.get("triggered_by") or "").strip()
    if not expected_trigger or expected_trigger != str(triggered_by or "").strip():
        return None

    started_at = str(latest_start.get("started_at") or latest_start.get("created_at") or "").strip()
    terminal_status = str(terminal.get("status") or "").strip()
    if terminal_status == "abandoned_interrupted":
        return {
            "detail": {
                "interrupted_at": str(terminal.get("completed_at") or "").strip(),
                "run_id": run_id,
                "started_at": started_at,
                "triggered_by": expected_trigger,
            },
            "kind": "interrupted_recovery",
        }

    failure_error = str(terminal.get("error") or "").strip()
    if terminal_status != "failed" or not _is_retryable_infrastructure_failure(failure_error):
        return None
    return {
        "detail": {
            "failed_at": str(terminal.get("completed_at") or "").strip(),
            "failure_class": "para_transport_unavailable",
            "run_id": run_id,
            "started_at": started_at,
            "triggered_by": expected_trigger,
        },
        "kind": "transient_failure_recovery",
    }


__all__ = ["pending_run_recovery"]
