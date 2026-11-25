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
                return {"archived": True, "transaction_id": txn.id, "idempotent": False}
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
    from app.domain.shared_services.user_cs_crm_store import list_crm_invoices

    data = list_crm_invoices(market_user_id=market_user_id, limit=500)
    rows = data.get("items") if isinstance(data, dict) else None
    total = data.get("total") if isinstance(data, dict) else None
    if not isinstance(rows, list) or type(total) is not int or total < len(rows):
        return {
            "rebuilt": 0, "rejected": 0, "complete": False,
            "reason_code": "invoice_source_unavailable", "market_user_id": market_user_id,
        }
    rebuilt = rejected = 0
    for inv in rows:
        outcome = (
            archive_from_crm_invoice(inv, market_user_id=market_user_id)
            if isinstance(inv, dict)
            else {"archived": False}
        )
        rebuilt += outcome.get("archived") is True
        rejected += outcome.get("archived") is not True
    return {
        "rebuilt": rebuilt,
        "rejected": rejected,
        "complete": total == len(rows) and rejected == 0,
        "reason_code": (
            "invoice_source_truncated"
            if total != len(rows)
            else ("invoice_archive_rejected" if rejected else None)
        ),
        "market_user_id": market_user_id,
    }
