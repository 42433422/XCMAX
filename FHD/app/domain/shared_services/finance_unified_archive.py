"""财务统一归档：CRM 发票 + pipeline 凭证 → financial_transactions / 本地索引。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _ledger_item_from_invoice(inv: dict[str, Any]) -> dict[str, Any]:
    amount = inv.get("amount_cents") or inv.get("amount")
    cents = int(amount) if amount is not None else 0
    if cents and cents < 10000 and isinstance(amount, (int, float)) and amount == cents:
        pass
    elif isinstance(amount, (int, float)) and amount > 100:
        cents = int(amount)
    return {
        "source_type": "crm_invoice",
        "source_id": inv.get("id"),
        "track": "contract",
        "amount_cents": cents,
        "status": str(inv.get("status") or "issued"),
        "invoice_no": str(inv.get("invoice_no") or ""),
        "payment_ref": str(inv.get("payment_reference") or ""),
        "occurred_at": str(inv.get("issued_at") or inv.get("created_at") or ""),
        "label": str(inv.get("label") or inv.get("invoice_no") or "CRM 账单"),
        "market_user_id": inv.get("market_user_id"),
        # An invoice is a source document, not a verified payment or profit.
        "document_only": True,
        "settlement_verified": False,
    }


def _items_from_pipeline(market_user_id: int | None, *, limit: int) -> list[dict[str, Any]]:
    from app.domain.shared_services.user_cs_pipeline import _iter_pipeline_docs

    items: list[dict[str, Any]] = []
    for doc in _iter_pipeline_docs():
        uid = int(doc.get("market_user_id") or 0)
        if market_user_id and uid != int(market_user_id):
            continue
        invoice = doc.get("invoice") if isinstance(doc.get("invoice"), dict) else None
        if invoice:
            inv = dict(invoice)
            inv.setdefault("market_user_id", uid)
            items.append(_ledger_item_from_invoice(inv))
        payment = doc.get("payment") if isinstance(doc.get("payment"), dict) else None
        if payment and payment.get("confirmed_at"):
            cents = int(payment.get("contract_amount_cents") or payment.get("amount_cents") or 0)
            items.append(
                {
                    "source_type": "pipeline_payment",
                    "source_id": uid,
                    "track": "contract",
                    "amount_cents": cents,
                    "status": str(payment.get("status") or "paid"),
                    "payment_ref": str(payment.get("reference") or ""),
                    "occurred_at": str(payment.get("confirmed_at") or ""),
                    "label": str(
                        doc.get("erp_customer_name") or doc.get("username") or f"客户{uid}"
                    ),
                    "market_user_id": uid,
                }
            )
        if len(items) >= limit:
            break
    return items[:limit]


def _items_from_db(
    market_user_id: int | None, *, track: str | None, limit: int
) -> list[dict[str, Any]]:
    try:
        from app.db import SessionLocal
        from app.db.models.finance import FinancialTransaction
    except RECOVERABLE_ERRORS:
        return []
    items: list[dict[str, Any]] = []
    try:
        with SessionLocal() as db:
            q = db.query(FinancialTransaction).order_by(
                FinancialTransaction.transaction_date.desc()
            )
            if market_user_id:
                q = q.filter(FinancialTransaction.counterparty_id == int(market_user_id))
            if track:
                q = q.filter(FinancialTransaction.transaction_type == track)
            rows = q.limit(limit).all()
            for row in rows:
                cents = int(Decimal(str(row.amount or 0)) * 100)
                entry = {
                    "source_type": "financial_transaction",
                    "source_id": row.id,
                    "track": str(row.transaction_type or "manual"),
                    "amount_cents": cents,
                    "status": str(row.status or ""),
                    "invoice_no": "",
                    "payment_ref": str(row.reference_id or ""),
                    "occurred_at": row.transaction_date.isoformat() if row.transaction_date else "",
                    "label": str(row.description or row.transaction_type or ""),
                    "market_user_id": row.counterparty_id,
                    "document_only": row.reference_type == "crm_invoice",
                    "settlement_verified": False,
                }
                if track and entry["track"] != track:
                    continue
                items.append(entry)
    except RECOVERABLE_ERRORS:
        logger.debug("financial_transactions query skipped", exc_info=True)
    return items


def list_ledger(
    *,
    market_user_id: int | None = None,
    track: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 2000))
    db_items = _items_from_db(market_user_id, track=track, limit=cap)
    if db_items:
        return db_items
    try:
        from app.domain.shared_services.user_cs_crm_store import list_crm_invoices

        crm = list_crm_invoices(market_user_id=market_user_id, limit=cap)
        rows = crm.get("items") if isinstance(crm, dict) else []
        items = [_ledger_item_from_invoice(r) for r in (rows or []) if isinstance(r, dict)]
        if track:
            items = [x for x in items if x.get("track") == track]
        if items:
            return items[:cap]
    except RECOVERABLE_ERRORS:
        logger.debug("crm invoice ledger fallback skipped", exc_info=True)
    return [
        row for row in _items_from_pipeline(market_user_id, limit=cap)
        if track is None or row.get("track") == track
    ]


def summarize_ledger(*, market_user_id: int | None = None) -> dict[str, Any]:
    items = list_ledger(market_user_id=market_user_id, limit=2000)
    summary: dict[str, dict[str, int]] = {}
    for row in items:
        tr = str(row.get("track") or "manual")
        bucket = summary.setdefault(tr, {"count": 0, "amount_cents": 0})
        bucket["count"] += 1
        bucket["amount_cents"] += int(row.get("amount_cents") or 0)
    return summary


def _invoice_archive_existing(
    db: Any,
    tenant_id: int,
    invoice_id: int,
    *,
    amount: Decimal,
    status: str,
    counterparty_id: int | None,
    occurred_at: datetime,
    description: str,
) -> dict[str, Any] | None:
    """An exact replay may reuse the original row; drift requires review."""
    from app.db.models.finance import FinancialTransaction

    row = db.query(FinancialTransaction).filter(
        FinancialTransaction.tenant_id == tenant_id,
        FinancialTransaction.transaction_type == "contract",
        FinancialTransaction.reference_type == "crm_invoice",
        FinancialTransaction.reference_id == invoice_id,
    ).one_or_none()
    if row is None:
        return None
    if (
        row.amount != amount
        or row.currency != "CNY"
        or row.status != status
        or row.counterparty_id != counterparty_id
        or row.transaction_date != occurred_at
        or row.description != description
    ):
        return {"archived": False, "reason_code": "invoice_archive_conflict"}
    return {"archived": True, "transaction_id": row.id, "idempotent": True}


def _crm_market_user_owned(tenant_id: int, market_user_id: int) -> bool:
    """Original invoice must map to an active host account in this tenant."""
    from app.db import HostSessionLocal
    from app.db.models.user import User

    with HostSessionLocal() as db:
        return db.query(User.id).filter(
            User.tenant_id == tenant_id,
            User.market_user_id == market_user_id,
            User.is_active.is_(True),
        ).first() is not None


def archive_from_crm_invoice(
    inv: dict[str, Any], *, market_user_id: int | None = None
) -> dict[str, Any]:
    """Archive one original CRM invoice without claiming that it was paid."""
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant_id = current_tenant_id()
    if tenant_id is None:
        return {"archived": False, "reason_code": "tenant_context_required"}
    if type(inv.get("id")) is not int:
        return {"archived": False, "reason_code": "invoice_identity_required"}
    invoice_id = inv["id"]
    if invoice_id <= 0:
        return {"archived": False, "reason_code": "invoice_identity_required"}
    # The legacy display facade guesses whether "amount" means yuan or cents.
    # That heuristic is not an authoritative accounting source.
    amount_cents = inv.get("amount_cents")
    if type(amount_cents) is not int or amount_cents < 0:
        return {"archived": False, "reason_code": "invoice_amount_invalid"}
    entry = _ledger_item_from_invoice(inv)
    raw_date = str(inv.get("issued_at") or "")
    try:
        occurred_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return {"archived": False, "reason_code": "invoice_date_required"}
    if occurred_at.tzinfo is None:
        return {"archived": False, "reason_code": "invoice_timezone_required"}
    occurred_at = occurred_at.astimezone(UTC).replace(tzinfo=None)
    raw_uid = market_user_id if market_user_id is not None else inv.get("market_user_id")
    if raw_uid is not None and (type(raw_uid) is not int or raw_uid <= 0):
        return {"archived": False, "reason_code": "invoice_counterparty_invalid"}
    uid = raw_uid
    # The request may restrict the subject but must not replace a different
    # original CRM invoice counterparty when replaying an existing source ID.
    source_uid = inv.get("market_user_id")
    if market_user_id is not None and source_uid is not None and source_uid != market_user_id:
        return {"archived": False, "reason_code": "invoice_counterparty_conflict"}

    # A caller-supplied invoice dictionary is NOT an original business voucher.
    # Read the CRM source independently before creating any financial record.
    try:
        from app.domain.shared_services.user_cs_crm_store import get_crm_invoice_by_id

        original = get_crm_invoice_by_id(invoice_id)
    except RECOVERABLE_ERRORS:
        logger.warning("CRM original invoice cannot be read back", exc_info=True)
        return {"archived": False, "reason_code": "invoice_source_unavailable"}
    if not isinstance(original, dict):
        return {"archived": False, "reason_code": "invoice_source_missing"}
    authoritative = _ledger_item_from_invoice(original)
    incoming = _ledger_item_from_invoice(inv)
    identity_fields = (
        "source_id", "market_user_id", "invoice_no", "amount_cents",
        "status", "occurred_at", "label",
    )
    if any(
        authoritative.get(field) != incoming.get(field)
        for field in identity_fields
    ):
        return {"archived": False, "reason_code": "invoice_source_conflict"}
    # A globally readable CRM invoice ID is not itself tenant authorization.
    # Only the live host identity mapping can justify a tenant's archive row.
    if type(uid) is not int or uid <= 0:
        return {"archived": False, "reason_code": "invoice_counterparty_invalid"}
    try:
        source_owned = _crm_market_user_owned(tenant_id, uid)
    except RECOVERABLE_ERRORS:
        logger.warning("CRM owner lookup failed; refusing archive", exc_info=True)
        return {"archived": False, "reason_code": "invoice_source_ownership_unavailable"}
    if not source_owned:
        return {"archived": False, "reason_code": "invoice_tenant_ownership_conflict"}

    amount = Decimal(amount_cents) / 100
    status = str(entry.get("status") or "issued")
    try:
        from sqlalchemy.exc import IntegrityError

        from app.db import SessionLocal
        from app.db.models.finance import FinancialTransaction

        def find_existing(db):
            return _invoice_archive_existing(
                db,
                tenant_id,
                invoice_id,
                amount=amount,
                status=status,
                counterparty_id=uid,
                occurred_at=occurred_at,
                description=entry["label"],
            )

        try:
            with SessionLocal() as db:
                existing = find_existing(db)
                if existing is not None:
                    return existing
                txn = FinancialTransaction(
                    transaction_type="contract",
                    tenant_id=tenant_id,
                    currency="CNY",
                    amount=amount,
                    reference_type="crm_invoice",
                    reference_id=invoice_id,
                    description=entry["label"],
                    status=status,
                    counterparty_id=uid,
                    transaction_date=occurred_at,
                )
                db.add(txn)
                db.commit()
                db.refresh(txn)
                transaction_id = txn.id
            # Check in a fresh session. A successful commit alone is not an
            # independent persisted readback of the source voucher identity.
            with SessionLocal() as check_db:
                verified = find_existing(check_db)
            if (
                not verified
                or verified.get("archived") is not True
                or verified.get("transaction_id") != transaction_id
            ):
                return {
                    "archived": False,
                    "reason_code": "invoice_archive_readback_failed",
                }
            return {"archived": True, "transaction_id": transaction_id, "idempotent": False}
        except IntegrityError:
            # A concurrent writer may have committed the same business reference.
            # The unique key protects it; only an exact readback counts as success.
            with SessionLocal() as db:
                return find_existing(db) or {
                    "archived": False, "reason_code": "invoice_archive_concurrent_conflict"
                }
    except RECOVERABLE_ERRORS:
        logger.warning("CRM invoice archive unavailable", exc_info=True)
        return {"archived": False, "reason_code": "invoice_archive_unavailable"}


def rebuild_ledger_archive(*, market_user_id: int | None = None) -> dict[str, Any]:
    """Rebuild only from an intact, duplicate-free paginated source listing.

    Collect and verify all pages before writing any archive rows. The source
    may still change between this read and the writes; callers must not treat
    a successful archive as bank settlement or a point-in-time audit snapshot.
    """
    from app.domain.shared_services.user_cs_crm_store import list_crm_invoices

    page_size = 500
    max_source_rows = 100_000
    offset = 0
    total: int | None = None
    rows: list[dict[str, Any]] = []
    source_ids: set[int] = set()
    pages_read = 0

    def incomplete(reason: str) -> dict[str, Any]:
        return {
            "rebuilt": 0,
            "rejected": 0,
            "complete": False,
            "reason_code": reason,
            "market_user_id": market_user_id,
            "source_total": total,
            "pages_read": pages_read,
        }

    while total is None or offset < total:
        data = list_crm_invoices(
            market_user_id=market_user_id, limit=page_size, offset=offset
        )
        page_rows = data.get("items") if isinstance(data, dict) else None
        page_total = data.get("total") if isinstance(data, dict) else None
        if (
            not isinstance(page_rows, list)
            or type(page_total) is not int
            or page_total < 0
        ):
            return incomplete("invoice_source_unavailable")
        if total is None:
            total = page_total
        if page_total != total:
            return incomplete("invoice_source_changed_during_pagination")
        if total > max_source_rows:
            return incomplete("invoice_source_exceeds_rebuild_limit")
        if "offset" in data and data["offset"] != offset:
            return incomplete("invoice_source_wrong_page")
        expected = min(page_size, total - offset)
        if len(page_rows) != expected:
            return incomplete("invoice_source_truncated")
        for inv in page_rows:
            if (
                not isinstance(inv, dict)
                or type(inv.get("id")) is not int
                or inv["id"] <= 0
            ):
                return incomplete("invoice_source_invalid_row")
            if inv["id"] in source_ids:
                return incomplete("invoice_source_duplicate")
            source_ids.add(inv["id"])
            rows.append(inv)
        pages_read += 1
        offset += len(page_rows)

    # Offset pagination is not a transactional snapshot: the underlying
    # CRM SQLite store may change between SELECTs. Confirm the entire ordered
    # source twice before any financial archive write; a mismatch is UNKNOWN,
    # not a successful partial rebuild.
    verify_offset = 0
    while verify_offset < len(rows):
        data = list_crm_invoices(
            market_user_id=market_user_id, limit=page_size, offset=verify_offset
        )
        page_rows = data.get("items") if isinstance(data, dict) else None
        page_total = data.get("total") if isinstance(data, dict) else None
        expected_rows = rows[verify_offset : verify_offset + page_size]
        if (
            type(page_total) is not int
            or page_total != total
            or not isinstance(page_rows, list)
            or page_rows != expected_rows
            or ("offset" in data and data["offset"] != verify_offset)
        ):
            return incomplete("invoice_source_changed_during_pagination")
        verify_offset += len(expected_rows)

    rebuilt = rejected = already_archived = 0
    for inv in rows:
        outcome = archive_from_crm_invoice(inv, market_user_id=market_user_id)
        if outcome.get("archived") is True:
            rebuilt += 1
            already_archived += outcome.get("idempotent") is True
        else:
            rejected += 1
    return {
        "rebuilt": rebuilt,
        "rejected": rejected,
        "already_archived": already_archived,
        "complete": rejected == 0,
        "reason_code": "invoice_archive_rejected" if rejected else None,
        "market_user_id": market_user_id,
        "source_total": total,
        "pages_read": pages_read,
    }
