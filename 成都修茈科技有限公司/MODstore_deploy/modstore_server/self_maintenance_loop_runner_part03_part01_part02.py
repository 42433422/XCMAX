# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _recent_employee_failure_count(lookback_hours: int) -> int:
    since = _facade()._utc_now() - _facade().timedelta(hours=lookback_hours)
    db = _facade().get_session_factory()()
    try:
        return (
            db.query(_facade().EmployeeExecutionMetric)
            .filter(_facade().EmployeeExecutionMetric.created_at >= since)
            .filter(_facade().EmployeeExecutionMetric.status != "success")
            .count()
        )
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to count recent employee failures")
        return 1
    finally:
        db.close()


def _recent_incident_signals(
    lookback_hours: int, *, limit: int = 8
) -> _facade().Dict[str, _facade().Any]:
    """Return fresh incident signals that should wake the maintenance loop.

    The 03:00 cron remains as a batch safety net, but Phase A treats new
    quality/error/security incidents as a real-time signal for employee
    delegation.
    """
    since = _facade()._utc_now() - _facade().timedelta(hours=lookback_hours)
    event_types = {
        "ci.failed",
        "incident.unknown",
        "on_error",
        "on_quality_fail",
        "security.alert",
    }
    db = _facade().get_session_factory()()
    try:
        query = (
            db.query(_facade().IncidentEvent)
            .filter(_facade().IncidentEvent.created_at >= since)
            .filter(_facade().IncidentEvent.event_type.in_(sorted(event_types)))
            .order_by(_facade().IncidentEvent.created_at.desc())
        )
        rows = query.limit(max(1, int(limit))).all()
        count = query.count()
        incidents: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for row in rows:
            payload: _facade().Dict[str, _facade().Any] = {}
            try:
                loaded = _facade().json.loads(row.payload_json or "{}")
                if isinstance(loaded, dict):
                    payload = loaded
            except _facade().json.JSONDecodeError:
                payload = {}
            incidents.append(
                {
                    "created_at": (
                        _facade()._iso(row.created_at)
                        if isinstance(row.created_at, _facade().datetime)
                        else str(row.created_at or "")
                    ),
                    "event_type": row.event_type,
                    "fingerprint": row.fingerprint,
                    "id": int(row.id),
                    "source": row.source,
                    "summary": str(payload.get("summary") or "")[:500],
                }
            )
        return {
            "count": int(count),
            "events": incidents,
            "lookback_hours": lookback_hours,
        }
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to read recent incident signals")
        return {"count": 1, "events": [], "error": "incident_signal_query_failed"}
    finally:
        db.close()


def evaluate_self_maintenance_need() -> _facade().Dict[str, _facade().Any]:
    """Return deterministic signals used by the threshold gate."""
    gaps: _facade().List[str] = []
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    device_id = _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    api_base = _facade().os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    branch = _facade().os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    runtime_provenance = _facade().collect_runtime_provenance(target_branch=branch or "main")
    if not api_base:
        gaps.append("missing MODSTORE_PARA_API_BASE")
    if not device_id:
        gaps.append("missing MODSTORE_PARA_DEVICE_ID")
    if not repo_url:
        gaps.append("missing MODSTORE_PARA_REPO_URL")
    elif "/Desktop/" in repo_url and (
        not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_ALLOW_DESKTOP_REPO", False)
    ):
        gaps.append("repo url still points into Desktop")
    if not branch:
        gaps.append("missing MODSTORE_PARA_BRANCH")
    if _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True) and (
        not runtime_provenance.get("ok")
    ):
        reasons = ",".join((str(item) for item in runtime_provenance.get("reasons") or []))
        gaps.append(f"runtime provenance blocked: {reasons or 'unknown'}")
    repo_path = _facade()._file_url_to_path(repo_url)
    if repo_path is not None and (not repo_path.exists()):
        gaps.append(f"repo url path does not exist: {repo_path}")
    lookback_hours = _facade()._env_int("MODSTORE_SELF_MAINTENANCE_LOOKBACK_HOURS", 24)
    failure_count = _facade()._recent_employee_failure_count(lookback_hours)
    incident_signals = _facade()._recent_incident_signals(lookback_hours)
    incident_count = int(incident_signals.get("count") or 0)
    proactive_signals = _facade().collect_proactive_signals()
    proactive_task_count = (
        len(proactive_signals.get("candidates") or [])
        if _facade()._env_bool("MODSTORE_SELF_EVOLUTION_PROACTIVE_ENABLED", True)
        else 0
    )
    signal_count = len(gaps) + failure_count + incident_count + proactive_task_count
    return {
        "api_base": api_base,
        "branch": branch,
        "device_id": device_id,
        "failure_count": failure_count,
        "gaps": gaps,
        "incident_count": incident_count,
        "incident_signals": incident_signals,
        "lookback_hours": lookback_hours,
        "proactive_signals": proactive_signals,
        "proactive_task_count": proactive_task_count,
        "repo_url": repo_url,
        "runtime_provenance": runtime_provenance,
        "signal_count": signal_count,
    }


def _last_started_at() -> _facade().Optional[_facade().datetime]:
    for row in reversed(_facade()._read_ledger()):
        if row.get("phase") == "start":
            return _facade()._parse_iso(row.get("started_at") or row.get("created_at"))
    return None
