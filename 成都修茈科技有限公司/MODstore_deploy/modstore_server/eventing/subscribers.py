"""Cross-cutting NeuroBus subscribers.

The publishers in :mod:`modstore_server.payment_api`, :mod:`refund_api` and
the outbox dispatcher emit canonical domain events. Instead of every API
adding bespoke calls into the notification / metrics / audit modules, the
subscribers here own those side-effects and stay decoupled from the
emitting code.

Wiring is explicit (call :func:`install_default_subscribers`) so unit tests
can choose to keep the bus quiet, and so a future independent service can
import this module without auto-registering for the FastAPI process.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter

from modstore_server.eventing.contracts import (
    WALLET_BALANCE_CHANGED,
    WORKFLOW_EVENT_TRIGGER,
    canonical_event_name,
)
from modstore_server.eventing.events import DomainEvent
from modstore_server.eventing.global_bus import neuro_bus

logger = logging.getLogger(__name__)


EVENT_PUBLISHED_TOTAL = Counter(
    "modstore_domain_events_published_total",
    "Total domain events that flowed through the NeuroBus subscribers.",
    ("event", "outcome"),
)


_INSTALLED = False


def _safe_amount(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _on_event_metric(event: DomainEvent) -> None:
    EVENT_PUBLISHED_TOTAL.labels(event.event_name, "received").inc()


def _on_event_audit(event: DomainEvent) -> None:
    """Structured audit log for every domain event.

    Uses ``logger.info`` with extra fields so log shippers can parse the
    record without us inventing yet another sink. The existing JSONL outbox
    plus the durable :class:`OutboxEvent` table remain authoritative.
    """

    logger.info(
        "domain-event %s subject=%s producer=%s id=%s",
        event.event_name,
        event.subject_id,
        event.producer,
        event.event_id,
        extra={
            "event_name": event.event_name,
            "event_subject": event.subject_id,
            "event_producer": event.producer,
            "event_id": event.event_id,
            "event_version": event.event_version,
        },
    )


def _on_payment_paid(event: DomainEvent) -> None:
    if canonical_event_name(event.event_name) != "payment.paid":
        return
    payload = event.payload or {}
    user_id = payload.get("user_id")
    try:
        user_id = int(user_id) if user_id is not None else 0
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return
    try:
        from modstore_server.notification_service import (
            NotificationType,
            create_notification,
        )
    except Exception:
        logger.exception("notification subscriber failed to import service")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()
        return

    amount = _safe_amount(payload.get("total_amount"))
    subject = str(payload.get("subject") or payload.get("item_name") or "订单")
    order_no = str(payload.get("out_trade_no") or event.subject_id)
    try:
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="支付成功",
            content=f"您购买的「{subject}」支付成功，金额 ¥{amount:.2f}",
            data={
                "order_no": order_no,
                "amount": amount,
                "item_name": subject,
                "event_id": event.event_id,
            },
        )
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "notified").inc()
    except Exception:
        logger.exception("payment.paid notification handler failed")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()


def _on_payment_paid_entitlement(event: DomainEvent) -> None:
    """Activate entitlements after a payment.paid event (Java-fulfilled orders excluded)."""
    if canonical_event_name(event.event_name) != "payment.paid":
        return
    payload = event.payload or {}
    out_trade_no = str(payload.get("out_trade_no") or event.subject_id or "")
    if not out_trade_no:
        return
    try:
        from modstore_server import payment_orders
        from modstore_server.models import get_session_factory
        from modstore_server.payment_fulfilment import FulfilContext, select_strategy
    except Exception:
        logger.exception("payment.paid entitlement subscriber failed to import")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()
        return

    try:
        user_id = int(payload.get("user_id") or 0)
        total_amount = float(payload.get("total_amount") or 0)
        item_id = int(payload.get("item_id") or 0)
        plan_id = str(payload.get("plan_id") or "").strip()
        order_kind = str(payload.get("order_kind") or "").strip()
    except (TypeError, ValueError):
        logger.warning(
            "payment.paid entitlement subscriber got malformed payload for %s", out_trade_no
        )
        return

    ctx = FulfilContext(
        out_trade_no=out_trade_no,
        user_id=user_id,
        total_amount=total_amount,
        item_id=item_id,
        plan_id=plan_id,
        kind=order_kind,
        order=dict(payload),
    )
    strategy = select_strategy(ctx)
    sf = get_session_factory()
    try:
        with sf() as session:
            if strategy.is_already_fulfilled(session, ctx):
                logger.debug("entitlement already fulfilled for %s, skipping", out_trade_no)
                return
            from datetime import datetime, timezone

            description, txn_type = strategy.description_and_txn_type(ctx)
            strategy.fulfill(
                session,
                ctx,
                now=datetime.now(timezone.utc),
                description=description,
                txn_type=txn_type,
            )
            if payment_orders.is_local_source_of_truth():
                payment_orders.merge_fields(out_trade_no, fulfilled=True)
            session.commit()
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "entitlement_granted").inc()
        logger.info("Entitlement granted via NeuroBus subscriber for order %s", out_trade_no)
    except Exception:
        logger.exception("payment.paid entitlement subscriber failed for %s", out_trade_no)
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()


def _on_payment_paid_invoice(event: DomainEvent) -> None:
    """Trigger invoice creation after a payment.paid event."""
    if canonical_event_name(event.event_name) != "payment.paid":
        return
    payload = event.payload or {}
    out_trade_no = str(payload.get("out_trade_no") or event.subject_id or "")
    user_id_raw = payload.get("user_id")
    try:
        user_id = int(user_id_raw) if user_id_raw is not None else 0
    except (TypeError, ValueError):
        user_id = 0
    if not out_trade_no or not user_id:
        return
    try:
        from modstore_server.invoice_api import create_invoice_for_order
    except ImportError:
        return
    except Exception:
        logger.exception("payment.paid invoice subscriber failed to import invoice_api")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()
        return
    try:
        create_invoice_for_order(
            out_trade_no=out_trade_no,
            user_id=user_id,
            amount=float(payload.get("total_amount") or 0),
            subject=str(payload.get("subject") or ""),
        )
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "invoice_created").inc()
    except Exception:
        logger.exception("payment.paid invoice creation failed for %s", out_trade_no)
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()


def _on_wallet_balance_changed(event: DomainEvent) -> None:
    """Analytics aggregation stub for wallet.balance_changed events."""
    if canonical_event_name(event.event_name) != WALLET_BALANCE_CHANGED:
        return
    payload = event.payload or {}
    user_id_raw = payload.get("user_id")
    try:
        user_id = int(user_id_raw) if user_id_raw is not None else 0
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return
    logger.debug(
        "wallet.balance_changed user=%s amount=%s source=%s",
        user_id,
        payload.get("amount"),
        payload.get("source_order_id"),
    )
    EVENT_PUBLISHED_TOTAL.labels(event.event_name, "received").inc()


def _on_workflow_event_trigger(event: DomainEvent) -> None:
    if canonical_event_name(event.event_name) != WORKFLOW_EVENT_TRIGGER:
        return
    payload = event.payload or {}
    try:
        wf_id = int(payload.get("workflow_id") or 0)
        uid = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        return
    if not wf_id or not uid:
        return
    inp = payload.get("input_data")
    if not isinstance(inp, dict):
        inp = {}
    try:
        from modstore_server.workflow_event_runner import run_workflow_for_trigger

        run_workflow_for_trigger(workflow_id=wf_id, user_id=uid, input_data=inp)
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "workflow_run").inc()
    except Exception:
        logger.exception("workflow.event_trigger subscriber failed")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()


def _on_refund_outcome(event: DomainEvent) -> None:
    name = canonical_event_name(event.event_name)
    if name not in {"refund.approved", "refund.rejected", "refund.failed"}:
        return
    payload = event.payload or {}
    try:
        user_id = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        return
    try:
        from modstore_server.notification_service import (
            NotificationType,
            create_notification,
        )
    except Exception:
        logger.exception("refund subscriber failed to import notification service")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()
        return

    amount = _safe_amount(payload.get("amount"))
    order_no = str(payload.get("order_no") or event.subject_id)
    if name == "refund.approved":
        title, content = (
            "退款成功",
            f"订单 {order_no} 的退款 ¥{amount:.2f} 已完成。",
        )
    elif name == "refund.rejected":
        title, content = (
            "退款被拒绝",
            f"订单 {order_no} 的退款申请未通过，请查看处理意见。",
        )
    else:
        title, content = (
            "退款执行失败",
            f"订单 {order_no} 的退款执行失败，请联系客服跟进。",
        )

    try:
        create_notification(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title=title,
            content=content,
            data={
                "order_no": order_no,
                "amount": amount,
                "refund_status": name,
                "event_id": event.event_id,
            },
        )
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "notified").inc()
    except Exception:
        logger.exception("refund notification handler failed")
        EVENT_PUBLISHED_TOTAL.labels(event.event_name, "subscriber_error").inc()


def install_default_subscribers(bus=None) -> None:
    """Wire metrics + audit + business notifications onto the NeuroBus.

    Idempotent: subsequent calls return early so multiple FastAPI startup
    hooks (or tests reusing the module) do not double-register handlers.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    target_bus = bus or neuro_bus
    target_bus.subscribe("*", _on_event_metric)
    target_bus.subscribe("*", _on_event_audit)
    target_bus.subscribe("payment.paid", _on_payment_paid)
    target_bus.subscribe("payment.paid", _on_payment_paid_entitlement)
    target_bus.subscribe("payment.paid", _on_payment_paid_invoice)
    target_bus.subscribe(WALLET_BALANCE_CHANGED, _on_wallet_balance_changed)
    target_bus.subscribe("refund.approved", _on_refund_outcome)
    target_bus.subscribe("refund.rejected", _on_refund_outcome)
    target_bus.subscribe("refund.failed", _on_refund_outcome)
    target_bus.subscribe(WORKFLOW_EVENT_TRIGGER, _on_workflow_event_trigger)
    _INSTALLED = True


def reset_for_tests() -> None:
    """Allow tests to re-register subscribers on a clean bus instance."""

    global _INSTALLED
    _INSTALLED = False


__all__ = [
    "EVENT_PUBLISHED_TOTAL",
    "install_default_subscribers",
    "reset_for_tests",
]
