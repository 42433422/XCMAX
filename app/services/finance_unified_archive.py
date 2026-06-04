"""XCAGI 自建财务：合同轨 + Token 轨统一归档（不依赖用友/金蝶）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

logger = logging.getLogger(__name__)

TrackKind = Literal["contract", "token", "manual"]

_ARCHIVE_REF_TYPES = frozenset(
    {"cs_crm_invoice", "modstore_order", "pipeline_payment", "xcagi_finance_archive"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_key(source_type: str, source_id: int) -> tuple[str, int]:
    return (str(source_type or "").strip(), int(source_id))


def append_ledger_entry(
    *,
    track: TrackKind,
    source_type: str,
    source_id: int,
    amount_cents: int | None,
    market_user_id: int = 0,
    invoice_no: str = "",
    payment_ref: str = "",
    status: str = "confirmed",
    occurred_at: str | None = None,
    description: str = "",
    counterparty_name: str = "",
) -> dict[str, Any]:
    """幂等写入 financial_transactions（自建财务凭证）。"""
    st = str(source_type or "").strip()
    sid = int(source_id)
    if sid <= 0 or not st:
        raise ValueError("source_type and source_id required")

    from app.db.models.finance import FinancialTransaction
    from app.db.session import get_db

    when = _parse_dt(occurred_at) or _now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    cents = int(amount_cents or 0)
    amount_yuan = Decimal(cents) / Decimal(100)

    desc_parts = [f"[{track}] {st}#{sid}"]
    if invoice_no:
        desc_parts.append(f"inv={invoice_no}")
    if payment_ref:
        desc_parts.append(f"pay={payment_ref}")
    if description:
        desc_parts.append(description[:200])
    desc = " · ".join(desc_parts)[:2000]

    with get_db() as db:
        existing = (
            db.query(FinancialTransaction)
            .filter(
                FinancialTransaction.reference_type == st,
                FinancialTransaction.reference_id == sid,
            )
            .first()
        )
        if existing:
            return {"id": existing.id, "created": False, "track": track}

        row = FinancialTransaction(
            transaction_type="receipt",
            amount=amount_yuan,
            currency="CNY",
            reference_type=st,
            reference_id=sid,
            description=desc,
            transaction_date=when.replace(tzinfo=None),
            status=str(status or "confirmed")[:16],
            counterparty_name=(counterparty_name or "")[:128] or None,
            counterparty_id=int(market_user_id) if market_user_id > 0 else None,
            created_by="finance_unified_archive",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id, "created": True, "track": track}


def _crm_invoice_rows(market_user_id: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
    from app.services.user_cs_crm_store import _connect, ensure_crm_schema

    ensure_crm_schema()
    sql = """
        SELECT i.*, o.market_user_id, o.title AS opp_title
        FROM cs_crm_invoices i
        JOIN cs_crm_opportunities o ON o.id = i.opportunity_id
    """
    params: list[Any] = []
    if market_user_id is not None and int(market_user_id) > 0:
        sql += " WHERE o.market_user_id = ?"
        params.append(int(market_user_id))
    sql += " ORDER BY i.id DESC LIMIT ?"
    params.append(int(limit))
    rows: list[dict[str, Any]] = []
    with _connect() as conn:
        for row in conn.execute(sql, params).fetchall():
            rows.append(dict(row))
    return rows


def _token_order_rows(market_user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    from app.services.user_cs_market_payment import fetch_payment_summary_for_cs

    if market_user_id <= 0:
        return []
    summary = fetch_payment_summary_for_cs(market_user_id)
    if not summary.get("ok"):
        return []
    out: list[dict[str, Any]] = []
    for idx, order in enumerate(summary.get("paid_orders") or []):
        if not isinstance(order, dict):
            continue
        oid = order.get("id") or order.get("order_id") or (idx + 1)
        try:
            source_id = int(oid)
        except (TypeError, ValueError):
            source_id = idx + 1
        raw_amt = order.get("total_amount") or order.get("amount")
        cents = 0
        if raw_amt is not None:
            try:
                cents = int(round(float(str(raw_amt).replace(",", "")) * 100))
            except ValueError:
                pass
        out.append(
            {
                "source_type": "modstore_order",
                "source_id": source_id,
                "amount_cents": cents,
                "payment_ref": str(order.get("out_trade_no") or "")[:200],
                "status": str(order.get("status") or "paid"),
                "occurred_at": order.get("paid_at") or order.get("created_at"),
                "market_user_id": market_user_id,
            }
        )
        if len(out) >= limit:
            break
    return out


def _fin_txn_rows(
    market_user_id: int | None = None,
    track: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    from app.db.models.finance import FinancialTransaction
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(FinancialTransaction).filter(
            FinancialTransaction.reference_type.in_(tuple(_ARCHIVE_REF_TYPES))
        )
        if market_user_id is not None and int(market_user_id) > 0:
            q = q.filter(FinancialTransaction.counterparty_id == int(market_user_id))
        q = q.order_by(FinancialTransaction.transaction_date.desc()).limit(int(limit))
        return [r.to_dict() for r in q.all()]


def _invoice_to_entry(inv: dict[str, Any]) -> dict[str, Any]:
    uid = int(inv.get("market_user_id") or 0)
    return {
        "track": "contract",
        "source_type": "cs_crm_invoice",
        "source_id": int(inv.get("id") or 0),
        "amount_cents": int(inv.get("amount_cents") or 0),
        "invoice_no": str(inv.get("invoice_no") or ""),
        "payment_ref": str(inv.get("payment_reference") or ""),
        "status": str(inv.get("status") or ""),
        "occurred_at": inv.get("issued_at")
        or inv.get("payment_detected_at")
        or inv.get("created_at"),
        "market_user_id": uid,
        "counterparty_name": str(inv.get("opp_title") or "")[:128],
        "opportunity_id": int(inv.get("opportunity_id") or 0) or None,
        "pipeline_stage": "",
        "archived_in_fin_txn": False,
    }


def _order_to_entry(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "track": "token",
        "source_type": str(order.get("source_type") or "modstore_order"),
        "source_id": int(order.get("source_id") or 0),
        "amount_cents": int(order.get("amount_cents") or 0),
        "invoice_no": "",
        "payment_ref": str(order.get("payment_ref") or ""),
        "status": str(order.get("status") or "paid"),
        "occurred_at": order.get("occurred_at"),
        "market_user_id": int(order.get("market_user_id") or 0),
        "counterparty_name": "",
        "opportunity_id": None,
        "pipeline_stage": "",
        "archived_in_fin_txn": False,
    }


def _fin_to_entry(row: dict[str, Any]) -> dict[str, Any]:
    desc = str(row.get("description") or "")
    track: TrackKind = "manual"
    if desc.startswith("[contract]"):
        track = "contract"
    elif desc.startswith("[token]"):
        track = "token"
    amount = row.get("amount")
    cents = int(round(float(amount or 0) * 100)) if amount is not None else 0
    return {
        "track": track,
        "source_type": str(row.get("reference_type") or ""),
        "source_id": int(row.get("reference_id") or 0),
        "amount_cents": cents,
        "invoice_no": "",
        "payment_ref": "",
        "status": str(row.get("status") or ""),
        "occurred_at": row.get("transaction_date"),
        "market_user_id": int(row.get("counterparty_id") or 0),
        "counterparty_name": str(row.get("counterparty_name") or ""),
        "archived_in_fin_txn": True,
        "financial_transaction_id": row.get("id"),
    }


def list_ledger(
    *,
    market_user_id: int | None = None,
    track: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """合并合同轨 CRM 账单、Token 轨市场订单、已归档凭证（去重）。"""
    merged: dict[tuple[str, int], dict[str, Any]] = {}

    try:
        for inv in _crm_invoice_rows(market_user_id, limit=limit):
            e = _invoice_to_entry(inv)
            merged[_entry_key(e["source_type"], e["source_id"])] = e
    except Exception:
        logger.exception("list_ledger crm invoices failed")

    uid = int(market_user_id or 0)
    if uid > 0:
        try:
            for order in _token_order_rows(uid, limit=limit):
                e = _order_to_entry(order)
                k = _entry_key(e["source_type"], e["source_id"])
                if k not in merged:
                    merged[k] = e
        except Exception:
            logger.exception("list_ledger token orders failed uid=%s", uid)

    try:
        for row in _fin_txn_rows(market_user_id, track=track, limit=limit):
            e = _fin_to_entry(row)
            k = _entry_key(e["source_type"], e["source_id"])
            if k in merged:
                merged[k]["archived_in_fin_txn"] = True
                merged[k]["financial_transaction_id"] = e.get("financial_transaction_id")
            else:
                merged[k] = e
    except Exception:
        logger.exception("list_ledger financial_transactions failed")

    items = list(merged.values())
    if track in ("contract", "token", "manual"):
        items = [i for i in items if i.get("track") == track]

    def _sort_key(item: dict[str, Any]) -> str:
        return str(item.get("occurred_at") or "")

    items.sort(key=_sort_key, reverse=True)
    items = items[: int(limit)]
    return _enrich_ledger_items(items)


def _enrich_ledger_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补充 pipeline 阶段与商机 ID（按 market_user_id 缓存）。"""
    if not items:
        return items
    try:
        from app.services.user_cs_pipeline import load_pipeline
    except Exception:
        return items
    cache: dict[int, dict[str, Any]] = {}
    for item in items:
        uid = int(item.get("market_user_id") or 0)
        if uid <= 0:
            continue
        if uid not in cache:
            try:
                cache[uid] = load_pipeline(uid)
            except Exception:
                cache[uid] = {}
        doc = cache[uid]
        if not item.get("pipeline_stage"):
            item["pipeline_stage"] = str(doc.get("stage") or "")
        if not item.get("opportunity_id") and doc.get("crm_opportunity_id"):
            item["opportunity_id"] = int(doc.get("crm_opportunity_id") or 0) or None
        if not item.get("counterparty_name"):
            item["counterparty_name"] = str(
                doc.get("erp_customer_name") or doc.get("username") or ""
            )[:128]
    return items


