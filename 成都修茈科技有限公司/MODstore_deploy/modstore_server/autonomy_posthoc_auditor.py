"""Independent post-execution verifier for narrowly supported autonomy actions.

The auditor never infers safety from an allow decision itself.  It requires a
later successful scheduler receipt plus a durable, structurally valid output
artifact before appending a conclusive ``no_prohibited_miss`` observation.
Unsupported actions and incomplete evidence remain unknown.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from modstore_server.autonomy_decision_audit import (
    record_posthoc_anomaly_evidence,
)
from modstore_server.db.scheduler_ops import JobRun
from modstore_server.models import AutonomyDecisionAudit, get_session_factory

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_METRICS_ACTION = "autonomy_metrics_snapshot"
_METRICS_SOURCE = "autonomy_metrics.cron"
_METRICS_JOB = "autonomy_metrics_snapshot"
_DETECTOR = "autonomy-posthoc-auditor.v1"
_VALID_SNAPSHOT_STATUSES = frozenset(
    {"collecting", "passed", "needs_tuning", "needs_review"}
)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _metrics_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    # Ask the producing module for its resolved path so the verifier observes
    # the exact artifact written by the current cleanroom/runtime environment.
    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()
    from app.domain.autonomy import operating_metrics

    return Path(operating_metrics._metrics_jsonl_path())  # noqa: SLF001


def _verify_metrics_artifact(
    *, action_id: str, metrics_path: Path
) -> dict[str, Any]:
    prefix = "autonomy-metrics:"
    snapshot_date = action_id[len(prefix) :] if action_id.startswith(prefix) else ""
    if not snapshot_date:
        return {"ok": False, "reason": "unsupported_action_id"}
    try:
        raw = metrics_path.read_bytes()
    except OSError:
        return {"ok": False, "reason": "metrics_artifact_unavailable"}

    matched: dict[int, dict[str, Any]] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict):
            continue
        if str(item.get("snapshot_date") or "") != snapshot_date:
            continue
        if str(item.get("cohort") or "operational") != "operational":
            continue
        try:
            window = int(item.get("window_days") or 0)
        except (TypeError, ValueError):
            continue
        if window in {30, 90}:
            matched[window] = item

    if set(matched) != {30, 90}:
        return {"ok": False, "reason": "metrics_windows_incomplete"}
    if any(
        str(item.get("status") or "") not in _VALID_SNAPSHOT_STATUSES
        or item.get("has_prohibited_miss") is True
        for item in matched.values()
    ):
        return {"ok": False, "reason": "metrics_artifact_reports_risk"}
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "ok": True,
        "artifact_sha256": digest,
        "snapshot_date": snapshot_date,
        "windows": [30, 90],
    }


def run_autonomy_posthoc_audit(
    *,
    metrics_path: str | Path | None = None,
    now: datetime | None = None,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Correlate allow decisions, later scheduler receipts and durable output.

    Only the metrics snapshot contract is supported initially.  Adding another
    action requires a dedicated verifier; generic success receipts can never
    prove that an arbitrary allowed action respected prohibited boundaries.
    """

    current = _utc(now)
    sf = session_factory or get_session_factory()
    with sf() as session:
        decisions = (
            session.query(AutonomyDecisionAudit)
            .filter(
                AutonomyDecisionAudit.record_type == "decision",
                AutonomyDecisionAudit.decision == "allow",
                AutonomyDecisionAudit.action == _METRICS_ACTION,
                AutonomyDecisionAudit.source == _METRICS_SOURCE,
            )
            .order_by(AutonomyDecisionAudit.occurred_at.asc())
            .all()
        )
        conclusive_ids = {
            str(row.action_id)
            for row in session.query(AutonomyDecisionAudit)
            .filter(
                AutonomyDecisionAudit.record_type == "posthoc_anomaly",
                AutonomyDecisionAudit.posthoc_verdict.in_(
                    ("no_prohibited_miss", "prohibited_miss")
                ),
            )
            .all()
        }
        successful_runs = (
            session.query(JobRun)
            .filter(JobRun.job_id == _METRICS_JOB, JobRun.status == "success")
            .order_by(JobRun.finished_at.desc(), JobRun.id.desc())
            .all()
        )

    first_allow: dict[str, datetime] = {}
    for row in decisions:
        action_id = str(row.action_id or "")
        occurred = _utc(row.occurred_at)
        if action_id and (
            action_id not in first_allow or occurred < first_allow[action_id]
        ):
            first_allow[action_id] = occurred

    artifact_path = _metrics_path(metrics_path)
    audited: list[str] = []
    incomplete: list[dict[str, str]] = []
    for action_id, allowed_at in sorted(first_allow.items()):
        if action_id in conclusive_ids:
            continue
        artifact = _verify_metrics_artifact(
            action_id=action_id,
            metrics_path=artifact_path,
        )
        if not artifact.get("ok"):
            incomplete.append(
                {"action_id": action_id, "reason": str(artifact.get("reason") or "unknown")}
            )
            continue
        receipt = next(
            (
                row
                for row in successful_runs
                if row.finished_at is not None and _utc(row.finished_at) >= allowed_at
            ),
            None,
        )
        if receipt is None:
            incomplete.append(
                {"action_id": action_id, "reason": "later_scheduler_receipt_missing"}
            )
            continue

        artifact_sha = str(artifact["artifact_sha256"])
        evidence_ref = f"scheduler-job:{receipt.id}+metrics-sha256:{artifact_sha[:40]}"
        event_key = hashlib.sha256(
            f"{action_id}|{receipt.id}|{artifact_sha}".encode("utf-8")
        ).hexdigest()[:40]
        record_posthoc_anomaly_evidence(
            action_id=action_id,
            verdict="no_prohibited_miss",
            evidence_ref=evidence_ref,
            detector=_DETECTOR,
            event_id=f"posthoc_{event_key}",
            occurred_at=current,
            session_factory=sf,
        )
        audited.append(action_id)

    return {
        "ok": True,
        "detector": _DETECTOR,
        "supported_contracts": [_METRICS_ACTION],
        "candidate_count": len(first_allow),
        "audited_count": len(audited),
        "audited_action_ids": audited,
        "incomplete_count": len(incomplete),
        "incomplete": incomplete,
        "writes_external_side_effects": False,
        "append_only_evidence_written": bool(audited),
    }


__all__ = ["run_autonomy_posthoc_audit"]
