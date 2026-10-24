# mypy: disable-error-code="arg-type, assignment"
"""Transactional customer issue intake into the existing ticket and incident bus."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.eventing import db_outbox
from modstore_server.models import IncidentClaim, IncidentEvent, IncidentInbox
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
        if ticket is None or ticket.status in {"resolved", "closed", "expired"}:
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
    db: Session,
    ticket: CustomerServiceTicket,
    *,
    revision: str = "",
    private_factory: bool = False,
    support_report: dict[str, Any] | None = None,
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
    summary = str(ticket.summary or "")
    if resolution.get("state") == "reopened" and resolution.get("reopen_note"):
        summary = f"客户重开说明：{resolution['reopen_note']}\n原问题：{summary}"
    payload = {
        "ticket_id": int(ticket.id),
        "ticket_no": ticket.ticket_no,
        "user_id": int(ticket.user_id),
        "tenant_id": int(ticket.user_id),
        "session_id": int(ticket.session_id),
        "title": ticket.title,
        "summary": summary[:1500],
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
        "work_order_id": evidence.get("work_order_id", ""),
        "support_bundle_sha256": evidence.get("support_bundle_sha256", ""),
        "support_bundle_base64": evidence.get("support_bundle_base64", ""),
        "customer_instance_id": evidence.get("customer_instance_id", ""),
        "product_version": evidence.get("product_version", ""),
        "git_sha": evidence.get("git_sha", ""),
    }
    if support_report:
        payload.update(support_report)
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
    """Consume original lineage; intact incidents and private runs stay idempotent."""
    from modstore_server.duty_workforce_contracts import enrich_customer_ticket_publish_payload
    from modstore_server.incident_bus import publish

    raw_payload = event.get("data")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    event_id = str(event.get("id") or "")
    if not event_id or not payload.get("ticket_id") or not payload.get("user_id"):
        return {"ok": False, "message": "customer issue event missing lineage"}
    with db_outbox.get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, int(payload["ticket_id"]))
        # Fail closed: forged or orphaned lineage must never reach incident publish.
        if ticket is None:
            return {"ok": False, "message": "customer issue ticket missing"}
        if int(ticket.user_id) != int(payload["user_id"]):
            return {"ok": False, "message": "customer issue ownership mismatch"}
        if ticket.status == "expired":
            return {"ok": True, "skipped": True, "reason": "ticket_expired"}
        from modstore_server.customer_issue_shared_repairs import active_shared_repair

        if active_shared_repair(db, ticket):
            return {"ok": True, "skipped": True, "reason": "shared_repair_reused"}
    if payload.get("intake_source") == "private_mod_rework":
        from modstore_server.customer_issue_private_factory import dispatch_private_rework

        return dispatch_private_rework(event_id, payload)
    fingerprint = hashlib.sha256(event_id.encode()).hexdigest()
    try:
        published = publish(
            INTAKE_EVENT,
            enrich_customer_ticket_publish_payload(payload),
            source="customer-issue-intake",
            fingerprint=fingerprint,
            dedupe_minutes=52_560_000,
            inbox_key=event_id,
        )
    except BOUNDARY_ERRORS as exc:
        record_dispatch_failure(payload, str(exc))
        raise
    return {"ok": True, "published": bool(published), "event_id": event_id}


def dispatch_pending_issue_events(ticket_id: int) -> None:
    """Retry original intake while retaining dispatched outbox evidence."""
    with db_outbox.get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, ticket_id)
        if ticket is None or ticket.status in {"resolved", "closed", "expired"}:
            return
        prefix, owner_id = f"{ticket.ticket_no}:", int(ticket.user_id)
    for record in db_outbox.fetch_pending(
        limit=100, aggregate_prefix=prefix, include_dispatched=True
    ):
        if (
            record.event_name != INTAKE_EVENT
            or int(record.payload.get("ticket_id") or 0) != ticket_id
            or int(record.payload.get("user_id") or 0) != owner_id
            or (
                record.status == "dispatched"
                and record.payload.get("intake_source") != "customer_feedback"
            )
        ):
            continue
        token = db_outbox.claim_record(record.id) if record.status != "dispatched" else ""
        if record.status != "dispatched" and not token:
            continue
        try:
            result = dispatch_issue_event(record.to_envelope())
        except BOUNDARY_ERRORS as exc:
            if record.status == "dispatched":
                raise
            db_outbox.mark_failed(record.id, str(exc)[:500], terminal=False, claim_token=token)
        else:
            if record.status == "dispatched":
                continue
            if result.get("ok"):
                db_outbox.mark_dispatched(record.id, claim_token=token)
            else:
                db_outbox.mark_failed(
                    record.id,
                    str(result.get("message") or "dispatch failed"),
                    terminal=False,
                    claim_token=token,
                )


def request_identity(owner_id: int, source: str, source_ref: str) -> str:
    raw = json.dumps([int(owner_id), source, source_ref], ensure_ascii=False)
    return "CI" + hashlib.sha256(raw.encode()).hexdigest()[:48]


def _persist_incident(event_type, payload, source, fp, dedupe_minutes, inbox_key):
    from modstore_server import incident_bus as bus

    get_session_factory = bus.get_session_factory
    _incident_payload = bus._incident_payload
    key = (
        hashlib.sha256(f"{event_type}:{source}:{inbox_key}".encode()).hexdigest()
        if inbox_key
        else ""
    )
    with get_session_factory()() as session:
        existing = session.get(IncidentInbox, key) if key else None
        if existing is not None:
            return int(existing.incident_event_id), False
        cutoff = datetime.now(UTC) - timedelta(minutes=max(0, int(dedupe_minutes)))
        old = (
            session.query(IncidentEvent)
            .filter(
                IncidentEvent.event_type == event_type,
                IncidentEvent.fingerprint == fp,
                IncidentEvent.created_at >= cutoff,
            )
            .order_by(IncidentEvent.id.desc())
            .first()
        )
        create = True
        if old:
            try:
                previous = _incident_payload(old)
            except ValueError:
                previous = {}
            create = (
                event_type == "ops.intake.customer_ticket"
                and source == "customer-issue-intake"
                and old.source == source
                and not previous.get("ticket_id")
                and payload.get("ticket_id")
            )
            if create:
                payload = {
                    **payload,
                    "_incident_replay": {
                        "original_event_id": int(old.id),
                        "original_payload_sha256": hashlib.sha256(
                            (old.payload_json or "").encode()
                        ).hexdigest(),
                    },
                }
        try:
            with session.begin_nested():
                ev = (
                    IncidentEvent(
                        event_type=event_type,
                        source=source,
                        payload_json=json.dumps(payload, ensure_ascii=False),
                        fingerprint=fp,
                        dispatched_count=0,
                    )
                    if create
                    else old
                )
                if create:
                    session.add(ev)
                    session.flush()
                if key:
                    session.add(IncidentInbox(inbox_key=key, incident_event_id=int(ev.id)))
                    session.flush()
            eid = int(ev.id)
            session.commit()
            return eid, bool(create)
        except IntegrityError:
            # The incident and inbox insert share the savepoint: the loser cannot
            # leave behind a second incident or poison the caller's transaction.
            existing = session.get(IncidentInbox, key) if key else None
            if existing is None:
                raise
            return int(existing.incident_event_id), False


def recover_pending_incidents(*, limit: int = 20) -> int:
    """Recover committed-but-unscheduled intake and reconcile interrupted dispatches."""
    from modstore_server import incident_bus as bus
    from modstore_server.node_coordinator import _database_time

    get_session_factory = bus.get_session_factory

    with get_session_factory()() as session:
        now = _database_time(session)
        rows = (
            session.query(IncidentEvent.id)
            .join(IncidentInbox, IncidentInbox.incident_event_id == IncidentEvent.id)
            .outerjoin(IncidentClaim, IncidentClaim.event_id == IncidentEvent.id)
            .filter(
                or_(
                    IncidentClaim.event_id.is_(None),
                    IncidentClaim.dispatch_state == "pending",
                    (IncidentClaim.dispatch_state.in_(["dispatching", "unknown"]))
                    & (IncidentClaim.lease_until <= now),
                ),
            )
            .order_by(IncidentEvent.id)
            .limit(max(1, int(limit)))
            .all()
        )
    for (event_id,) in rows:
        bus._dispatch_incident(int(event_id))
    return len(rows)
