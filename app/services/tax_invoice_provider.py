"""税务开票适配器（金税/百望云 stub）。"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from typing import Any


class TaxInvoiceProvider(ABC):
    @abstractmethod
    def issue_invoice(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class StubTaxInvoiceProvider(TaxInvoiceProvider):
    def issue_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "stub",
            "invoice_no": f"STUB-{uuid.uuid4().hex[:10].upper()}",
            "status": "issued",
            "amount_cents": payload.get("amount_cents"),
        }


class BaiwangTaxInvoiceProvider(TaxInvoiceProvider):
    def issue_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "baiwang",
            "invoice_no": f"BW-{uuid.uuid4().hex[:12].upper()}",
            "status": "issued",
            "amount_cents": payload.get("amount_cents"),
            "external_ref": os.environ.get("BAIWANG_SANDBOX", "1"),
        }


def get_tax_invoice_provider() -> TaxInvoiceProvider:
    raw = (os.environ.get("TAX_INVOICE_PROVIDER") or "stub").strip().lower()
    if raw in ("baiwang", "百望"):
        return BaiwangTaxInvoiceProvider()
    return StubTaxInvoiceProvider()


def issue_crm_invoice_for_pipeline(doc: dict[str, Any]) -> dict[str, Any]:
    from app.services.user_cs_crm_store import create_invoice_for_opportunity

    opp_id = int(doc.get("crm_opportunity_id") or 0)
    if opp_id <= 0:
        raise ValueError("crm_opportunity_id required")
    payment = doc.get("payment") if isinstance(doc.get("payment"), dict) else {}
    amount = payment.get("contract_amount_cents")
    provider = get_tax_invoice_provider()
    issued = provider.issue_invoice(
        {
            "amount_cents": amount,
            "market_user_id": doc.get("market_user_id"),
            "payment_reference": payment.get("reference") or payment.get("out_trade_no"),
        }
    )
    inv = create_invoice_for_opportunity(
        opp_id,
        amount_cents=int(amount) if amount is not None else None,
        payment_reference=str(issued.get("invoice_no") or ""),
        quote_id=int(doc.get("crm_quote_id") or 0) or None,
    )
    doc = dict(doc)
    doc["crm_invoice_id"] = inv.get("id")
    doc["invoice"] = {
        "id": inv.get("id"),
        "invoice_no": inv.get("invoice_no") or issued.get("invoice_no"),
        "status": inv.get("status"),
        "amount_cents": inv.get("amount_cents"),
        "provider": issued.get("provider"),
    }
    try:
        from app.services.finance_unified_archive import archive_from_crm_invoice

        archive_from_crm_invoice({**inv, "market_user_id": int(doc.get("market_user_id") or 0)})
    except Exception:
        import logging

        logging.getLogger(__name__).exception("finance archive after pipeline tax invoice")
    return doc
