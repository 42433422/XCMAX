"""
InventoryService Domain Event Handlers (V2)

Auto-generated event handlers for inventory domain
"""

import logging
import os
from typing import Any

from app.domain.neuro.neuro_uow import NeuroUnitOfWork
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.command_gateway import try_complete_command_reply
from app.neuro_bus.events.base import NeuroEvent
from app.services.inventory_service import InventoryService
from app.neuro_bus.events.inventory_events import (
    InventoryCheckCompletedEvent,
    InventoryStockInEvent,
    InventoryStockOutEvent,
    InventoryTransferEvent,
)

logger = logging.getLogger(__name__)


class InventoryServiceDomainHandlers:
    """InventoryService 领域事件处理器"""

    def __init__(self):
        self.bus = get_neuro_bus()
        self._inventory = InventoryService()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("inventory.stock_in", self.handle_stock_in)
        self.bus.subscribe("inventory.stock_out", self.handle_stock_out)
        self.bus.subscribe("inventory.transfer", self.handle_transfer)
        self.bus.subscribe("inventory.check_completed", self.handle_check_completed)
        logger.info("[InventoryServiceDomain] 已注册 {len(self.bus.subscribers)} 个事件处理器")

    async def handle_stock_in(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 stock_in 事件"""
        logger.info("[InventoryServiceDomain] 处理 stock_in: %s", event.payload)
        p = event.payload
        try:
            if os.environ.get("XCAGI_NEURO_UOW_ON_INVENTORY", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                from sqlalchemy import text

                with NeuroUnitOfWork() as session:
                    session.execute(text("SELECT 1"))
            result = self._inventory.inventory_in(
                product_id=p.get("product_id"),
                warehouse_id=p.get("warehouse_id"),
                quantity=float(p.get("quantity", 0)),
                batch_no=p.get("batch_no"),
                location_id=p.get("location_id"),
                unit_price=float(p["unit_price"]) if p.get("unit_price") is not None else None,
                reference_type=p.get("reference_type"),
                reference_id=p.get("reference_id"),
                operator=p.get("operator"),
                remark=p.get("remark"),
            )
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[InventoryServiceDomain] stock_in 失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_stock_out(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 stock_out 事件"""
        logger.info("[InventoryServiceDomain] 处理 stock_out: %s", event.payload)
        p = event.payload
        try:
            result = self._inventory.inventory_out(
                product_id=p.get("product_id"),
                warehouse_id=p.get("warehouse_id"),
                quantity=float(p.get("quantity", 0)),
                batch_no=p.get("batch_no"),
                location_id=p.get("location_id"),
                unit_price=float(p["unit_price"]) if p.get("unit_price") is not None else None,
                reference_type=p.get("reference_type"),
                reference_id=p.get("reference_id"),
                operator=p.get("operator"),
                remark=p.get("remark"),
            )
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[InventoryServiceDomain] stock_out 失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_transfer(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 transfer 事件"""
        logger.info("[InventoryServiceDomain] 处理 transfer: %s", event.payload)
        p = event.payload
        try:
            result = self._inventory.inventory_transfer(
                product_id=p.get("product_id"),
                from_warehouse_id=p.get("from_warehouse_id"),
                to_warehouse_id=p.get("to_warehouse_id"),
                quantity=float(p.get("quantity", 0)),
                batch_no=p.get("batch_no"),
                from_location_id=p.get("from_location_id"),
                to_location_id=p.get("to_location_id"),
                operator=p.get("operator"),
                remark=p.get("remark"),
            )
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[InventoryServiceDomain] transfer 失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_check_completed(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 check_completed 事件"""
        logger.info(f"[InventoryServiceDomain] 处理 check_completed: {event.payload}")
        if isinstance(event, InventoryCheckCompletedEvent):
            logger.info(f"[InventoryServiceDomain] Check ID: {event.payload.get('check_id')}")
        return {"success": True, "event_type": "inventory.check_completed"}


# 全局处理器实例
_handlers: InventoryServiceDomainHandlers = None


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
