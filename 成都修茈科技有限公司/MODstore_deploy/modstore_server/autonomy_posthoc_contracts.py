"""Dedicated post-execution verifiers for autonomy decision contracts.

Each verifier consumes only typed operational receipts.  It never treats the
original allow decision as proof, and missing or contradictory evidence stays
inconclusive.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from modstore_server.db.employee_ops import (
    EmployeeChangeRequest,
    EmployeeSuggestion,
    IncidentEvent,
)

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_CHANGE_REQUEST_ACTION = re.compile(r"^change-request:(\d+):apply$")
_MERGE_ACTION = re.compile(
    r"^loop:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r":self_maintenance_l1_merge$",
    re.IGNORECASE,
)
_SHA = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
_TERMINAL_NO_EFFECT = frozenset(
    {
        "cancelled",
        "dispatch_error",
        "dispatch_failed",
        "failed",
        "merge_conflict",
    }
)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _payload(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_repo_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or Path(raw).is_absolute():
        return ""
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _matching_validation_failure(
    session: Any,
    *,
    change_request_id: int,
    allowed_at: datetime,
) -> tuple[EmployeeSuggestion | None, str]:
    rows = (
        session.query(EmployeeSuggestion)
        .filter(
            EmployeeSuggestion.kind == "cr_narrow_ci_failure",
            EmployeeSuggestion.source_employee_id == "evolution-engine",
            EmployeeSuggestion.created_at >= allowed_at,
        )
        .order_by(EmployeeSuggestion.created_at.asc(), EmployeeSuggestion.id.asc())
        .all()
    )
    for row in rows:
        payload = _payload(row.payload_json)
        try:
            candidate_id = int(payload.get("change_request_id") or 0)
        except (TypeError, ValueError):
            continue
        validation = payload.get("validation")
        if candidate_id != change_request_id or not isinstance(validation, dict):
            continue
        failed_step = str(validation.get("failed_step") or "").strip()
        if failed_step:
            return row, failed_step
    return None, ""


def _matching_verify_event(
    session: Any,
    *,
    change_request_id: int,
    applied_at: datetime,
) -> tuple[IncidentEvent | None, dict[str, Any]]:
    rows = (
        session.query(IncidentEvent)
        .filter(
            IncidentEvent.event_type == "change_request.verify_complete",
            IncidentEvent.created_at >= applied_at,
        )
        .order_by(IncidentEvent.created_at.asc(), IncidentEvent.id.asc())
        .all()
    )
    for row in rows:
        payload = _payload(row.payload_json)
        try:
            candidate_id = int(payload.get("change_request_id") or 0)
        except (TypeError, ValueError):
            continue
        if candidate_id == change_request_id:
            return row, payload
    return None, {}


def _post_apply_scope_verdict(
    session: Any,
    *,
    change_request: EmployeeChangeRequest,
    payload: dict[str, Any],
) -> dict[str, Any]:
    rel_path = _safe_repo_path(payload.get("repo_relative_path"))
    if not rel_path:
        return {"ok": False, "reason": "verified_repo_path_invalid"}
    try:
        from modstore_server.employee_runtime import load_employee_pack
        from modstore_server.employee_scope_policy import (
            validate_agent_repo_write,
            workspace_policy_from_manifest,
        )

        pack = load_employee_pack(session, str(change_request.source_employee_id or ""))
        manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        scope_globs, forbidden_globs, _approval_globs = workspace_policy_from_manifest(manifest)
    except Exception:  # noqa: BLE001 - evidence outage must stay unknown, not crash the job
        return {"ok": False, "reason": "workspace_policy_unavailable"}
    if not scope_globs and not forbidden_globs:
        return {"ok": False, "reason": "workspace_policy_missing"}
    allowed, _message = validate_agent_repo_write(
        rel_path,
        scope_globs,
        forbidden_globs,
    )
    if not allowed:
        return {
            "ok": True,
            "verdict": "prohibited_miss",
            "reason": "post_apply_scope_violation",
        }
    return {"ok": True, "verdict": "no_prohibited_miss"}


def verify_code_write_action(
    *,
    action_id: str,
    allowed_at: datetime,
    session_factory: Callable[..., Any],
) -> dict[str, Any]:
    """Verify a code-write allow using a later no-effect or apply receipt."""

    match = _CHANGE_REQUEST_ACTION.fullmatch(str(action_id or ""))
    if match is None:
        return {"ok": False, "reason": "unsupported_change_request_action_id"}
    change_request_id = int(match.group(1))
    with session_factory() as session:
        row = session.get(EmployeeChangeRequest, change_request_id)
        if row is None:
            return {"ok": False, "reason": "change_request_missing"}

        applied_at = _utc(row.applied_at) if row.applied_at is not None else None
        if applied_at is None:
            failure, failed_step = _matching_validation_failure(
                session,
                change_request_id=change_request_id,
                allowed_at=_utc(allowed_at),
            )
            if failure is None:
                return {"ok": False, "reason": "terminal_no_effect_receipt_missing"}
            return {
                "ok": True,
                "verdict": "no_prohibited_miss",
                "evidence_ref": (f"employee-suggestion:{int(failure.id)}:narrow-ci:{failed_step}"),
                "reason": "narrow_ci_blocked_before_apply",
            }
        if applied_at < _utc(allowed_at):
            return {"ok": False, "reason": "apply_predates_allow"}

        event, payload = _matching_verify_event(
            session,
            change_request_id=change_request_id,
            applied_at=applied_at,
        )
        if event is None:
            return {"ok": False, "reason": "post_apply_verification_missing"}
        failed_checks = payload.get("failed_checks")
        if payload.get("ok") is not True or not isinstance(failed_checks, list) or failed_checks:
            return {"ok": False, "reason": "post_apply_verification_failed"}
        scope = _post_apply_scope_verdict(
            session,
            change_request=row,
            payload=payload,
        )
        if not scope.get("ok"):
            return scope
        return {
            "ok": True,
            "verdict": str(scope.get("verdict") or "no_prohibited_miss"),
            "evidence_ref": f"incident-event:{int(event.id)}:change-request-verified",
            "reason": str(scope.get("reason") or "applied_verified_with_scope_recheck"),
        }


def load_self_maintenance_records(path: str | Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        from modstore_server.self_maintenance_loop_runner import ledger_path

        resolved = ledger_path()
    else:
        resolved = Path(path)
    if not resolved.is_file():
        return []
    records: list[dict[str, Any]] = []
    with resolved.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def default_para_task_fetcher(task_id: str) -> dict[str, Any]:
    api_base = str(os.environ.get("MODSTORE_PARA_API_BASE") or "").strip()
    if not api_base:
        raise RuntimeError("para_api_base_missing")
    from modstore_server.self_maintenance_loop_runner import _fetch_para_task_state

    return _fetch_para_task_state(api_base, task_id)


def _recorded_at_or_after(record: dict[str, Any], allowed_at: datetime) -> bool:
    raw = str(
        record.get("created_at") or record.get("completed_at") or record.get("observed_at") or ""
    ).strip()
    if not raw:
        return False
    try:
        return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00"))) >= _utc(allowed_at)
    except ValueError:
        return False


def verify_self_maintenance_merge_action(
    *,
    action_id: str,
    allowed_at: datetime,
    records: list[dict[str, Any]],
    para_task_fetcher: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Verify a merge allow from Para final state and exact-SHA receipts."""

    match = _MERGE_ACTION.fullmatch(str(action_id or ""))
    if match is None:
        return {"ok": False, "reason": "unsupported_merge_action_id"}
    run_id = match.group(1)
    run_records = [
        record
        for record in records
        if str(record.get("run_id") or "") == run_id and _recorded_at_or_after(record, allowed_at)
    ]
    request = next(
        (
            record
            for record in run_records
            if record.get("event") == "merge_requested" and record.get("ok") is True
        ),
        None,
    )
    task_id = str((request or {}).get("para_task_id") or "").strip()
    if not task_id:
        return {"ok": False, "reason": "merge_request_receipt_missing"}
    try:
        task = para_task_fetcher(task_id)
    except Exception:
        return {"ok": False, "reason": "para_task_state_unavailable"}
    if not isinstance(task, dict):
        return {"ok": False, "reason": "para_task_state_invalid"}
    task_status = str(task.get("status") or "").strip().lower()
    task_merge_sha = str(task.get("merge_commit_sha") or "").strip().lower()
    if task_status in _TERMINAL_NO_EFFECT and not task_merge_sha:
        return {
            "ok": True,
            "verdict": "no_prohibited_miss",
            "evidence_ref": f"para-task:{task_id}:terminal:{task_status}",
            "reason": "merge_terminal_without_mutation",
        }
    if task_status != "merged" or not _SHA.fullmatch(task_merge_sha):
        return {"ok": False, "reason": "para_merge_not_conclusive"}

    merged = next(
        (
            record
            for record in reversed(run_records)
            if record.get("event") == "merge_completed"
            and record.get("ok") is True
            and str(record.get("status") or "") == "completed_merged"
            and str(record.get("merge_sha") or "").lower() == task_merge_sha
        ),
        None,
    )
    verified = next(
        (
            record
            for record in reversed(run_records)
            if record.get("event") == "post_deploy_verified"
            and record.get("ok") is True
            and record.get("identity_verified") is True
            and str(record.get("status") or "") == "verified"
            and str(record.get("environment") or "").lower() == "production"
            and str(record.get("merge_sha") or "").lower() == task_merge_sha
        ),
        None,
    )
    workflow_run_id = str((verified or {}).get("workflow_run_id") or "").strip()
    if merged is None or verified is None or not workflow_run_id:
        return {"ok": False, "reason": "exact_production_receipt_missing"}
    return {
        "ok": True,
        "verdict": "no_prohibited_miss",
        "evidence_ref": (
            f"para-task:{task_id}:merged:{task_merge_sha[:12]}" f"+workflow:{workflow_run_id}"
        ),
        "reason": "merged_and_exact_production_identity_verified",
    }


__all__ = [
    "default_para_task_fetcher",
    "load_self_maintenance_records",
    "verify_code_write_action",
    "verify_self_maintenance_merge_action",
]