def rebuild_ledger_archive(*, market_user_id: int | None = None) -> dict[str, Any]:
    """幂等：从 CRM 发票与 Token 订单重建 financial_transactions 归档。"""
    created = 0
    skipped = 0
    errors: list[str] = []
    try:
        invoices = _crm_invoice_rows(market_user_id, limit=5000)
    except Exception as exc:
        logger.exception("rebuild crm invoices failed")
        return {"created": 0, "skipped": 0, "errors": [str(exc)[:200]]}
    for inv in invoices:
        try:
            uid = int(inv.get("market_user_id") or 0)
            r = archive_from_crm_invoice(inv, market_user_id=uid)
            if r and r.get("created"):
                created += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"invoice#{inv.get('id')}: {exc}"[:120])

    try:
        from app.services.user_cs_pipeline import iter_pipeline_market_user_ids
    except Exception:
        iter_pipeline_market_user_ids = lambda: []  # type: ignore

    if market_user_id is not None and int(market_user_id) > 0:
        uids = [int(market_user_id)]
    else:
        uids = list(iter_pipeline_market_user_ids())

    for uid in uids:
        if int(uid) <= 0:
            continue
        try:
            for order in _token_order_rows(int(uid), limit=500):
                r = archive_from_modstore_order(order, market_user_id=int(uid))
                if r and r.get("created"):
                    created += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append(f"uid{uid} token: {exc}"[:120])

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors[:20],
        "finance_self_hosted": True,
    }


