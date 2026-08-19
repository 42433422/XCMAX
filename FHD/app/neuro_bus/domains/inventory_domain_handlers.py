"""
InventoryService Domain Event Handlers (V2)

Auto-generated event handlers for inventory domain
"""

import logging
import os
from typing import Any

from app.domain.neuro.neuro_uow import NeuroUnitOfWork
from app.neuro_bus import bus as neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.events.inventory_events import (
    InventoryCheckCompletedEvent,
    InventoryStockInEvent,
    InventoryStockOutEvent,
    InventoryTransferEvent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

PurchaseService = None


def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "InventoryServiceDomain",
    priority: EventPriority = EventPriority.NORMAL,
) -> str:
    """发布 NeuroBus 事件（失败只警告，不抛错）。"""
    try:
        bus = neuro_bus.get_neuro_bus()
        event = NeuroEvent(
            event_type=event_type,
            payload=payload,
            source=source,
            priority=priority,
        )
        bus.publish(event)
        return event.metadata.event_id
    except RECOVERABLE_ERRORS as exc:
        logger.warning("发布事件失败 %s: %s", event_type, exc)
        return ""


def _resolve_purchase_service_cls():
    cls = PurchaseService
    if cls is not None:
        return cls
    from app.services.purchase_service import PurchaseService as _PurchaseService

    return _PurchaseService


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def handle_auto_inbound_requested(event: NeuroEvent) -> dict[str, Any]:
    """处理 ``inventory.auto_inbound_requested`` 事件并创建入库单。"""
    payload = dict(event.payload or {})
    inbound_data = {
        "ocr_request_id": payload.get("ocr_request_id"),
        "supplier_id": payload.get("supplier_id"),
        "warehouse_id": payload.get("warehouse_id"),
        "items": payload.get("items", []),
        "total_amount": payload.get("total_amount") or 0,
        "invoice_no": payload.get("invoice_no"),
        "handler": "ocr-auto",
        "order_id": payload.get("order_id"),
        "applicant_id": payload.get("applicant_id"),
    }

    try:
        service_cls = _resolve_purchase_service_cls()
        svc = service_cls()
        result = svc.create_purchase_inbound(inbound_data)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("[InventoryServiceDomain] create_purchase_inbound 失败: %s", exc)
        _publish_event(
            "inventory.inbound_failed",
            {
                "ocr_request_id": inbound_data.get("ocr_request_id"),
                "supplier_id": inbound_data.get("supplier_id"),
                "error": str(exc),
            },
            source="InventoryServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "ocr_request_id": inbound_data.get("ocr_request_id"),
            "stage": "create_purchase_inbound",
        }

    if not result.get("success"):
        message = result.get("message") or "create_purchase_inbound failed"
        _publish_event(
            "inventory.inbound_failed",
            {
                "ocr_request_id": inbound_data.get("ocr_request_id"),
                "supplier_id": inbound_data.get("supplier_id"),
                "error": message,
            },
            source="InventoryServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": message,
            "ocr_request_id": inbound_data.get("ocr_request_id"),
            "stage": "create_purchase_inbound",
        }

    data = result.get("data") or {}
    inbound_id = data.get("id")
    inbound_no = data.get("inbound_no")
    total_amount = data.get("total_amount")
    if total_amount is None:
        total_amount = inbound_data.get("total_amount")

    _publish_event(
        "finance.approval_requested",
        {
            "business_type": "purchase_inbound",
            "business_id": inbound_id,
            "amount": _coerce_float(total_amount),
            "applicant_id": payload.get("applicant_id"),
            "inbound_no": inbound_no,
            "supplier_id": payload.get("supplier_id"),
            "invoice_no": payload.get("invoice_no"),
            "ocr_request_id": payload.get("ocr_request_id"),
        },
        source="InventoryServiceDomain",
        priority=EventPriority.HIGH,
    )
    _publish_event(
        "inventory.inbound_created",
        {
            "inbound_id": inbound_id,
            "inbound_no": inbound_no,
            "supplier_id": payload.get("supplier_id"),
            "warehouse_id": payload.get("warehouse_id"),
            "total_amount": _coerce_float(total_amount),
            "items": payload.get("items", []),
        },
        source="InventoryServiceDomain",
    )

    return {
        "success": True,
        "inbound_id": inbound_id,
        "inbound_no": inbound_no,
        "business_id": inbound_id,
    }


class InventoryServiceDomainHandlers:
    """InventoryService 领域事件处理器"""

    def __init__(self):
        self.bus = neuro_bus.get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("inventory.stock_in", self.handle_stock_in)
        self.bus.subscribe("inventory.stock_out", self.handle_stock_out)
        self.bus.subscribe("inventory.transfer", self.handle_transfer)
        self.bus.subscribe("inventory.auto_inbound_requested", handle_auto_inbound_requested)
        self.bus.subscribe("inventory.check_completed", self.handle_check_completed)
        logger.info("[InventoryServiceDomain] 已注册 {len(self.bus.subscribers)} 个事件处理器")

    async def handle_stock_in(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 stock_in 事件"""
        logger.info("[InventoryServiceDomain] 处理 stock_in: %s", event.payload)
        if isinstance(event, InventoryStockInEvent):
            logger.info("[InventoryServiceDomain] Product: %s", event.payload.get("product_id"))
        if os.environ.get("XCAGI_NEURO_UOW_ON_INVENTORY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            from sqlalchemy import text

            with NeuroUnitOfWork() as session:
                session.execute(text("SELECT 1"))
        return {"success": True, "event_type": "inventory.stock_in"}

    async def handle_stock_out(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 stock_out 事件"""
        logger.info("[InventoryServiceDomain] 处理 stock_out: %s", event.payload)
        if isinstance(event, InventoryStockOutEvent):
            logger.info("[InventoryServiceDomain] Quantity: %s", event.payload.get("quantity"))
        return {"success": True, "event_type": "inventory.stock_out"}

    async def handle_transfer(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 transfer 事件"""
        logger.info("[InventoryServiceDomain] 处理 transfer: %s", event.payload)
        if isinstance(event, InventoryTransferEvent):
            logger.info(
                "[InventoryServiceDomain] origin: %s",
                event.payload.get("from_location"),
            )
        return {"success": True, "event_type": "inventory.transfer"}

    async def handle_check_completed(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 check_completed 事件"""
        logger.info("[InventoryServiceDomain] 处理 check_completed: %s", event.payload)
        if isinstance(event, InventoryCheckCompletedEvent):
            logger.info("[InventoryServiceDomain] Check ID: %s", event.payload.get("check_id"))
        return {"success": True, "event_type": "inventory.check_completed"}


# 全局处理器实例
_handlers: InventoryServiceDomainHandlers | None = None


def get_inventory_handlers() -> InventoryServiceDomainHandlers:
    """获取领域处理器单例"""
    global _handlers
    if _handlers is None:
        _handlers = InventoryServiceDomainHandlers()
    return _handlers


def register_inventory_domain_handlers(bus):
    """注册所有 Inventory 领域事件处理器到 NeuroBus"""
    handlers = get_inventory_handlers()
    handlers.register()
    logger.info("[InventoryDomain] 所有事件处理器已注册")
