"""
InventoryService Domain Event Handlers (V2)

库存领域事件处理器：
- ``inventory.auto_inbound_requested``：消费 OCR 完成事件触发的自动入库请求，
  调用 ``PurchaseService.create_purchase_inbound`` 创建入库单；成功后发布
  ``finance.approval_requested`` 推送财务审批，失败发布 ``inventory.inbound_failed``。
- ``inventory.stock_in/out/transfer/check_completed``：保留原 log 行为（向后兼容）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.domain.neuro.neuro_uow import NeuroUnitOfWork
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.events.inventory_events import (
    InventoryCheckCompletedEvent,
    InventoryStockInEvent,
    InventoryStockOutEvent,
    InventoryTransferEvent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 模块级占位：测试通过 patch("...PurchaseService") 替换；生产环境在 handler 内延迟导入。
# 必须放在模块级才能被 unittest.mock.patch 命中（函数内 from X import Y 会创建
# 局部变量，无法被模块级 patch 影响）。
PurchaseService = None


# ---------------------------------------------------------------------------
# 工具：发布事件（模块级，便于在异步 handler 中调用）
# ---------------------------------------------------------------------------
def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "InventoryServiceDomain",
    priority: EventPriority = EventPriority.NORMAL,
) -> str:
    """发布 NeuroBus 事件；失败不抛异常，返回空字符串。"""
    # 延迟导入：避免模块级绑定导致测试 patch 不生效（test isolation）
    from app.neuro_bus.bus import get_neuro_bus

    try:
        bus = get_neuro_bus()
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


def _build_inbound_data(event_payload: dict[str, Any]) -> dict[str, Any]:
    """从 ``inventory.auto_inbound_requested`` payload 构造 ``create_purchase_inbound`` 入参。

    - 透传 supplier_id / warehouse_id / items / handler / remark
    - 不传 inbound_no（让 PurchaseService 自动生成）
    - 不传 order_id（OCR 触发的入库通常无关联采购订单）
    """
    items = [
        {
            "product_id": it.get("product_id"),
            "quantity": it.get("quantity", 0),
            "unit_price": it.get("unit_price", 0),
            "product_name": it.get("product_name"),
            "batch_no": it.get("batch_no"),
            "unit": it.get("unit", "个"),
        }
        for it in (event_payload.get("items") or [])
    ]
    return {
        "supplier_id": event_payload.get("supplier_id"),
        "warehouse_id": event_payload.get("warehouse_id"),
        "items": items,
        "handler": "ocr-auto-inbound",
        "remark": (
            f"OCR 自动入库: invoice={event_payload.get('invoice_no') or ''}, "
            f"ocr_request_id={event_payload.get('ocr_request_id') or ''}"
        ).strip(),
    }


async def handle_auto_inbound_requested(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``inventory.auto_inbound_requested``：自动创建入库单 + 推送审批。

    流程：
    1. 从 event payload 构造 ``create_purchase_inbound`` 入参
    2. 调用 ``PurchaseService.create_purchase_inbound``
    3. 成功 → 发布 ``finance.approval_requested``（带入库单 ID + 金额 + 申请人）
    4. 失败 → 发布 ``inventory.inbound_failed``（带错误信息 + ocr_request_id）

    任何异常都被捕获，绝不抛出（避免崩溃 NeuroBus dispatch loop）。
    """
    payload = dict(event.payload or {})
    ocr_request_id = payload.get("ocr_request_id") or ""
    applicant_id = payload.get("applicant_id")

    logger.info(
        "[InventoryServiceDomain] 处理 auto_inbound_requested: ocr_request_id=%s",
        ocr_request_id,
    )

    # 优先使用模块级 PurchaseService（便于测试 patch）；
    # 模块级为 None 时（生产环境）走延迟导入，避免触发 app.services 包级循环导入。
    purchase_service_cls = PurchaseService
    if purchase_service_cls is None:
        try:
            from app.services.purchase_service import (
                PurchaseService as _LazyPurchaseService,
            )

            purchase_service_cls = _LazyPurchaseService
        except RECOVERABLE_ERRORS as exc:
            logger.error(
                "[InventoryServiceDomain] PurchaseService 延迟导入失败: %s", exc
            )
            _publish_event(
                "inventory.inbound_failed",
                {
                    "ocr_request_id": ocr_request_id,
                    "error": f"PurchaseService import failed: {exc}",
                    "stage": "import",
                },
                source="InventoryServiceDomain",
                priority=EventPriority.HIGH,
            )
            return {"success": False, "error": str(exc), "stage": "import"}

    inbound_data = _build_inbound_data(payload)

    try:
        service = purchase_service_cls()
        result = service.create_purchase_inbound(inbound_data)
    except Exception as exc:  # noqa: BLE001 — 任何异常都不能崩溃总线
        logger.exception(
            "[InventoryServiceDomain] create_purchase_inbound 抛异常: %s", exc
        )
        _publish_event(
            "inventory.inbound_failed",
            {
                "ocr_request_id": ocr_request_id,
                "error": str(exc),
                "stage": "create_inbound",
            },
            source="InventoryServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "create_inbound",
            "ocr_request_id": ocr_request_id,
        }

    if not result.get("success"):
        # 业务失败（如 supplier 不存在、库存入库失败等）
        error_msg = result.get("message") or "create_purchase_inbound returned failure"
        logger.warning(
            "[InventoryServiceDomain] create_purchase_inbound 业务失败: %s", error_msg
        )
        _publish_event(
            "inventory.inbound_failed",
            {
                "ocr_request_id": ocr_request_id,
                "error": error_msg,
                "stage": "business",
            },
            source="InventoryServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": error_msg,
            "stage": "business",
            "ocr_request_id": ocr_request_id,
        }

    inbound = result.get("data") or {}
    inbound_id = inbound.get("id")
    inbound_no = inbound.get("inbound_no")
    total_amount = inbound.get("total_amount") or payload.get("total_amount") or 0

    # 推送财务审批
    approval_event_id = _publish_event(
        "finance.approval_requested",
        {
            "business_type": "purchase_inbound",
            "business_id": inbound_id,
            "inbound_no": inbound_no,
            "amount": float(total_amount),
            "applicant_id": applicant_id,
            "supplier_id": payload.get("supplier_id"),
            "warehouse_id": payload.get("warehouse_id"),
            "ocr_request_id": ocr_request_id,
            "invoice_no": payload.get("invoice_no"),
        },
        source="InventoryServiceDomain",
    )

    logger.info(
        "[InventoryServiceDomain] 自动入库成功 inbound_id=%s, 已推送审批 event_id=%s",
        inbound_id,
        approval_event_id,
    )

    return {
        "success": True,
        "inbound_id": inbound_id,
        "inbound_no": inbound_no,
        "approval_event_id": approval_event_id,
        "ocr_request_id": ocr_request_id,
    }


