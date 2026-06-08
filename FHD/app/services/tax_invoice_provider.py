"""自建 Stub 税控 / CRM 发票开具。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def issue_crm_invoice_for_pipeline(doc: dict[str, Any]) -> dict[str, Any]:
    from app.services.user_cs_crm_store import create_crm_invoice_for_pipeline

    doc = dict(doc)
    uid = int(doc.get("market_user_id") or 0)
    payment = doc.get("payment") if isinstance(doc.get("payment"), dict) else {}
    amount_cents = int(payment.get("contract_amount_cents") or 0)
    inv = create_crm_invoice_for_pipeline(
        uid,
        opportunity_id=int(doc.get("crm_opportunity_id") or 0) or None,
        amount_cents=amount_cents,
        username=str(doc.get("username") or ""),
    )
    doc["invoice"] = inv
    doc["crm_invoice_id"] = int(inv.get("id") or 0)
    doc["invoice_no"] = str(inv.get("invoice_no") or "")
    return doc
