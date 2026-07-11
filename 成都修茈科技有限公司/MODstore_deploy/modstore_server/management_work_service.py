"""管理端 AI 员工统一任务生命周期、验收和故障恢复。"""

from __future__ import annotations

import hmac
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from modstore_server.models import (
    ManagementDecision,
    ManagementWorkEvent,
    ManagementWorkItem,
    get_session_factory,
)
from modstore_server.security_boundary import opaque_ref

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"accepted", "cancelled"})
ACTIVE_STATUSES = frozenset(
    {
        "assigned",
        "running",
        "cancel_requested",
        "waiting_decision",
        "retrying",
        "verifying",
        "delivered",
    }
)
CLAIMABLE_STATUSES = frozenset({"assigned", "retrying"})
EMPLOYEE_PARTITION = "management_duty"
_OWNER_IM_SLOTS = threading.BoundedSemaphore(4)


class WorkItemConflict(ValueError):
    pass


class ManagementExecutionTimeout(TimeoutError):
    pass


class ManagementExecutionCancelled(RuntimeError):
    pass


class ManagementExecutionProcessError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _is_sha256_digest(value: Any) -> bool:
    digest = str(value or "")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _event(
    session: Any,
    row: ManagementWorkItem,
    event_type: str,
    *,
    actor_type: str = "system",
    actor_id: str = "",
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        ManagementWorkEvent(
            work_item_id=int(row.id),
            event_type=_bounded_text(event_type, 64),
            actor_type=_bounded_text(actor_type, 32) or "system",
            actor_id=_bounded_text(actor_id, 128),
            message=_bounded_text(message, 8000),
            payload_json=_dumps(payload or {}),
        )
    )


def _serialize_work_item(row: ManagementWorkItem) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "task_id": str(row.task_id),
        "created_by_user_id": int(row.created_by_user_id or 0),
        "source_kind": str(row.source_kind or ""),
        "source_ref": str(row.source_ref or ""),
        "title": str(row.title or ""),
        "description": str(row.description or ""),
        "owner_employee_id": str(row.owner_employee_id or ""),
        # This ledger is deliberately for the platform owner's management-side
        # duty roster.  Enterprise/store employees have a separate user-facing
        # lifecycle and must never silently enter this queue.
        "employee_partition": EMPLOYEE_PARTITION,
        "status": str(row.status or ""),
        "priority": str(row.priority or ""),
        "risk_level": str(row.risk_level or ""),
        "acceptance_required": bool(row.acceptance_required),
        "acceptance_criteria": _loads(row.acceptance_criteria_json, []),
        "input": _loads(row.input_json, {}),
        "progress": int(row.progress or 0),
        "current_stage": str(row.current_stage or ""),
        "last_update": str(row.last_update or ""),
        "result_summary": str(row.result_summary or ""),
        "artifacts": _loads(row.artifacts_json, []),
        "evidence": _loads(row.evidence_json, []),
        "error_kind": str(row.error_kind or ""),
        "error": str(row.error or ""),
        "attempt_count": int(row.attempt_count or 0),
        "max_attempts": int(row.max_attempts or 0),
        "lease_expires_at": (row.lease_expires_at.isoformat() if row.lease_expires_at else None),
        "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_management_employees() -> list[dict[str, Any]]:
    """Return the management-side duty roster SSOT, never store employees."""

    from modstore_server.catalog_store import files_dir
    from modstore_server.duty_employee_registry import duty_employee_records
    from modstore_server.duty_roster import (
        all_planned_employee_ids,
        yuangon_area_for_pkg,
    )
    from modstore_server.employee_runtime import (
        MANAGEMENT_PRIMARY_WORK_RESERVED_IDS,
        load_employee_pack,
        management_work_runtime_issues,
    )

    records = duty_employee_records()
    package_root = files_dir()
    rows: list[dict[str, Any]] = []
    sf = get_session_factory()
    with sf() as session:
        for employee_id in sorted(all_planned_employee_ids()):
            record = records.get(employee_id) if isinstance(records, dict) else None
            record = record if isinstance(record, dict) else {}
            stored_filename = str(record.get("stored_filename") or "").strip()
            registered = bool(
                record and stored_filename and (package_root / stored_filename).is_file()
            )
            runtime_issues: list[str] = []
            if registered:
                try:
                    runtime_issues = management_work_runtime_issues(
                        load_employee_pack(session, employee_id)
                    )
                except Exception as exc:
                    runtime_issues = [f"运行时校验失败: {exc}"]
            else:
                runtime_issues = ["管理端岗位包未部署"]
            rows.append(
                {
                    "employee_id": employee_id,
                    "name": str(record.get("name") or record.get("label") or employee_id),
                    "area": str(yuangon_area_for_pkg(employee_id) or ""),
                    "employee_partition": EMPLOYEE_PARTITION,
                    "manifest_registered": registered,
                    "runtime_executable": not runtime_issues,
                    "primary_assignable": bool(
                        not runtime_issues
                        and employee_id not in MANAGEMENT_PRIMARY_WORK_RESERVED_IDS
                    ),
                    "runtime_issues": runtime_issues,
                }
            )
    return rows


def _require_management_employee(employee_id: str) -> str:
    from modstore_server.duty_roster import is_planned_duty_employee_id

    normalized = _bounded_text(employee_id, 128)
    if not normalized or not is_planned_duty_employee_id(normalized):
        raise ValueError(f"{normalized or 'employee'} 不是管理端在岗员工")
    from modstore_server.catalog_store import files_dir
    from modstore_server.duty_employee_registry import get_duty_employee_record

    record = get_duty_employee_record(normalized) or {}
    stored_filename = str(record.get("stored_filename") or "").strip()
    if not stored_filename or not (files_dir() / stored_filename).is_file():
        raise ValueError(f"{normalized} 的管理端岗位包未部署，不能接真实任务")
    return normalized


def _require_executable_management_employee(employee_id: str) -> str:
    normalized = _require_management_employee(employee_id)
    from modstore_server.employee_runtime import (
        MANAGEMENT_PRIMARY_WORK_RESERVED_IDS,
        load_employee_pack,
        management_work_runtime_issues,
    )

    if normalized in MANAGEMENT_PRIMARY_WORK_RESERVED_IDS:
        raise ValueError(f"{normalized} 是路由/验收专岗，不能作为主任务负责人")

    sf = get_session_factory()
    with sf() as session:
        issues = management_work_runtime_issues(load_employee_pack(session, normalized))
    if issues:
        raise ValueError(f"{normalized} 当前不可执行：{'; '.join(issues[:3])}")
    return normalized