class InventoryServiceDomainHandlers:
    """InventoryService 领域事件处理器"""

    def __init__(self):
        self.bus = get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("inventory.stock_in", self.handle_stock_in)
        self.bus.subscribe("inventory.stock_out", self.handle_stock_out)
        self.bus.subscribe("inventory.transfer", self.handle_transfer)
        self.bus.subscribe("inventory.check_completed", self.handle_check_completed)
        # 新增：自动入库请求 → 自动创建入库单 + 推送审批
        self.bus.subscribe("inventory.auto_inbound_requested", handle_auto_inbound_requested)
        logger.info(
            "[InventoryServiceDomain] 已注册 %d 个事件处理器",
            len(self.bus._handlers.get("inventory.auto_inbound_requested", [])),
        )

    async def handle_stock_in(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 stock_in 事件（保留原 log 行为）"""
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
        """处理 stock_out 事件（保留原 log 行为）"""
        logger.info("[InventoryServiceDomain] 处理 stock_out: %s", event.payload)
        if isinstance(event, InventoryStockOutEvent):
            logger.info("[InventoryServiceDomain] Quantity: %s", event.payload.get("quantity"))
        return {"success": True, "event_type": "inventory.stock_out"}

    async def handle_transfer(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 transfer 事件（保留原 log 行为）"""
        logger.info("[InventoryServiceDomain] 处理 transfer: %s", event.payload)
        if isinstance(event, InventoryTransferEvent):
            logger.info(
                "[InventoryServiceDomain] origin: %s",
                event.payload.get("from_location"),
            )
        return {"success": True, "event_type": "inventory.transfer"}

    async def handle_check_completed(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 check_completed 事件（保留原 log 行为）"""
        logger.info("[InventoryServiceDomain] 处理 check_completed: %s", event.payload)
        if isinstance(event, InventoryCheckCompletedEvent):
            logger.info("[InventoryServiceDomain] Check ID: %s", event.payload.get("check_id"))
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
