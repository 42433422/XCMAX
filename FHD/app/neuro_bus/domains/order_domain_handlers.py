"""
Order 领域处理器逻辑

从 order_domain.py 迁出的 @self.on 处理器闭包。
通过 register_order_domain_handlers(domain) 注册到 domain 实例。

样板路径说明：``order.created`` 处理器除 metrics 外，会写入 EventStore
与可查询内存投影；这是「1 条域事件样板闭环」副作用，不代表订单域全域已落地。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

__all__ = [
    "register_order_domain_handlers",
    "apply_order_created_side_effect",
    "get_order_created_event_log",
    "get_order_created_projection",
    "clear_order_created_side_effects",
]

_lock = threading.RLock()
# 样板可查询投影：order_id -> 最新 order.created 副作用记录
_ORDER_CREATED_PROJECTIONS: dict[str, dict[str, Any]] = {}
# 样板可查询 event log（按写入顺序）
_ORDER_CREATED_EVENT_LOG: list[dict[str, Any]] = []


def get_order_created_event_log() -> list[dict[str, Any]]:
    """返回样板路径写入的 order.created 事件日志副本。"""
    with _lock:
        return [dict(row) for row in _ORDER_CREATED_EVENT_LOG]


def get_order_created_projection(order_id: str) -> dict[str, Any] | None:
    """按 order_id 查询样板投影。"""
    with _lock:
        row = _ORDER_CREATED_PROJECTIONS.get(order_id)
        return dict(row) if row else None


def clear_order_created_side_effects() -> None:
    """清空样板副作用状态（单测隔离）。"""
    with _lock:
        _ORDER_CREATED_PROJECTIONS.clear()
        _ORDER_CREATED_EVENT_LOG.clear()


def apply_order_created_side_effect(event: NeuroEvent) -> dict[str, Any]:
    """样板真实副作用：EventStore append + 内存投影 / event log。

    可被 handler 与单测直接调用，便于断言「不只 logger+metrics」。
    """
    payload = dict(event.payload or {})
    order_id = str(payload.get("order_id") or "")
    if not order_id:
        raise ValueError("order.created payload 缺少 order_id")

    stream_id = f"order:{order_id}"
    store_id = ""
    try:
        from app.neuro_bus.event_store import get_event_store

        store_id = get_event_store().append(event, stream_id=stream_id)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("样板路径写入 EventStore 失败: %s", exc)

    record = {
        "order_id": order_id,
        "customer_id": payload.get("customer_id"),
        "total_amount": payload.get("total_amount"),
        "item_count": payload.get("item_count"),
        "stream_id": stream_id,
        "store_id": store_id,
        "event_type": event.event_type,
        "status": "projected",
    }
    with _lock:
        _ORDER_CREATED_PROJECTIONS[order_id] = dict(record)
        _ORDER_CREATED_EVENT_LOG.append(dict(record))
    return record


def register_order_domain_handlers(domain):
    """注册 Order 领域事件处理器到 domain 实例。

    将原 order_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """

    @domain.on("order.created", priority=1, channel=DomainChannel.RELIABLE)
    async def on_order_created(event):
        order_id = event.payload.get("order_id")
        logger.info("Order created: %s", order_id)
        bump_domain_handler_metric("order.created")
        # Sample durable side-effect (not metrics-only): persist to neuro_event_log.
        try:
            from app.neuro_bus.domains.application_event_consumers import (
                _persist_event_log,
            )

            row_id = _persist_event_log(event, side_effect="order.created.sample_loop")
            logger.info(
                "Order created persisted neuro_event_log#%s order_id=%s",
                row_id,
                order_id,
            )
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("order.created persist skipped", exc_info=True)
        # 样板闭环副作用（非全域）：可查询 EventStore + 投影
        try:
            apply_order_created_side_effect(event)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("样板路径 order.created 副作用失败: %s", exc)

    @domain.on("order.paid", priority=0, channel=DomainChannel.RELIABLE)
    async def on_order_paid(event):
        order_id = event.payload.get("order_id")
        amount = event.payload.get("amount")
        logger.info("Order paid: %s, amount=%s", order_id, amount)
        from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

        bump_domain_handler_metric("order.paid")

    @domain.on("order.shipped", priority=1, channel=DomainChannel.STANDARD)
    async def on_order_shipped(event):
        order_id = event.payload.get("order_id")
        shipment_id = event.payload.get("shipment_id")
        logger.info("Order shipped: %s, shipment=%s", order_id, shipment_id)
        bump_domain_handler_metric("order.shipped")