def _serialize_event(row: ManagementWorkEvent) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "event_type": str(row.event_type or ""),
        "actor_type": str(row.actor_type or ""),
        "actor_id": str(row.actor_id or ""),
        "message": str(row.message or ""),
        "payload": _loads(row.payload_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_decision(row: ManagementDecision) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "decision_id": str(row.decision_id),
        "requested_by_employee_id": str(row.requested_by_employee_id or ""),
        "question": str(row.question or ""),
        "options": _loads(row.options_json, []),
        "recommendation": str(row.recommendation or ""),
        "status": str(row.status or ""),
        "decision": str(row.decision or ""),
        "note": str(row.note or ""),
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "last_reminded_at": (row.last_reminded_at.isoformat() if row.last_reminded_at else None),
        "reminder_count": int(row.reminder_count or 0),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def _serialize_verification_receipt(row: Any) -> dict[str, Any]:
    return {
        "receipt_id": str(row.receipt_id or ""),
        "task_id": str(row.task_id or ""),
        "attempt": int(row.attempt or 0),
        "result_digest": str(row.result_digest or ""),
        "fact_bundle_digest": str(row.fact_bundle_digest or ""),
        "fact_required": bool(row.fact_required),
        "fact_outcome": str(row.fact_outcome or ""),
        "audit_outcome": str(row.audit_outcome or ""),
        "status": str(row.status or ""),
        "verifier_employee_id": str(row.verifier_employee_id or ""),
        "audit": _loads(row.audit_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _record_verification_receipt(
    *,
    task_id: str,
    result_digest: str,
    fact_snapshot: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    from modstore_server.management_work_evidence import (
        persisted_fact_bundle_digest,
        verify_persisted_fact_evidence,
        verify_snapshot_signature,
    )
    from modstore_server.models import (
        ManagementWorkEvidence,
        ManagementWorkVerificationReceipt,
    )

    sf = get_session_factory()
    with sf() as session:
        work = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .one()
        )
        attempt = int(work.attempt_count or 0)
        fact_outcome = str(fact_snapshot.get("outcome") or "invalid")
        audit_outcome = str(audit.get("outcome") or "invalid")
        clean_result_digest = str(result_digest or "")
        if not _is_sha256_digest(clean_result_digest):
            raise WorkItemConflict(
                "verification receipt result digest must be 64-character lowercase hex"
            )
        if not verify_snapshot_signature(fact_snapshot):
            raise WorkItemConflict("independent fact snapshot signature is invalid")
        if str(fact_snapshot.get("task_id") or "") != str(task_id):
            raise WorkItemConflict("independent fact snapshot belongs to another task")
        snapshot_result_digest = str(fact_snapshot.get("runtime_claim_sha256") or "")
        if not snapshot_result_digest or not hmac.compare_digest(
            clean_result_digest, snapshot_result_digest
        ):
            raise WorkItemConflict("verification result digest does not match fact snapshot")
        facts = (
            session.query(ManagementWorkEvidence)
            .filter(
                ManagementWorkEvidence.work_item_id == int(work.id),
                ManagementWorkEvidence.attempt == attempt,
            )
            .all()
        )
        if bool(fact_snapshot.get("required")) and fact_outcome == "pass" and not facts:
            raise WorkItemConflict("required independent fact evidence is missing")
        for fact in facts:
            valid, reason = verify_persisted_fact_evidence(
                fact,
                task_id=str(task_id),
                attempt=attempt,
                work_item_id=int(work.id),
                require_passing=(fact_outcome == "pass"),
            )
            if not valid:
                raise WorkItemConflict(reason)
        fact_digest = persisted_fact_bundle_digest(
            facts,
            task_id=str(task_id),
            attempt=attempt,
        )
        if not _is_sha256_digest(fact_digest):
            raise WorkItemConflict(
                "verification receipt fact bundle digest must be 64-character lowercase hex"
            )
        status = "pass" if fact_outcome == "pass" and audit_outcome == "pass" else "fail"
        existing = (
            session.query(ManagementWorkVerificationReceipt)
            .filter(
                ManagementWorkVerificationReceipt.work_item_id == int(work.id),
                ManagementWorkVerificationReceipt.attempt == attempt,
            )
            .first()
        )
        if existing is not None:
            if (
                str(existing.result_digest or "") != clean_result_digest
                or str(existing.fact_bundle_digest or "") != fact_digest
            ):
                raise WorkItemConflict(
                    "verification receipt already exists for this attempt with different evidence"
                )
            return _serialize_verification_receipt(existing)
        safe_audit = {
            "outcome": audit_outcome,
            "reason": str(audit.get("reason") or "")[:4000],
            "report": audit.get("report") if isinstance(audit.get("report"), dict) else None,
        }
        row = ManagementWorkVerificationReceipt(
            receipt_id=f"mvr_{uuid.uuid4().hex}",
            work_item_id=int(work.id),
            task_id=str(task_id)[:64],
            attempt=attempt,
            result_digest=clean_result_digest[:64],
            fact_bundle_digest=fact_digest[:64],
            fact_required=bool(fact_snapshot.get("required")),
            fact_outcome=fact_outcome[:24],
            audit_outcome=audit_outcome[:24],
            status=status,
            verifier_employee_id="delivery-receipt-officer",
            audit_json=_dumps(safe_audit)[:200_000],
        )
        session.add(row)
        session.flush()
        _event(
            session,
            work,
            "task.verification_receipt",
            actor_type="employee",
            actor_id="delivery-receipt-officer",
            message=(
                "独立事实与语义验收均通过"
                if status == "pass"
                else f"验收回执未通过：fact={fact_outcome}, audit={audit_outcome}"
            ),
            payload={
                "receipt_id": row.receipt_id,
                "status": status,
                "fact_outcome": fact_outcome,
                "audit_outcome": audit_outcome,
                "fact_bundle_digest": fact_digest,
            },
        )
        session.commit()
        session.refresh(row)
        return _serialize_verification_receipt(row)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _assert_current_delivery_gate(
    session: Any,
    row: ManagementWorkItem,
    *,
    receipt: Any | None = None,
) -> Any:
    """Recheck immutable facts and operation state at every delivery transition."""

    from modstore_server.management_work_evidence import (
        persisted_fact_bundle_digest,
        verify_persisted_fact_evidence,
    )
    from modstore_server.models import (
        ManagementWorkEvidence,
        ManagementWorkOperation,
        ManagementWorkVerificationReceipt,
    )

    attempt = int(row.attempt_count or 0)
    if receipt is None:
        receipt = (
            session.query(ManagementWorkVerificationReceipt)
            .filter(
                ManagementWorkVerificationReceipt.work_item_id == int(row.id),
                ManagementWorkVerificationReceipt.attempt == attempt,
            )
            .first()
        )
    if receipt is None:
        raise WorkItemConflict("current attempt has no passing independent verification receipt")
    if int(receipt.work_item_id or 0) != int(row.id):
        raise WorkItemConflict("verification receipt belongs to another work item")
    if str(receipt.task_id or "") != str(row.task_id or ""):
        raise WorkItemConflict("verification receipt belongs to another task")
    if int(receipt.attempt or 0) != attempt:
        raise WorkItemConflict("verification receipt belongs to another attempt")
    if str(receipt.status or "") != "pass":
        raise WorkItemConflict("current attempt has no passing independent verification receipt")
    if str(receipt.fact_outcome or "") != "pass":
        raise WorkItemConflict("verification receipt fact outcome is not passing")
    if str(receipt.audit_outcome or "") != "pass":
        raise WorkItemConflict("verification receipt audit outcome is not passing")
    if str(receipt.verifier_employee_id or "") != "delivery-receipt-officer":
        raise WorkItemConflict("verification receipt verifier is not authoritative")
    result_digest = str(receipt.result_digest or "")
    if not _is_sha256_digest(result_digest):
        raise WorkItemConflict(
            "verification receipt result digest must be 64-character lowercase hex"
        )
    receipt_fact_digest = str(receipt.fact_bundle_digest or "")
    if not _is_sha256_digest(receipt_fact_digest):
        raise WorkItemConflict(
            "verification receipt fact bundle digest must be 64-character lowercase hex"
        )
    try:
        receipt_audit = json.loads(str(receipt.audit_json or ""))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkItemConflict("verification receipt audit payload is malformed") from exc
    if not isinstance(receipt_audit, dict):
        raise WorkItemConflict("verification receipt audit payload is malformed")
    if str(receipt_audit.get("outcome") or "") != str(receipt.audit_outcome or ""):
        raise WorkItemConflict("verification receipt audit outcome does not match its payload")
    if not isinstance(receipt_audit.get("report"), dict):
        raise WorkItemConflict("passing verification receipt audit report is malformed")

    facts = (
        session.query(ManagementWorkEvidence)
        .filter(
            ManagementWorkEvidence.work_item_id == int(row.id),
            ManagementWorkEvidence.attempt == attempt,
        )
        .all()
    )
    if bool(receipt.fact_required) and not facts:
        raise WorkItemConflict("required independent fact evidence is missing")
    now = _now()
    for fact in facts:
        valid, reason = verify_persisted_fact_evidence(
            fact,
            task_id=str(row.task_id),
            attempt=attempt,
            work_item_id=int(row.id),
            require_passing=True,
            now=now,
        )
        if not valid:
            raise WorkItemConflict(reason)
    current_fact_digest = persisted_fact_bundle_digest(
        facts,
        task_id=str(row.task_id),
        attempt=attempt,
    )
    if not hmac.compare_digest(receipt_fact_digest, current_fact_digest):
        raise WorkItemConflict("verification receipt fact bundle digest mismatch")

    operations = (
        session.query(ManagementWorkOperation)
        .filter(ManagementWorkOperation.work_item_id == int(row.id))
        .all()
    )
    safe_operation_states = {
        "succeeded": {"not_required", "available", "compensated"},
        "failed": {"not_required"},
    }
    for operation in operations:
        status = str(operation.status or "")
        compensation_status = str(operation.compensation_status or "")
        if str(operation.task_id or "") != str(row.task_id or ""):
            raise WorkItemConflict(
                f"operation {operation.operation_id} does not belong to task {row.task_id}"
            )
        allowed_compensation_states = safe_operation_states.get(status)
        if (
            allowed_compensation_states is None
            or compensation_status not in allowed_compensation_states
        ):
            raise WorkItemConflict(
                f"operation {operation.operation_id} has unsafe state "
                f"status={status or '<empty>'}, "
                f"compensation_status={compensation_status or '<empty>'}"
            )
    return receipt


def _notify_owner(item: dict[str, Any], *, title: str, content: str, event: str) -> None:
    user_id = int(item.get("created_by_user_id") or 0)
    if user_id <= 0:
        return
    data = {
        "event": event,
        "task_id": item.get("task_id"),
        "employee_id": item.get("owner_employee_id"),
        "status": item.get("status"),
        "priority": item.get("priority"),
    }
    try:
        from modstore_server.notification_service import (
            NotificationType,
            create_notification,
        )

        create_notification(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title=title,
            content=content,
            data=data,
        )
    except Exception:
        logger.warning(
            "management work notification failed task_ref=%s",
            opaque_ref(item.get("task_id"), namespace="management-task"),
        )
    # IM is an additional delivery channel, not part of the durable state
    # transition.  A dead/public candidate must never make decision, delivery
    # or recovery APIs wait for the sum of every network timeout.  The durable
    # in-app notification above remains synchronous; IM delivery is bounded
    # and best-effort in a daemon thread.
    if not _OWNER_IM_SLOTS.acquire(blocking=False):
        logger.warning(
            "management work IM queue saturated task_ref=%s",
            opaque_ref(item.get("task_id"), namespace="management-task"),
        )
        return

    def _send_im() -> None:
        try:
            from modstore_server.notification_service import employee_message_to_boss

            employee_message_to_boss(
                user_id,
                str(item.get("owner_employee_id") or "task-router-officer"),
                content,
                notification={
                    "event_id": ":".join(
                        [
                            str(event),
                            str(item.get("task_id") or ""),
                            str(item.get("status") or ""),
                            str(item.get("updated_at") or ""),
                        ]
                    ),
                    "event": event,
                    "title": title,
                    "task_id": item.get("task_id"),
                    "route": f"management_work/{item.get('task_id') or ''}",
                    "channel": "management_work",
                    # MODstore and FHD have independent user-id sequences.
                    # The FHD bridge must resolve this logical owner reference
                    # to its own active management administrator instead of
                    # treating the MODstore numeric id as a local foreign key.
                    "recipient_kind": "management_owner",
                    # Preserve the authenticated FHD actor reference supplied
                    # when the work item was created. The FHD bridge must
                    # resolve this exact reference and must not pick an
                    # arbitrary administrator when it is present.
                    "recipient_ref": str(item.get("source_ref") or "")[:256],
                    "priority": (
                        "high"
                        if event
                        in {
                            "management_work.decision_required",
                            "management_work.blocked",
                            "management_work.escalated",
                        }
                        else "normal"
                    ),
                },
            )
        except Exception:
            logger.exception("management work IM failed task_id=%s", item.get("task_id"))
        finally:
            _OWNER_IM_SLOTS.release()

    threading.Thread(
        target=_send_im,
        name=f"management-work-im-{str(item.get('task_id') or 'unknown')[-8:]}",
        daemon=True,
    ).start()


def create_work_item(
    *,
    created_by_user_id: int | None,
    title: str,
    description: str,
    owner_employee_id: str,
    source_kind: str = "admin",
    source_ref: str = "",
    priority: str = "P1",
    risk_level: str = "medium",
    acceptance_required: bool = True,
    acceptance_criteria: list[Any] | None = None,
    input_data: dict[str, Any] | None = None,
    max_attempts: int = 3,
    idempotency_key: str = "",
) -> dict[str, Any]:
    desc = _bounded_text(description, 100_000)
    item_title = _bounded_text(title, 256) or _bounded_text(desc, 256)
    if not item_title:
        raise ValueError("title or description is required")
    criteria = [
        _bounded_text(value, 4000)
        for value in (acceptance_criteria or [])[:30]
        if _bounded_text(value, 4000)
    ]
    if not criteria:
        criteria = ["交付结果必须直接回应任务描述，并包含至少一项可核验的执行证据"]
    normalized_risk = _bounded_text(risk_level, 16).lower() or "medium"
    requires_human_acceptance = bool(acceptance_required) or normalized_risk in {
        "high",
        "critical",
    }
    idem = _bounded_text(idempotency_key, 128) or None
    sf = get_session_factory()

    # Idempotency dominates routing.  A retry of the same create request must
    # not call the model again and silently produce a second route decision.
    if idem:
        with sf() as session:
            existing = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.idempotency_key == idem)
                .first()
            )
            if existing is not None:
                return {"created": False, "item": _serialize_work_item(existing)}

    requested_owner = _bounded_text(owner_employee_id, 128)
    route_decision: dict[str, Any] | None = None
    if not requested_owner or requested_owner.lower() == "auto":
        from modstore_server.task_router import resolve_management_work_owner

        route_decision = resolve_management_work_owner(desc or item_title, input_data or {})
        requested_owner = str(route_decision.get("employee_id") or "")
    # Enforce the same fail-closed rule as the desktop/mobile selector.  A
    # direct API caller must not persist work that no runtime can execute, nor
    # turn routing/receipt control roles into primary workers.
    owner = _require_executable_management_employee(requested_owner)

    with sf() as session:
        # Close the race between the short preflight lookup and insertion.
        if idem:
            existing = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.idempotency_key == idem)
                .first()
            )
            if existing is not None:
                return {"created": False, "item": _serialize_work_item(existing)}
        row = ManagementWorkItem(
            task_id=f"mwi_{uuid.uuid4().hex}",
            idempotency_key=idem,
            created_by_user_id=(int(created_by_user_id) if created_by_user_id else None),
            source_kind=_bounded_text(source_kind, 32) or "admin",
            source_ref=_bounded_text(source_ref, 256),
            title=item_title,
            description=desc,
            owner_employee_id=owner,
            status="assigned",
            priority=(_bounded_text(priority, 8) or "P1").upper(),
            risk_level=normalized_risk,
            acceptance_required=requires_human_acceptance,
            acceptance_criteria_json=_dumps(criteria),
            input_json=_dumps(input_data or {}),
            max_attempts=max(1, min(int(max_attempts or 3), 10)),
            updated_at=_now(),
        )
        session.add(row)
        session.flush()
        _event(
            session,
            row,
            "task.created",
            actor_type="user" if created_by_user_id else "system",
            actor_id=str(created_by_user_id or "system"),
            message=item_title,
        )
        if route_decision is not None:
            _event(
                session,
                row,
                "task.routed",
                actor_type="employee",
                actor_id="task-router-officer",
                message=f"自动派发给 {owner}：{route_decision.get('reason') or ''}",
                payload=route_decision,
            )
        session.commit()
        session.refresh(row)
        return {"created": True, "item": _serialize_work_item(row)}