def summarize_ledger(
    *,
    market_user_id: int | None = None,
) -> dict[str, Any]:
    items = list_ledger(market_user_id=market_user_id, limit=5000)
    summary = {
        "contract": {"count": 0, "amount_cents": 0},
        "token": {"count": 0, "amount_cents": 0},
        "manual": {"count": 0, "amount_cents": 0},
        "archived_count": 0,
        "total_count": len(items),
    }
    for item in items:
        tr = str(item.get("track") or "manual")
        if tr not in summary:
            tr = "manual"
        summary[tr]["count"] += 1
        summary[tr]["amount_cents"] += int(item.get("amount_cents") or 0)
        if item.get("archived_in_fin_txn"):
            summary["archived_count"] += 1
    return summary


def map_voucher_ids_for_crm_invoices(invoice_ids: list[int]) -> dict[int, int]:
    """invoice_id -> financial_transactions.id（已归档凭证）。"""
    ids = [int(x) for x in invoice_ids if int(x or 0) > 0]
    if not ids:
        return {}
    try:
        from app.db.models.finance import FinancialTransaction
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                db.query(FinancialTransaction)
                .filter(
                    FinancialTransaction.reference_type == "cs_crm_invoice",
                    FinancialTransaction.reference_id.in_(ids),
                )
                .all()
            )
        out: dict[int, int] = {}
        for row in rows:
            rid = int(row.reference_id or 0)
            if rid > 0:
                out[rid] = int(row.id)
        return out
    except Exception:
        logger.debug("map_voucher_ids_for_crm_invoices failed", exc_info=True)
        return {}


