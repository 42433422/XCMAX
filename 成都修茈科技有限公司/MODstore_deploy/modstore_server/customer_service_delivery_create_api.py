# mypy: disable-error-code="arg-type, assignment, index, union-attr"
"""客户定制交付创建与交付前免费变更 API。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.account_license_plans import account_license_plan
from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import _schedule_customer_ticket_incident
from modstore_server.customer_service_delivery_api import (
    _custom_delivery_payload,
    _start_custom_delivery_run,
)
from modstore_server.customer_service_delivery_models import (
    CustomDeliveryCreateBody,
    custom_delivery_crm,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_evidence as _custom_delivery_evidence,
)
from modstore_server.customer_service_orchestrator import (
    audit,
    enqueue_customer_service_event,
)
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import Entitlement, User, UserPlan
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter()
_get_current_user = get_current_user


def _active_permanent_purchase(db: Session, user_id: int) -> dict[str, Any] | None:
    plan_rows = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == int(user_id), UserPlan.is_active.is_(True))
        .order_by(UserPlan.id.desc())
        .all()
    )
    for plan_row in plan_rows:
        plan_id = str(plan_row.plan_id or "")
        plan = account_license_plan(plan_id) or {}
        if str(plan.get("license_type") or "") != "permanent":
            continue
        entitlements = (
            db.query(Entitlement)
            .filter(
                Entitlement.user_id == int(user_id),
                Entitlement.entitlement_type == "plan",
                Entitlement.is_active.is_(True),
            )
            .order_by(Entitlement.id.desc())
            .all()
        )
        entitlement = next(
            (
                row
                for row in entitlements
                if str(row.source_order_id or "").strip()
                and _entitlement_matches_plan(row, plan_id)
            ),
            None,
        )
        purchase_key = (
            f"entitlement:{int(entitlement.id)}"
            if entitlement is not None
            else f"user-plan:{int(plan_row.id)}"
        )
        return {
            "purchase_key": purchase_key,
            "user_plan_id": int(plan_row.id),
            "entitlement_id": int(entitlement.id) if entitlement is not None else None,
            "source_order_id": (
                str(entitlement.source_order_id or "") if entitlement is not None else ""
            ),
            "plan_id": plan_id,
            "plan_title": str(plan.get("title") or plan_id),
            "account_tier": str(plan.get("account_tier") or "normal"),
        }
    return None


def _entitlement_matches_plan(entitlement: Entitlement, plan_id: str) -> bool:
    try:
        metadata = json.loads(str(entitlement.metadata_json or "{}"))
    except (TypeError, ValueError):
        return False
    return isinstance(metadata, dict) and str(metadata.get("plan_id") or "") == plan_id


@router.post("/custom-deliveries")
async def create_custom_delivery(
    body: CustomDeliveryCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    purchase = _active_permanent_purchase(db, int(user.id))
    if purchase is None:
        raise HTTPException(403, "定制交付仅对已购买四个永久账户档位的客户开放")
    prior_tickets = (
        db.query(CustomerServiceTicket)
        .filter(
            CustomerServiceTicket.user_id == int(user.id),
            CustomerServiceTicket.intent == "custom_delivery",
        )
        .order_by(CustomerServiceTicket.id.asc())
        .all()
    )
    # The purchased account (user_id) is the delivery SSOT. Plan and entitlement
    # rows may be replaced by a tier upgrade or commerce reconciliation; that must
    # not grant the same account a second included initial delivery.
    account_initial_tickets: list[CustomerServiceTicket] = []
    legacy_delivered = False
    for prior_ticket in prior_tickets:
        prior_evidence = _custom_delivery_evidence(prior_ticket)
        prior_terms = prior_evidence.get("delivery_terms")
        prior_terms = prior_terms if isinstance(prior_terms, dict) else {}
        if str(prior_terms.get("pricing_mode") or "") == "initial_included":
            account_initial_tickets.append(prior_ticket)
        if str(prior_ticket.status or "") in {"resolved", "closed", "done"} and not str(
            prior_terms.get("purchase_key") or ""
        ):
            legacy_delivered = True

    active_initial = next(
        (
            ticket
            for ticket in account_initial_tickets
            if str(ticket.status or "") not in {"resolved", "closed", "done"}
        ),
        None,
    )
    now_iso = datetime.now(UTC).isoformat()
    if active_initial is not None:
        active_evidence = _custom_delivery_evidence(active_initial)
        previous_kind = str(active_evidence.get("kind") or "")
        if previous_kind and previous_kind != body.kind:
            active_evidence["kind"] = "bundle"
        change = {
            "title": body.title.strip(),
            "requirements": body.requirements.strip(),
            "acceptance_criteria": body.acceptance_criteria.strip(),
            "suggested_id": str(body.suggested_id or "").strip(),
            "submitted_at": now_iso,
            "included_in_purchase": True,
        }
        changes = [
            row for row in active_evidence.get("pre_delivery_changes", []) if isinstance(row, dict)
        ]
        changes.append(change)
        active_evidence["pre_delivery_changes"] = changes[-50:]
        active_evidence["requirements"] = (
            f"{str(active_evidence.get('requirements') or '').strip()}\n\n"
            f"【交付前免费追加】{change['title']}\n{change['requirements']}"
        ).strip()
        active_evidence["acceptance_criteria"] = (
            f"{str(active_evidence.get('acceptance_criteria') or '').strip()}\n\n"
            f"【追加验收标准】{change['acceptance_criteria']}"
        ).strip()
        active_evidence["acceptance_status"] = "pending"
        for key in (
            "accepted_at",
            "accepted_by_user_id",
            "acceptance_actor",
            "internal_approved_at",
            "delivery_artifacts",
            "download_grants",
        ):
            active_evidence.pop(key, None)
        runs = [row for row in active_evidence.get("runs", []) if isinstance(row, dict)]
        try:
            run = await _start_custom_delivery_run(
                user_id=int(user.id),
                evidence=active_evidence,
                attempt=len(runs) + 1,
                rework_note=(
                    f"交付前免费追加需求：{change['title']}\n"
                    f"{change['requirements']}\n追加验收：{change['acceptance_criteria']}"
                ),
            )
            active_evidence["runs"] = [*runs, run]
            active_evidence.pop("start_error", None)
        except RECOVERABLE_ERRORS as exc:
            logger.exception(
                "pre-delivery included revision start failed ticket=%s",
                active_initial.ticket_no,
            )
            active_evidence["start_error"] = str(exc)[:1000]
        active_initial.evidence_json = json_dumps(active_evidence)
        active_initial.status = "processing"
        active_initial.decision_status = "pending"
        active_initial.closed_at = None
        active_initial.updated_at = datetime.now(UTC)
        db.add(
            CustomerServiceMessage(
                session_id=int(active_initial.session_id),
                ticket_id=int(active_initial.id),
                user_id=int(user.id),
                role="user",
                content=(
                    f"【交付前免费追加需求】{change['title']}\n"
                    f"{change['requirements']}\n验收标准：{change['acceptance_criteria']}"
                ),
                payload_json=json_dumps({"delivery_change": change, "included_in_purchase": True}),
            )
        )
        audit(
            db,
            event_type="custom_delivery_pre_delivery_change_added",
            session_id=int(active_initial.session_id),
            ticket_id=int(active_initial.id),
            actor=user,
            actor_type="user",
            detail={
                "included_in_purchase": True,
                "source": "desktop_private_delivery",
                "change": change,
            },
        )
        enqueue_customer_service_event(
            db,
            event_type="customer_service.custom_delivery_pre_delivery_change_added",
            aggregate_id=str(active_initial.ticket_no),
            payload={
                "ticket_id": int(active_initial.id),
                "ticket_no": str(active_initial.ticket_no),
                "user_id": int(user.id),
                "included_in_purchase": True,
            },
        )
        db.commit()
        db.refresh(active_initial)
        return await _custom_delivery_payload(active_initial)
    initial_delivery_consumed = any(
        str(ticket.status or "") in {"resolved", "closed", "done"}
        for ticket in account_initial_tickets
    )
    pricing_mode = (
        "post_delivery_addon"
        if initial_delivery_consumed or legacy_delivered
        else "initial_included"
    )
    crm = custom_delivery_crm({})
    crm["assignment"] = {
        "status": "assigned",
        "owner_name": "生产员工",
        "assigned_at": now_iso,
        "note": "按购买账户交付规则自动指派",
    }
    crm["contract"] = {
        "status": "waived",
        "note": "沿用购买账户与原项目约定",
        "updated_at": now_iso,
    }
    if pricing_mode == "initial_included":
        crm["quote"] = {
            "status": "waived",
            "amount": 0,
            "currency": "CNY",
            "note": "首次交付前开发已包含在购买账户内",
            "updated_at": now_iso,
        }
        crm["payment"] = {
            "status": "waived",
            "amount_paid": 0,
            "currency": "CNY",
            "note": "首次交付沿用永久账户购买款",
            "updated_at": now_iso,
        }
    evidence: dict[str, Any] = {
        "schema_version": 3,
        "delivery_managed_by": "custom_delivery",
        "kind": body.kind,
        "title": body.title.strip(),
        "requirements": body.requirements.strip(),
        "acceptance_criteria": body.acceptance_criteria.strip(),
        "suggested_id": str(body.suggested_id or "").strip(),
        "acceptance_status": "pending",
        "runs": [],
        "install_receipts": [],
        "crm": crm,
        "delivery_terms": {
            "pricing_mode": pricing_mode,
            "initial_development_free": pricing_mode == "initial_included",
            "requires_new_quote_and_payment": pricing_mode == "post_delivery_addon",
            "classified_at": now_iso,
            **purchase,
        },
    }
    session = CustomerServiceSession(
        user_id=int(user.id),
        channel="desktop_private_delivery",
        status="open",
        title=body.title.strip(),
        intent="custom_delivery",
        context_json=json_dumps({"source": "desktop_private_delivery", "kind": body.kind}),
        last_message=body.requirements.strip()[:2000],
    )
    db.add(session)
    db.flush()
    ticket = CustomerServiceTicket(
        session_id=int(session.id),
        user_id=int(user.id),
        ticket_no=(
            f"CD{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            f"{int(user.id):04d}{uuid.uuid4().hex[:6].upper()}"
        ),
        title=body.title.strip(),
        intent="custom_delivery",
        subject_type={
            "module": "custom_module",
            "employee": "custom_employee",
            "bundle": "custom_bundle",
        }[body.kind],
        status="processing",
        priority="normal",
        evidence_json=json_dumps(evidence),
        summary=body.requirements.strip()[:2000],
        decision_status="pending",
        automation_level="assisted",
    )
    db.add(ticket)
    db.flush()
    db.add(
        CustomerServiceMessage(
            session_id=int(session.id),
            ticket_id=int(ticket.id),
            user_id=int(user.id),
            role="user",
            content=body.requirements.strip(),
            payload_json=json_dumps({"acceptance_criteria": body.acceptance_criteria.strip()}),
        )
    )
    audit(
        db,
        event_type="custom_delivery_created",
        session_id=int(session.id),
        ticket_id=int(ticket.id),
        actor=user,
        detail={"kind": body.kind, "source": "desktop_private_delivery"},
    )
    enqueue_customer_service_event(
        db,
        "customer_service.custom_delivery_created",
        ticket.ticket_no,
        {"ticket_id": int(ticket.id), "ticket_no": ticket.ticket_no, "kind": body.kind},
    )
    db.commit()

    if pricing_mode == "initial_included":
        try:
            run = await _start_custom_delivery_run(
                user_id=int(user.id), evidence=evidence, attempt=1
            )
            evidence["runs"] = [run]
        except RECOVERABLE_ERRORS as exc:
            logger.exception("custom delivery production start failed ticket=%s", ticket.ticket_no)
            evidence["start_error"] = str(exc)[:1000]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(ticket)

    _schedule_customer_ticket_incident(
        {
            "subject_id": ticket.ticket_no,
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "title": ticket.title,
            "intent": "custom_delivery",
            "issue_domain": "custom",
            "status": ticket.status,
            "summary": ticket.summary,
            "user_id": int(user.id),
            "session_id": int(session.id),
            "scope": "modstore",
            "source": "customer_ticket",
            "delivery_managed_by": "custom_delivery",
            "raw": {"title": ticket.title, "body": ticket.summary, "kind": body.kind},
        }
    )
    return await _custom_delivery_payload(ticket)
