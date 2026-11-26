"""模型支付订单：本地 JSON 落盘，供异步通知幂等更新（沙箱/单机够用，生产请换数据库）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_data_dir

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def order_store_path() -> Path:
    custom = (os.environ.get("MODEL_PAYMENT_ORDER_STORE_PATH") or "").strip()
    if custom:
        return Path(custom)
    return Path(get_data_dir()) / "model_payment_orders.json"


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_state() -> dict[str, Any]:
    return {"orders": {}, "entitlements": {}, "unmatched_notifications": {}}


def _load() -> dict[str, Any]:
    p = order_store_path()
    if not p.is_file():
        return _empty_state()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("payment ledger root must be a mapping")
            data.setdefault("orders", {})
            if not isinstance(data["orders"], dict):
                raise ValueError("payment orders must be a mapping")
            data.setdefault("entitlements", {})
            if not isinstance(data["entitlements"], dict):
                raise ValueError("payment entitlements must be a mapping")
            data.setdefault("unmatched_notifications", {})
            if not isinstance(data["unmatched_notifications"], dict):
                # Payment evidence must not be silently discarded or overwritten.
                raise ValueError("unmatched payment evidence has invalid schema")
            return data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        # An unreadable existing ledger is not an empty payment ledger:
        # treating it as empty could overwrite valid paid orders or evidence.
        logger.error("payment order ledger unreadable: %s", e)
        raise


def _atomic_write(p: Path, payload: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    if os.name == "posix":
        directory_fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def record_checkout_pending(
    *,
    out_trade_no: str,
    plan_id: str,
    amount_cents: int,
    amount_yuan: str,
    local_user_id: int | None = None,
    tenant_id: int | None = None,
) -> None:
    """预下单成功后写入待支付订单。"""
    with _lock:
        data = _load()
        orders: dict[str, Any] = data["orders"]
        row: dict[str, Any] = {
            "out_trade_no": out_trade_no,
            "tenant_id": tenant_id,
            "plan_id": plan_id,
            "amount_cents": int(amount_cents),
            "amount_yuan": amount_yuan,
            "status": "pending_payment",
            "trade_no": None,
            "created_at": _utc_iso(),
            "paid_at": None,
            "notify_count": 0,
            "last_notify_at": None,
        }
        if local_user_id is not None:
            row["local_user_id"] = int(local_user_id)
        if out_trade_no in orders or any(
            item.get("out_trade_no") == out_trade_no
            for item in data["unmatched_notifications"].values()
            if isinstance(item, dict)
        ):
            raise ValueError("payment_order_requires_manual_identity_reconciliation")
        orders[out_trade_no] = row
        _atomic_write(order_store_path(), data)
    logger.info("[model-payment] order pending out_trade_no=%s plan_id=%s", out_trade_no, plan_id)


def apply_notify_paid(
    *,
    out_trade_no: str,
    trade_no: str,
    total_amount: str,
) -> tuple[str, dict[str, Any] | None]:
    """
    验签通过后调用：金额一致则置为 paid，重复通知幂等。

    返回 (reason, order_snapshot)；reason 取值：
    marked_paid | already_paid | fulfillment_pending | unknown_order | amount_mismatch | trade_mismatch
    | invalid_notify | reconciliation_required
    """
    with _lock:
        data = _load()
        orders: dict[str, Any] = data["orders"]
        if not out_trade_no.strip() or not trade_no.strip() or not total_amount.strip():
            return "invalid_notify", None
        o = orders.get(out_trade_no)
        unmatched: dict[str, Any] = data.setdefault("unmatched_notifications", {})
        if out_trade_no in orders and not isinstance(o, dict):
            return "order_record_corrupt", None
        if not o:
            # Signed unknown payments must leave durable, retry-idempotent
            # evidence. Never grant an entitlement or acknowledge the provider.
            digest = hashlib.sha256(
                json.dumps([out_trade_no, trade_no, total_amount], ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest()
            now = _utc_iso()
            entry = unmatched.get(digest)
            if not isinstance(entry, dict):
                entry = {
                    "out_trade_no": out_trade_no,
                    "trade_no": trade_no,
                    "total_amount": total_amount,
                    "first_seen_at": now,
                    "retry_count": 0,
                    "state": "requires_reconciliation",
                }
            entry["last_seen_at"] = now
            entry["retry_count"] = int(entry["retry_count"]) + 1
            unmatched[digest] = entry
            _atomic_write(order_store_path(), data)
            logger.error(
                "[model-payment] verified unmatched notification persisted out_trade_no=%s",
                out_trade_no,
            )
            return "unknown_order", None

        # A newly located merchant order cannot silently consume a previously
        # quarantined provider payment. Reconciliation must be explicit.
        if any(
            item.get("out_trade_no") == out_trade_no
            for item in unmatched.values()
            if isinstance(item, dict)
        ):
            return "reconciliation_required", dict(o)
        # A provider trade identity may not pay two different local orders.
        if any(
            str(existing.get("trade_no") or "").strip() == trade_no
            for key, existing in orders.items()
            if key != out_trade_no and isinstance(existing, dict)
        ):
            return "trade_mismatch", dict(o)

        try:
            expected_yuan = f"{int(o['amount_cents']) / 100:.2f}"
        except (TypeError, ValueError, KeyError):
            expected_yuan = str(o.get("amount_yuan") or "")

        if total_amount != expected_yuan:
            logger.warning(
                "[model-payment] notify: 金额不一致 out_trade_no=%s expected=%s got=%s",
                out_trade_no,
                expected_yuan,
                total_amount,
            )
            return "amount_mismatch", dict(o)

        # A replay may only acknowledge the provider transaction originally
        # bound to this order. A different signed trade ID is not the same
        # payment, even when the amount and merchant order number match.
        saved_trade_no = str(o.get("trade_no") or "").strip()
        if saved_trade_no and trade_no != saved_trade_no:
            logger.error(
                "[model-payment] notify trade identity conflict for out_trade_no=%s",
                out_trade_no,
            )
            return "trade_mismatch", dict(o)

        # A delayed paid callback cannot undo a closed/refunded state or
        # override an unresolved refund. Hold the identity for reconciliation.
        if o.get("status") in {
            "closed",
            "refunded",
            "partially_refunded",
            "refund_requested",
            "refund_pending_reconciliation",
        }:
            return "terminal_order_conflict", dict(o)

        now = _utc_iso()
        if o.get("status") == "paid":
            o["notify_count"] = int(o.get("notify_count") or 0) + 1
            o["last_notify_at"] = now
            _atomic_write(order_store_path(), data)
            return "already_paid", dict(o)

        o["notify_count"] = int(o.get("notify_count") or 0) + 1
        o["last_notify_at"] = now
        o["status"] = "paid_pending_fulfillment"
        o["trade_no"] = trade_no
        o["paid_at"] = o.get("paid_at") or now
        # Freeze the verified payment before applying the existing license. A
        # retry after a process/write failure keeps the original trial deadline.
        _atomic_write(order_store_path(), data)

        plan_id = str(o.get("plan_id") or "")
        if not _apply_saas_subscription_if_needed(
            plan_id=plan_id, local_user_id=o.get("local_user_id"), paid_at=o["paid_at"]
        ):
            return "fulfillment_pending", dict(o)
        o["status"] = "paid"
        ent_snapshot: dict[str, Any] | None = None
        if plan_id:
            ent_snapshot = _grant_entitlement_inplace(
                data,
                plan_id=plan_id,
                out_trade_no=out_trade_no,
                trade_no=trade_no,
                paid_at=o["paid_at"],
            )

        snap = dict(o)
        if ent_snapshot is not None:
            snap["entitlement"] = ent_snapshot
        _atomic_write(order_store_path(), data)
        logger.info(
            "[model-payment] order paid out_trade_no=%s trade_no=%s plan_id=%s purchase_count=%s",
            out_trade_no,
            trade_no,
            plan_id,
            (ent_snapshot or {}).get("purchase_count"),
        )
        return "marked_paid", snap


def _apply_saas_subscription_if_needed(*, plan_id: str, local_user_id: Any, paid_at: str) -> bool:
    """SaaS 套餐支付成功后绑定 tenants.plan_id。"""
    if not str(plan_id or "").startswith("saas-"):
        return True
    try:
        uid = int(local_user_id)
    except (TypeError, ValueError):
        logger.warning("[model-payment] saas plan paid but no local_user_id plan_id=%s", plan_id)
        return False
    try:
        from app.application.tenant_subscription_app_service import apply_paid_plan_for_user
        from app.infrastructure.billing.saas_plans import is_saas_plan_id, plan_by_id, trial_days

        if not is_saas_plan_id(plan_id):
            return False
        plan = plan_by_id(plan_id) or {}
        if plan.get("license_type") == "trial":
            expires = datetime.fromisoformat(paid_at) + timedelta(
                days=max(1, int(plan.get("duration_days") or trial_days()))
            )
            applied = apply_paid_plan_for_user(
                user_id=uid,
                plan_id=plan_id,
                sync_from_market=True,
                active_plan_expires_at=expires.isoformat(),
                verified_payment_grant=True,
            )
        else:
            applied = apply_paid_plan_for_user(
                user_id=uid, plan_id=plan_id, verified_payment_grant=True
            )
        if applied:
            logger.info(
                "[model-payment] saas subscription applied user_id=%s plan_id=%s",
                uid,
                plan_id,
            )
        return bool(applied)
    except RECOVERABLE_ERRORS:
        logger.exception(
            "[model-payment] saas subscription apply failed user_id=%s plan_id=%s",
            local_user_id,
            plan_id,
        )
        return False


def _grant_entitlement_inplace(
    data: dict[str, Any],
    *,
    plan_id: str,
    out_trade_no: str,
    trade_no: str,
    paid_at: str,
) -> dict[str, Any]:
    """在同一份 data 上累加一次已购权益。调用方负责最终 _atomic_write。"""
    ents: dict[str, Any] = data.setdefault("entitlements", {})
    cur = ents.get(plan_id) or {}
    purchase_count = int(cur.get("purchase_count") or 0) + 1
    record = {
        "plan_id": plan_id,
        "purchase_count": purchase_count,
        "first_paid_at": cur.get("first_paid_at") or paid_at,
        "last_paid_at": paid_at,
        "last_out_trade_no": out_trade_no,
        "last_trade_no": trade_no,
    }
    ents[plan_id] = record
    return dict(record)


def list_entitlements() -> list[dict[str, Any]]:
    """返回已购权益（按 last_paid_at 倒序）。"""
    with _lock:
        data = _load()
    ents: dict[str, Any] = data.get("entitlements") or {}
    items = [dict(v) for v in ents.values() if isinstance(v, dict)]
    items.sort(key=lambda r: str(r.get("last_paid_at") or ""), reverse=True)
    return items


def get_entitlement(plan_id: str) -> dict[str, Any] | None:
    """按 plan_id 查已购记录；未购返回 None。"""
    if not plan_id:
        return None
    with _lock:
        data = _load()
    ents: dict[str, Any] = data.get("entitlements") or {}
    record = ents.get(plan_id)
    if isinstance(record, dict):
        return dict(record)
    return None


def list_orders() -> list[dict[str, Any]]:
    """本地订单记录快照（按创建时间升序）。"""
    with _lock:
        data = _load()
    orders = data.get("orders")
    items = [dict(v) for v in (orders or {}).values() if isinstance(v, dict)]
    items.sort(key=lambda r: str(r.get("created_at") or ""))
    return items


def get_order(out_trade_no: str) -> dict[str, Any] | None:
    """读取本地订单记录快照。"""
    if not out_trade_no:
        return None
    with _lock:
        data = _load()
    o = (data.get("orders") or {}).get(out_trade_no)
    return dict(o) if isinstance(o, dict) else None


def update_order_status(
    *,
    out_trade_no: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """原地更新订单状态（closed / refunded 等）。找不到返回 None。"""
    if not out_trade_no:
        return None
    with _lock:
        data = _load()
        orders: dict[str, Any] = data.setdefault("orders", {})
        o = orders.get(out_trade_no)
        if not isinstance(o, dict):
            return None
        o["status"] = status
        o["updated_at"] = _utc_iso()
        if extra:
            o.update(
                {
                    k: v
                    for k, v in extra.items()
                    if k not in {"local_user_id", "tenant_id", "out_trade_no"}
                }
            )
        _atomic_write(order_store_path(), data)
        return dict(o)


def count_orders() -> int:
    """当前 JSON 订单存储中的订单总数（供诊断接口展示）。"""
    with _lock:
        data = _load()
    orders = data.get("orders")
    return len(orders) if isinstance(orders, dict) else 0


def json_store_has_unmigrated_orders() -> bool:
    """本地 JSON 订单文件是否仍存有订单。

    历史兼容查询，仅判断本地 JSON，不表示 PostgreSQL 迁移已实现。
    文件不存在或无订单时返回 ``False``。
    """
    if not order_store_path().is_file():
        return False
    with _lock:
        data = _load()
    orders = data.get("orders")
    return bool(isinstance(orders, dict) and orders)


def list_unmatched_notifications() -> list[dict[str, Any]]:
    """Read-only durable evidence for manual gateway reconciliation.

    This JSON adapter is single-host legacy; it does not prove PostgreSQL
    multi-process exactly-once semantics or independently verified settlement.
    """
    with _lock:
        entries = _load().get("unmatched_notifications", {})
    return [dict(item) for item in entries.values() if isinstance(item, dict)]


def reserve_refund_attempt(
    *, out_trade_no: str, out_request_no: str, amount_cents: int
) -> tuple[str, dict[str, Any] | None]:
    """Atomically reserve one distinct refund request in the original ledger.

    No provider request may be made unless this durable claim is committed.
    Pending or unknown provider outcomes cannot be auto-replayed. This is a
    single-process JSON legacy safeguard, not PostgreSQL multi-process safety.
    """
    if (
        not out_trade_no
        or not out_request_no
        or len(out_request_no) > 64
        or type(amount_cents) is not int
        or amount_cents <= 0
    ):
        return "refund_request_invalid", None
    with _lock:
        state = _load()
        order = state["orders"].get(out_trade_no)
        if not isinstance(order, dict):
            return "refund_order_missing", None
        if order.get("status") not in {"paid", "partially_refunded"}:
            return "refund_order_not_settled", dict(order)
        if type(order.get("amount_cents")) is not int or order["amount_cents"] <= 0:
            return "refund_order_amount_missing", dict(order)
        attempts = order.setdefault("refund_attempts", {})
        if not isinstance(attempts, dict):
            return "refund_history_corrupt", dict(order)
        if out_request_no in attempts:
            existing = attempts[out_request_no]
            return "refund_request_replay", dict(existing) if isinstance(existing, dict) else None
        confirmed = 0
        for prior in attempts.values():
            if not isinstance(prior, dict):
                return "refund_history_corrupt", None
            if prior.get("state") != "confirmed":
                return "refund_requires_reconciliation", dict(order)
            if type(prior.get("amount_cents")) is not int or prior["amount_cents"] < 0:
                return "refund_history_corrupt", None
            confirmed += prior["amount_cents"]
        if confirmed + amount_cents > order["amount_cents"]:
            return "refund_amount_exceeds_original", dict(order)
        attempts[out_request_no] = {
            "out_request_no": out_request_no,
            "amount_cents": amount_cents,
            "state": "pending_provider_confirmation",
            "created_at": _utc_iso(),
        }
        order["status"] = "refund_pending_reconciliation"
        _atomic_write(order_store_path(), state)
        return "refund_reserved", dict(attempts[out_request_no])


def observe_refund_provider_result(
    *, out_trade_no: str, out_request_no: str, provider_reported_success: bool
) -> bool:
    """Persist an observation, never confuse provider response with settlement."""
    with _lock:
        state = _load()
        order = state["orders"].get(out_trade_no)
        attempt = (
            (order.get("refund_attempts") or {}).get(out_request_no)
            if isinstance(order, dict)
            else None
        )
        if not isinstance(attempt, dict) or attempt.get("state") not in {
            "pending_provider_confirmation",
            "provider_reported_success",
            "provider_response_unknown",
        }:
            return False
        attempt["state"] = (
            "provider_reported_success"
            if provider_reported_success
            else "provider_response_unknown"
        )
        attempt["last_provider_response_at"] = _utc_iso()
        _atomic_write(order_store_path(), state)
        return True


def confirm_refund_from_provider_query(
    *, out_trade_no: str, out_request_no: str, amount_cents: int
) -> tuple[str, dict[str, Any] | None]:
    """Confirm only the same original refund after a separate gateway query.

    This verifies the provider query identity and requested amount. It does NOT
    certify bank settlement or financial profit; independent external evidence
    is still required for those claims.
    """
    with _lock:
        state = _load()
        order = state["orders"].get(out_trade_no)
        attempt = (
            (order.get("refund_attempts") or {}).get(out_request_no)
            if isinstance(order, dict)
            else None
        )
        if not isinstance(order, dict) or not isinstance(attempt, dict):
            return "refund_request_missing", None
        if type(amount_cents) is not int or attempt.get("amount_cents") != amount_cents:
            return "refund_amount_mismatch", dict(attempt)
        if attempt.get("state") == "confirmed":
            return "already_confirmed", dict(attempt)
        if attempt.get("state") not in {
            "pending_provider_confirmation",
            "provider_reported_success",
            "provider_response_unknown",
        }:
            return "refund_request_invalid_state", dict(attempt)
        attempts = order["refund_attempts"]
        total = sum(
            x["amount_cents"]
            for x in attempts.values()
            if isinstance(x, dict) and (x.get("state") == "confirmed" or x is attempt)
        )
        if type(order.get("amount_cents")) is not int or total > order["amount_cents"]:
            return "refund_amount_exceeds_original", dict(attempt)
        attempt["state"] = "confirmed"
        attempt["confirmed_at"] = _utc_iso()
        order["refunded_amount_cents"] = total
        order["status"] = "refunded" if total == order["amount_cents"] else "partially_refunded"
        _atomic_write(order_store_path(), state)
        return "refund_confirmed", dict(attempt)