def list_work_items(
    *,
    statuses: Iterable[str] | None = None,
    owner_employee_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    wanted = [str(value).strip() for value in (statuses or []) if str(value).strip()]
    sf = get_session_factory()
    with sf() as session:
        query = session.query(ManagementWorkItem)
        if wanted:
            query = query.filter(ManagementWorkItem.status.in_(wanted))
        owner = _bounded_text(owner_employee_id, 128)
        if owner:
            query = query.filter(ManagementWorkItem.owner_employee_id == owner)
        rows = (
            query.order_by(ManagementWorkItem.updated_at.desc(), ManagementWorkItem.id.desc())
            .limit(max(1, min(int(limit or 100), 500)))
            .all()
        )
        return [_serialize_work_item(row) for row in rows]


def get_work_item(task_id: str, *, include_timeline: bool = True) -> dict[str, Any] | None:
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if row is None:
            return None
        out = _serialize_work_item(row)
        if include_timeline:
            events = (
                session.query(ManagementWorkEvent)
                .filter(ManagementWorkEvent.work_item_id == row.id)
                .order_by(ManagementWorkEvent.id.asc())
                .all()
            )
            decisions = (
                session.query(ManagementDecision)
                .filter(ManagementDecision.work_item_id == row.id)
                .order_by(ManagementDecision.id.asc())
                .all()
            )
            out["events"] = [_serialize_event(event) for event in events]
            out["decisions"] = [_serialize_decision(decision) for decision in decisions]
            from modstore_server.management_work_evidence import list_fact_evidence
            from modstore_server.management_work_operations import list_task_operations
            from modstore_server.models import ManagementWorkVerificationReceipt

            receipts = (
                session.query(ManagementWorkVerificationReceipt)
                .filter(ManagementWorkVerificationReceipt.work_item_id == int(row.id))
                .order_by(ManagementWorkVerificationReceipt.attempt.asc())
                .all()
            )
            out["fact_evidence"] = list_fact_evidence(str(task_id))
            out["verification_receipts"] = [
                _serialize_verification_receipt(receipt) for receipt in receipts
            ]
            out["operations"] = list_task_operations(str(task_id))
        return out


def _management_execution_timeout_seconds(target_employee_id: str) -> int:
    verifier = str(target_employee_id or "") == "delivery-receipt-officer"
    env_name = (
        "MODSTORE_MANAGEMENT_WORK_VERIFIER_TIMEOUT_SECONDS"
        if verifier
        else "MODSTORE_MANAGEMENT_WORK_EXECUTION_TIMEOUT_SECONDS"
    )
    default = 300 if verifier else 900
    try:
        value = int(os.environ.get(env_name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(15, min(value, 7200))


def _management_execution_workspace_root(employee_id: str) -> str:
    """Return the server-owned workspace root used by management employees."""

    explicit = str(os.environ.get("MODSTORE_MANAGEMENT_WORKSPACE_ROOT") or "").strip()
    if explicit:
        try:
            resolved = Path(explicit).expanduser().resolve()
        except OSError:
            resolved = Path("/")
        if resolved.is_dir() and resolved != Path(resolved.anchor):
            return str(resolved)

    candidates: list[Path] = []
    for key in (
        "MODSTORE_GIT_REPO_ROOT",
        "XCMAX_MONOREPO_ROOT",
        "MODSTORE_REPO_ROOT",
    ):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            resolved = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved != Path(resolved.anchor):
            for candidate in (
                resolved,
                resolved / "成都修茈科技有限公司",
            ):
                if candidate.is_dir() and candidate not in candidates:
                    candidates.append(candidate)
    if not candidates:
        return ""

    scope_globs: list[str] = []
    try:
        from modstore_server.employee_runtime import load_employee_pack
        from modstore_server.employee_scope_policy import workspace_policy_from_manifest

        sf = get_session_factory()
        with sf() as session:
            pack = load_employee_pack(session, str(employee_id))
        manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        scope_globs, _forbidden, _approval = workspace_policy_from_manifest(manifest)
    except Exception:
        scope_globs = []
    if scope_globs:
        prefixes = {
            str(glob).replace("\\", "/").split("/", 1)[0]
            for glob in scope_globs
            if str(glob).strip()
        }
        candidates.sort(
            key=lambda candidate: sum(1 for prefix in prefixes if (candidate / prefix).exists()),
            reverse=True,
        )
    return str(candidates[0])


def _terminate_execution_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        logger.error("management execution process would not exit pid=%s", process.pid)


def _task_has_cancel_request(task_id: str) -> bool:
    try:
        item = get_work_item(task_id, include_timeline=False)
        return bool(item and item.get("status") == "cancel_requested")
    except Exception:
        logger.warning(
            "management execution cancel probe failed task_ref=%s",
            opaque_ref(task_id, namespace="management-task"),
        )
        return False


def _drain_process_pipe(
    stream: Any,
    output: bytearray,
    *,
    max_bytes: int,
    keep_tail: bool,
    overflow: list[bool],
) -> None:
    try:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                return
            if len(output) + len(chunk) > max_bytes:
                overflow[0] = True
            output.extend(chunk)
            if len(output) > max_bytes:
                if keep_tail:
                    del output[: len(output) - max_bytes]
                else:
                    del output[max_bytes:]
    except (OSError, ValueError):
        return


def _run_management_execution_process(
    task: str,
    input_data: dict[str, Any],
    *,
    task_id: str,
    target_employee_id: str,
    created_by_user_id: int,
    include_dependencies: bool,
    max_concurrency: int,
    allow_high_risk_real_run: bool,
) -> dict[str, Any]:
    """Run one employee call in a killable process with cancellation polling."""

    timeout_seconds = _management_execution_timeout_seconds(target_employee_id)
    request = {
        "task": str(task or ""),
        "input_data": input_data if isinstance(input_data, dict) else {},
        "target_employee_id": str(target_employee_id or ""),
        "created_by_user_id": int(created_by_user_id or 0),
        "include_dependencies": bool(include_dependencies),
        "max_concurrency": max(1, min(int(max_concurrency or 1), 8)),
        "allow_high_risk_real_run": bool(allow_high_risk_real_run),
    }
    env = os.environ.copy()
    # Fact-signing and platform-control credentials stay in the parent verifier.
    for secret_name in (
        "MODSTORE_MANAGEMENT_EVIDENCE_HMAC_KEY",
        "MODSTORE_JWT_SECRET",
        "PAYMENT_SECRET_KEY",
        "XCAGI_MARKET_INTERNAL_API_KEY",
        "MODSTORE_INTERNAL_API_KEY",
        "XCAGI_CS_INTAKE_LINK_SECRET",
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        "FIREBASE_SERVICE_ACCOUNT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "SMTP_PASSWORD",
    ):
        env.pop(secret_name, None)
    inherited_paths = [value for value in sys.path if str(value).strip()]
    existing_paths = [
        value for value in str(env.get("PYTHONPATH") or "").split(os.pathsep) if value
    ]
    env["PYTHONPATH"] = os.pathsep.join(list(dict.fromkeys([*inherited_paths, *existing_paths])))
    process = subprocess.Popen(
        [sys.executable, "-m", "modstore_server.management_work_process"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _terminate_execution_process(process)
        raise ManagementExecutionProcessError("management worker pipes unavailable")

    request_bytes = _dumps(request).encode("utf-8")
    response_bytes = bytearray()
    log_tail = bytearray()
    response_overflow = [False]
    log_overflow = [False]

    def _send_request() -> None:
        try:
            process.stdin.write(request_bytes)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

    writer = threading.Thread(target=_send_request, daemon=True)
    response_reader = threading.Thread(
        target=_drain_process_pipe,
        args=(process.stdout, response_bytes),
        kwargs={
            "max_bytes": 4_000_000,
            "keep_tail": False,
            "overflow": response_overflow,
        },
        daemon=True,
    )
    log_reader = threading.Thread(
        target=_drain_process_pipe,
        args=(process.stderr, log_tail),
        kwargs={
            "max_bytes": 12_000,
            "keep_tail": True,
            "overflow": log_overflow,
        },
        daemon=True,
    )
    writer.start()
    response_reader.start()
    log_reader.start()
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        while process.poll() is None:
            if _task_has_cancel_request(task_id):
                _terminate_execution_process(process)
                raise ManagementExecutionCancelled(
                    "management work cancellation interrupted employee process"
                )
            if time.monotonic() >= deadline:
                _terminate_execution_process(process)
                raise ManagementExecutionTimeout("management employee exceeded hard timeout")
            time.sleep(0.5)
    except BaseException:
        _terminate_execution_process(process)
        raise
    finally:
        writer.join(timeout=1)
        response_reader.join(timeout=3)
        log_reader.join(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    if response_overflow[0]:
        raise ManagementExecutionProcessError("employee process response exceeds 4 MB")
    if not response_bytes:
        raise ManagementExecutionProcessError(
            "employee process exited without response "
            f"log_ref={opaque_ref(bytes(log_tail), namespace='management-child-log')}"
        )
    try:
        response = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagementExecutionProcessError(
            "employee process returned malformed response"
        ) from exc
    if not isinstance(response, dict) or not response.get("ok"):
        raw_code = str(response.get("error_code") or "") if isinstance(response, dict) else ""
        error_code = (
            raw_code
            if raw_code in {"invalid_request", "management_worker_failed"}
            else "management_worker_failed"
        )
        raise ManagementExecutionProcessError(error_code)
    result = response.get("result")
    if not isinstance(result, dict):
        raise ManagementExecutionProcessError("employee process result must be an object")
    return result


def _owned_running(
    session: Any, task_id: str, employee_id: str, lease_token: str
) -> ManagementWorkItem:
    query = session.query(ManagementWorkItem).filter(ManagementWorkItem.task_id == str(task_id))
    if session.bind is not None and session.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise KeyError("work item not found")
    if str(row.owner_employee_id) != str(employee_id):
        raise WorkItemConflict("employee does not own work item")
    if row.status != "running":
        raise WorkItemConflict(f"work item is {row.status}, not running")
    if not lease_token or str(row.lease_token or "") != str(lease_token):
        raise WorkItemConflict("invalid lease token")
    lease_expires_at = _as_utc(row.lease_expires_at)
    if lease_expires_at is None or lease_expires_at <= _now():
        raise WorkItemConflict("work item lease has expired")
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE. A conditional no-op write establishes a
        # transaction barrier against a concurrent cancellation before any
        # caller can renew, deliver, or fail this lease.
        matched = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.id == int(row.id),
                ManagementWorkItem.status == "running",
                ManagementWorkItem.owner_employee_id == str(employee_id),
                ManagementWorkItem.lease_token == str(lease_token),
                ManagementWorkItem.lease_expires_at == row.lease_expires_at,
            )
            .update(
                {ManagementWorkItem.status: ManagementWorkItem.status},
                synchronize_session=False,
            )
        )
        if matched != 1:
            raise WorkItemConflict("work item lease changed concurrently")
        session.flush()
    return row


def claim_work_item(
    task_id: str,
    *,
    employee_id: str,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    now = _now()
    sf = get_session_factory()
    from sqlalchemy import or_

    with sf() as session:
        existing = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if existing is None:
            raise KeyError("work item not found")
        if str(existing.owner_employee_id) != str(employee_id):
            raise WorkItemConflict("employee does not own work item")
        lease_token = uuid.uuid4().hex
        lease_expires_at = now + timedelta(seconds=max(15, min(lease_seconds, 3600)))
        # Compare-and-set: only one concurrent worker may move the same row from
        # assigned/retry-ready to running.  A plain SELECT followed by mutation
        # allowed two processes to receive valid leases.
        updated = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.task_id == str(task_id),
                ManagementWorkItem.owner_employee_id == str(employee_id),
                ManagementWorkItem.status.in_(CLAIMABLE_STATUSES),
                ManagementWorkItem.attempt_count < ManagementWorkItem.max_attempts,
                or_(
                    ManagementWorkItem.next_retry_at.is_(None),
                    ManagementWorkItem.next_retry_at <= now,
                ),
            )
            .update(
                {
                    ManagementWorkItem.status: "running",
                    ManagementWorkItem.attempt_count: ManagementWorkItem.attempt_count + 1,
                    ManagementWorkItem.lease_token: lease_token,
                    ManagementWorkItem.heartbeat_at: now,
                    ManagementWorkItem.lease_expires_at: lease_expires_at,
                    ManagementWorkItem.next_retry_at: None,
                    ManagementWorkItem.started_at: existing.started_at or now,
                    ManagementWorkItem.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            session.rollback()
            current = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.task_id == str(task_id))
                .first()
            )
            state = str(current.status if current is not None else "missing")
            raise WorkItemConflict(f"work item is not claimable: {state}")
        session.flush()
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .one()
        )
        _event(
            session,
            row,
            "task.claimed",
            actor_type="employee",
            actor_id=employee_id,
            payload={
                "attempt": row.attempt_count,
                "lease_expires_at": row.lease_expires_at,
            },
        )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)
        out["lease_token"] = row.lease_token
        return out


def heartbeat_work_item(
    task_id: str,
    *,
    employee_id: str,
    lease_token: str,
    progress: int | None = None,
    stage: str = "",
    message: str = "",
    evidence: list[Any] | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        row = _owned_running(session, task_id, employee_id, lease_token)
        old_progress = int(row.progress or 0)
        if progress is not None:
            row.progress = max(old_progress, min(max(int(progress), 0), 99))
        if stage:
            row.current_stage = _bounded_text(stage, 128)
        if message:
            row.last_update = _bounded_text(message, 8000)
        if evidence:
            merged = _loads(row.evidence_json, [])
            merged.extend(evidence)
            row.evidence_json = _dumps(merged[-200:])
        row.heartbeat_at = now
        row.lease_expires_at = now + timedelta(seconds=max(15, min(lease_seconds, 3600)))
        row.updated_at = now
        if message or row.progress != old_progress or evidence:
            _event(
                session,
                row,
                "task.progress",
                actor_type="employee",
                actor_id=employee_id,
                message=message,
                payload={"progress": row.progress, "stage": row.current_stage},
            )
        session.commit()
        session.refresh(row)
        return _serialize_work_item(row)


def request_decision(
    task_id: str,
    *,
    employee_id: str,
    lease_token: str,
    question: str,
    options: list[Any] | None = None,
    recommendation: str = "",
    due_seconds: int = 3600,
) -> dict[str, Any]:
    prompt = _bounded_text(question, 12_000)
    if not prompt:
        raise ValueError("question is required")
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        row = _owned_running(session, task_id, employee_id, lease_token)
        decision = ManagementDecision(
            decision_id=f"mdc_{uuid.uuid4().hex}",
            work_item_id=row.id,
            requested_by_employee_id=employee_id,
            question=prompt,
            options_json=_dumps(options or []),
            recommendation=_bounded_text(recommendation, 8000),
            status="pending",
            requested_at=now,
            due_at=now + timedelta(seconds=max(60, min(int(due_seconds or 3600), 604800))),
            last_reminded_at=now,
            reminder_count=1,
        )
        session.add(decision)
        row.status = "waiting_decision"
        # Pausing for an owner decision is not a failed execution attempt.  The
        # worker releases its lease and will reclaim after the answer, so undo
        # this claim's attempt increment to preserve the configured retry
        # budget for actual execution/rework.
        row.attempt_count = max(0, int(row.attempt_count or 0) - 1)
        row.lease_token = ""
        row.lease_expires_at = None
        row.heartbeat_at = now
        row.last_update = prompt
        row.updated_at = now
        session.flush()
        _event(
            session,
            row,
            "decision.requested",
            actor_type="employee",
            actor_id=employee_id,
            message=prompt,
            payload={
                "decision_id": decision.decision_id,
                "recommendation": recommendation,
            },
        )
        session.commit()
        session.refresh(row)
        session.refresh(decision)
        item_out = _serialize_work_item(row)
        decision_out = _serialize_decision(decision)
    option_text = ""
    if options:
        option_text = "\n选项：" + " / ".join(str(value) for value in options[:8])
    recommendation_text = f"\n建议：{recommendation}" if recommendation else ""
    _notify_owner(
        item_out,
        title=f"{employee_id} 等你决策",
        content=f"任务《{item_out['title']}》需要你的决定：{prompt}{option_text}{recommendation_text}",
        event="management_work.decision_required",
    )
    return {"item": item_out, "decision": decision_out}


def resolve_decision(
    decision_id: str,
    *,
    decided_by_user_id: int,
    decision_text: str,
    note: str = "",
) -> dict[str, Any]:
    answer = _bounded_text(decision_text, 12_000)
    if not answer:
        raise ValueError("decision is required")
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        decision = (
            session.query(ManagementDecision)
            .filter(ManagementDecision.decision_id == str(decision_id))
            .first()
        )
        if decision is None:
            raise KeyError("decision not found")
        if decision.status != "pending":
            raise WorkItemConflict(f"decision already {decision.status}")
        row = session.get(ManagementWorkItem, decision.work_item_id)
        if row is None:
            raise KeyError("work item not found")
        if row.status != "waiting_decision":
            raise WorkItemConflict(
                f"work item is {row.status}; this decision can no longer resume it"
            )
        decision.status = "decided"
        decision.decision = answer
        decision.note = _bounded_text(note, 8000)
        decision.decided_at = now
        decision.decided_by_user_id = int(decided_by_user_id)
        row.status = "assigned"
        row.last_update = f"老板决策：{answer}"
        row.updated_at = now
        _event(
            session,
            row,
            "decision.resolved",
            actor_type="user",
            actor_id=str(decided_by_user_id),
            message=answer,
            payload={"decision_id": decision.decision_id, "note": note},
        )
        session.commit()
        session.refresh(row)
        session.refresh(decision)
        return {
            "item": _serialize_work_item(row),
            "decision": _serialize_decision(decision),
        }


def deliver_work_item(
    task_id: str,
    *,
    employee_id: str,
    lease_token: str,
    summary: str,
    artifacts: list[Any] | None = None,
    evidence: list[Any] | None = None,
    no_artifact_reason: str = "",
    verification_receipt_id: str = "",
    candidate_result_digest: str = "",
) -> dict[str, Any]:
    result_summary = _bounded_text(summary, 50_000)
    if not result_summary:
        raise ValueError("summary is required")
    artifact_rows = artifacts or []
    evidence_rows = evidence or []
    if not artifact_rows and not evidence_rows and not _bounded_text(no_artifact_reason, 2000):
        raise ValueError("artifact, evidence or no_artifact_reason is required")
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        row = _owned_running(session, task_id, employee_id, lease_token)
        from modstore_server.models import ManagementWorkVerificationReceipt

        receipt = (
            session.query(ManagementWorkVerificationReceipt)
            .filter(
                ManagementWorkVerificationReceipt.receipt_id == str(verification_receipt_id),
                ManagementWorkVerificationReceipt.work_item_id == int(row.id),
                ManagementWorkVerificationReceipt.attempt == int(row.attempt_count or 0),
            )
            .first()
        )
        if receipt is None:
            raise WorkItemConflict("independent verification receipt is required before delivery")
        _assert_current_delivery_gate(session, row, receipt=receipt)
        if not candidate_result_digest or not hmac.compare_digest(
            str(receipt.result_digest or ""), str(candidate_result_digest)
        ):
            raise WorkItemConflict("candidate result digest does not match verification receipt")
        row.status = "delivered"
        row.progress = 100
        row.error_kind = ""
        row.error = ""
        row.next_retry_at = None
        row.result_summary = result_summary
        row.artifacts_json = _dumps(artifact_rows)
        merged_evidence = _loads(row.evidence_json, [])
        merged_evidence.extend(evidence_rows)
        if no_artifact_reason:
            merged_evidence.append({"kind": "no_artifact_reason", "value": no_artifact_reason})
        row.evidence_json = _dumps(merged_evidence[-500:])
        row.lease_token = ""
        row.lease_expires_at = None
        row.delivered_at = now
        row.updated_at = now
        _event(
            session,
            row,
            "task.delivered",
            actor_type="employee",
            actor_id=employee_id,
            message=result_summary,
            payload={
                "artifact_count": len(artifact_rows),
                "evidence_count": len(merged_evidence),
                "verification_receipt_id": receipt.receipt_id,
            },
        )
        if not bool(row.acceptance_required):
            row.status = "accepted"
            row.accepted_at = now
            row.completed_at = now
            _event(
                session,
                row,
                "task.auto_accepted",
                actor_type="system",
                message="任务配置为自动验收，交付证据已记录",
            )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)
    _notify_owner(
        out,
        title=(
            f"{employee_id} 已交付，等待验收"
            if out["status"] == "delivered"
            else f"{employee_id} 已完成并通过自动验收"
        ),
        content=f"任务《{out['title']}》已交付：{result_summary[:500]}",
        event="management_work.delivered",
    )
    return out


def review_delivery(
    task_id: str,
    *,
    reviewed_by_user_id: int,
    accepted: bool,
    feedback: str = "",
) -> dict[str, Any]:
    now = _now()
    notify_blocked = False
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if row is None:
            raise KeyError("work item not found")
        if row.status != "delivered":
            raise WorkItemConflict(f"work item is {row.status}, not delivered")
        if accepted:
            _assert_current_delivery_gate(session, row)
            row.status = "accepted"
            row.accepted_at = now
            row.completed_at = now
            event_type = "task.accepted"
        else:
            row.progress = min(int(row.progress or 0), 95)
            row.last_update = _bounded_text(feedback, 8000) or "交付被退回"
            event_type = "task.rejected"
            if int(row.attempt_count or 0) < int(row.max_attempts or 0):
                row.status = "assigned"
                row.error_kind = ""
                row.error = ""
            else:
                row.status = "blocked"
                row.error_kind = "acceptance_rejected"
                row.error = row.last_update
                row.next_retry_at = None
                notify_blocked = True
        row.updated_at = now
        _event(
            session,
            row,
            event_type,
            actor_type="user",
            actor_id=str(reviewed_by_user_id),
            message=feedback,
            payload={
                "accepted": bool(accepted),
                "attempt": int(row.attempt_count or 0),
                "max_attempts": int(row.max_attempts or 0),
                "blocked": bool(notify_blocked),
            },
        )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)
    if notify_blocked:
        _notify_owner(
            out,
            title=f"{out['owner_employee_id']} 的交付验收未通过",
            content=f"任务《{out['title']}》已用尽 {out['max_attempts']} 次执行机会，需要你明确重试：{out['error'][:500]}",
            event="management_work.acceptance_blocked",
        )
    return out


def fail_work_item(
    task_id: str,
    *,
    employee_id: str,
    lease_token: str,
    error_kind: str,
    error: str,
    retryable: bool = True,
    evidence: list[Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    notify = False
    sf = get_session_factory()
    with sf() as session:
        row = _owned_running(session, task_id, employee_id, lease_token)
        from modstore_server.models import ManagementWorkOperation

        uncertain_operations = (
            session.query(ManagementWorkOperation)
            .filter(
                ManagementWorkOperation.work_item_id == int(row.id),
                ManagementWorkOperation.status.in_(["running", "uncertain"]),
            )
            .all()
        )
        if uncertain_operations:
            for operation in uncertain_operations:
                if operation.status == "running":
                    operation.status = "uncertain"
                    operation.lease_expires_at = None
                    operation.error = "员工进程退出时副作用结果未确认"
                    operation.compensation_status = (
                        "required" if operation.reversible else "unavailable"
                    )
                    operation.updated_at = now
            retryable = False
            error_kind = "side_effect_outcome_unknown"
            error = "员工进程已退出，但存在结果未知的外部副作用，禁止自动重放"
        row.error_kind = _bounded_text(error_kind, 64) or "unknown"
        row.error = _bounded_text(error, 20_000) or "unknown failure"
        merged_evidence = _loads(row.evidence_json, [])
        failure_evidence = list(evidence or [])
        if failure_evidence:
            merged_evidence.extend(failure_evidence)
            row.evidence_json = _dumps(merged_evidence[-500:])
        row.lease_token = ""
        row.lease_expires_at = None
        if retryable and int(row.attempt_count or 0) < int(row.max_attempts or 0):
            delay = min(3600, 30 * (2 ** max(0, int(row.attempt_count or 1) - 1)))
            row.status = "retrying"
            row.next_retry_at = now + timedelta(seconds=delay)
            event_type = "task.retry_scheduled"
        else:
            row.status = "blocked"
            row.next_retry_at = None
            event_type = "task.blocked"
            notify = True
        row.updated_at = now
        _event(
            session,
            row,
            event_type,
            actor_type="employee",
            actor_id=employee_id,
            message=row.error,
            payload={
                "error_kind": row.error_kind,
                "retryable": bool(retryable),
                "evidence_count": len(failure_evidence),
            },
        )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)
    if notify:
        _notify_owner(
            out,
            title=f"{employee_id} 的任务需要你介入",
            content=f"任务《{out['title']}》已阻塞：{out['error'][:500]}",
            event="management_work.blocked",
        )
    return out


def retry_work_item(task_id: str, *, requested_by_user_id: int, note: str = "") -> dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if row is None:
            raise KeyError("work item not found")
        if row.status not in {"blocked", "retrying", "failed"}:
            raise WorkItemConflict(f"work item is not retryable: {row.status}")
        from modstore_server.models import ManagementWorkOperation

        operations = (
            session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.work_item_id == int(row.id))
            .all()
        )
        unresolved = [
            operation
            for operation in operations
            if str(operation.status or "") in {"running", "uncertain"}
            or str(operation.compensation_status or "")
            in {"required", "failed", "conflict", "unavailable"}
        ]
        if unresolved:
            raise WorkItemConflict("任务存在结果未知或补偿失败的副作用，必须先完成恢复核对")
        previous_max_attempts = int(row.max_attempts or 0)
        if int(row.attempt_count or 0) >= previous_max_attempts:
            # A human retry is an explicit one-attempt override, not an
            # unbounded reset of the automatic retry policy.
            row.max_attempts = int(row.attempt_count or 0) + 1
        row.status = "assigned"
        row.error_kind = ""
        row.error = ""
        row.next_retry_at = None
        row.lease_token = ""
        row.lease_expires_at = None
        row.last_update = _bounded_text(note, 8000) or "人工重新派发"
        row.updated_at = _now()
        _event(
            session,
            row,
            "task.retry_requested",
            actor_type="user",
            actor_id=str(requested_by_user_id),
            message=note,
            payload={
                "previous_max_attempts": previous_max_attempts,
                "max_attempts": int(row.max_attempts or 0),
            },
        )
        session.commit()
        session.refresh(row)
        return _serialize_work_item(row)


def _close_pending_decisions(
    session: Any,
    row: ManagementWorkItem,
    *,
    status: str,
    event_type: str,
    message: str,
) -> int:
    pending = (
        session.query(ManagementDecision)
        .filter(
            ManagementDecision.work_item_id == int(row.id),
            ManagementDecision.status == "pending",
        )
        .all()
    )
    for decision in pending:
        decision.status = _bounded_text(status, 16)
        _event(
            session,
            row,
            event_type,
            message=message or decision.question,
            payload={"decision_id": decision.decision_id},
        )
    return len(pending)


def _finalize_cancelled_row(
    session: Any,
    row: ManagementWorkItem,
    *,
    actor_type: str,
    actor_id: str,
    reason: str,
    event_type: str = "task.cancelled",
) -> None:
    now = _now()
    row.status = "cancelled"
    row.current_stage = "cancelled"
    row.last_update = _bounded_text(reason, 8000) or "任务已停止"
    row.lease_token = ""
    row.lease_expires_at = None
    row.next_retry_at = None
    row.completed_at = now
    row.updated_at = now
    closed_decisions = _close_pending_decisions(
        session,
        row,
        status="cancelled",
        event_type="decision.cancelled",
        message="任务已停止，原决策不再有效",
    )
    _event(
        session,
        row,
        event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        message=row.last_update,
        payload={"closed_decisions": closed_decisions},
    )


def cancel_work_item(
    task_id: str,
    *,
    requested_by_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    """请求停止任务，并对正在执行的任务使用两阶段取消。

    执行中的独立子进程会被终止；服务端再依据 operation 台账
    核对已发生的外部效果。只有无效果或补偿完成才进入
    ``cancelled``，结果未知或不可补偿时保持 ``blocked`` 等老板处理。
    """

    message = _bounded_text(reason, 8000) or "老板请求停止任务"
    sf = get_session_factory()
    from modstore_server.models import ManagementWorkOperation

    with sf() as preflight_session:
        preflight_row = (
            preflight_session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if preflight_row is None:
            raise KeyError("work item not found")
        preflight_status = str(preflight_row.status or "")
        if preflight_status == "delivered":
            raise WorkItemConflict("已交付任务请使用验收退回，不能绕过交付审查取消")
        operation_count = (
            preflight_session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.work_item_id == int(preflight_row.id))
            .count()
        )

    if preflight_status not in {"running", "verifying", "cancel_requested"} and operation_count:
        from modstore_server.management_work_operations import (
            compensate_task_file_operations,
        )

        compensation = compensate_task_file_operations(task_id, reason=message)
        if compensation.get("ok") is not True:
            with sf() as recovery_session:
                recovery_row = (
                    recovery_session.query(ManagementWorkItem)
                    .filter(ManagementWorkItem.task_id == str(task_id))
                    .one()
                )
                if str(recovery_row.status or "") in TERMINAL_STATUSES:
                    raise WorkItemConflict(
                        f"work item became {recovery_row.status} during cancellation"
                    )
                recovery_row.status = "blocked"
                recovery_row.current_stage = "side_effect_recovery"
                recovery_row.error_kind = "side_effect_recovery_required"
                recovery_row.error = "任务停止前发现无法确认或无法补偿的外部副作用"
                recovery_row.last_update = recovery_row.error
                recovery_row.next_retry_at = None
                recovery_row.updated_at = _now()
                _event(
                    recovery_session,
                    recovery_row,
                    "task.side_effect_recovery_required",
                    actor_type="user",
                    actor_id=str(requested_by_user_id),
                    message=recovery_row.error,
                    payload=compensation,
                )
                recovery_session.commit()
                recovery_session.refresh(recovery_row)
                recovery_out = _serialize_work_item(recovery_row)
            _notify_owner(
                recovery_out,
                title=f"任务《{recovery_out['title']}》存在待处理外部效果",
                content=recovery_out["error"],
                event="management_work.blocked",
            )
            return recovery_out

    changed = False
    with sf() as session:
        out: dict[str, Any] | None = None
        for _attempt in range(4):
            row = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.task_id == str(task_id))
                .first()
            )
            if row is None:
                raise KeyError("work item not found")
            previous_status = str(row.status or "")
            if previous_status == "cancelled":
                return _serialize_work_item(row)
            if previous_status == "accepted":
                raise WorkItemConflict("已验收任务不可取消，请新建后续任务")
            if previous_status == "cancel_requested":
                return _serialize_work_item(row)

            now = _now()
            safe_stopping = previous_status in {"running", "verifying"}
            values = {
                ManagementWorkItem.status: ("cancel_requested" if safe_stopping else "cancelled"),
                ManagementWorkItem.current_stage: (
                    "safe_stopping" if safe_stopping else "cancelled"
                ),
                ManagementWorkItem.last_update: message,
                ManagementWorkItem.next_retry_at: None,
                ManagementWorkItem.updated_at: now,
            }
            if not safe_stopping:
                values.update(
                    {
                        ManagementWorkItem.lease_token: "",
                        ManagementWorkItem.lease_expires_at: None,
                        ManagementWorkItem.completed_at: now,
                    }
                )
            updated = (
                session.query(ManagementWorkItem)
                .filter(
                    ManagementWorkItem.id == int(row.id),
                    ManagementWorkItem.status == previous_status,
                )
                .update(values, synchronize_session=False)
            )
            if updated != 1:
                session.rollback()
                continue

            session.expire_all()
            row = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.task_id == str(task_id))
                .one()
            )
            changed = True
            if safe_stopping:
                _event(
                    session,
                    row,
                    "task.cancel_requested",
                    actor_type="user",
                    actor_id=str(requested_by_user_id),
                    message=message,
                    payload={
                        "previous_status": previous_status,
                        "semantics": "terminate_isolated_process_then_reconcile_operations",
                        "lease_expires_at": (
                            row.lease_expires_at.isoformat() if row.lease_expires_at else None
                        ),
                    },
                )
            else:
                closed_decisions = _close_pending_decisions(
                    session,
                    row,
                    status="cancelled",
                    event_type="decision.cancelled",
                    message="任务已停止，原决策不再有效",
                )
                _event(
                    session,
                    row,
                    "task.cancelled",
                    actor_type="user",
                    actor_id=str(requested_by_user_id),
                    message=message,
                    payload={
                        "previous_status": previous_status,
                        "closed_decisions": closed_decisions,
                    },
                )
            session.commit()
            session.refresh(row)
            out = _serialize_work_item(row)
            break
        if out is None:
            raise WorkItemConflict("任务状态正在变化，请重试停止")

    if changed:
        _notify_owner(
            out,
            title=(
                f"任务《{out['title']}》正在安全停止"
                if out["status"] == "cancel_requested"
                else f"任务《{out['title']}》已停止"
            ),
            content=(
                "台账已禁止后续验收和交付；正在终止独立进程并核对外部效果。"
                if out["status"] == "cancel_requested"
                else message
            ),
            event=(
                "management_work.cancel_requested"
                if out["status"] == "cancel_requested"
                else "management_work.cancelled"
            ),
        )
    return out


