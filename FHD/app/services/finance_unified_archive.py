"""财务统一归档：CRM 发票 + pipeline 凭证 → financial_transactions / 本地索引。"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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
    from app.services.user_cs_pipeline import _iter_pipeline_docs

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
                    "label": str(doc.get("erp_customer_name") or doc.get("username") or f"客户{uid}"),
                    "market_user_id": uid,
                }
            )
        if len(items) >= limit:
            break
    return items[:limit]


def _items_from_db(market_user_id: int | None, *, track: str | None, limit: int) -> list[dict[str, Any]]:
    try:
        from app.db import SessionLocal
        from app.db.models.finance import FinancialTransaction
    except OPERATIONAL_ERRORS:
        return []
    items: list[dict[str, Any]] = []
    try:
        with SessionLocal() as db:
            q = db.query(FinancialTransaction).order_by(FinancialTransaction.transaction_date.desc())
            if market_user_id:
                q = q.filter(FinancialTransaction.counterparty_id == int(market_user_id))
            rows = q.limit(limit).all()
            for row in rows:
                cents = int(float(row.amount or 0) * 100)
                entry = {
                    "source_type": "financial_transaction",
                    "source_id": row.id,
                    "track": track or str(row.transaction_type or "manual"),
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
    except OPERATIONAL_ERRORS:
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
        from app.services.user_cs_crm_store import list_crm_invoices

        crm = list_crm_invoices(market_user_id=market_user_id, limit=cap)
        rows = crm.get("items") if isinstance(crm, dict) else []
        items = [_ledger_item_from_invoice(r) for r in rows if isinstance(r, dict)]
        if track:
            items = [x for x in items if x.get("track") == track]
        if items:
            return items[:cap]
    except OPERATIONAL_ERRORS:
        logger.debug("crm invoice ledger fallback skipped", exc_info=True)
    return _items_from_pipeline(market_user_id, limit=cap)


def summarize_ledger(*, market_user_id: int | None = None) -> dict[str, Any]:
    items = list_ledger(market_user_id=market_user_id, limit=2000)
    summary: dict[str, dict[str, int]] = {}
    for row in items:
        tr = str(row.get("track") or "manual")
        bucket = summary.setdefault(tr, {"count": 0, "amount_cents": 0})
        bucket["count"] += 1
        bucket["amount_cents"] += int(row.get("amount_cents") or 0)
    return summary


def archive_from_crm_invoice(inv: dict[str, Any], *, market_user_id: int | None = None) -> dict[str, Any]:
    uid = int(market_user_id or inv.get("market_user_id") or 0)
    entry = _ledger_item_from_invoice(inv)
    try:
        from app.db import SessionLocal
        from app.db.models.finance import FinancialTransaction

        amount_cents = int(entry.get("amount_cents") or 0)
        with SessionLocal() as db:
            txn = FinancialTransaction(
                transaction_type=str(entry.get("track") or "contract"),
                amount=Decimal(amount_cents) / Decimal(100),
                reference_type="crm_invoice",
                reference_id=int(inv.get("id") or 0) or None,
                description=entry.get("label"),
                status=str(entry.get("status") or "archived"),
                counterparty_id=uid or None,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(txn)
            db.commit()
            db.refresh(txn)
            return {"archived": True, "transaction_id": txn.id}
    except OPERATIONAL_ERRORS as exc:
        logger.debug("DB archive skipped: %s", exc)
        return {"archived": True, "transaction_id": None, "local_only": True, "entry": entry}


def rebuild_ledger_archive(*, market_user_id: int | None = None) -> dict[str, Any]:
    from app.services.user_cs_crm_store import list_crm_invoices

    data = list_crm_invoices(market_user_id=market_user_id, limit=500)
    rows = data.get("items") if isinstance(data, dict) else []
    rebuilt = 0
    for inv in rows:
        if isinstance(inv, dict):
            archive_from_crm_invoice(inv, market_user_id=market_user_id)
            rebuilt += 1
    return {"rebuilt": rebuilt, "market_user_id": market_user_id}
