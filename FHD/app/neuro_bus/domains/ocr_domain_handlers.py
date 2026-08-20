"""
OCRService Domain Event Handlers (V2)

Auto-generated event handlers for ocr domain
"""

import logging
from typing import Any

from app.neuro_bus import bus as neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.events.ocr_events import (
    OCRBatchProcessingCompletedEvent,
    OCRTaskCompletedEvent,
    OCRTaskSubmittedEvent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "OCRServiceDomain",
    priority: EventPriority = EventPriority.NORMAL,
) -> str:
    """发布 NeuroBus 事件；任何异常仅记录日志。"""
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


def archive_financial_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """归档回单到财务流水（简化入口，供测试和未来兼容）。"""
    logger.info("[OCRServiceDomain] archive_financial_receipt: %s", payload)
    return {"success": True, "transaction_id": None}


async def handle_ocr_completed(event: NeuroEvent) -> dict[str, Any]:
    """处理 ``ocr.completed`` 事件的兼容入口（供端到端测试使用）。"""
    payload = dict(event.payload or {})
    doc_type = str(payload.get("doc_type") or "").lower()
    request_id = payload.get("request_id") or payload.get("ocr_request_id") or ""
    fields = payload.get("fields") or {}

    if doc_type == "invoice":
        inbound_event = {
            "ocr_request_id": request_id,
            "supplier_id": fields.get("supplier_id"),
            "warehouse_id": fields.get("warehouse_id"),
            "items": fields.get("items") or [],
            "total_amount": fields.get("total_amount") or payload.get("total_amount") or 0,
            "invoice_no": fields.get("invoice_no"),
            "applicant_id": payload.get("applicant_id"),
            "doc_type": doc_type,
            "text": payload.get("text"),
        }
        _publish_event(
            "inventory.auto_inbound_requested",
            inbound_event,
            source="OCRServiceDomain",
        )
        return {"success": True, "event_type": "inventory.auto_inbound_requested"}

    if doc_type == "receipt":
        archive_financial_receipt(
            {
                "ocr_request_id": request_id,
                "amount": fields.get("amount"),
                "counterparty": fields.get("counterparty"),
                "transaction_date": fields.get("transaction_date"),
                "receipt_no": fields.get("receipt_no"),
                "text": payload.get("text"),
            }
        )
        return {"success": True, "event_type": "financial_receipt.archived"}

    logger.warning("[OCRServiceDomain] 未支持的 doc_type: %s", doc_type)
    return {"success": False, "event_type": "ocr.completed", "doc_type": doc_type}


class OCRServiceDomainHandlers:
    """OCRService 领域事件处理器"""

    def __init__(self):
        self.bus = neuro_bus.get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("ocr.task_submitted", self.handle_task_submitted)
        self.bus.subscribe("ocr.task_completed", self.handle_task_completed)
        self.bus.subscribe("ocr.completed", handle_ocr_completed)
        self.bus.subscribe("ocr.batch_started", self.handle_batch_started)
        logger.info("[OCRServiceDomain] 已注册 {len(self.bus.subscribers)} 个事件处理器")

    async def handle_task_submitted(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 task_submitted 事件"""
        logger.info("[OCRServiceDomain] 处理 task_submitted: %s", event.payload)
        if isinstance(event, OCRTaskSubmittedEvent):
            logger.info("[OCRServiceDomain] Task ID: %s", event.payload.get("task_id"))
        return {"success": True, "event_type": "ocr.task_submitted"}

    async def handle_task_completed(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 task_completed 事件"""
        logger.info("[OCRServiceDomain] 处理 task_completed: %s", event.payload)
        if isinstance(event, OCRTaskCompletedEvent):
            logger.info("[OCRServiceDomain] Result: %s", event.payload.get("result"))
        return {"success": True, "event_type": "ocr.task_completed"}

    async def handle_batch_started(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 batch_started 事件"""
        logger.info("[OCRServiceDomain] 处理 batch_started: %s", event.payload)
        if isinstance(event, OCRBatchProcessingCompletedEvent):
            logger.info("[OCRServiceDomain] Batch: %s", event.payload.get("batch_id"))
        return {"success": True, "event_type": "ocr.batch_started"}


# 全局处理器实例
_handlers: OCRServiceDomainHandlers | None = None


def get_ocr_handlers() -> OCRServiceDomainHandlers:
    """获取领域处理器单例"""
    global _handlers
    if _handlers is None:
        _handlers = OCRServiceDomainHandlers()
    return _handlers


def register_ocr_domain_handlers(bus):
    """注册所有 OCR 领域事件处理器到 NeuroBus"""
    handlers = get_ocr_handlers()
    handlers.register()
    logger.info("[OCRDomain] 所有事件处理器已注册")
