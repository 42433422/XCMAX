# mypy: disable-error-code="arg-type"
"""Independent post-execution verifier for supported autonomy actions.

The auditor never infers safety from an allow decision itself.  It requires a
contract-specific later receipt before appending a conclusive observation.
Unsupported actions and incomplete or contradictory evidence remain unknown.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from modstore_server.autonomy_decision_audit import (
    record_posthoc_anomaly_evidence,
)
from modstore_server.autonomy_posthoc_contracts import (
    default_para_task_fetcher,
    load_self_maintenance_records,
    verify_code_write_action,
    verify_daily_digest_action,
    verify_self_maintenance_merge_action,
)
from modstore_server.autonomy_posthoc_github import (
    verify_github_self_maintenance_merge as default_github_merge_fetcher,
)
from modstore_server.autonomy_posthoc_github import (
    verify_github_self_maintenance_veto as default_github_veto_fetcher,
)
from modstore_server.autonomy_posthoc_storage import (
    load_storage_pressure_records,
    verify_storage_pressure_action,
)
from modstore_server.db.scheduler_ops import JobRun
from modstore_server.models import AutonomyDecisionAudit, get_session_factory

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_METRICS_ACTION = "autonomy_metrics_snapshot"
_METRICS_SOURCE = "autonomy_metrics.cron"
_METRICS_JOB = "autonomy_metrics_snapshot"
_CODE_WRITE_ACTION = "code_write"
_CODE_WRITE_SOURCE = "modstore.auto_approve_policy"
_DAILY_DIGEST_ACTION = "daily_digest"
_DAILY_DIGEST_SOURCE = "daily_digest.cron"
_MERGE_ACTION = "self_maintenance_l1_merge"
_MERGE_SOURCE = "self_maintenance_loop.remote_merge_request"
_STORAGE_ACTION = "bounded_storage_retention"
_STORAGE_SOURCE = "storage_pressure_self_heal"
_DETECTOR = "autonomy-posthoc-auditor.v2"
_VALID_SNAPSHOT_STATUSES = frozenset({"collecting", "passed", "needs_tuning", "needs_review"})


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


def _verify_metrics_artifact(*, action_id: str, metrics_path: Path) -> dict[str, Any]:
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
    storage_audit_path: str | Path | None = None,
    self_maintenance_ledger_path: str | Path | None = None,
    para_task_fetcher: Callable[[str], dict[str, Any]] | None = None,
    github_merge_fetcher: Callable[..., dict[str, Any]] | None = None,
    github_veto_fetcher: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
    session_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Correlate allow decisions with dedicated independent verifiers."""

    current = _utc(now)
    cutoff = current - timedelta(days=30)
    sf = session_factory or get_session_factory()
    with sf() as session:
        decisions = (
            session.query(AutonomyDecisionAudit)
            .filter(
                AutonomyDecisionAudit.record_type == "decision",
                AutonomyDecisionAudit.decision == "allow",
                AutonomyDecisionAudit.occurred_at >= cutoff,
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
        successful_metric_runs = (
            session.query(JobRun)
            .filter(JobRun.job_id == _METRICS_JOB, JobRun.status == "success")
            .order_by(JobRun.finished_at.desc(), JobRun.id.desc())
            .all()
        )

    first_allow: dict[str, tuple[datetime, str, str]] = {}
    for row in decisions:
        action_id = str(row.action_id or "")
        occurred = _utc(row.occurred_at)
        previous = first_allow.get(action_id)
        if action_id and (previous is None or occurred < previous[0]):
            first_allow[action_id] = (
                occurred,
                str(row.action or ""),
                str(row.source or ""),
            )

    metric_candidates = any(
        action == _METRICS_ACTION and source == _METRICS_SOURCE
        for _allowed_at, action, source in first_allow.values()
    )
    artifact_path = _metrics_path(metrics_path) if metric_candidates else None
    merge_candidates = any(
        action == _MERGE_ACTION and source == _MERGE_SOURCE
        for _allowed_at, action, source in first_allow.values()
    )
    merge_records = (
        load_self_maintenance_records(self_maintenance_ledger_path) if merge_candidates else []
    )
    storage_candidates = any(
        action == _STORAGE_ACTION and source == _STORAGE_SOURCE
        for _allowed_at, action, source in first_allow.values()
    )
    storage_records = (
        load_storage_pressure_records(storage_audit_path) if storage_candidates else []
    )
    fetch_para_task = para_task_fetcher or default_para_task_fetcher
    fetch_github_merge = github_merge_fetcher or default_github_merge_fetcher
    fetch_github_veto = github_veto_fetcher or default_github_veto_fetcher
    audited: list[str] = []
    incomplete: list[dict[str, str]] = []
    for action_id, contract in sorted(first_allow.items()):
        if action_id in conclusive_ids:
            continue
        allowed_at, action, source = contract
        observation: dict[str, Any]
        if action == _METRICS_ACTION and source == _METRICS_SOURCE:
            artifact = _verify_metrics_artifact(
                action_id=action_id,
                metrics_path=artifact_path or Path(),
            )
            receipt = next(
                (
                    row
                    for row in successful_metric_runs
                    if row.finished_at is not None and _utc(row.finished_at) >= allowed_at
                ),
                None,
            )
            if not artifact.get("ok"):
                observation = artifact
            elif receipt is None:
                observation = {"ok": False, "reason": "later_scheduler_receipt_missing"}
            else:
                artifact_sha = str(artifact["artifact_sha256"])
                observation = {
                    "ok": True,
                    "verdict": "no_prohibited_miss",
                    "evidence_ref": (
                        f"scheduler-job:{receipt.id}+metrics-sha256:{artifact_sha[:40]}"
                    ),
                }
        elif action == _CODE_WRITE_ACTION and source == _CODE_WRITE_SOURCE:
            observation = verify_code_write_action(
                action_id=action_id,
                allowed_at=allowed_at,
                session_factory=sf,
            )
        elif action == _DAILY_DIGEST_ACTION and source == _DAILY_DIGEST_SOURCE:
            observation = verify_daily_digest_action(
                action_id=action_id,
                allowed_at=allowed_at,
                session_factory=sf,
            )
        elif action == _MERGE_ACTION and source == _MERGE_SOURCE:
            observation = verify_self_maintenance_merge_action(
                action_id=action_id,
                allowed_at=allowed_at,
                records=merge_records,
                para_task_fetcher=fetch_para_task,
                github_merge_fetcher=fetch_github_merge,
                github_veto_fetcher=fetch_github_veto,
            )
        elif action == _STORAGE_ACTION and source == _STORAGE_SOURCE:
            observation = verify_storage_pressure_action(
                action_id=action_id,
                allowed_at=allowed_at,
                records=storage_records,
            )
        else:
            observation = {"ok": False, "reason": "unsupported_contract"}
        if not observation.get("ok"):
            incomplete.append(
                {
                    "action_id": action_id,
                    "reason": str(observation.get("reason") or "unknown"),
                }
            )
            continue

        verdict = str(observation.get("verdict") or "no_prohibited_miss")
        evidence_ref = str(observation.get("evidence_ref") or "")
        if not evidence_ref:
            incomplete.append({"action_id": action_id, "reason": "evidence_ref_missing"})
            continue
        event_key = hashlib.sha256(f"{action_id}|{verdict}|{evidence_ref}".encode()).hexdigest()[
            :40
        ]
        record_posthoc_anomaly_evidence(
            action_id=action_id,
            verdict=verdict,
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
        "supported_contracts": [
            _METRICS_ACTION,
            _CODE_WRITE_ACTION,
            _DAILY_DIGEST_ACTION,
            _MERGE_ACTION,
            _STORAGE_ACTION,
        ],
        "candidate_count": len(first_allow),
        "audited_count": len(audited),
        "audited_action_ids": audited,
        "incomplete_count": len(incomplete),
        "incomplete": incomplete,
        "writes_external_side_effects": False,
        "append_only_evidence_written": bool(audited),
    }


__all__ = ["run_autonomy_posthoc_audit"]
