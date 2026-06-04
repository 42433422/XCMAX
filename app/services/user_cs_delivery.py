"""签约后交付：预期时间、制作里程碑、到款检测与自动账单。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MILESTONES: list[dict[str, Any]] = [
    {"id": "scope", "label": "需求与范围确认", "weight": 10, "done": False},
    {"id": "design", "label": "方案与原型设计", "weight": 15, "done": False},
    {"id": "dev", "label": "定制开发实现", "weight": 40, "done": False},
    {"id": "qa", "label": "联调与测试", "weight": 20, "done": False},
    {"id": "accept", "label": "验收与交付上线", "weight": 15, "done": False},
]

_PAYMENT_HINT_RE = re.compile(
    r"已付款|已付清|到款|到账|打款|转账成功|款项已|支付了|付款完成|汇款",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_progress_percent(milestones: list[dict[str, Any]]) -> int:
    total = 0
    done = 0
    for m in milestones:
        try:
            w = int(m.get("weight") or 0)
        except (TypeError, ValueError):
            w = 0
        total += w
        if m.get("done"):
            done += w
    if total <= 0:
        return 0
    return min(100, max(0, round(done * 100 / total)))


def default_delivery_block(*, expected_delivery_at: str = "") -> dict[str, Any]:
    now = _now_iso()
    return {
        "expected_delivery_at": (expected_delivery_at or "").strip()[:32],
        "milestones": [dict(m) for m in DEFAULT_MILESTONES],
        "progress_percent": 0,
        "started_at": None,
        "completed_at": None,
        "last_progress_notice_at": None,
        "updated_at": now,
    }


def ensure_delivery_on_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """已签约及之后阶段：确保 pipeline 含 delivery / payment 结构。"""
    stage = str(doc.get("stage") or "idle")
    from app.services.user_cs_pipeline import _stage_rank

    if _stage_rank(stage) < _stage_rank("signed"):
        return doc
    doc = dict(doc)
    delivery = doc.get("delivery")
    if not isinstance(delivery, dict) or not delivery.get("milestones"):
        doc["delivery"] = default_delivery_block()
    payment = doc.get("payment")
    if not isinstance(payment, dict):
        doc["payment"] = {
            "contract_amount_cents": None,
            "currency": "CNY",
            "status": "pending",
            "detected_at": None,
            "confirmed_at": None,
            "reference": "",
        }
    return doc


def apply_contract_snapshot_to_doc(
    doc: dict[str, Any], contract_values: dict[str, Any] | None
) -> dict[str, Any]:
    """从合同字段同步金额到 payment，便于对账出账。"""
    if not contract_values:
        return doc
    doc = ensure_delivery_on_doc(doc)
    raw = str(contract_values.get("total_amount_number") or "").strip().replace(",", "")
    payment = dict(doc.get("payment") or {})
    if raw:
        try:
            cents = int(round(float(raw) * 100))
            payment["contract_amount_cents"] = cents
        except ValueError:
            pass
    out_no = str(
        contract_values.get("expected_out_trade_no") or contract_values.get("out_trade_no") or ""
    ).strip()
    if out_no:
        payment["expected_out_trade_no"] = out_no[:64]
    party = str(contract_values.get("party_a_name") or "").strip()
    if party and not payment.get("payer_name"):
        payment["payer_name"] = party[:128]
    doc["payment"] = payment
    doc["contract_snapshot"] = {
        "party_a_name": party,
        "total_amount_number": raw,
        "sign_date": str(contract_values.get("sign_date") or "")[:32],
        "main_function_list": str(contract_values.get("main_function_list") or "")[:2000],
        "synced_at": _now_iso(),
    }
    return doc


def update_delivery_plan(
    doc: dict[str, Any],
    *,
    expected_delivery_at: str = "",
    milestones: list[dict[str, Any]] | None = None,
    start_delivery: bool = False,
) -> dict[str, Any]:
    doc = ensure_delivery_on_doc(doc)
    delivery = dict(doc.get("delivery") or {})
    if expected_delivery_at:
        delivery["expected_delivery_at"] = expected_delivery_at.strip()[:32]
    if milestones is not None:
        delivery["milestones"] = milestones
    delivery["progress_percent"] = compute_progress_percent(list(delivery.get("milestones") or []))
    now = _now_iso()
    if start_delivery and not delivery.get("started_at"):
        delivery["started_at"] = now
    if delivery["progress_percent"] >= 100 and not delivery.get("completed_at"):
        delivery["completed_at"] = now
    delivery["updated_at"] = now
    doc["delivery"] = delivery
    return doc


def detect_payment_in_messages(texts: list[str]) -> tuple[bool, str]:
    blob = "\n".join(texts)
    if not blob.strip():
        return False, ""
    m = _PAYMENT_HINT_RE.search(blob)
    if not m:
        return False, ""
    return True, m.group(0)[:64]


def build_delivery_progress_message(doc: dict[str, Any], *, client_name: str = "") -> str:
    delivery = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else {}
    milestones = list(delivery.get("milestones") or [])
    pct = int(delivery.get("progress_percent") or 0)
    expected = str(delivery.get("expected_delivery_at") or "").strip()
    who = (client_name or "您好").strip()
    if who and not who.endswith("好") and who != "您好":
        greeting = f"{who}，您好"
    else:
        greeting = who if who else "您好"

    lines = [
        f"{greeting}！",
        "",
        "向您同步定制软件制作进度：",
        f"· 当前整体进度：{pct}%",
    ]
    if expected:
        lines.append(f"· 预计交付时间：{expected}")
    lines.append("· 阶段明细：")
    for m in milestones:
        mark = "✓" if m.get("done") else "○"
        lines.append(f"  {mark} {m.get('label', '')}")
    lines.extend(["", "如有疑问请在本群留言，我们会及时回复。"])
    return "\n".join(lines)


def try_confirm_payment_and_invoice(
    market_user_id: int,
    doc: dict[str, Any],
    *,
    message_texts: list[str] | None = None,
    force: bool = False,
    payment_reference: str = "",
) -> dict[str, Any]:
    """
    检测群聊到款话术或 force 确认后，写入 payment 并自动创建 CRM 账单。
    返回 { payment_detected, invoice_created, invoice, payment, error }
    """
    from app.services.user_cs_crm_store import (
        create_invoice_for_opportunity,
        get_crm_bundle_for_market_user,
    )

    doc = ensure_delivery_on_doc(doc)
    payment = dict(doc.get("payment") or {})
    result: dict[str, Any] = {
        "payment_detected": False,
        "invoice_created": False,
        "invoice": None,
        "payment": payment,
        "error": "",
    }

    detected = False
    hint = (payment_reference or "").strip()
    gateway_verified = False
    matched_order: dict[str, Any] | None = None

    expected_out = str(payment.get("expected_out_trade_no") or "").strip()
    amount_cents = payment.get("contract_amount_cents")
    if amount_cents is None:
        qd = doc.get("quote_draft") if isinstance(doc.get("quote_draft"), dict) else {}
        amount_cents = qd.get("amount_cents")
    try:
        amount_cents_int = int(amount_cents) if amount_cents is not None else None
    except (TypeError, ValueError):
        amount_cents_int = None

    try:
        from app.services.user_cs_market_payment import fetch_payment_summary_for_cs

        market_pay = fetch_payment_summary_for_cs(
            int(market_user_id),
            min_amount_cents=amount_cents_int,
            expected_out_trade_no=expected_out,
        )
        result["market_payment"] = {
            "ok": market_pay.get("ok"),
            "source": market_pay.get("source"),
            "error": market_pay.get("error") or "",
        }
        if market_pay.get("payment_verified") and isinstance(market_pay.get("matched_order"), dict):
            gateway_verified = True
            matched_order = market_pay["matched_order"]
            detected = True
            hint = str(matched_order.get("out_trade_no") or hint or "gateway_paid")[:200]
            payment["gateway_status"] = str(matched_order.get("status") or "paid")
            payment["out_trade_no"] = str(matched_order.get("out_trade_no") or "")[:64]
            payment["pay_type"] = str(matched_order.get("pay_type") or "")[:32]
            payment["gateway_source"] = market_pay.get("source") or ""
    except Exception:
        logger.exception("market payment verify failed uid=%s", market_user_id)

    if not detected and not hint and message_texts:
        detected, hint = detect_payment_in_messages(message_texts)
    if force:
        detected = True
        if not hint:
            hint = "manual_confirm"

    if not detected and payment.get("status") not in ("detected", "confirmed", "paid"):
        return result

    now = _now_iso()
    if payment.get("status") not in ("confirmed", "paid"):
        payment["status"] = "confirmed" if force else "detected"
        payment["detected_at"] = payment.get("detected_at") or now
        if force or payment["status"] == "confirmed":
            payment["confirmed_at"] = now
        payment["reference"] = hint[:200]
    result["payment_detected"] = True
    result["payment"] = payment

    opp_id = int(doc.get("crm_opportunity_id") or 0)
    if opp_id <= 0:
        bundle = get_crm_bundle_for_market_user(int(market_user_id))
        opp = bundle.get("opportunity") or {}
        opp_id = int(opp.get("id") or 0)

    if matched_order and amount_cents_int is None:
        raw_amt = matched_order.get("total_amount")
        if raw_amt is not None:
            try:
                amount_cents_int = int(round(float(str(raw_amt).replace(",", "")) * 100))
                payment["contract_amount_cents"] = amount_cents_int
            except ValueError:
                pass
    amount_cents = amount_cents_int

    if opp_id <= 0:
        result["error"] = "尚未建立 CRM 商机，请先同步 CRM"
        return result

    if doc.get("crm_invoice_id") and not force and not gateway_verified:
        inv_row = {"id": doc.get("crm_invoice_id"), "status": "issued"}
        result["invoice"] = inv_row
        result["invoice_created"] = True
        return result

    mp = result.get("market_payment") if isinstance(result.get("market_payment"), dict) else {}
    if mp.get("ok") and not gateway_verified and not force:
        payment["verification"] = "chat_heuristic"
        result["payment"] = payment
    elif gateway_verified:
        payment["verification"] = "gateway"
    elif force:
        payment["verification"] = "manual"

    try:
        inv = create_invoice_for_opportunity(
            opp_id,
            amount_cents=amount_cents,
            payment_reference=hint,
            quote_id=int(doc.get("crm_quote_id") or 0) or None,
        )
    except Exception as exc:
        logger.exception("create_invoice failed uid=%s", market_user_id)
        result["error"] = str(exc)[:300]
        return result

    if inv:
        payment["status"] = "paid"
        payment["invoice_id"] = inv.get("id")
        result["invoice_created"] = True
        result["invoice"] = inv
        doc["crm_invoice_id"] = inv.get("id")
        doc["invoice"] = {
            "id": inv.get("id"),
            "invoice_no": inv.get("invoice_no"),
            "status": inv.get("status"),
            "amount_cents": inv.get("amount_cents"),
            "issued_at": inv.get("issued_at"),
        }
        try:
            from app.services.finance_unified_archive import archive_from_crm_invoice

            archive_from_crm_invoice({**inv, "market_user_id": int(market_user_id)})
        except Exception:
            logger.exception("finance archive after payment confirm uid=%s", market_user_id)

    result["payment"] = payment
    return result


def sync_delivery_crm(doc: dict[str, Any]) -> dict[str, Any]:
    """将 delivery / payment 同步到 CRM SQLite。"""
    try:
        from app.services.user_cs_crm_store import sync_delivery_and_invoice_from_pipeline

        return sync_delivery_and_invoice_from_pipeline(doc)
    except Exception:
        logger.exception("sync_delivery_crm failed")
        return doc


def on_pipeline_saved(doc: dict[str, Any]) -> dict[str, Any]:
    """save_pipeline 之后：补齐交付结构并同步 CRM。"""
    stage = str(doc.get("stage") or "idle")
    from app.services.user_cs_pipeline import _stage_rank

    if _stage_rank(stage) < _stage_rank("signed"):
        return doc
    doc = ensure_delivery_on_doc(doc)
    if stage in ("delivering", "signed") and not doc.get("delivery", {}).get("started_at"):
        if stage == "delivering":
            doc = update_delivery_plan(doc, start_delivery=True)
    doc = sync_delivery_crm(doc)
    return doc
