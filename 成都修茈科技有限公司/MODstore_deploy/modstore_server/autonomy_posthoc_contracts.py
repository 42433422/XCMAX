"""Dedicated post-execution verifiers for autonomy decision contracts.

Each verifier consumes only typed operational receipts.  It never treats the
original allow decision as proof, and missing or contradictory evidence stays
inconclusive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from modstore_server.db.employee_ops import (
    DailyDigestRecord,
    EmployeeChangeRequest,
    EmployeeSuggestion,
    IncidentEvent,
)

UTC = timezone.utc  # noqa: UP017 - production runtime still supports Python 3.10
_CHANGE_REQUEST_ACTION = re.compile(r"^change-request:(\d+):apply$")
_DAILY_DIGEST_ACTION = re.compile(r"^daily-digest:(\d{4}-\d{2}-\d{2})$")
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


def verify_daily_digest_action(
    *,
    action_id: str,
    allowed_at: datetime,
    session_factory: Callable[..., Any],
) -> dict[str, Any]:
    """Verify a digest allow from its later durable delivery receipt.

    A scheduler success is not sufficient: the independently persisted digest
    row must match the guarded calendar day, be written after the allow
    decision, and contain a coherent delivered-recipient receipt.  No address
    or message body is copied into the autonomy ledger.
    """

    match = _DAILY_DIGEST_ACTION.fullmatch(str(action_id or ""))
    if match is None:
        return {"ok": False, "reason": "unsupported_daily_digest_action_id"}
    day = match.group(1)
    from modstore_server.daily_digest import DEFAULT_DIGEST_EMAIL

    configured_recipients = {
        chunk.strip().lower()
        for chunk in os.environ.get(
            "MODSTORE_DAILY_DIGEST_EMAIL",
            DEFAULT_DIGEST_EMAIL,
        )
        .replace(";", ",")
        .split(",")
        if chunk.strip() and "@" in chunk
    }
    if not configured_recipients:
        return {"ok": False, "reason": "daily_digest_authorized_recipients_unavailable"}
    with session_factory() as session:
        rows = (
            session.query(DailyDigestRecord)
            .filter(
                DailyDigestRecord.day == day,
                DailyDigestRecord.source == "daily_digest",
                DailyDigestRecord.delivered.is_(True),
                DailyDigestRecord.created_at >= _utc(allowed_at),
            )
            .order_by(DailyDigestRecord.created_at.asc(), DailyDigestRecord.id.asc())
            .all()
        )
    if not rows:
        return {"ok": False, "reason": "daily_digest_delivery_receipt_missing"}

    for row in rows:
        if not str(row.subject or "").strip() or not str(row.body_html or "").strip():
            continue
        try:
            recipients = json.loads(row.recipients_json or "[]")
            deliveries = json.loads(row.delivery_json or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(recipients, list) or not isinstance(deliveries, list):
            continue
        recipient_set = {
            str(value).strip().lower() for value in recipients if str(value or "").strip()
        }
        if recipient_set != configured_recipients:
            continue
        delivered_rows = [
            item
            for item in deliveries
            if isinstance(item, dict)
            and item.get("delivered") is True
            and str(item.get("to") or "").strip().lower() in recipient_set
            and bool(str(item.get("mode") or "").strip())
        ]
        if not recipient_set or not delivered_rows:
            continue
        digest = hashlib.sha256(
            "\n".join(
                (
                    str(row.id),
                    str(row.day or ""),
                    str(row.subject or ""),
                    str(row.body_html or ""),
                    str(row.recipients_json or ""),
                    str(row.delivery_json or ""),
                )
            ).encode("utf-8")
        ).hexdigest()
        return {
            "ok": True,
            "verdict": "no_prohibited_miss",
            "evidence_ref": f"daily-digest-record:{int(row.id)}:sha256:{digest[:40]}",
            "reason": "durable_digest_delivery_receipt_verified",
        }
    return {"ok": False, "reason": "daily_digest_delivery_receipt_incoherent"}


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


def _failed_merge_request_attempt(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for record in reversed(records):
        policy = (
            record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        )
        if (
            str(record.get("phase") or "") == "complete"
            and str(record.get("status") or "") == "completed_held_for_remediation"
            and str(policy.get("action") or "") == "hold_for_automated_remediation"
            and str(policy.get("reason") or "") == "para_merge_request_failed"
            and str(record.get("para_task_id") or "").strip()
            and str(record.get("branch") or "").strip()
        ):
            return record
    return None


def verify_self_maintenance_merge_action(
    *,
    action_id: str,
    allowed_at: datetime,
    records: list[dict[str, Any]],
    para_task_fetcher: Callable[[str], dict[str, Any]],
    github_merge_fetcher: Callable[..., dict[str, Any]],
    github_veto_fetcher: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Verify a merge allow from independent durable evidence.

    Exact production identity remains the strongest path. Historical Para
    state may be unavailable after task retention expires, so a read-only
    GitHub verifier can instead prove the merge action, bounded scope, checks,
    and current main ancestry. Both paths fail closed.
    """

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
    failed_attempt = _failed_merge_request_attempt(run_records) if request is None else None
    task_receipt = request or failed_attempt or {}
    task_id = str(task_receipt.get("para_task_id") or "").strip()
    if not task_id:
        return {"ok": False, "reason": "merge_request_receipt_missing"}
    branch = str(task_receipt.get("branch") or "").strip()
    base_branch = str(
        task_receipt.get("base_branch") or os.environ.get("MODSTORE_PARA_BRANCH") or "main"
    ).strip()
    para_reason = ""
    try:
        task = para_task_fetcher(task_id)
    except Exception:
        task = {}
        para_reason = "para_task_state_unavailable"
    if not isinstance(task, dict):
        task = {}
        para_reason = "para_task_state_invalid"
    task_status = str(task.get("status") or "").strip().lower()
    task_merge_sha = str(task.get("merge_commit_sha") or "").strip().lower()
    if task_status in _TERMINAL_NO_EFFECT and not task_merge_sha:
        if failed_attempt is not None:
            try:
                veto = github_veto_fetcher(
                    branch=branch,
                    base_branch=base_branch,
                )
            except Exception:
                veto = {"ok": False, "reason": "github_veto_evidence_unavailable"}
            if not isinstance(veto, dict) or veto.get("ok") is not True:
                return {
                    "ok": False,
                    "reason": (
                        str(veto.get("reason") or "github_veto_evidence_invalid")
                        if isinstance(veto, dict)
                        else "github_veto_evidence_invalid"
                    ),
                }
            veto_ref = str(veto.get("evidence_ref") or "").strip()
            if not veto_ref:
                return {"ok": False, "reason": "github_veto_evidence_ref_missing"}
            return {
                "ok": True,
                "verdict": "no_prohibited_miss",
                "evidence_ref": (f"para-task:{task_id}:terminal:{task_status}+{veto_ref}"),
                "reason": "merge_request_failed_and_pull_remained_vetoed",
            }
        return {
            "ok": True,
            "verdict": "no_prohibited_miss",
            "evidence_ref": f"para-task:{task_id}:terminal:{task_status}",
            "reason": "merge_terminal_without_mutation",
        }
    if task_status == "merged" and _SHA.fullmatch(task_merge_sha):
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
        if merged is not None and verified is not None and workflow_run_id:
            return {
                "ok": True,
                "verdict": "no_prohibited_miss",
                "evidence_ref": (
                    f"para-task:{task_id}:merged:{task_merge_sha[:12]}"
                    f"+workflow:{workflow_run_id}"
                ),
                "reason": "merged_and_exact_production_identity_verified",
            }
        para_reason = "exact_production_receipt_missing"
    elif not para_reason:
        para_reason = "para_merge_not_conclusive"

    try:
        github = github_merge_fetcher(
            branch=branch,
            base_branch=base_branch,
            allowed_at=allowed_at,
            expected_merge_sha=(task_merge_sha if _SHA.fullmatch(task_merge_sha) else ""),
        )
    except Exception:
        github = {"ok": False, "reason": "github_merge_evidence_unavailable"}
    if isinstance(github, dict) and github.get("ok") is True:
        return github
    github_reason = (
        str(github.get("reason") or "").strip()
        if isinstance(github, dict)
        else "github_merge_evidence_invalid"
    )
    return {
        "ok": False,
        "reason": github_reason or para_reason or "merge_evidence_inconclusive",
    }


__all__ = [
    "default_para_task_fetcher",
    "load_self_maintenance_records",
    "verify_code_write_action",
    "verify_daily_digest_action",
    "verify_self_maintenance_merge_action",
]
