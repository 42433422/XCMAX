"""Start one owner-bound workbench delivery generation."""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.customer_delivery_failure import start_failure_message
from modstore_server.customer_service_delivery_completion import complete_delivery_if_ready
from modstore_server.customer_service_delivery_models import (
    custom_delivery_brief as _custom_delivery_brief,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
    custom_delivery_crm,
    custom_delivery_evidence,
    custom_delivery_pricing_mode,
    delivery_snapshot_matches,
)
from modstore_server.customer_service_tools import audit, json_dumps
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import RECOVERABLE_ERRORS


async def _start_custom_delivery_run(
    *,
    user_id: int,
    evidence: dict[str, Any],
    attempt: int,
    rework_note: str = "",
    ticket_id: int = 0,
    session_id: str = "",
) -> dict[str, Any]:
    blockers = custom_delivery_commerce_blockers(evidence)
    if blockers:
        raise ValueError(f"商务交付条件未完成：{'、'.join(blockers)}")
    session_options: dict[str, Any] = {"session_id": session_id} if session_id else {}
    if evidence.get("source_mode") == "versioned_main":
        from modstore_server.customer_delivery_versioned import start_versioned_main_run

        return await start_versioned_main_run(
            user_id=user_id,
            ticket_id=ticket_id,
            evidence=evidence,
            attempt=attempt,
            **session_options,
        )
    from modstore_server.workbench_api import start_workbench_session_for_user

    kind = str(evidence.get("kind") or "").strip()
    payload: dict[str, Any] = {
        "intent": "employee" if kind == "employee" else "mod",
        "brief": _custom_delivery_brief(evidence, rework_note),
        "suggested_mod_id": str(evidence.get("suggested_id") or "").strip() or None,
        "replace": False,
        "generate_full_suite": kind == "bundle",
        "generate_frontend": kind in {"module", "bundle"},
        "employee_target": "pack_plus_workflow",
        "embed_script_workflow": kind == "employee",
    }
    started = await start_workbench_session_for_user(
        int(user_id),
        payload,
        delivery_context={"ticket_id": ticket_id, "evidence": evidence} if ticket_id else None,
        **session_options,
    )
    return {
        "kind": kind,
        "attempt": int(attempt),
        "session_id": str(started.get("session_id") or ""),
        "status": str(started.get("status") or "running"),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _ticket_revision(ticket: CustomerServiceTicket) -> dict[str, Any]:
    return {
        name: getattr(ticket, name)
        for name in ("id", "user_id", "lock_version", "evidence_json", "status")
    }


def _save_delivery_evidence(
    db: Session,
    ticket: CustomerServiceTicket,
    evidence: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
) -> bool:
    """Save only the ticket version read by this caller, including legacy writers."""
    before = expected if expected is not None else _ticket_revision(ticket)
    version = int(before["lock_version"] or 0)
    with db.no_autoflush:
        complete_delivery_if_ready(ticket, evidence)
        changed = (
            db.query(CustomerServiceTicket)
            .filter_by(**before)
            .update(
                {
                    "evidence_json": json_dumps(evidence),
                    "lock_version": version + 1,
                    "updated_at": datetime.now(UTC),
                    "status": ticket.status,
                    "decision_status": ticket.decision_status,
                    "closed_at": ticket.closed_at,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            db.rollback()
        db.refresh(ticket)
    return changed == 1


def _paid_delivery_generation(ticket: CustomerServiceTicket, evidence: dict[str, Any]) -> str:
    crm = custom_delivery_crm(evidence)
    identity = {
        "ticket_id": ticket.id,
        "owner_user_id": ticket.user_id,
        "attempt": 1,
        "quote": crm["quote"],
        "payment": {
            name: crm["payment"].get(name)
            for name in ("reference", "amount_paid", "currency", "status")
        },
        "request": {
            name: evidence.get(name)
            for name in (
                "kind",
                "title",
                "requirements",
                "acceptance_criteria",
                "suggested_id",
                "source_mode",
            )
        },
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def _payment_covers_quote(evidence: dict[str, Any]) -> bool:
    crm = custom_delivery_crm(evidence)
    try:
        paid, quote = float(crm["payment"].get("amount_paid") or 0), float(
            crm["quote"].get("amount") or 0
        )
    except (TypeError, ValueError):
        return False
    return math.isfinite(paid) and math.isfinite(quote) and 0 < quote <= paid


async def recover_paid_delivery_start(db: Session, ticket: CustomerServiceTicket) -> bool:
    """An uncertain dispatch may only recover its original owner-bound receipt."""
    evidence = custom_delivery_evidence(ticket)
    generation = str(evidence.get("delivery_generation") or "")
    if (
        not generation
        or custom_delivery_pricing_mode(evidence) != "post_delivery_addon"
        or custom_delivery_crm(evidence)["payment"].get("status") != "paid"
        or any(isinstance(row, dict) for row in evidence.get("runs", []))
        or generation != _paid_delivery_generation(ticket, evidence)
        or not _payment_covers_quote(evidence)
    ):
        return False
    from modstore_server.workbench_delivery_bridge import get_workbench_session_snapshot

    try:
        snapshot = await get_workbench_session_snapshot(generation, int(ticket.user_id))
    except RECOVERABLE_ERRORS:
        return False
    if not snapshot or not delivery_snapshot_matches(snapshot, ticket, generation):
        return False
    # Older unrelated workbench snapshots without a ticket binding are not
    # evidence that this reserved production attempt reached its owner.
    if snapshot.get("ticket_id") != ticket.id and not isinstance(
        snapshot.get("source_scope"), dict
    ):
        return False
    evidence["runs"] = [
        {
            "kind": str(evidence.get("kind") or ""),
            "attempt": 1,
            "session_id": generation,
            "status": str(snapshot.get("status") or "running"),
            "created_at": datetime.now(UTC).isoformat(),
        }
    ]
    evidence.pop("start_error", None)
    return _save_delivery_evidence(db, ticket, evidence)


async def persist_delivery_update(
    db: Session,
    ticket: CustomerServiceTicket,
    evidence: dict[str, Any],
    *,
    event_type: str,
    detail: dict[str, Any],
    operation: str,
    actor: User | None = None,
    actor_type: str = "system",
) -> bool:
    """Commit paid terms and one SQL claim before admitting native production."""
    before = custom_delivery_evidence(ticket)
    pending = str(before.get("delivery_generation") or "")
    if pending and not any(
        isinstance(row, dict) and row.get("session_id") == pending for row in before.get("runs", [])
    ):
        # Preserve the only identity that can recover an uncertain native start.
        # Assignment/contract updates do not change this frozen purchase scope.
        if _paid_delivery_generation(ticket, evidence) != pending:
            return False
    claim = (
        custom_delivery_pricing_mode(evidence) == "post_delivery_addon"
        and not custom_delivery_commerce_blockers(evidence)
        and _payment_covers_quote(evidence)
        and not any(isinstance(row, dict) for row in evidence.get("runs", []))
        and not evidence.get("delivery_generation")
    )
    generation = ""
    if claim:
        generation = _paid_delivery_generation(ticket, evidence)
        evidence["delivery_generation"] = generation
    if not _save_delivery_evidence(db, ticket, evidence):
        return False
    claimed_revision = _ticket_revision(ticket)
    audit(
        db,
        event_type=event_type,
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor=actor,
        actor_type=actor_type,
        detail=detail,
    )
    # A process loss or lost native response after this commit must retain the
    # original generation. No request may infer "not started" from empty runs.
    db.commit()
    db.refresh(ticket)
    if not claim:
        await recover_paid_delivery_start(db, ticket)
        return True
    if _ticket_revision(ticket) != claimed_revision:
        return True
    try:
        run = await _start_custom_delivery_run(
            ticket_id=int(claimed_revision["id"]),
            user_id=int(claimed_revision["user_id"]),
            evidence=evidence,
            attempt=1,
            session_id=generation,
        )
        if run.get("session_id") != generation:
            raise ValueError("Native delivery returned another generation")
        evidence["runs"] = [run]
        evidence.pop("start_error", None)
    except RECOVERABLE_ERRORS as exc:
        evidence["start_error"] = start_failure_message(
            operation, type(exc).__name__, unconfirmed=True
        )
    _save_delivery_evidence(db, ticket, evidence, expected=claimed_revision)
    return True
