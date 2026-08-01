"""Disk-pressure detection and bounded autonomous retention.

The daily retention job limits growth, but it does not answer the incident
question: when the filesystem is already under pressure, did the system notice,
perform only the pre-approved cleanup, and prove that pressure was relieved?

This module closes that loop without broad filesystem deletion.  It can only
invoke :mod:`file_retention_janitor`, whose targets and notification kinds are
explicit allow-lists.  Every observation is appended to a bounded rolling JSONL
ledger; an action is additionally recorded in the append-only autonomy decision
table.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_DIR = str(Path.home() / ".xcmax" / "modstore-daily")
DEFAULT_AUDIT_NAME = "storage_pressure_self_heal_runs.jsonl"
DEFAULT_LEASE_NAME = "storage_pressure_self_heal.lock"
GIB = 1024**3


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or DEFAULT_RUNTIME_DIR).expanduser()


def audit_path() -> Path:
    raw = str(os.environ.get("MODSTORE_STORAGE_SELF_HEAL_AUDIT_FILE") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_AUDIT_NAME


def lease_path() -> Path:
    raw = str(os.environ.get("MODSTORE_STORAGE_SELF_HEAL_LOCK_FILE") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_LEASE_NAME


def _audit_archive_path() -> Path:
    path = audit_path()
    return path.with_suffix(path.suffix + ".1")


def _audit_max_bytes() -> int:
    return _bounded_env_int("MODSTORE_STORAGE_AUDIT_MAX_MIB", 16, 1, 1024) * 1024**2


def _monitor_path() -> Path:
    explicit = str(os.environ.get("MODSTORE_STORAGE_MONITOR_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    database_url = str(os.environ.get("DATABASE_URL") or "").strip().lower()
    if database_url and not database_url.startswith("sqlite"):
        return _runtime_dir().resolve()

    from modstore_server.models import default_db_path

    return default_db_path().parent.resolve()


def _database_size_bytes() -> int:
    database_url = str(os.environ.get("DATABASE_URL") or "").strip().lower()
    if database_url and not database_url.startswith("sqlite"):
        return 0
    try:
        from modstore_server.models import default_db_path

        path = default_db_path()
        return int(path.stat().st_size) if path.exists() else 0
    except OSError:
        return 0


def collect_storage_snapshot(
    *,
    disk_usage_fn: Callable[[str], Any] = shutil.disk_usage,
) -> Dict[str, Any]:
    """Collect one filesystem observation from the data-bearing mount."""

    path = _monitor_path()
    usage = disk_usage_fn(str(path))
    total = max(0, int(usage.total))
    free = max(0, int(usage.free))
    used = max(0, int(getattr(usage, "used", total - free)))
    used_percent = round((used / total) * 100.0, 3) if total else 100.0
    return {
        "path": str(path),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": used_percent,
        "database_size_bytes": _database_size_bytes(),
        "observed_at": _utc().isoformat(),
    }


def pressure_thresholds() -> Dict[str, Any]:
    trigger_free_gib = _bounded_env_float("MODSTORE_STORAGE_MIN_FREE_GIB", 10.0, 0.25, 4096.0)
    trigger_used_percent = _bounded_env_float("MODSTORE_STORAGE_MAX_USED_PERCENT", 90.0, 50.0, 99.9)
    recovery_free_gib = _bounded_env_float(
        "MODSTORE_STORAGE_RECOVERY_MIN_FREE_GIB",
        max(12.0, trigger_free_gib),
        trigger_free_gib,
        4096.0,
    )
    recovery_used_percent = _bounded_env_float(
        "MODSTORE_STORAGE_RECOVERY_MAX_USED_PERCENT",
        min(88.0, trigger_used_percent),
        40.0,
        trigger_used_percent,
    )
    return {
        "trigger_min_free_bytes": int(trigger_free_gib * GIB),
        "trigger_max_used_percent": trigger_used_percent,
        "recovery_min_free_bytes": int(recovery_free_gib * GIB),
        "recovery_max_used_percent": recovery_used_percent,
    }


def pressure_reasons(snapshot: Dict[str, Any], thresholds: Dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(snapshot.get("free_bytes") or 0) < int(thresholds["trigger_min_free_bytes"]):
        reasons.append("free_bytes_below_threshold")
    if float(snapshot.get("used_percent") or 0.0) >= float(thresholds["trigger_max_used_percent"]):
        reasons.append("used_percent_at_or_above_threshold")
    return reasons


def recovery_verified(snapshot: Dict[str, Any], thresholds: Dict[str, Any]) -> bool:
    """Use hysteresis so a tiny reclaim does not cause repair/flap claims."""

    return int(snapshot.get("free_bytes") or 0) >= int(
        thresholds["recovery_min_free_bytes"]
    ) and float(snapshot.get("used_percent") or 0.0) <= float(
        thresholds["recovery_max_used_percent"]
    )


def _append_audit(record: Dict[str, Any]) -> None:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        try:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        try:
            current_size = int(path.stat().st_size) if path.exists() else 0
        except OSError:
            current_size = 0
        if current_size >= _audit_max_bytes():
            archive = _audit_archive_path()
            archive.unlink(missing_ok=True)
            path.replace(archive)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _read_audit(limit: int = 100) -> list[Dict[str, Any]]:
    path = audit_path()
    sources = [_audit_archive_path(), path]
    if not any(source.exists() for source in sources):
        return []
    rows: list[Dict[str, Any]] = []
    for source in sources:
        if not source.exists():
            continue
        try:
            with source.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except OSError:
            logger.exception("storage pressure audit read failed: path=%s", source)
    return rows[-max(1, int(limit)) :]


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _utc(parsed)


def _last_action_at() -> datetime | None:
    for row in reversed(_read_audit(limit=500)):
        if not bool(row.get("action_taken")):
            continue
        parsed = _parse_timestamp(row.get("finished_at"))
        if parsed is not None:
            return parsed
    return None


@contextmanager
def _exclusive_lease() -> Iterator[bool]:
    path = lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except ImportError:  # pragma: no cover - Windows is best-effort single process.
            acquired = True
        except (BlockingIOError, OSError):
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        fh.close()


def _record_alignment_decision(*, run_id: str, decision: str, policy: str) -> None:
    """Best-effort typed decision evidence; failure is captured in the run audit."""

    from modstore_server.autonomy_decision_audit import append_autonomy_decision

    append_autonomy_decision(
        action_id=f"storage-pressure:{run_id}",
        action="bounded_storage_retention",
        decision=decision,
        policy=policy,
        risk_level="low" if decision == "allow" else "blocked",
        actor_class="system",
        run_id=run_id,
        source="storage_pressure_self_heal",
    )


def _publish_unresolved_incident(result: Dict[str, Any]) -> bool:
    from modstore_server.incident_bus import publish

    after = result.get("after") if isinstance(result.get("after"), dict) else {}
    return publish(
        "log.anomaly",
        {
            "type": "storage_pressure_persists",
            "severity": "high",
            "summary": "bounded retention completed but storage pressure remains",
            "run_id": result.get("run_id"),
            "free_bytes": after.get("free_bytes"),
            "used_percent": after.get("used_percent"),
            "status": result.get("status"),
        },
        source="storage-pressure-self-heal",
        fingerprint=f"storage-pressure:{result.get('status')}",
    )


def _finalize(result: Dict[str, Any]) -> Dict[str, Any]:
    result["finished_at"] = _utc().isoformat()
    result["schema_version"] = "storage_pressure_self_heal.v1"
    result["audit_path"] = str(audit_path())
    result["audit_written"] = True
    try:
        _append_audit(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("storage pressure audit append failed")
        result["audit_written"] = False
        result["ok"] = False
        result["status"] = "audit_failed"
        result["audit_error"] = f"{type(exc).__name__}:{str(exc)[:240]}"
    return result


def run_storage_pressure_self_heal(
    *,
    now: datetime | None = None,
    disk_usage_fn: Callable[[str], Any] = shutil.disk_usage,
    retention_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    notification_verifier: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Observe storage and execute the one bounded low-risk repair policy."""

    observed_at = _utc(now)
    run_id = uuid.uuid4().hex
    thresholds = pressure_thresholds()
    result: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": observed_at.isoformat(),
        "ok": True,
        "status": "observing",
        "action_taken": False,
        "policy": "storage_pressure_low_risk_retention_v1",
        "thresholds": thresholds,
    }

    try:
        before = collect_storage_snapshot(disk_usage_fn=disk_usage_fn)
    except Exception as exc:  # noqa: BLE001
        result.update(
            {
                "ok": False,
                "status": "observation_failed",
                "error": f"{type(exc).__name__}:{str(exc)[:240]}",
            }
        )
        return _finalize(result)

    reasons = pressure_reasons(before, thresholds)
    result.update({"before": before, "pressure_reasons": reasons})
    if not reasons:
        result["status"] = "healthy_no_action"
        result["postcondition"] = {
            "pressure_detected": False,
            "recovery_verified": True,
        }
        return _finalize(result)

    if not _env_bool("MODSTORE_STORAGE_SELF_HEAL_ENABLED", True):
        result.update(
            {
                "ok": False,
                "status": "operator_veto",
                "postcondition": {
                    "pressure_detected": True,
                    "recovery_verified": False,
                },
            }
        )
        try:
            _record_alignment_decision(
                run_id=run_id,
                decision="block",
                policy="storage_self_heal_disabled_by_operator_veto",
            )
            result["decision_audit_written"] = True
        except Exception as exc:  # noqa: BLE001
            result["decision_audit_written"] = False
            result["decision_audit_error"] = type(exc).__name__
        return _finalize(result)

    with _exclusive_lease() as acquired:
        if not acquired:
            result["ok"] = False
            result["status"] = "lease_busy"
            result["postcondition"] = {
                "pressure_detected": True,
                "recovery_verified": False,
            }
            return _finalize(result)

        cooldown_minutes = _bounded_env_int(
            "MODSTORE_STORAGE_SELF_HEAL_COOLDOWN_MINUTES", 60, 1, 1440
        )
        last_action = _last_action_at()
        if last_action is not None:
            next_allowed = last_action + timedelta(minutes=cooldown_minutes)
            if observed_at < next_allowed:
                result.update(
                    {
                        "ok": False,
                        "status": "pressure_cooldown",
                        "cooldown_minutes": cooldown_minutes,
                        "next_action_at": next_allowed.isoformat(),
                        "postcondition": {
                            "pressure_detected": True,
                            "recovery_verified": False,
                        },
                    }
                )
                return _finalize(result)

        try:
            _record_alignment_decision(
                run_id=run_id,
                decision="allow",
                policy="storage_pressure_low_risk_retention_v1",
            )
            result["decision_audit_written"] = True
        except Exception as exc:  # noqa: BLE001
            logger.exception("storage pressure autonomy decision audit failed")
            result["decision_audit_written"] = False
            result["decision_audit_error"] = type(exc).__name__

        if retention_runner is None:
            from modstore_server.file_retention_janitor import run_retention_janitor

            retention_runner = run_retention_janitor
        if notification_verifier is None:
            from modstore_server.file_retention_janitor import prune_notifications

            notification_verifier = prune_notifications

        result["action_taken"] = True
        try:
            retention = retention_runner(dry_run=False, notification_dry_run=False)
            remaining_notifications = notification_verifier(dry_run=True)
            after = collect_storage_snapshot(disk_usage_fn=disk_usage_fn)
        except Exception as exc:  # noqa: BLE001
            result.update(
                {
                    "ok": False,
                    "status": "repair_failed",
                    "error": f"{type(exc).__name__}:{str(exc)[:240]}",
                }
            )
            try:
                result["after"] = collect_storage_snapshot(disk_usage_fn=disk_usage_fn)
            except Exception:  # noqa: BLE001
                pass
            try:
                result["incident_emitted"] = _publish_unresolved_incident(result)
            except Exception as incident_exc:  # noqa: BLE001
                logger.exception("storage pressure repair failure incident publish failed")
                result["incident_emitted"] = False
                result["incident_error"] = type(incident_exc).__name__
            return _finalize(result)

        free_delta = int(after.get("free_bytes") or 0) - int(before.get("free_bytes") or 0)
        database_retention = (
            retention.get("database_retention")
            if isinstance(retention.get("database_retention"), dict)
            else {}
        )
        removed_files = int(retention.get("removed_count") or 0)
        removed_notifications = int(database_retention.get("removed_count") or 0)
        remaining_count = int(remaining_notifications.get("candidate_count") or 0)
        janitor_ok = bool(retention.get("ok")) and str(retention.get("status")) != "failed"
        recovered = recovery_verified(after, thresholds)
        physical_reclaim_observed = free_delta > 0
        logical_retention_verified = remaining_count == 0
        result.update(
            {
                "after": after,
                "retention": {
                    "ok": janitor_ok,
                    "status": retention.get("status"),
                    "removed_files": removed_files,
                    "released_file_bytes": int(retention.get("released_bytes") or 0),
                    "removed_notifications": removed_notifications,
                    "remaining_notification_candidates": remaining_count,
                    "notification_delete_truncated": bool(database_retention.get("truncated")),
                },
                "postcondition": {
                    "pressure_detected": True,
                    "recovery_verified": recovered,
                    "physical_reclaim_observed": physical_reclaim_observed,
                    "free_bytes_delta": free_delta,
                    "logical_retention_verified": logical_retention_verified,
                    "business_notification_scope_unchanged_by_contract": True,
                },
            }
        )

        if not janitor_ok:
            result.update({"ok": False, "status": "repair_failed"})
        elif recovered:
            result.update({"ok": True, "status": "recovered"})
        elif removed_files == 0 and removed_notifications == 0:
            result.update({"ok": False, "status": "no_safe_candidates"})
        else:
            result.update({"ok": False, "status": "pressure_persists"})

        if not result["ok"]:
            try:
                result["incident_emitted"] = _publish_unresolved_incident(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("storage pressure unresolved incident publish failed")
                result["incident_emitted"] = False
                result["incident_error"] = type(exc).__name__
        return _finalize(result)


def require_successful_storage_self_heal(result: Dict[str, Any]) -> Dict[str, Any]:
    """Make unresolved pressure visible as a failed scheduler job."""

    if result.get("ok") is not True:
        raise RuntimeError(f"storage_self_heal_unresolved:{result.get('status') or 'unknown'}")
    return result


def get_storage_pressure_status(*, limit: int = 20) -> Dict[str, Any]:
    rows = _read_audit(limit=max(1, min(int(limit), 200)))
    latest = rows[-1] if rows else None
    return {
        "ok": bool(latest and latest.get("ok") is True),
        "latest": latest,
        "runs": rows,
        "run_count": len(rows),
        "audit_path": str(audit_path()),
    }


__all__ = [
    "audit_path",
    "collect_storage_snapshot",
    "get_storage_pressure_status",
    "pressure_reasons",
    "pressure_thresholds",
    "recovery_verified",
    "require_successful_storage_self_heal",
    "run_storage_pressure_self_heal",
]