def finalize_requested_cancellation(
    task_id: str,
    *,
    employee_id: str,
    lease_token: str,
    reason: str = "",
) -> dict[str, Any] | None:
    """在员工当前原子步骤返回后收口两阶段取消。"""

    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if row is None:
            raise KeyError("work item not found")
        if row.status == "cancelled":
            return _serialize_work_item(row)
        if row.status != "cancel_requested":
            return None
        if str(row.owner_employee_id or "") != str(employee_id):
            raise WorkItemConflict("employee does not own cancellation")
        if not lease_token or str(row.lease_token or "") != str(lease_token):
            raise WorkItemConflict("cancellation lease has been superseded")
        from modstore_server.management_work_operations import (
            compensate_task_file_operations,
        )

        compensation = compensate_task_file_operations(
            task_id,
            reason=_bounded_text(reason, 1000) or "老板取消管理任务",
        )
        if compensation.get("ok") is not True:
            row.status = "blocked"
            row.current_stage = "side_effect_recovery"
            row.error_kind = "side_effect_recovery_required"
            row.error = "任务已停止，但存在无法确认或无法补偿的外部副作用"
            row.last_update = row.error
            row.lease_token = ""
            row.lease_expires_at = None
            row.next_retry_at = None
            row.updated_at = _now()
            _event(
                session,
                row,
                "task.side_effect_recovery_required",
                actor_type="system",
                actor_id="management-operation-recovery",
                message=row.error,
                payload=compensation,
            )
        else:
            _finalize_cancelled_row(
                session,
                row,
                actor_type="employee",
                actor_id=employee_id,
                reason=_bounded_text(reason, 8000) or "当前执行步骤已收尾，任务已安全停止",
            )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)
    if out["status"] == "cancelled":
        _notify_owner(
            out,
            title=f"任务《{out['title']}》已安全停止",
            content=out["last_update"],
            event="management_work.cancelled",
        )
    else:
        _notify_owner(
            out,
            title=f"任务《{out['title']}》存在待处理外部效果",
            content=out["error"],
            event="management_work.blocked",
        )
    return out


