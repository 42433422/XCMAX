"""内部客服：交付计划、到款核对与进度通知。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_delivery_on_doc(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else {}
    delivery.setdefault("milestones", [])
    delivery.setdefault("status", "planned")
    doc["delivery"] = delivery
    payment = doc.get("payment") if isinstance(doc.get("payment"), dict) else {}
    doc["payment"] = payment
    invoice = doc.get("invoice") if isinstance(doc.get("invoice"), dict) else {}
    doc["invoice"] = invoice
    return doc


def update_delivery_plan(
    doc: dict[str, Any],
    *,
    expected_delivery_at: str = "",
    milestones: list[dict[str, Any]] | None = None,
    start_delivery: bool = False,
) -> dict[str, Any]:
    doc = ensure_delivery_on_doc(doc)
    delivery = dict(doc["delivery"])
    if expected_delivery_at.strip():
        delivery["expected_delivery_at"] = expected_delivery_at.strip()
    if milestones is not None:
        delivery["milestones"] = milestones
    if start_delivery:
        delivery["status"] = "in_progress"
        delivery["started_at"] = delivery.get("started_at") or _now_iso()
    delivery["updated_at"] = _now_iso()
    doc["delivery"] = delivery
    return doc


def apply_contract_snapshot_to_doc(doc: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    fields = dict(doc.get("contract_fields") or {})
    fields.update({k: str(v) for k, v in values.items() if v is not None})
    doc["contract_fields"] = fields
    amount = str(values.get("total_amount_number") or "").strip()
    if amount:
        payment = dict(doc.get("payment") or {})
        try:
            payment["contract_amount_cents"] = int(float(amount.replace(",", "")) * 100)
        except ValueError:
            pass
        doc["payment"] = payment
    return doc


def build_delivery_progress_message(doc: dict[str, Any], *, client_name: str = "") -> str:
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else {}
    client = client_name or str(doc.get("erp_customer_name") or doc.get("username") or "客户")
    status = str(delivery.get("status") or "planned")
    expected = str(delivery.get("expected_delivery_at") or "").strip()
    lines = [f"【交付进度】{client}", f"当前状态：{status}"]
    if expected:
        lines.append(f"预计交付：{expected[:10]}")
    milestones = delivery.get("milestones") if isinstance(delivery.get("milestones"), list) else []
    done = sum(1 for m in milestones if isinstance(m, dict) and m.get("done"))
    if milestones:
        lines.append(f"里程碑：{done}/{len(milestones)} 已完成")
    return "\n".join(lines)


def try_confirm_payment_and_invoice(
    market_user_id: int,
    doc: dict[str, Any],
    *,
    message_texts: list[str] | None = None,
    force: bool = False,
    payment_reference: str = "",
) -> dict[str, Any]:
    doc = ensure_delivery_on_doc(doc)
    payment = dict(doc.get("payment") or {})
    ref = (payment_reference or "").strip()
    detected = force
    if not detected and ref:
        detected = True
    if not detected and message_texts:
        pattern = re.compile(r"(已付|到账|转账|支付成功|payment)", re.I)
        detected = any(pattern.search(str(t)) for t in message_texts)
    outcome: dict[str, Any] = {
        "payment_detected": detected,
        "invoice_created": False,
        "payment": payment,
        "invoice": doc.get("invoice"),
        "market_payment": None,
        "error": "",
    }
    if not detected:
        return outcome
    payment["confirmed_at"] = _now_iso()
    payment["status"] = "paid"
    if ref:
        payment["reference"] = ref
    outcome["payment"] = payment
    if not doc.get("invoice"):
        try:
            from app.services.tax_invoice_provider import issue_crm_invoice_for_pipeline

            doc = issue_crm_invoice_for_pipeline(doc)
            outcome["invoice"] = doc.get("invoice")
            outcome["invoice_created"] = bool(outcome["invoice"])
        except Exception as exc:
            outcome["error"] = str(exc)[:300]
    return outcome