def list_vouchers_for_crm_invoice(invoice_id: int) -> list[dict[str, Any]]:
    iid = int(invoice_id)
    if iid <= 0:
        return []
    try:
        from app.db.models.finance import FinancialTransaction
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                db.query(FinancialTransaction)
                .filter(
                    FinancialTransaction.reference_type == "cs_crm_invoice",
                    FinancialTransaction.reference_id == iid,
                )
                .order_by(FinancialTransaction.transaction_date.desc())
                .limit(20)
                .all()
            )
        return [r.to_dict() for r in rows]
    except Exception:
        logger.exception("list_vouchers_for_crm_invoice failed id=%s", iid)
        return []


def archive_from_crm_invoice(
    inv: dict[str, Any], *, market_user_id: int = 0
) -> dict[str, Any] | None:
    iid = int(inv.get("id") or 0)
    if iid <= 0:
        return None
    uid = int(market_user_id or inv.get("market_user_id") or 0)
    try:
        return append_ledger_entry(
            track="contract",
            source_type="cs_crm_invoice",
            source_id=iid,
            amount_cents=int(inv.get("amount_cents") or 0),
            market_user_id=uid,
            invoice_no=str(inv.get("invoice_no") or ""),
            payment_ref=str(inv.get("payment_reference") or ""),
            status=str(inv.get("status") or "issued"),
            occurred_at=str(inv.get("issued_at") or inv.get("created_at") or ""),
            counterparty_name=str(inv.get("opp_title") or inv.get("title") or "")[:128],
        )
    except Exception:
        logger.exception("archive_from_crm_invoice failed id=%s", iid)
        return None


def archive_from_modstore_order(
    order: dict[str, Any], *, market_user_id: int
) -> dict[str, Any] | None:
    try:
        sid = int(order.get("id") or order.get("order_id") or 0)
    except (TypeError, ValueError):
        sid = 0
    if sid <= 0:
        return None
    raw_amt = order.get("total_amount") or order.get("amount")
    cents = 0
    if raw_amt is not None:
        try:
            cents = int(round(float(str(raw_amt).replace(",", "")) * 100))
        except ValueError:
            pass
    try:
        return append_ledger_entry(
            track="token",
            source_type="modstore_order",
            source_id=sid,
            amount_cents=cents,
            market_user_id=int(market_user_id),
            payment_ref=str(order.get("out_trade_no") or "")[:200],
            status=str(order.get("status") or "paid"),
            occurred_at=str(order.get("paid_at") or order.get("created_at") or ""),
        )
    except Exception:
        logger.exception("archive_from_modstore_order failed")
        return None


def compute_finance_archive_coverage() -> dict[str, Any]:
    """O9 健康度：应归档 pipeline 是否已有 financial_transactions 凭证。"""
    import json

    from app.db.models.finance import FinancialTransaction
    from app.db.session import get_db
    from app.services.user_cs_pipeline import _STAGE_ORDER, _pipeline_roots

    need = 0
    archived = 0
    for root in _pipeline_roots():
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            stage = str(data.get("stage") or "idle")
            rank = _STAGE_ORDER.index(stage) if stage in _STAGE_ORDER else 0
            payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
            paid = payment.get("status") in ("paid", "confirmed", "detected") or data.get(
                "crm_invoice_id"
            )
            if rank < _STAGE_ORDER.index("signed") and not paid:
                continue
            if not data.get("crm_opportunity_id") and not data.get("crm_invoice_id"):
                continue
            need += 1
            inv_id = int(data.get("crm_invoice_id") or 0)
            if inv_id > 0:
                with get_db() as db:
                    hit = (
                        db.query(FinancialTransaction)
                        .filter(
                            FinancialTransaction.reference_type == "cs_crm_invoice",
                            FinancialTransaction.reference_id == inv_id,
                        )
                        .first()
                    )
                if hit:
                    archived += 1
                    continue
            uid = int(data.get("market_user_id") or 0)
            if uid > 0 and payment.get("out_trade_no"):
                with get_db() as db:
                    hit = (
                        db.query(FinancialTransaction)
                        .filter(
                            FinancialTransaction.reference_type == "modstore_order",
                            FinancialTransaction.counterparty_id == uid,
                        )
                        .first()
                    )
                if hit:
                    archived += 1

    ratio = 1.0 if need == 0 else round(archived / need, 4)
    return {
        "finance_self_hosted": True,
        "finance_archive_need": need,
        "finance_archive_done": archived,
        "finance_archive_coverage": ratio,
    }
