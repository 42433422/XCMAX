# mypy: disable-error-code="arg-type, union-attr"
"""Strict, read-only customer value evidence aggregation.

Payment status alone is intentionally insufficient. Production value requires
provider proof, a positive amount, a production environment and exclusion of
test/internal/refunded records. Delivery receipts are append-only and only
become a paid outcome when they share the same order number with a qualifying
payment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from sqlalchemy.exc import SQLAlchemyError

from modstore_server import payment_orders
from modstore_server.customer_value_classification import amount_cents as _amount_cents
from modstore_server.customer_value_classification import (
    classify_payment_order,
)
from modstore_server.customer_value_classification import (
    parse_datetime as _parse_datetime,
)
from modstore_server.customer_value_classification import (
    payment_amount_cents,
)
from modstore_server.customer_value_classification import (
    sanitize_evidence as _sanitize_evidence,
)
from modstore_server.customer_value_classification import text as _text
from modstore_server.customer_value_classification import truthy as _truthy
from modstore_server.models import (
    CustomerValueReceipt,
    UpdateInstallationReceipt,
    get_session_factory,
)
from modstore_server.standard_delivery_api import configured_internal_installation_ids

UTC = timezone.utc  # noqa: UP017 - MODstore CI and production still support Python 3.10

EVIDENCE_SCHEMA = "customer_value_evidence.v1"
RECEIPT_KINDS = frozenset(
    {"goal", "delivery", "first_use", "outcome", "acceptance", "reuse", "refund"}
)
VERIFICATION_STATUSES = frozenset({"pending_evidence", "verified", "reversed"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JAVA_PAGE_SIZE = 1000
_JAVA_MAX_ORDERS = 100_000


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _internal_api_key() -> str:
    return _text(
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY"),
        4096,
    )


def _load_java_payment_orders(window_days: int) -> list[dict[str, Any]]:
    """Read minimal payment proof from the Java/PostgreSQL source of truth."""

    key = _internal_api_key()
    if not key:
        raise RuntimeError("java_payment_internal_key_unavailable")
    base_url = _text(
        os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080",
        2048,
    ).rstrip("/")
    if not base_url:
        raise RuntimeError("java_payment_service_url_unavailable")

    orders: list[dict[str, Any]] = []
    offset = 0
    max_pages = (_JAVA_MAX_ORDERS // _JAVA_PAGE_SIZE) + 1
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        for _page_number in range(max_pages):
            response = client.get(
                f"{base_url}/api/internal/payment/value-evidence",
                params={
                    "window_days": window_days,
                    "limit": _JAVA_PAGE_SIZE,
                    "offset": offset,
                },
                headers={"X-Internal-Api-Key": key},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("java_payment_evidence_payload_invalid")
            if (
                payload.get("ok") is not True
                or payload.get("source") != "java_postgresql"
            ):
                raise RuntimeError("java_payment_evidence_source_untrusted")
            page = payload.get("orders")
            if not isinstance(page, list) or any(
                not isinstance(item, dict) for item in page
            ):
                raise RuntimeError("java_payment_evidence_orders_invalid")
            total = int(payload.get("total") or 0)
            if total < 0 or total > _JAVA_MAX_ORDERS:
                raise RuntimeError("java_payment_evidence_total_out_of_bounds")
            orders.extend(dict(item) for item in page)
            if len(orders) >= total:
                break
            if not page or len(orders) > _JAVA_MAX_ORDERS:
                raise RuntimeError("java_payment_evidence_pagination_incomplete")
            offset += _JAVA_PAGE_SIZE
        else:
            raise RuntimeError("java_payment_evidence_pagination_incomplete")
    return orders


def load_authoritative_payment_orders(window_days: int) -> dict[str, Any]:
    """Return payment rows plus explicit source availability and ownership."""

    days = max(1, min(int(window_days), 3650))
    if payment_orders.is_local_source_of_truth():
        try:
            found, _ = payment_orders.list_orders(status="paid", limit=_JAVA_MAX_ORDERS)
            rows = [dict(item) for item in found if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            return {
                "orders": [],
                "source_owner": "python_payment_orders",
                "source_available": False,
                "source_authoritative": False,
            }
        return {
            "orders": rows,
            "source_owner": "python_payment_orders",
            "source_available": True,
            "source_authoritative": True,
        }

    try:
        rows = _load_java_payment_orders(days)
    except (httpx.HTTPError, RuntimeError, TypeError, ValueError):
        return {
            "orders": [],
            "source_owner": "java_postgresql_internal_api",
            "source_available": False,
            "source_authoritative": False,
        }
    return {
        "orders": rows,
        "source_owner": "java_postgresql_internal_api",
        "source_available": True,
        "source_authoritative": True,
    }


def append_customer_value_receipt(
    payload: dict[str, Any],
    *,
    payment_order: dict[str, Any] | None = None,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one receipt or return the existing idempotent record.

    ``verified`` acceptance receipts must be complete and, when tied to an
    order, that order must independently pass the strict payment classifier.
    Pending evidence may be recorded, but is never included in verified counts.
    """

    data = dict(payload or {})
    receipt_kind = _text(data.get("receipt_kind"), 32).lower()
    verification_status = _text(
        data.get("verification_status") or "pending_evidence", 32
    ).lower()
    if receipt_kind not in RECEIPT_KINDS:
        raise ValueError(f"unsupported receipt_kind: {receipt_kind or '<empty>'}")
    if verification_status not in VERIFICATION_STATUSES:
        raise ValueError(f"unsupported verification_status: {verification_status}")

    source_event_id = _text(data.get("source_event_id"), 192)
    if not source_event_id:
        raise ValueError("source_event_id is required")

    customer_ref = _text(data.get("customer_ref"), 128)
    goal_id = _text(data.get("customer_goal_id"), 128)
    order_no = _text(data.get("order_no"), 96)
    artifact_id = _text(data.get("artifact_id"), 256)
    acceptance_id = _text(data.get("acceptance_id"), 128)
    if verification_status == "verified":
        required = {"customer_ref": customer_ref, "customer_goal_id": goal_id}
        if receipt_kind in {"delivery", "first_use", "outcome", "acceptance", "reuse"}:
            required["artifact_id"] = artifact_id
        if receipt_kind == "acceptance":
            required["acceptance_id"] = acceptance_id
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError("verified receipt missing: " + ", ".join(missing))
        if receipt_kind in {"delivery", "first_use", "outcome", "acceptance", "reuse"}:
            evidence = (
                data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
            )
            artifact_sha256 = _text(evidence.get("artifact_sha256"), 64).lower()
            if not _SHA256.fullmatch(artifact_sha256):
                raise ValueError("verified delivery requires evidence.artifact_sha256")
            if receipt_kind in {"first_use", "reuse"}:
                task_type = _text(evidence.get("task_type"), 128).lower()
                if (
                    not _text(evidence.get("run_id"), 192)
                    or evidence.get("success") is not True
                    or evidence.get("business_output") is not True
                    or not task_type
                    or task_type in {"login", "auth", "authentication", "session"}
                ):
                    raise ValueError(
                        f"verified {receipt_kind} requires a successful business output and run_id"
                    )
            if receipt_kind == "outcome":
                outcome_keys = (
                    "baseline",
                    "target",
                    "measured_value",
                    "comparison",
                    "unit",
                    "measurement_window",
                    "source_material_summary",
                    "source_material_sha256",
                )
                if any(evidence.get(key) in (None, "") for key in outcome_keys):
                    raise ValueError(
                        "verified outcome requires baseline, target, measured value, unit, window and source material"
                    )
                if _text(evidence.get("comparison"), 8).lower() not in {"ge", "le"}:
                    raise ValueError("verified outcome comparison must be ge or le")
                if not _SHA256.fullmatch(
                    _text(evidence.get("source_material_sha256"), 64).lower()
                ):
                    raise ValueError(
                        "verified outcome requires evidence.source_material_sha256"
                    )
            if receipt_kind == "acceptance" and data.get("lifecycle_v2") is True:
                customer_confirmed = evidence.get("customer_confirmed") is True
                signed_digest = _text(
                    evidence.get("signed_document_sha256"), 64
                ).lower()
                if not customer_confirmed and not _SHA256.fullmatch(signed_digest):
                    raise ValueError(
                        "customer acceptance requires account confirmation or signed document"
                    )
        if receipt_kind == "goal" and data.get("lifecycle_v2") is True:
            evidence = (
                data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
            )
            goal_keys = (
                "baseline",
                "target",
                "comparison",
                "unit",
                "measurement_window",
                "agreement_sha256",
            )
            if any(evidence.get(key) in (None, "") for key in goal_keys):
                raise ValueError("verified goal requires a complete agreed KPI")
            if _text(evidence.get("comparison"), 8).lower() not in {"ge", "le"}:
                raise ValueError("verified goal comparison must be ge or le")
            if evidence.get("customer_confirmed") is not True or not _SHA256.fullmatch(
                _text(evidence.get("agreement_sha256"), 64).lower()
            ):
                raise ValueError("verified goal requires customer confirmation and agreement digest")
        if order_no:
            if payment_order is None:
                payment_order = payment_orders.find(order_no)
            eligible, reason = classify_payment_order(dict(payment_order or {}))
            if not eligible:
                raise ValueError(
                    f"order is not verified production payment evidence: {reason}"
                )

    occurred_at = _parse_datetime(data.get("occurred_at")) or (now or datetime.now(UTC))
    occurred_at = occurred_at.astimezone(UTC)
    sanitized_evidence = _sanitize_evidence(data.get("evidence") or {})
    evidence_json = _canonical_json(sanitized_evidence)
    evidence_digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
    identity = {
        "receipt_kind": receipt_kind,
        "source_event_id": source_event_id,
        "customer_goal_id": goal_id,
        "order_no": order_no,
        "artifact_id": artifact_id,
        "acceptance_id": acceptance_id,
        "evidence_digest": evidence_digest,
    }
    receipt_id = (
        "cvr_"
        + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:48]
    )

    sf = session_factory or get_session_factory()
    with sf() as session:
        if (
            verification_status == "verified"
            and receipt_kind == "outcome"
            and data.get("lifecycle_v2") is True
        ):
            goals = (
                session.query(CustomerValueReceipt)
                .filter(
                    CustomerValueReceipt.order_no == order_no,
                    CustomerValueReceipt.customer_ref == customer_ref,
                    CustomerValueReceipt.customer_goal_id == goal_id,
                    CustomerValueReceipt.verification_status == "verified",
                    CustomerValueReceipt.receipt_kind == "goal",
                    CustomerValueReceipt.occurred_at <= occurred_at.replace(tzinfo=None),
                )
                .order_by(CustomerValueReceipt.occurred_at.desc())
                .all()
            )
            if not goals:
                raise ValueError("outcome requires a prior customer-confirmed KPI goal")
            try:
                goal_evidence = json.loads(goals[0].evidence_json or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                goal_evidence = {}
            comparable = (
                "baseline",
                "target",
                "comparison",
                "unit",
                "measurement_window",
            )
            if any(
                sanitized_evidence.get(key) != goal_evidence.get(key)
                for key in comparable
            ):
                raise ValueError("outcome KPI does not match the prior customer agreement")
        if verification_status == "verified" and receipt_kind == "reuse":
            prior = (
                session.query(CustomerValueReceipt)
                .filter(
                    CustomerValueReceipt.order_no == order_no,
                    CustomerValueReceipt.customer_ref == customer_ref,
                    CustomerValueReceipt.customer_goal_id == goal_id,
                    CustomerValueReceipt.verification_status == "verified",
                    CustomerValueReceipt.receipt_kind.in_(["first_use", "acceptance"]),
                    CustomerValueReceipt.occurred_at
                    <= occurred_at.replace(tzinfo=None),
                )
                .all()
            )
            acceptances = [row for row in prior if row.receipt_kind == "acceptance"]
            first_uses = [row for row in prior if row.receipt_kind == "first_use"]
            acceptance = max(acceptances, key=lambda row: row.occurred_at, default=None)
            first_use = min(first_uses, key=lambda row: row.occurred_at, default=None)
            if acceptance is None or first_use is None:
                raise ValueError(
                    "reuse requires verified first_use and acceptance receipts"
                )
            accepted_at = acceptance.occurred_at.replace(tzinfo=UTC)
            if occurred_at < accepted_at + timedelta(hours=24):
                raise ValueError("reuse must occur at least 24 hours after acceptance")
            try:
                first_evidence = json.loads(first_use.evidence_json or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                first_evidence = {}
            first_run_id = _text(first_evidence.get("run_id"), 192)
            reuse_run_id = _text(sanitized_evidence.get("run_id"), 192)
            if not first_run_id or first_run_id == reuse_run_id:
                raise ValueError("reuse requires a different run_id from first_use")
        existing = (
            session.query(CustomerValueReceipt)
            .filter(CustomerValueReceipt.receipt_id == receipt_id)
            .first()
        )
        if existing is not None:
            return {"ok": True, "created": False, "receipt_id": receipt_id}
        row = CustomerValueReceipt(
            receipt_id=receipt_id,
            receipt_kind=receipt_kind,
            verification_status=verification_status,
            customer_ref=customer_ref,
            customer_goal_id=goal_id,
            order_no=order_no,
            artifact_id=artifact_id,
            acceptance_id=acceptance_id,
            amount_cents=max(0, int(data.get("amount_cents") or 0)),
            currency=_text(data.get("currency") or "CNY", 8).upper(),
            payment_provider=_text(data.get("payment_provider"), 32).lower(),
            provider_trade_no=_text(data.get("provider_trade_no"), 128),
            provider_verification=_text(data.get("provider_verification"), 64).lower(),
            environment=_text(data.get("environment"), 32).lower(),
            source_event_id=source_event_id,
            source_employee_id=_text(data.get("source_employee_id"), 128),
            supersedes_receipt_id=_text(data.get("supersedes_receipt_id"), 96),
            evidence_json=evidence_json,
            evidence_digest=evidence_digest,
            occurred_at=occurred_at.replace(tzinfo=None),
            recorded_at=(now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None),
        )
        session.add(row)
        session.commit()
    return {"ok": True, "created": True, "receipt_id": receipt_id}


def build_customer_value_evidence(
    *,
    window_days: int = 90,
    orders: list[dict[str, Any]] | None = None,
    session_factory: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the safe aggregate consumed by the founder scorecard."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    days = max(1, min(int(window_days), 3650))
    cutoff = current - timedelta(days=days)
    if orders is None:
        payment_source = load_authoritative_payment_orders(days)
        source_owner = str(payment_source.get("source_owner") or "unavailable")
        source_available = payment_source.get("source_available") is True
        source_authoritative = payment_source.get("source_authoritative") is True
        raw_orders = [
            dict(item)
            for item in payment_source.get("orders") or []
            if isinstance(item, dict)
        ]
    else:
        source_owner = "injected"
        source_available = True
        source_authoritative = True
        raw_orders = list(orders)

    excluded: Counter[str] = Counter()
    eligible_orders: dict[str, dict[str, Any]] = {}
    for order in raw_orders:
        eligible, reason = classify_payment_order(order, cutoff=cutoff)
        if not eligible:
            if reason != "not_paid":
                excluded[reason] += 1
            continue
        order_no = _text(order.get("out_trade_no") or order.get("order_no"), 96)
        if order_no:
            eligible_orders[order_no] = order

    sf = session_factory or get_session_factory()
    append_only_store_available = True
    receipts: list[CustomerValueReceipt] = []
    installation_receipts: list[UpdateInstallationReceipt] = []
    try:
        with sf() as session:
            receipts = (
                session.query(CustomerValueReceipt)
                .filter(CustomerValueReceipt.occurred_at >= cutoff.replace(tzinfo=None))
                .all()
            )
            installation_receipts = (
                session.query(UpdateInstallationReceipt)
                .filter(
                    UpdateInstallationReceipt.reported_at >= cutoff.replace(tzinfo=None)
                )
                .order_by(
                    UpdateInstallationReceipt.reported_at.desc(),
                    UpdateInstallationReceipt.id.desc(),
                )
                .all()
            )
    except SQLAlchemyError:
        append_only_store_available = False
        receipts = []

    verified_receipts = [
        row for row in receipts if row.verification_status == "verified"
    ]
    refunded_order_nos = {
        row.order_no
        for row in verified_receipts
        if row.receipt_kind == "refund" and row.order_no
    }
    for order_no in list(eligible_orders):
        if order_no in refunded_order_nos:
            excluded["refunded"] += 1
            eligible_orders.pop(order_no, None)

    paid_amount_cents = sum(_amount_cents(order) for order in eligible_orders.values())
    customer_goal_ids = {
        row.customer_goal_id
        for row in verified_receipts
        if row.receipt_kind in {"goal", "delivery", "acceptance"}
        and row.customer_goal_id
    }
    raw_delivered_receipts = [
        row
        for row in verified_receipts
        if row.receipt_kind in {"delivery", "acceptance"}
    ]
    delivered_receipts: list[CustomerValueReceipt] = []
    for row in raw_delivered_receipts:
        try:
            evidence = json.loads(row.evidence_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        artifact_sha256 = (
            _text(evidence.get("artifact_sha256"), 64).lower()
            if isinstance(evidence, dict)
            else ""
        )
        if row.artifact_id and _SHA256.fullmatch(artifact_sha256):
            delivered_receipts.append(row)
    paid_delivery_orders = {
        row.order_no
        for row in delivered_receipts
        if row.order_no and row.order_no in eligible_orders
    }
    paid_acceptance_orders = {
        row.order_no
        for row in delivered_receipts
        if row.receipt_kind == "acceptance"
        and row.order_no
        and row.order_no in eligible_orders
    }

    release_sha = _text(os.environ.get("XCMAX_RELEASE_SHA"), 40).lower()
    if not re.fullmatch(r"[0-9a-f]{40}", release_sha):
        release_sha = ""
    latest_install_by_device: dict[tuple[int, str], UpdateInstallationReceipt] = {}
    internal_installation_ids = {
        value.casefold() for value in configured_internal_installation_ids()
    }
    for row in installation_receipts:
        key = (int(row.user_id), _text(row.installation_id, 64))
        if key[1]:
            latest_install_by_device.setdefault(key, row)

    receipts_by_order: dict[str, list[CustomerValueReceipt]] = {}
    for row in verified_receipts:
        if row.order_no:
            receipts_by_order.setdefault(str(row.order_no), []).append(row)

    def receipt_evidence(row: CustomerValueReceipt | None) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            parsed = json.loads(row.evidence_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    lifecycle_rows: list[dict[str, Any]] = []
    stage_counts: Counter[str] = Counter()
    complete_entities: set[str] = set()
    lifecycle_gaps: Counter[str] = Counter()
    for order_no, order in eligible_orders.items():
        try:
            user_id = int(order.get("user_id"))
        except (TypeError, ValueError):
            user_id = 0
        entity_ref = _text(
            order.get("enterprise_subject_id")
            or order.get("business_entity_id")
            or order.get("company_tax_id"),
            256,
        )
        customer_alias = (
            "customer-" + hashlib.sha256(entity_ref.encode()).hexdigest()[:12]
            if entity_ref
            else ""
        )
        order_receipts = receipts_by_order.get(order_no, [])
        receipts_by_goal: dict[str, list[CustomerValueReceipt]] = {}
        for row in order_receipts:
            if row.customer_goal_id:
                receipts_by_goal.setdefault(str(row.customer_goal_id), []).append(row)

        def goal_rank(rows: list[CustomerValueReceipt]) -> tuple[int, int, datetime]:
            kinds: dict[str, CustomerValueReceipt] = {}
            for candidate in sorted(rows, key=lambda item: item.occurred_at):
                kinds.setdefault(str(candidate.receipt_kind), candidate)
            first = kinds.get("first_use")
            measured_outcome = kinds.get("outcome")
            accepted = kinds.get("acceptance")
            reused = kinds.get("reuse")
            achieved = False
            outcome_data = receipt_evidence(measured_outcome)
            try:
                measured_value = float(outcome_data.get("measured_value"))
                target_value = float(outcome_data.get("target"))
            except (TypeError, ValueError):
                measured_value = target_value = float("nan")
            operator = _text(outcome_data.get("comparison"), 8).lower()
            if operator == "ge":
                achieved = measured_value >= target_value
            elif operator == "le":
                achieved = measured_value <= target_value
            sequence_valid = bool(
                first
                and measured_outcome
                and accepted
                and reused
                and achieved
                and first.occurred_at
                <= measured_outcome.occurred_at
                <= accepted.occurred_at
                and accepted.occurred_at + timedelta(hours=24)
                <= reused.occurred_at
            )
            latest = max(
                (row.occurred_at for row in rows),
                default=datetime.min,
            )
            return sequence_valid, len(kinds), latest

        selected_rows = (
            max(receipts_by_goal.values(), key=goal_rank) if receipts_by_goal else []
        )
        by_kind: dict[str, CustomerValueReceipt] = {}
        for row in sorted(selected_rows, key=lambda item: item.occurred_at):
            by_kind.setdefault(str(row.receipt_kind), row)

        matching_installs = [
            row
            for (
                receipt_user_id,
                _installation_id,
            ), row in latest_install_by_device.items()
            if receipt_user_id == user_id
            and _installation_id.casefold() not in internal_installation_ids
            and row.status == "installed"
            and _text(row.installed_build_sha, 40).lower() == release_sha
        ]
        first_use = by_kind.get("first_use")
        goal = by_kind.get("goal")
        outcome = by_kind.get("outcome")
        acceptance = by_kind.get("acceptance")
        reuse = by_kind.get("reuse")
        first_evidence = receipt_evidence(first_use)
        outcome_evidence = receipt_evidence(outcome)
        acceptance_evidence = receipt_evidence(acceptance)
        reuse_evidence = receipt_evidence(reuse)
        comparison = _text(outcome_evidence.get("comparison"), 8).lower()
        try:
            measured = float(outcome_evidence.get("measured_value"))
            target = float(outcome_evidence.get("target"))
        except (TypeError, ValueError):
            measured = target = float("nan")
        outcome_achieved = (
            comparison == "ge"
            and measured >= target
            or comparison == "le"
            and measured <= target
        )

        stages = {
            "payment": True,
            "installation": bool(release_sha and user_id and matching_installs),
            "first_use": bool(
                first_use
                and first_evidence.get("success") is True
                and first_evidence.get("business_output") is True
                and _text(first_evidence.get("run_id"), 192)
                and _text(first_evidence.get("task_type"), 128).lower()
                not in {"", "login", "auth", "authentication", "session"}
            ),
            "outcome": bool(
                outcome
                and all(
                    outcome_evidence.get(key) not in (None, "")
                    for key in (
                        "baseline",
                        "target",
                        "measured_value",
                        "comparison",
                        "unit",
                        "measurement_window",
                        "source_material_summary",
                        "source_material_sha256",
                    )
                )
                and outcome_achieved
            ),
            "acceptance": bool(
                acceptance
                and (
                    acceptance_evidence.get("customer_confirmed") is True
                    or _SHA256.fullmatch(
                        _text(
                            acceptance_evidence.get("signed_document_sha256"), 64
                        ).lower()
                    )
                )
            ),
            "reuse": False,
        }
        if reuse and acceptance and first_use:
            accepted_at = acceptance.occurred_at.replace(tzinfo=UTC)
            reused_at = reuse.occurred_at.replace(tzinfo=UTC)
            stages["reuse"] = bool(
                reuse_evidence.get("success") is True
                and reuse_evidence.get("business_output") is True
                and _text(reuse_evidence.get("run_id"), 192)
                and _text(reuse_evidence.get("task_type"), 128).lower()
                not in {"", "login", "auth", "authentication", "session"}
                and _text(reuse_evidence.get("run_id"), 192)
                != _text(first_evidence.get("run_id"), 192)
                and reused_at >= accepted_at + timedelta(hours=24)
            )
        for stage, passed in stages.items():
            if passed:
                stage_counts[stage] += 1
            else:
                lifecycle_gaps[stage] += 1
        paid_at = _parse_datetime(order.get("paid_at"))
        install_times = [
            row.reported_at.replace(tzinfo=UTC)
            for row in matching_installs
            if row.reported_at
        ]
        same_goal = bool(
            first_use
            and outcome
            and acceptance
            and reuse
            and len(
                {
                    first_use.customer_goal_id,
                    outcome.customer_goal_id,
                    acceptance.customer_goal_id,
                    reuse.customer_goal_id,
                }
            )
            == 1
        )
        ordered = bool(
            paid_at
            and install_times
            and first_use
            and goal
            and outcome
            and acceptance
            and reuse
            and same_goal
            and goal.occurred_at <= first_use.occurred_at
            and any(
                paid_at <= installed_at <= first_use.occurred_at.replace(tzinfo=UTC)
                for installed_at in install_times
            )
            and first_use.occurred_at <= outcome.occurred_at <= acceptance.occurred_at
            and acceptance.occurred_at + timedelta(hours=24) <= reuse.occurred_at
        )
        if not ordered:
            lifecycle_gaps["sequence"] += 1
        complete = bool(entity_ref and ordered and all(stages.values()))
        if complete:
            complete_entities.add(entity_ref)
        lifecycle_rows.append(
            {
                "customer_alias": customer_alias or "unverified-enterprise-subject",
                "stages": stages,
                "ordered": ordered,
                "complete": complete,
                "gaps": [stage for stage, passed in stages.items() if not passed]
                + ([] if ordered else ["sequence"])
                + ([] if entity_ref else ["enterprise_subject"]),
            }
        )

    excluded_keys = (
        "test_record",
        "internal_order",
        "refunded",
        "nonpositive_amount",
        "missing_paid_at",
        "missing_provider_proof",
        "nonproduction",
        "outside_window",
    )
    result = {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": current.isoformat(),
        "window_days": days,
        "value_ledger_ready": bool(
            source_available and source_authoritative and append_only_store_available
        ),
        "source_available": source_available,
        "source_authoritative": source_authoritative,
        "source_owner": source_owner,
        "append_only_store_available": append_only_store_available,
        "verified_paid_count": len(eligible_orders),
        "verified_paid_amount_cents": paid_amount_cents,
        "customer_goal_count": len(customer_goal_ids),
        "delivered_count": len(delivered_receipts),
        "unproven_delivery_count": len(raw_delivered_receipts)
        - len(delivered_receipts),
        "paid_delivery_count": len(paid_delivery_orders),
        "paid_acceptance_count": len(paid_acceptance_orders),
        "production_value_verified": bool(eligible_orders),
        "outcome_verified": bool(paid_delivery_orders),
        "customer_acceptance_verified": bool(paid_acceptance_orders),
        "lifecycle_schema": "customer_value_lifecycle/v2",
        "release_sha": release_sha,
        "six_stage_counts": {
            stage: int(stage_counts.get(stage, 0))
            for stage in (
                "payment",
                "installation",
                "first_use",
                "outcome",
                "acceptance",
                "reuse",
            )
        },
        "complete_customer_count": len(complete_entities),
        "complete_customer_target": 3,
        "three_customer_loop_verified": len(complete_entities) >= 3,
        "lifecycle_gaps": dict(sorted(lifecycle_gaps.items())),
        "customers": lifecycle_rows,
        "excluded": {key: int(excluded.get(key, 0)) for key in excluded_keys},
    }
    return result


def payment_evidence_marker(
    *, provider: str, verification: str, trade_no: str
) -> dict[str, Any]:
    """Canonical fields written only after a gateway verification succeeds."""

    deploy_tier = _text(os.environ.get("MODSTORE_DEPLOY_TIER") or "local", 32).lower()
    test_mode = _truthy(os.environ.get("ALIPAY_DEBUG")) or _truthy(
        os.environ.get("MODSTORE_PAYMENT_TEST_MODE")
    )
    return {
        "payment_provider": _text(provider, 32).lower(),
        "provider_trade_no": _text(trade_no, 128),
        "provider_verification": _text(verification, 64).lower(),
        "provider_verified_at": datetime.now(UTC).isoformat(),
        "provider_test_mode": test_mode,
        "payment_environment": deploy_tier,
    }


__all__ = [
    "EVIDENCE_SCHEMA",
    "append_customer_value_receipt",
    "build_customer_value_evidence",
    "classify_payment_order",
    "load_authoritative_payment_orders",
    "payment_amount_cents",
    "payment_evidence_marker",
]