def reassign_work_item(
    task_id: str,
    *,
    new_employee_id: str,
    requested_by_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    """把未完成任务可审计地改派给另一名管理端员工。"""

    target = _require_executable_management_employee(new_employee_id)
    allowed = {"assigned", "retrying", "waiting_decision", "blocked", "failed"}
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .first()
        )
        if row is None:
            raise KeyError("work item not found")
        previous_status = str(row.status or "")
        previous_owner = str(row.owner_employee_id or "")
        if previous_owner == target:
            raise WorkItemConflict("任务已由该员工负责")
        if previous_status not in allowed:
            if previous_status in {"running", "cancel_requested", "verifying"}:
                raise WorkItemConflict("任务正在执行或停止中，请先完成停止再改派")
            if previous_status == "delivered":
                raise WorkItemConflict("任务已交付，请先验收退回后再改派")
            raise WorkItemConflict(f"任务状态 {previous_status} 不可改派")

        from modstore_server.models import ManagementWorkOperation

        operations = (
            session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.work_item_id == int(row.id))
            .all()
        )
        if any(
            str(operation.status or "") in {"running", "uncertain"}
            or str(operation.compensation_status or "")
            in {"required", "failed", "conflict", "unavailable"}
            for operation in operations
        ):
            raise WorkItemConflict("任务存在未核对的外部效果，不能直接改派")

        previous_progress = int(row.progress or 0)
        previous_max_attempts = int(row.max_attempts or 0)
        attempt_count = int(row.attempt_count or 0)
        new_max_attempts = (
            attempt_count + 1 if attempt_count >= previous_max_attempts else previous_max_attempts
        )
        last_update = _bounded_text(reason, 8000) or f"人工改派给 {target}"
        updated = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.id == int(row.id),
                ManagementWorkItem.status == previous_status,
                ManagementWorkItem.owner_employee_id == previous_owner,
            )
            .update(
                {
                    ManagementWorkItem.owner_employee_id: target,
                    ManagementWorkItem.status: "assigned",
                    ManagementWorkItem.progress: 0,
                    ManagementWorkItem.current_stage: "reassigned",
                    ManagementWorkItem.last_update: last_update,
                    ManagementWorkItem.error_kind: "",
                    ManagementWorkItem.error: "",
                    ManagementWorkItem.max_attempts: new_max_attempts,
                    ManagementWorkItem.next_retry_at: None,
                    ManagementWorkItem.lease_token: "",
                    ManagementWorkItem.lease_expires_at: None,
                    ManagementWorkItem.updated_at: _now(),
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            session.rollback()
            current = (
                session.query(ManagementWorkItem)
                .filter(ManagementWorkItem.task_id == str(task_id))
                .first()
            )
            raise WorkItemConflict(
                f"任务已并发进入 {current.status if current else 'missing'}，未执行改派"
            )
        session.expire_all()
        row = (
            session.query(ManagementWorkItem)
            .filter(ManagementWorkItem.task_id == str(task_id))
            .one()
        )
        closed_decisions = _close_pending_decisions(
            session,
            row,
            status="superseded",
            event_type="decision.superseded",
            message="任务已改派，原员工的决策请求已作废",
        )
        _event(
            session,
            row,
            "task.reassigned",
            actor_type="user",
            actor_id=str(requested_by_user_id),
            message=row.last_update,
            payload={
                "from_employee_id": previous_owner,
                "to_employee_id": target,
                "previous_status": previous_status,
                "previous_progress": previous_progress,
                "attempt_count": attempt_count,
                "previous_max_attempts": previous_max_attempts,
                "max_attempts": int(row.max_attempts or 0),
                "closed_decisions": closed_decisions,
            },
        )
        session.commit()
        session.refresh(row)
        out = _serialize_work_item(row)

    _notify_owner(
        out,
        title=f"任务《{out['title']}》已改派给 {target}",
        content=f"原负责人 {previous_owner}，改派原因：{out['last_update']}",
        event="management_work.reassigned",
    )
    return out


def recover_stale_work_items(*, limit: int = 100) -> dict[str, Any]:
    """回收过期租约、到期重试和超时决策；不会把它们伪装成完成。"""

    now = _now()
    recovered = 0
    blocked = 0
    cancelled = 0
    decision_timeouts = 0
    decision_reminders = 0
    notifications: list[tuple[dict[str, Any], str]] = []
    cancellation_notifications: list[dict[str, Any]] = []
    sf = get_session_factory()
    with sf() as session:
        from modstore_server.models import ManagementWorkOperation

        stale = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.status.in_(["running", "cancel_requested"]),
                ManagementWorkItem.lease_expires_at.is_not(None),
                ManagementWorkItem.lease_expires_at <= now,
            )
            .order_by(ManagementWorkItem.lease_expires_at.asc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for row in stale:
            active_operations = (
                session.query(ManagementWorkOperation)
                .filter(
                    ManagementWorkOperation.work_item_id == int(row.id),
                    ManagementWorkOperation.status.in_(["running", "uncertain"]),
                )
                .all()
            )
            if active_operations:
                for operation in active_operations:
                    if operation.status == "running":
                        operation.status = "uncertain"
                        operation.lease_expires_at = None
                        operation.error = "任务租约结束时副作用结果仍未确认"
                        operation.compensation_status = (
                            "required" if operation.reversible else "unavailable"
                        )
                        operation.updated_at = now
                        _event(
                            session,
                            row,
                            "operation.uncertain",
                            actor_type="system",
                            actor_id="management-work-watchdog",
                            message=operation.error,
                            payload={
                                "operation_id": operation.operation_id,
                                "operation_key": operation.operation_key,
                                "kind": operation.kind,
                            },
                        )
                row.status = "blocked"
                row.current_stage = "side_effect_recovery"
                row.lease_token = ""
                row.lease_expires_at = None
                row.next_retry_at = None
                row.error_kind = "side_effect_outcome_unknown"
                row.error = "执行租约已结束，但存在结果未知的外部副作用，禁止自动重放"
                row.updated_at = now
                _event(
                    session,
                    row,
                    "task.side_effect_recovery_required",
                    actor_type="system",
                    actor_id="management-work-watchdog",
                    message=row.error,
                    payload={
                        "operation_ids": [operation.operation_id for operation in active_operations]
                    },
                )
                notifications.append((_serialize_work_item(row), row.error))
                blocked += 1
                continue
            if row.status == "cancel_requested":
                _finalize_cancelled_row(
                    session,
                    row,
                    actor_type="system",
                    actor_id="management-work-watchdog",
                    reason="停止请求后执行租约已结束，看门狗已安全收口",
                )
                cancellation_notifications.append(_serialize_work_item(row))
                cancelled += 1
                continue
            row.lease_token = ""
            row.lease_expires_at = None
            row.error_kind = "lease_expired"
            row.error = "员工执行心跳超时"
            if int(row.attempt_count or 0) < int(row.max_attempts or 0):
                row.status = "retrying"
                row.next_retry_at = now + timedelta(seconds=30)
                recovered += 1
                event_type = "task.lease_recovered"
            else:
                row.status = "blocked"
                row.next_retry_at = None
                blocked += 1
                event_type = "task.blocked"
                notifications.append(
                    (_serialize_work_item(row), "员工执行心跳超时且重试次数已耗尽")
                )
            row.updated_at = now
            _event(session, row, event_type, message=row.error)

        due_retries = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.status == "retrying",
                ManagementWorkItem.next_retry_at.is_not(None),
                ManagementWorkItem.next_retry_at <= now,
            )
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for row in due_retries:
            unresolved = (
                session.query(ManagementWorkOperation.id)
                .filter(
                    ManagementWorkOperation.work_item_id == int(row.id),
                    ManagementWorkOperation.status.in_(["running", "uncertain"]),
                )
                .first()
            )
            if unresolved is not None:
                row.status = "blocked"
                row.next_retry_at = None
                row.error_kind = "side_effect_outcome_unknown"
                row.error = "存在结果未知的外部副作用，禁止进入自动重试"
                row.updated_at = now
                _event(
                    session,
                    row,
                    "task.side_effect_recovery_required",
                    actor_type="system",
                    actor_id="management-work-watchdog",
                    message=row.error,
                )
                notifications.append((_serialize_work_item(row), row.error))
                blocked += 1
                continue
            row.status = "assigned"
            row.next_retry_at = None
            row.updated_at = now
            _event(
                session,
                row,
                "task.retry_ready",
                message="重试已到期，重新进入待领取队列",
            )
            recovered += 1

        decisions = (
            session.query(ManagementDecision)
            .filter(
                ManagementDecision.status == "pending",
                ManagementDecision.due_at.is_not(None),
                ManagementDecision.due_at <= now,
            )
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for decision in decisions:
            decision.status = "expired"
            row = session.get(ManagementWorkItem, decision.work_item_id)
            if row is None or row.status != "waiting_decision":
                continue
            row.status = "blocked"
            row.error_kind = "decision_timeout"
            row.error = "等待老板决策超时"
            row.updated_at = now
            _event(
                session,
                row,
                "decision.expired",
                message=decision.question,
                payload={"decision_id": decision.decision_id},
            )
            notifications.append(
                (_serialize_work_item(row), f"决策超时：{decision.question[:300]}")
            )
            decision_timeouts += 1
            blocked += 1
        try:
            reminder_seconds = max(
                300,
                min(
                    int(os.environ.get("MODSTORE_MANAGEMENT_DECISION_REMINDER_SECONDS", "1800")),
                    86400,
                ),
            )
        except (TypeError, ValueError):
            reminder_seconds = 1800
        reminder_cutoff = now - timedelta(seconds=reminder_seconds)
        reminders = (
            session.query(ManagementDecision)
            .filter(
                ManagementDecision.status == "pending",
                ManagementDecision.due_at.is_not(None),
                ManagementDecision.due_at > now,
                (
                    ManagementDecision.last_reminded_at.is_(None)
                    | (ManagementDecision.last_reminded_at <= reminder_cutoff)
                ),
            )
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for decision in reminders:
            row = session.get(ManagementWorkItem, decision.work_item_id)
            if row is None or row.status != "waiting_decision":
                continue
            decision.last_reminded_at = now
            decision.reminder_count = int(decision.reminder_count or 0) + 1
            _event(
                session,
                row,
                "decision.reminded",
                message=decision.question,
                payload={
                    "decision_id": decision.decision_id,
                    "reminder_count": decision.reminder_count,
                },
            )
            notifications.append(
                (
                    _serialize_work_item(row),
                    f"员工仍在等你决定：{decision.question[:300]}",
                )
            )
            decision_reminders += 1
        session.commit()

    for item, reason in notifications:
        _notify_owner(
            item,
            title=f"任务《{item['title']}》需要你介入",
            content=reason,
            event="management_work.escalated",
        )
    for item in cancellation_notifications:
        _notify_owner(
            item,
            title=f"任务《{item['title']}》已安全停止",
            content=item["last_update"],
            event="management_work.cancelled",
        )
    return {
        "ok": True,
        "recovered": recovered,
        "blocked": blocked,
        "cancelled": cancelled,
        "decision_timeouts": decision_timeouts,
        "decision_reminders": decision_reminders,
    }


def work_item_summary() -> dict[str, Any]:
    from sqlalchemy import func

    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(ManagementWorkItem.status, func.count(ManagementWorkItem.id))
            .group_by(ManagementWorkItem.status)
            .all()
        )
        pending_decisions = (
            session.query(func.count(ManagementDecision.id))
            .filter(ManagementDecision.status == "pending")
            .scalar()
            or 0
        )
    by_status = {str(status): int(count or 0) for status, count in rows}
    return {
        "by_status": by_status,
        "active": sum(by_status.get(status, 0) for status in ACTIVE_STATUSES),
        "pending_decisions": int(pending_decisions),
        "accepted": by_status.get("accepted", 0),
        "blocked": by_status.get("blocked", 0),
    }


def _execution_summary(result: dict[str, Any]) -> str:
    for candidate in (
        result.get("summary"),
        result.get("message"),
        (
            (result.get("result") or {}).get("summary")
            if isinstance(result.get("result"), dict)
            else ""
        ),
    ):
        text = _bounded_text(candidate, 4000)
        if text:
            return text
    raw = _dumps(result)
    return raw[:4000] if raw else "员工执行已返回结构化结果"


def _bounded_runtime_evidence(result: Any) -> Any:
    """Keep a diagnosable runtime result without allowing ledger bloat."""

    evidence_json = _dumps(result)
    if len(evidence_json) <= 120_000:
        return result
    return {"truncated": True, "preview": evidence_json[:120_000]}


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    raw = str(value or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else ""
    if not raw.startswith("{"):
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_acceptance_audit_report(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        execution = node.get("result") if isinstance(node.get("result"), dict) else {}
        actions = execution.get("result") if isinstance(execution.get("result"), dict) else {}
        outputs = actions.get("outputs") if isinstance(actions.get("outputs"), list) else []
        for output in outputs:
            if not isinstance(output, dict):
                continue
            report = _parse_json_object(output.get("output"))
            if report and ("verdict" in report or "criteria" in report):
                return report
    return None


def _validate_acceptance_audit(
    report: Any,
    *,
    criteria: list[str],
    evidence_ids: set[str],
    required_fact_evidence_id: str = "",
    required_fact_evidence_ids: set[str] | None = None,
    required_operation_evidence_ids: set[str] | None = None,
) -> tuple[str, str]:
    """Return ``pass|fail|inconclusive|invalid`` and a bounded reason."""

    if not isinstance(report, dict):
        return "invalid", "acceptance verifier returned no JSON report"
    if not criteria:
        return "invalid", "management work has no acceptance criteria"
    if str(report.get("status") or "").strip().lower() != "success":
        return "invalid", "acceptance verifier status is not success"
    verdict = str(report.get("verdict") or "").strip().upper()
    if verdict not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        return "invalid", "acceptance verifier verdict is invalid"
    if len(str(report.get("summary") or "").strip()) < 10:
        return "invalid", "acceptance verifier summary is missing"
    rows = report.get("criteria") if isinstance(report.get("criteria"), list) else []
    if len(rows) != len(criteria):
        return "invalid", "acceptance verifier did not cover every criterion"

    required_facts = set(required_fact_evidence_ids or set())
    if required_fact_evidence_id:
        required_facts.add(required_fact_evidence_id)
    required_operations = set(required_operation_evidence_ids or set())
    statuses: list[str] = []
    for index, criterion in enumerate(criteria, start=1):
        row = rows[index - 1]
        if not isinstance(row, dict):
            return "invalid", f"criterion_{index} report is malformed"
        expected_id = f"criterion_{index}"
        if str(row.get("criterion_id") or "") != expected_id:
            return "invalid", f"{expected_id} is missing or out of order"
        if str(row.get("criterion") or "") != criterion:
            return "invalid", f"{expected_id} text does not match the ledger"
        status = str(row.get("status") or "").strip().lower()
        if status not in {"pass", "fail", "unverified"}:
            return "invalid", f"{expected_id} status is invalid"
        statuses.append(status)
        refs = row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else []
        clean_refs = [str(ref).strip() for ref in refs if str(ref).strip()]
        unknown = [ref for ref in clean_refs if ref not in evidence_ids]
        if unknown:
            return "invalid", f"{expected_id} references unknown evidence: {unknown[0]}"
        if status == "pass" and not clean_refs:
            return "invalid", f"{expected_id} passed without evidence"
        if status == "pass" and required_facts and not required_facts.intersection(clean_refs):
            return (
                "invalid",
                f"{expected_id} passed without required independent fact evidence",
            )
        if (
            status == "pass"
            and required_operations
            and not required_operations.intersection(clean_refs)
        ):
            return (
                "invalid",
                f"{expected_id} passed without required operation receipt evidence",
            )

    if verdict == "PASS" and all(status == "pass" for status in statuses):
        return "pass", "independent acceptance audit passed"
    if verdict == "FAIL" and "fail" in statuses:
        return "fail", str(report.get("summary") or "acceptance audit failed")[:2000]
    if verdict == "INCONCLUSIVE" and "unverified" in statuses:
        return (
            "inconclusive",
            str(report.get("summary") or "acceptance audit inconclusive")[:2000],
        )
    return "invalid", "acceptance verdict does not match criterion statuses"


def _run_independent_acceptance_audit(
    *,
    task_id: str,
    task_text: str,
    criteria: list[str],
    runtime_result: dict[str, Any],
    fact_snapshot: dict[str, Any],
    created_by_user_id: int,
    dispatch: Any,
) -> dict[str, Any]:
    evidence_id = "evidence_1"
    runtime_preview = _dumps(runtime_result)[:60_000]
    criterion_rows = [
        {"criterion_id": f"criterion_{index}", "criterion": criterion}
        for index, criterion in enumerate(criteria, start=1)
    ]
    evidence_catalog = [
        {
            "evidence_id": evidence_id,
            "kind": "employee_runtime_claim",
            "trust_level": "untrusted_employee_claim",
            "admissible_for_fact_pass": False,
            "content": runtime_preview,
        }
    ]
    required_fact_ids: set[str] = set()
    required_operation_ids: set[str] = set()
    if fact_snapshot:
        for index, fact in enumerate(fact_snapshot.get("facts") or [], start=1):
            if not isinstance(fact, dict):
                continue
            fact_id = str(fact.get("evidence_id") or f"fact_{index}")[:128]
            verified_strong = bool(
                fact.get("verified") is True and fact.get("strength") == "strong"
            )
            evidence_catalog.append(
                {
                    "evidence_id": fact_id,
                    "kind": str(fact.get("kind") or "independent_fact"),
                    "trust_level": "independent_observation",
                    "admissible_for_fact_pass": verified_strong,
                    "content": _dumps(fact)[:40_000],
                }
            )
            if verified_strong and fact.get("kind") == "operation":
                required_operation_ids.add(fact_id)
            elif verified_strong:
                required_fact_ids.add(fact_id)
        evidence_catalog.append(
            {
                "evidence_id": "fact_bundle",
                "kind": "signed_fact_bundle",
                "trust_level": "integrity_receipt",
                "admissible_for_fact_pass": False,
                "content": _dumps(
                    {
                        "outcome": fact_snapshot.get("outcome"),
                        "snapshot_sha256": fact_snapshot.get("snapshot_sha256"),
                        "signature_alg": fact_snapshot.get("signature_alg"),
                    }
                ),
            }
        )
    audit_context = {
        "task_id": task_id,
        "criteria": criterion_rows,
        "independent_fact_required": bool(fact_snapshot.get("required")),
        "required_fact_evidence_ids": sorted(required_fact_ids),
        "required_operation_evidence_ids": sorted(required_operation_ids),
        "evidence_catalog": evidence_catalog,
    }
    audit_task = (
        "独立审核管理任务交付，严格按输入的 criteria 和 evidence_catalog "
        "输出指定 JSON；只读验收，不得执行外部副作用。\n原任务："
        f"{task_text[:4000]}"
    )
    try:
        verifier_runtime = dispatch(
            audit_task,
            {
                "task": audit_task,
                "user_request": audit_task,
                "management_acceptance_audit": audit_context,
                "external_side_effects": False,
            },
            target_employee_id="delivery-receipt-officer",
            created_by_user_id=created_by_user_id,
            include_dependencies=False,
            max_concurrency=1,
            allow_high_risk_real_run=False,
        )
    except Exception as exc:  # noqa: BLE001 - normalized into fail-closed audit
        return {
            "outcome": "unavailable",
            "reason": f"acceptance verifier unavailable: {type(exc).__name__}: {exc}"[:2000],
            "report": None,
            "runtime": {"error_type": type(exc).__name__, "message": str(exc)[:2000]},
        }
    verifier_ok, verifier_reason = execution_result_is_accepted(verifier_runtime)
    report = _extract_acceptance_audit_report(verifier_runtime)
    if not verifier_ok:
        return {
            "outcome": "unavailable",
            "reason": f"acceptance verifier runtime rejected: {verifier_reason}"[:2000],
            "report": report,
            "runtime": _bounded_runtime_evidence(verifier_runtime),
        }
    outcome, reason = _validate_acceptance_audit(
        report,
        criteria=criteria,
        evidence_ids={str(row["evidence_id"]) for row in evidence_catalog},
        required_fact_evidence_ids=(required_fact_ids if fact_snapshot.get("required") else set()),
        required_operation_evidence_ids=(
            required_operation_ids if fact_snapshot.get("operation_required") else set()
        ),
    )
    return {
        "outcome": outcome,
        "reason": reason,
        "report": report,
        "runtime": _bounded_runtime_evidence(verifier_runtime),
    }


def execution_result_is_accepted(result: Any) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, "employee runtime returned a non-object result"
    if result.get("ok") is not True:
        return (
            False,
            _bounded_text(result.get("error"), 2000) or "employee runtime ok=false",
        )
    if result.get("accepted_completion") is False:
        return False, f"duty graph status={result.get('status') or 'not accepted'}"
    if str(result.get("status") or "").lower() in {
        "blocked",
        "failed",
        "partial",
        "cancelled",
    }:
        return False, f"employee runtime status={result.get('status')}"
    return True, "runtime accepted"


def dispatch_assigned_work_items(*, limit: int = 3, lease_seconds: int = 300) -> dict[str, Any]:
    """让真实员工运行时领取统一台账中的 assigned 任务。

    调度器周期调用本函数。执行期间独立心跳线程续租；进程崩溃后 watchdog 会回收
    过期租约并重试，因此 HTTP 请求断开或桌面重启不会丢任务。
    """

    candidates = list_work_items(statuses=["assigned"], limit=max(1, min(limit, 20)))
    processed = 0
    delivered = 0
    retrying = 0
    blocked = 0
    cancelled = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for item in candidates:
        task_id = str(item.get("task_id") or "")
        employee_id = str(item.get("owner_employee_id") or "")
        try:
            claimed = claim_work_item(
                task_id,
                employee_id=employee_id,
                lease_seconds=lease_seconds,
            )
        except (WorkItemConflict, KeyError):
            skipped += 1
            continue

        processed += 1
        lease_token = str(claimed.get("lease_token") or "")
        stop_heartbeat = threading.Event()

        def _heartbeat_loop() -> None:
            interval = max(5.0, min(float(lease_seconds) / 3.0, 60.0))
            while not stop_heartbeat.wait(interval):
                try:
                    heartbeat_work_item(
                        task_id,
                        employee_id=employee_id,
                        lease_token=lease_token,
                        lease_seconds=lease_seconds,
                    )
                except WorkItemConflict:
                    # A user cancellation intentionally invalidates running
                    # heartbeats.  This is normal convergence, not an outage.
                    return
                except Exception:
                    logger.exception("management work heartbeat failed task_id=%s", task_id)
                    return

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"management-work-heartbeat-{task_id[-8:]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            heartbeat_work_item(
                task_id,
                employee_id=employee_id,
                lease_token=lease_token,
                progress=5,
                stage="employee_execution",
                message="员工已领取任务并开始执行",
                lease_seconds=lease_seconds,
            )
            stopped = finalize_requested_cancellation(
                task_id,
                employee_id=employee_id,
                lease_token=lease_token,
                reason="员工尚未进入主执行步骤，任务已安全停止",
            )
            if stopped is not None:
                if stopped.get("status") == "cancelled":
                    cancelled += 1
                else:
                    blocked += 1
                continue
            execution_mode = (
                str(os.environ.get("MODSTORE_MANAGEMENT_WORK_EXECUTION_MODE") or "process")
                .strip()
                .lower()
            )
            if execution_mode in {"inline", "in_process", "test"}:
                from modstore_server.employee_orchestrator import plan_and_dispatch

                execution_dispatch = plan_and_dispatch
            else:

                def execution_dispatch(
                    child_task: str,
                    child_input: dict[str, Any],
                    **child_kwargs: Any,
                ) -> dict[str, Any]:
                    return _run_management_execution_process(
                        child_task,
                        child_input,
                        task_id=task_id,
                        target_employee_id=str(child_kwargs.get("target_employee_id") or ""),
                        created_by_user_id=int(child_kwargs.get("created_by_user_id") or 0),
                        include_dependencies=bool(child_kwargs.get("include_dependencies", False)),
                        max_concurrency=int(child_kwargs.get("max_concurrency") or 1),
                        allow_high_risk_real_run=bool(
                            child_kwargs.get("allow_high_risk_real_run", False)
                        ),
                    )

            detail = get_work_item(task_id, include_timeline=True) or item
            execution_input = dict(item.get("input") or {})
            task_text = str(item.get("description") or item.get("title") or "")
            # Some specialist prompts only inspect normalized input and do not
            # look back at the separate executor `task` argument. Preserve the
            # owner's natural-language request in both canonical input keys.
            execution_input.setdefault("task", task_text)
            execution_input.setdefault("user_request", task_text)
            # Management employees operate in a server-selected workspace. A
            # caller-supplied project_root must never widen filesystem scope.
            management_workspace = _management_execution_workspace_root(employee_id)
            if management_workspace:
                execution_input["project_root"] = management_workspace
            decided = [
                {
                    "decision_id": decision.get("decision_id"),
                    "question": decision.get("question"),
                    "decision": decision.get("decision"),
                    "note": decision.get("note"),
                }
                for decision in detail.get("decisions", [])
                if isinstance(decision, dict) and decision.get("status") == "decided"
            ]
            rejection_feedback = [
                event.get("message")
                for event in detail.get("events", [])
                if isinstance(event, dict)
                and event.get("event_type")
                in {"task.rejected", "task.retry_scheduled", "task.blocked"}
                and str(event.get("message") or "").strip()
            ]
            acceptance_criteria = [
                str(value).strip()
                for value in (item.get("acceptance_criteria") or [])
                if str(value).strip()
            ]
            execution_input["management_work"] = {
                "task_id": task_id,
                "employee_partition": EMPLOYEE_PARTITION,
                "priority": item.get("priority"),
                "risk_level": item.get("risk_level"),
                "acceptance_criteria": acceptance_criteria,
                "resolved_decisions": decided,
                "review_feedback": rejection_feedback[-5:],
                "last_update": item.get("last_update") or "",
                "task_description": task_text,
                "operation_context": {
                    "protocol": "management-operation-v1",
                    "task_id": task_id,
                    "task_revision": 1,
                    "attempt": int(claimed.get("attempt_count") or 1),
                    "employee_id": employee_id,
                    "require_registered_side_effects": True,
                },
            }
            result = execution_dispatch(
                task_text,
                execution_input,
                target_employee_id=employee_id,
                created_by_user_id=int(item.get("created_by_user_id") or 0),
                # The duty roster contains advisory collaboration edges and a
                # few historical cycles.  A management ledger owner must be
                # able to execute its own assignment deterministically; team
                # expansion is handled explicitly as child work, while the
                # independent receipt officer remains a separate verifier.
                include_dependencies=False,
                max_concurrency=2,
                allow_high_risk_real_run=False,
            )
            stopped = finalize_requested_cancellation(
                task_id,
                employee_id=employee_id,
                lease_token=lease_token,
                reason="员工当前执行步骤已返回，已阻止后续验收和交付",
            )
            if stopped is not None:
                if stopped.get("status") == "cancelled":
                    cancelled += 1
                else:
                    blocked += 1
                continue
            runtime_ok, reason = execution_result_is_accepted(result)
            from modstore_server.management_work_evidence import (
                collect_independent_fact_snapshot,
                persist_fact_snapshot,
                redact_runtime_claim,
            )

            redacted_result = redact_runtime_claim(result)
            runtime_evidence = _bounded_runtime_evidence(redacted_result)
            audit: dict[str, Any] | None = None
            fact_snapshot: dict[str, Any] = {}
            receipt: dict[str, Any] | None = None
            ok = runtime_ok
            error_kind = "runtime_not_accepted"
            if runtime_ok:
                fact_snapshot = collect_independent_fact_snapshot(
                    task_id=task_id,
                    employee_id=employee_id,
                    task_text=task_text,
                    task_input=execution_input,
                    runtime_result=result,
                )
                persist_fact_snapshot(
                    task_id=task_id,
                    attempt=int(claimed.get("attempt_count") or 1),
                    snapshot=fact_snapshot,
                )
                fact_outcome = str(fact_snapshot.get("outcome") or "invalid")
                if fact_outcome == "pass":
                    audit = _run_independent_acceptance_audit(
                        task_id=task_id,
                        task_text=task_text,
                        criteria=acceptance_criteria,
                        runtime_result=redacted_result,
                        fact_snapshot=fact_snapshot,
                        created_by_user_id=int(item.get("created_by_user_id") or 0),
                        dispatch=execution_dispatch,
                    )
                else:
                    audit = {
                        "outcome": ("fail" if fact_outcome == "fail" else "inconclusive"),
                        "reason": str(fact_snapshot.get("reason") or "")[:2000],
                        "report": None,
                        "runtime": None,
                    }
                receipt = _record_verification_receipt(
                    task_id=task_id,
                    result_digest=str(fact_snapshot.get("runtime_claim_sha256") or ""),
                    fact_snapshot=fact_snapshot,
                    audit=audit,
                )
                outcome = str(audit.get("outcome") or "invalid")
                if outcome != "pass":
                    ok = False
                    reason = str(audit.get("reason") or "independent acceptance failed")
                    error_kind = {
                        "fail": "acceptance_failed",
                        "inconclusive": "acceptance_inconclusive",
                        "invalid": "acceptance_verifier_invalid",
                        "unavailable": "acceptance_verifier_unavailable",
                    }.get(outcome, "acceptance_verifier_invalid")
                    if fact_outcome != "pass":
                        error_kind = (
                            "independent_fact_failed"
                            if fact_outcome == "fail"
                            else "independent_fact_inconclusive"
                        )
            stopped = finalize_requested_cancellation(
                task_id,
                employee_id=employee_id,
                lease_token=lease_token,
                reason="独立验收步骤已返回，已阻止交付入账",
            )
            if stopped is not None:
                if stopped.get("status") == "cancelled":
                    cancelled += 1
                else:
                    blocked += 1
                continue
            if ok:
                heartbeat_work_item(
                    task_id,
                    employee_id=employee_id,
                    lease_token=lease_token,
                    progress=90,
                    stage="verification",
                    message="执行完成，正在提交证据等待验收",
                    lease_seconds=lease_seconds,
                )
                deliver_work_item(
                    task_id,
                    employee_id=employee_id,
                    lease_token=lease_token,
                    summary=_execution_summary(result),
                    evidence=[
                        {
                            "kind": "employee_runtime_result",
                            "employee_id": employee_id,
                            "value": runtime_evidence,
                        },
                        {
                            "kind": "acceptance_audit",
                            "employee_id": "delivery-receipt-officer",
                            "outcome": audit.get("outcome") if audit else "invalid",
                            "report": audit.get("report") if audit else None,
                            "runtime": audit.get("runtime") if audit else None,
                        },
                        {
                            "kind": "independent_fact_snapshot",
                            "outcome": fact_snapshot.get("outcome"),
                            "snapshot_sha256": fact_snapshot.get("snapshot_sha256"),
                            "required": fact_snapshot.get("required"),
                            "facts": fact_snapshot.get("facts"),
                        },
                        {
                            "kind": "verification_receipt",
                            "receipt_id": receipt.get("receipt_id") if receipt else "",
                            "fact_bundle_digest": (
                                receipt.get("fact_bundle_digest") if receipt else ""
                            ),
                        },
                    ],
                    verification_receipt_id=(
                        str(receipt.get("receipt_id") or "") if receipt else ""
                    ),
                    candidate_result_digest=str(fact_snapshot.get("runtime_claim_sha256") or ""),
                )
                delivered += 1
            else:
                failure_evidence: list[dict[str, Any]] = [
                    {
                        "kind": (
                            "employee_runtime_result" if runtime_ok else "employee_runtime_failure"
                        ),
                        "employee_id": employee_id,
                        "reason": reason,
                        "value": runtime_evidence,
                    }
                ]
                if audit is not None:
                    failure_evidence.append(
                        {
                            "kind": "acceptance_audit",
                            "employee_id": "delivery-receipt-officer",
                            "outcome": audit.get("outcome"),
                            "reason": audit.get("reason"),
                            "report": audit.get("report"),
                            "runtime": audit.get("runtime"),
                        }
                    )
                if fact_snapshot:
                    failure_evidence.append(
                        {
                            "kind": "independent_fact_snapshot",
                            "outcome": fact_snapshot.get("outcome"),
                            "reason": fact_snapshot.get("reason"),
                            "snapshot_sha256": fact_snapshot.get("snapshot_sha256"),
                            "required": fact_snapshot.get("required"),
                            "facts": fact_snapshot.get("facts"),
                        }
                    )
                failed = fail_work_item(
                    task_id,
                    employee_id=employee_id,
                    lease_token=lease_token,
                    error_kind=error_kind,
                    error=reason,
                    retryable=True,
                    evidence=failure_evidence,
                )
                if failed.get("status") == "retrying":
                    retrying += 1
                else:
                    blocked += 1
        except Exception as exc:  # noqa: BLE001 - persisted into retry/blocked state
            try:
                stopped = finalize_requested_cancellation(
                    task_id,
                    employee_id=employee_id,
                    lease_token=lease_token,
                    reason="执行步骤已退出，任务按停止请求收口",
                )
            except (KeyError, WorkItemConflict):
                stopped = None
            if stopped is not None:
                if stopped.get("status") == "cancelled":
                    cancelled += 1
                else:
                    blocked += 1
                continue
            logger.warning(
                "management work execution failed task_ref=%s",
                opaque_ref(task_id, namespace="management-task"),
            )
            try:
                failed = fail_work_item(
                    task_id,
                    employee_id=employee_id,
                    lease_token=lease_token,
                    error_kind=type(exc).__name__,
                    error=str(exc),
                    retryable=True,
                    evidence=[
                        {
                            "kind": "employee_runtime_exception",
                            "employee_id": employee_id,
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:2000],
                        }
                    ],
                )
                if failed.get("status") == "retrying":
                    retrying += 1
                else:
                    blocked += 1
            except Exception as persist_exc:  # noqa: BLE001
                errors.append({"task_id": task_id, "error": str(persist_exc)[:500]})
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1.0)

    return {
        "ok": not errors,
        "processed": processed,
        "delivered": delivered,
        "retrying": retrying,
        "blocked": blocked,
        "cancelled": cancelled,
        "skipped": skipped,
        "errors": errors,
    }


__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "WorkItemConflict",
    "cancel_work_item",
    "claim_work_item",
    "create_work_item",
    "deliver_work_item",
    "dispatch_assigned_work_items",
    "execution_result_is_accepted",
    "fail_work_item",
    "finalize_requested_cancellation",
    "get_work_item",
    "heartbeat_work_item",
    "list_management_employees",
    "list_work_items",
    "recover_stale_work_items",
    "reassign_work_item",
    "request_decision",
    "resolve_decision",
    "retry_work_item",
    "review_delivery",
    "work_item_summary",
]
