"""Thin operations-line consumers over the existing SQL/commerce authorities.

The original intake, work-order, payment, delivery and customer receipt APIs own
the business writes. This adapter only creates an idempotent requirement in the
existing work-order service and reads back those authorities. It never sends a
customer message, creates a payment, signs acceptance or buys external resources.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from modstore_server.customer_value_classification import (
    classify_payment_order,
    parse_datetime,
    payment_amount_cents,
)
from modstore_server.customer_value_lifecycle import _receipt_evidence
from modstore_server.db.db_base import get_session_factory
from modstore_server.db.identity import LandingContactSubmission, User
from modstore_server.models import CustomerValueReceipt, Invoice, ReconciliationReport
from modstore_server.models_cs import CustomerServiceTicket

BUSINESS_STEPS = frozenset({"O1", "O2", "O3", "O4", "O5", "O6", "O8", "O9", "O10"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BusinessScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    landing_contact_id: int | None = Field(default=None, gt=0)
    ticket_id: int | None = Field(default=None, gt=0)
    customer_user_id: int | None = Field(default=None, gt=0)
    order_no: str = Field(default="", max_length=96)
    customer_goal_id: str = Field(default="", max_length=128)
    artifact_id: str = Field(default="", max_length=256)
    artifact_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    invoice_id: int | None = Field(default=None, gt=0)
    reconciliation_report_id: int | None = Field(default=None, gt=0)


class MissingEvidence(ValueError):
    pass


def _require(condition: Any, reason: str) -> None:
    if not condition:
        raise MissingEvidence(reason)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _lead(db, scope):
    lead = db.get(LandingContactSubmission, scope.landing_contact_id)
    _require(lead is not None, "landing_contact_missing")
    meta = json.loads(lead.meta_json or "{}")
    _require(
        meta.get("privacy_agreed") is True and lead.message.strip(),
        "contact_consent_or_requirement_missing",
    )
    return lead, {
        "source": "landing_contact_submissions",
        "source_id": lead.id,
        "requirements_sha256": _digest(
            [lead.message, lead.company, parse_datetime(lead.created_at).isoformat()]
        ),
        "stage": "prospect",
        "payment_verified": False,
    }


def create_prospect_requirement(db, landing_contact_id: int) -> dict[str, Any]:
    """Reuse the original work-order writer in the intake transaction."""
    from modstore_server.work_order_api import CandidateBody, _create_candidate, _created_facts

    lead, fact = _lead(db, BusinessScope(landing_contact_id=landing_contact_id))
    candidate = _create_candidate(
        db,
        CandidateBody(
            source="landing_contact",
            dedup_key=f"landing-contact:{lead.id}",
            reason="prospect_requirement",
            context={**fact, "requirements": lead.message, "customer_scoped": True},
        ),
    )
    original = _created_facts(db, candidate["wo_id"])[2]
    _require(
        original.get("requirements_sha256") == fact["requirements_sha256"],
        "original_requirement_changed",
    )
    return {**fact, "work_order_id": candidate["wo_id"], "work_order_status": candidate["status"]}


def _ticket(db, scope):
    ticket = db.get(CustomerServiceTicket, scope.ticket_id) if scope.ticket_id else None
    _require(
        not scope.landing_contact_id or ticket is not None, "prospect_customer_binding_missing"
    )
    if scope.ticket_id:
        _require(ticket is not None, "customer_ticket_missing")
        _require(scope.customer_user_id in (None, ticket.user_id), "ticket_customer_mismatch")
        if scope.landing_contact_id:
            evidence = json.loads(ticket.evidence_json or "{}")
            binding = evidence.get("prospect_binding") or {}
            _, lead_fact = _lead(db, scope)
            _require(
                binding.get("landing_contact_id") == scope.landing_contact_id
                and binding.get("customer_user_id") == ticket.user_id
                and binding.get("source") == "authenticated_customer_delivery_request"
                and binding.get("requirements_sha256") == lead_fact["requirements_sha256"],
                "prospect_customer_binding_missing",
            )
    owner_id = ticket.user_id if ticket else scope.customer_user_id
    owner = db.get(User, owner_id) if owner_id else None
    _require(
        owner is not None
        and not owner.is_admin
        and not owner.deleted_at
        and owner.account_state not in {"deleted", "disabled", "suspended", "blocked"},
        "active_customer_identity_missing",
    )
    if ticket:
        _require(ticket.submitter_type == "customer", "customer_origin_ticket_required")
    return ticket, int(owner.id)


def bind_prospect_to_customer(db, user: User, landing_contact_id: int) -> dict[str, Any]:
    """Called only by the original authenticated customer delivery creation API."""
    from modstore_server.auth_service import verified_email_digest

    lead, source = _lead(db, BusinessScope(landing_contact_id=landing_contact_id))
    identity = verified_email_digest(str(user.email or ""))
    _require(
        not user.is_admin
        and bool(user.email)
        and identity == user.verified_email_sha256
        and identity == verified_email_digest(lead.email),
        "prospect_requires_customer_verified_email",
    )
    return {
        "landing_contact_id": lead.id,
        "customer_user_id": int(user.id),
        "requirements_sha256": source["requirements_sha256"],
        "source": "authenticated_customer_delivery_request",
    }


def _order(scope, owner_id, ticket):
    from modstore_server.customer_value_payment_source import load_authoritative_payment_orders

    number = scope.order_no
    if ticket:
        evidence = json.loads(ticket.evidence_json or "{}")
        terms = evidence.get("delivery_terms") or {}
        payment = (evidence.get("crm") or {}).get("payment") or {}
        linked = (
            terms.get("source_order_id")
            if terms.get("pricing_mode") == "initial_included"
            else payment.get("reference")
        )
        _require(linked and number in ("", linked), "ticket_payment_order_mismatch")
        number = str(linked)
    _require(number, "payment_order_identity_missing")
    source = load_authoritative_payment_orders(3650)
    _require(
        source.get("source_available") is True and source.get("source_authoritative") is True,
        "payment_authority_unavailable",
    )
    rows = [row for row in source.get("orders") or [] if isinstance(row, dict)]
    matches = [row for row in rows if str(row.get("out_trade_no") or row.get("order_no")) == number]
    _require(len(matches) == 1, "payment_order_missing_or_ambiguous")
    order = matches[0]
    _require(str(order.get("user_id")) == str(owner_id), "payment_customer_mismatch")
    eligible, reason = classify_payment_order(order)
    _require(eligible, "payment_" + reason)
    _require(
        (parse_datetime(order.get("paid_at")) or datetime.max.replace(tzinfo=UTC))
        <= datetime.now(UTC),
        "payment_time_in_future",
    )
    if ticket and terms.get("pricing_mode") != "initial_included":
        quote = (evidence.get("crm") or {}).get("quote") or {}
        quoted = payment_amount_cents({"total_amount": quote.get("amount")})
        _require(
            quote.get("status") == "accepted"
            and quoted > 0
            and payment_amount_cents(order) >= quoted,
            "original_quote_payment_amount_mismatch",
        )
        if terms.get("pricing_mode") == "post_delivery_addon":
            _require(
                order.get("order_kind") == "custom_delivery", "dedicated_delivery_payment_missing"
            )
    return (
        order,
        rows,
        {
            "source": source["source_owner"],
            "order_no": number,
            "customer_user_id": owner_id,
            "amount_cents": payment_amount_cents(order),
            "payment_sha256": _digest(order),
        },
    )


def _receipts(db, scope, owner_id, number):
    rows = db.scalars(
        select(CustomerValueReceipt)
        .where(
            CustomerValueReceipt.order_no == number,
            CustomerValueReceipt.verification_status == "verified",
            CustomerValueReceipt.environment.in_(("production", "prod")),
            CustomerValueReceipt.occurred_at <= datetime.now(UTC),
        )
        .order_by(CustomerValueReceipt.occurred_at, CustomerValueReceipt.id)
    ).all()
    _require(not any(row.receipt_kind == "refund" for row in rows), "payment_refunded")
    return [
        row
        for row in rows
        if row.customer_ref == f"paid-user:{owner_id}"
        and row.customer_goal_id == scope.customer_goal_id
        and row.currency == "CNY"
    ]


def _value_fact(db, step_id, scope, owner_id, number):
    _require(scope.customer_goal_id, "customer_goal_identity_missing")
    rows = _receipts(db, scope, owner_id, number)
    goals = [
        row
        for row in rows
        if row.receipt_kind == "goal" and _receipt_evidence(row).get("customer_confirmed") is True
    ]
    _require(goals, "customer_confirmed_goal_missing")
    goal = goals[-1]
    if step_id == "O2":
        return {"source": "customer_value_receipts", "receipt_ids": [goal.receipt_id]}
    deliveries = [
        row
        for row in rows
        if row.receipt_kind == "delivery"
        and row.occurred_at >= goal.occurred_at
        and row.artifact_id == scope.artifact_id
        and _receipt_evidence(row).get("artifact_sha256") == scope.artifact_sha256
    ]
    _require(
        scope.artifact_id and _SHA256.fullmatch(scope.artifact_sha256) and deliveries,
        "exact_customer_delivery_missing",
    )
    delivery = deliveries[-1]
    chosen = [goal, delivery]
    if step_id in {"O6", "O7", "O8"}:
        usage = [
            row
            for row in rows
            if row.receipt_kind == "first_use"
            and row.occurred_at >= delivery.occurred_at
            and row.artifact_id == scope.artifact_id
            and _receipt_evidence(row).get("artifact_sha256") == scope.artifact_sha256
            and _receipt_evidence(row).get("success") is True
            and _receipt_evidence(row).get("business_output") is True
        ]
        _require(usage, "customer_business_usage_missing")
        chosen.append(usage[-1])
    if step_id in {"O7", "O8"}:
        agreed = _receipt_evidence(goal)
        outcomes = []
        for row in rows:
            evidence = _receipt_evidence(row)
            if (
                row.receipt_kind != "outcome"
                or row.occurred_at < chosen[-1].occurred_at
                or row.artifact_id != scope.artifact_id
                or evidence.get("artifact_sha256") != scope.artifact_sha256
                or any(
                    evidence.get(key) != agreed.get(key)
                    for key in ("baseline", "target", "comparison", "unit", "measurement_window")
                )
            ):
                continue
            measured, target = evidence.get("measured_value"), evidence.get("target")
            if all(
                type(value) in (int, float) and math.isfinite(value)
                for value in (measured, target, evidence.get("baseline"))
            ):
                if (agreed.get("comparison") == "ge" and measured >= target) or (
                    agreed.get("comparison") == "le" and measured <= target
                ):
                    outcomes.append(row)
        _require(outcomes, "agreed_business_outcome_missing")
        chosen.append(outcomes[-1])
    if step_id == "O8":
        accepted = [
            row
            for row in rows
            if row.receipt_kind == "acceptance"
            and row.occurred_at >= chosen[-1].occurred_at
            and row.artifact_id == scope.artifact_id
            and _receipt_evidence(row).get("artifact_sha256") == scope.artifact_sha256
            and _receipt_evidence(row).get("customer_confirmed") is True
        ]
        _require(accepted, "independent_customer_acceptance_missing")
        chosen.append(accepted[-1])
    return {
        "source": "customer_value_receipts",
        "receipt_ids": [row.receipt_id for row in chosen],
        "artifact_id": scope.artifact_id,
        "artifact_sha256": scope.artifact_sha256,
    }


def _native_delivery(step_id, ticket):
    from modstore_server.customer_delivery_receipts import all_artifacts_running

    evidence = json.loads(ticket.evidence_json or "{}")
    artifacts = evidence.get("delivery_artifacts") or []
    generation = evidence.get("delivery_generation")
    grants = [
        row
        for row in evidence.get("download_grants") or []
        if row.get("owner_user_id") == ticket.user_id and row.get("generation") == generation
    ]
    _require(
        generation
        and artifacts
        and all(
            any(
                all(
                    grant.get(key) == artifact.get(key)
                    for key in ("kind", "id", "version", "package_sha256")
                )
                for grant in grants
            )
            for artifact in artifacts
        ),
        "customer_download_delivery_missing",
    )
    if step_id in {"O6", "O7", "O8"}:
        _require(
            all_artifacts_running(ticket, evidence), "original_delivery_runtime_receipt_missing"
        )
    if step_id in {"O7", "O8"}:
        _require(
            evidence.get("acceptance_status") == "accepted"
            and evidence.get("accepted_by_user_id") == ticket.user_id
            and evidence.get("acceptance_actor") == "customer",
            "independent_customer_acceptance_missing",
        )
    return {
        "source": "customer_service_tickets",
        "ticket_id": ticket.id,
        "generation": generation,
        "artifacts_sha256": _digest(artifacts),
        "receipt_ids": [
            row.get("receipt_id")
            for row in evidence.get("receipt_events") or []
            if row.get("generation") == generation and row.get("verified") is True
        ],
    }


def _observe(db, step_id, scope):
    if scope.landing_contact_id and step_id in {"O1", "O2"}:
        lead, fact = _lead(db, scope)
        if step_id == "O2":
            from modstore_server.customer_service_tools import begin_immediate_write

            # Serialize on the original lead; keep one original work-order identity.
            db.rollback()
            begin_immediate_write(db)
            db.execute(
                select(LandingContactSubmission)
                .where(LandingContactSubmission.id == scope.landing_contact_id)
                .with_for_update()
            ).scalar_one()
            fact = create_prospect_requirement(db, scope.landing_contact_id)
        return fact
    ticket, owner_id = _ticket(db, scope)
    if step_id in {"O1", "O2"} and ticket:
        _require(ticket.summary or ticket.title, "customer_requirement_missing")
        return {
            "source": "customer_service_tickets",
            "ticket_id": ticket.id,
            "customer_user_id": owner_id,
            "stage": "existing_customer",
            "requirements_sha256": _digest([ticket.title, ticket.summary]),
        }
    if step_id == "O3" and ticket:
        from modstore_server.customer_service_delivery_models import custom_delivery_crm

        evidence = json.loads(ticket.evidence_json or "{}")
        crm = custom_delivery_crm(evidence)
        quote, contract = crm["quote"], crm["contract"]
        if (evidence.get("delivery_terms") or {}).get("pricing_mode") != "initial_included":
            _require(
                quote.get("status") == "accepted"
                and quote.get("quote_no")
                and payment_amount_cents({"total_amount": quote.get("amount")}) > 0,
                "accepted_original_quote_missing",
            )
            if (evidence.get("delivery_terms") or {}).get("pricing_mode") == "legacy":
                _require(
                    contract.get("status") == "signed" and contract.get("reference"),
                    "signed_contract_missing",
                )
            return {
                "source": "customer_service_tickets",
                "ticket_id": ticket.id,
                "quote_sha256": _digest(quote),
                "contract_sha256": _digest(contract),
            }
    order, orders, fact = _order(scope, owner_id, ticket)
    number = fact["order_no"]
    _receipts(db, scope, owner_id, number)  # A native refund invalidates every later step.
    if step_id in {"O1", "O2", "O5", "O6", "O7", "O8"}:
        if ticket and not scope.customer_goal_id:
            return {**fact, **_native_delivery(step_id, ticket)}
        return {
            **fact,
            **_value_fact(db, "O2" if step_id == "O1" else step_id, scope, owner_id, number),
        }
    if step_id in {"O3", "O4"}:
        return fact
    if step_id == "O9":
        invoices = db.scalars(
            select(Invoice).where(Invoice.user_id == owner_id, Invoice.status == "issued")
        ).all()
        issued = []
        by_number = {str(row.get("out_trade_no") or row.get("order_no")): row for row in orders}
        for row in invoices:
            ids = json.loads(row.order_ids_json or "[]")
            if (
                number not in ids
                or scope.invoice_id not in (None, row.id)
                or not row.pdf_url
                or not row.issued_at
                or len(ids) != len(set(ids))
            ):
                continue
            originals = [by_number.get(key, {}) for key in ids]
            if all(
                str(item.get("user_id")) == str(owner_id) and classify_payment_order(item)[0]
                for item in originals
            ) and payment_amount_cents({"total_amount": row.amount}) == sum(
                payment_amount_cents(item) for item in originals
            ):
                issued.append(row)
        _require(len(issued) == 1, "issued_order_invoice_missing_or_ambiguous")
        return {
            **fact,
            "source": "invoices",
            "invoice_id": issued[0].id,
            "document_sha256": _digest([issued[0].pdf_url, issued[0].issued_at]),
        }
    paid_at = parse_datetime(order.get("paid_at")).replace(tzinfo=None)
    reports = db.scalars(
        select(ReconciliationReport)
        .where(
            ReconciliationReport.status == "confirmed",
            ReconciliationReport.period_start <= paid_at,
            ReconciliationReport.period_end > paid_at,
        )
        .order_by(ReconciliationReport.id.desc())
    ).all()
    for report in reports:
        if scope.reconciliation_report_id not in (None, report.id) or not report.confirmed_at:
            continue
        population = [
            row
            for row in orders
            if classify_payment_order(row)[0]
            and report.period_start
            <= parse_datetime(row.get("paid_at")).replace(tzinfo=None)
            < report.period_end
        ]
        if report.total_orders == len(population) and payment_amount_cents(
            {"total_amount": report.total_gmv}
        ) == sum(payment_amount_cents(row) for row in population):
            return {
                **fact,
                "source": "reconciliation_reports",
                "report_id": report.id,
                "population_sha256": _digest(sorted(_digest(row) for row in population)),
                "basis": "authoritative_payment_orders_and_confirmed_internal_report",
            }
    raise MissingEvidence("current_confirmed_reconciliation_missing")


def observe_business_step(step_id: str, context: dict[str, Any]) -> dict[str, Any]:
    try:
        scope = BusinessScope.model_validate(context.get("business") or {})
        with get_session_factory()() as db:
            fact = _observe(db, step_id, scope)
        result = {"ok": True, "status": "completed", "evidence": fact}
    except MissingEvidence as exc:
        result = {"ok": False, "status": "waiting_evidence", "reason": str(exc)}
    return {"step": step_id, "result": result}
