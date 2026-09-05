# mypy: disable-error-code="arg-type, assignment"
"""Transactional customer issue intake into the existing ticket and incident bus."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.eventing import db_outbox
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import BOUNDARY_ERRORS

INTAKE_EVENT = "ops.intake.customer_ticket"


def record_dispatch_failure(payload: dict[str, Any], error: str) -> None:
    """Persist retryable dispatch failure against the original authenticated lineage."""
    from modstore_server.models import get_session_factory

    ticket_id = int(payload.get("ticket_id") or 0)
    owner_id = int(payload.get("user_id") or payload.get("tenant_id") or 0)
    if not ticket_id or not owner_id:
        return
    with get_session_factory()() as db:
        ticket = db.query(CustomerServiceTicket).filter_by(id=ticket_id, user_id=owner_id).first()
        if ticket is None or ticket.status in {"resolved", "closed"}:
            return
        evidence = json_loads(ticket.evidence_json, {})
        resolution = issue_resolution(ticket, evidence)
        resolution.update(
            state="dispatch_failed",
            last_error=str(error)[:1000],
            updated_at=datetime.now(UTC).isoformat(),
        )
        evidence["resolution"] = resolution
        ticket.evidence_json = json_dumps(evidence)
        ticket.status = "processing"
        ticket.closed_at = None
        db.commit()


def enqueue_issue(
    db: Session, ticket: CustomerServiceTicket, *, revision: str = "", private_factory: bool = False
) -> str:
    evidence = json_loads(ticket.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    resolution = issue_resolution(ticket, evidence)
    evidence["resolution"] = resolution
    ticket.evidence_json = json_dumps(evidence)
    revision = (
        revision
        or hashlib.sha256(str(ticket.summary or ticket.title or "").encode()).hexdigest()[:24]
    )
    key = f"{ticket.ticket_no}:{revision}"
    domain = str(evidence.get("issue_domain") or "")
    text = f"{ticket.title} {ticket.summary}".lower()
    scope = "modstore" if resolution["route"] == "private_mod" else "fhd"
    if domain in {"website", "官网"} or any(
        word in text for word in ("website", "官网", "首页", "landing", "xiu-ci", "xiuci")
    ):
        scope = "website"
    elif domain in {"desktop", "android", "fhd", "modstore"}:
        scope = domain
    payload = {
        "ticket_id": int(ticket.id),
        "ticket_no": ticket.ticket_no,
        "user_id": int(ticket.user_id),
        "tenant_id": int(ticket.user_id),
        "session_id": int(ticket.session_id),
        "title": ticket.title,
        "summary": str(ticket.summary or "")[:1500],
        "intent": ticket.intent,
        "issue_domain": evidence.get("issue_domain", "platform"),
        "source": "customer_ticket",
        "source_ref": resolution["source_ref"],
        "intake_source": evidence.get("source", ""),
        "scope": scope,
        "user_confirmed_domain": evidence.get("user_confirmed_domain") or domain,
        "resolution": {
            key: value
            for key, value in resolution.items()
            if key not in {"original_request", "team"}
        },
        "target_mod_id": resolution.get("target_mod_id", ""),
        "installed_version": evidence.get("installed_version", ""),
    }
    if ticket.intent == "custom_delivery":
        payload["delivery_managed_by"] = "custom_delivery"
    if private_factory:
        payload["intake_source"] = "private_mod_rework"
    if evidence.get("shared_core_prerequisite") and not evidence.get(
        "shared_core_prerequisite_release"
    ):
        payload.update(intake_source="private_mod_prerequisite", scope="fhd")
        payload["resolution"] = {**payload["resolution"], "route": "shared_core"}
        payload["summary"] = str(evidence["shared_core_prerequisite"])[:1500]
    db_outbox.enqueue(db, INTAKE_EVENT, key, payload, producer="customer-issue-intake")
    return f"{INTAKE_EVENT}:{key}"


def dispatch_issue_event(event: dict[str, Any]) -> dict[str, Any]:
    """Outbox consumer; a retry can never create a second incident for the same input."""
    from modstore_server.duty_workforce_contracts import (
        enrich_customer_ticket_publish_payload,
    )
    from modstore_server.incident_bus import publish

    raw_payload = event.get("data")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    event_id = str(event.get("id") or "")
    if not event_id or not payload.get("ticket_id") or not payload.get("user_id"):
        return {"ok": False, "message": "customer issue event missing lineage"}
    if payload.get("intake_source") == "private_mod_rework":
        from modstore_server.customer_issue_private_factory import (
            dispatch_private_rework,
        )

        return dispatch_private_rework(event_id, payload)
    fingerprint = hashlib.sha256(event_id.encode()).hexdigest()
    try:
        published = publish(
            INTAKE_EVENT,
            enrich_customer_ticket_publish_payload(payload),
            source="customer-issue-intake",
            fingerprint=fingerprint,
            dedupe_minutes=52_560_000,
        )
    except BOUNDARY_ERRORS as exc:
        record_dispatch_failure(payload, str(exc))
        raise
    return {"ok": True, "published": bool(published), "event_id": event_id}


def dispatch_pending_issue_events(ticket_id: int) -> None:
    """Wake the existing durable outbox for this ticket; the worker retries failures."""
    for record in db_outbox.fetch_pending(limit=100):
        if (
            record.event_name != INTAKE_EVENT
            or int(record.payload.get("ticket_id") or 0) != ticket_id
        ):
            continue
        try:
            result = dispatch_issue_event(record.to_envelope())
        except BOUNDARY_ERRORS as exc:
            db_outbox.mark_failed(record.id, str(exc)[:500], terminal=False)
        else:
            if result.get("ok"):
                db_outbox.mark_dispatched(record.id)
            else:
                db_outbox.mark_failed(
                    record.id,
                    str(result.get("message") or "dispatch failed"),
                    terminal=False,
                )


def request_identity(owner_id: int, source: str, source_ref: str) -> str:
    raw = json.dumps([int(owner_id), source, source_ref], ensure_ascii=False)
    return "CI" + hashlib.sha256(raw.encode()).hexdigest()[:48]
