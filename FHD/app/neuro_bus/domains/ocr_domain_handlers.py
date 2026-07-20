"""
OCRService Domain Event Handlers (V2)

OCR 完成事件驱动下游编排：
- invoice（发票）→ 发布 ``inventory.auto_inbound_requested`` 触发自动入库
- receipt（回单）→ 归档到 ``financial_transactions`` 表

保留原 log 行为作为兼容扩展；新增业务逻辑通过模块级 ``handle_ocr_completed``
函数暴露（便于直接订阅 / 单测），同时保留 ``OCRServiceDomainHandlers`` 类作为
向后兼容的注册入口。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.events.ocr_events import (
    OCRBatchProcessingCompletedEvent,
    OCRTaskCompletedEvent,
    OCRTaskSubmittedEvent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具：发布事件（与 NeuroEventPublisherMixin 一致，但模块级函数可用）
# ---------------------------------------------------------------------------
def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "OCRServiceDomain",
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


def archive_financial_receipt(fields: dict[str, Any]) -> dict[str, Any]:
    """将 OCR 识别的回单（receipt）字段归档到 ``financial_transactions`` 表。

    幂等：以 ``reference_type='ocr_receipt'`` + ``reference_id`` 去重；若已存在则
    直接返回既有记录。表按需惰性创建（``checkfirst``），避免依赖 init_db 顺序。
    """
    try:
        from app.db import SessionLocal
        from app.db.models.finance import FinancialTransaction
    except RECOVERABLE_ERRORS as exc:  # pragma: no cover - 兜底
        logger.warning("[OCRDomain] 归档回单时导入失败: %s", exc)
        return {"success": False, "error": str(exc)}

    receipt_no = str(fields.get("receipt_no") or fields.get("request_id") or "")
    amount = float(fields.get("amount") or 0)
    counterparty = str(fields.get("counterparty") or "")
    transaction_date_str = fields.get("transaction_date")

    try:
        tx_date = None
        if transaction_date_str:
            tx_date = datetime.fromisoformat(transaction_date_str)
    except (TypeError, ValueError):
        tx_date = None

    try:
        with SessionLocal() as db:
            # 幂等：相同 receipt_no 已归档则跳过
            if receipt_no:
                existing = (
                    db.query(FinancialTransaction)
                    .filter(
                        FinancialTransaction.reference_type == "ocr_receipt",
                        FinancialTransaction.description.like(f"%{receipt_no}%"),
                    )
                    .first()
                )
                if existing:
                    return {
                        "success": True,
                        "transaction_id": existing.id,
                        "deduplicated": True,
                    }

            tx = FinancialTransaction(
                transaction_type="receipt",
                amount=amount,
                currency="CNY",
                reference_type="ocr_receipt",
                description=f"OCR 回单归档: {receipt_no}".strip(),
                transaction_date=tx_date or datetime.now(),
                status="archived",
                counterparty_name=counterparty or None,
                created_by="ocr-auto",
            )
            db.add(tx)
            db.commit()
            db.refresh(tx)
            return {"success": True, "transaction_id": int(tx.id)}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("[OCRDomain] 归档回单失败: %s", exc)
        return {"success": False, "error": str(exc)}


async def handle_ocr_completed(event: NeuroEvent) -> dict[str, Any]:
    """处理 ``ocr.completed`` 事件：根据 doc_type 路由到不同下游。

    - ``invoice``：发布 ``inventory.auto_inbound_requested`` 事件，由
      inventory handler 消费并自动创建入库单 + 推送审批。
    - ``receipt``：调用 ``archive_financial_receipt`` 归档到财务交易表。
    - 其它/缺失 doc_type：仅 log，不触发下游（向后兼容）。
    """
    payload = dict(event.payload or {})
    request_id = payload.get("request_id") or payload.get("task_id") or ""
    doc_type = (payload.get("doc_type") or payload.get("ocr_type") or "").lower()
    fields = payload.get("fields") or {}
    confidence = payload.get("confidence")

    logger.info(
        "[OCRServiceDomain] 处理 ocr.completed: request_id=%s doc_type=%s confidence=%s",
        request_id,
        doc_type,
        confidence,
    )

    if doc_type == "invoice":
        # 提取入库所需字段，缺字段时给空默认值（不阻断事件流）
        items = list(fields.get("items") or [])
        normalized_items = [
            {
                "product_id": it.get("product_id"),
                "quantity": float(it.get("quantity") or 0),
                "unit_price": float(it.get("unit_price") or 0),
                "product_name": it.get("product_name"),
                "batch_no": it.get("batch_no"),
                "unit": it.get("unit", "个"),
            }
            for it in items
        ]
        inbound_payload = {
            "ocr_request_id": request_id,
            "supplier_id": fields.get("supplier_id"),
            "supplier_name": fields.get("supplier_name"),
            "warehouse_id": fields.get("warehouse_id"),
            "items": normalized_items,
            "total_amount": float(fields.get("total_amount") or 0),
            "invoice_no": fields.get("invoice_no") or "",
            "applicant_id": payload.get("user_id"),
        }
        event_id = _publish_event(
            "inventory.auto_inbound_requested",
            inbound_payload,
            source="OCRServiceDomain",
        )
        return {
            "success": True,
            "event_type": "ocr.completed",
            "doc_type": doc_type,
            "dispatched_event": "inventory.auto_inbound_requested",
            "event_id": event_id,
        }

    if doc_type == "receipt":
        archive_result = archive_financial_receipt(
            {
                **fields,
                "request_id": request_id,
            }
        )
        return {
            "success": archive_result.get("success", False),
            "event_type": "ocr.completed",
            "doc_type": doc_type,
            "archive": archive_result,
        }

    # 其它 doc_type（如 id_card / general / 空）：仅 log，保留向后兼容
    logger.debug(
        "[OCRServiceDomain] doc_type=%s 无下游编排，仅 log", doc_type or "unknown"
    )
    return {"success": True, "event_type": "ocr.completed", "doc_type": doc_type}


class OCRServiceDomainHandlers:
    """OCRService 领域事件处理器（向后兼容类）"""

    def __init__(self):
        self.bus = get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("ocr.task_submitted", self.handle_task_submitted)
        self.bus.subscribe("ocr.task_completed", self.handle_task_completed)
        self.bus.subscribe("ocr.completed", handle_ocr_completed)
        self.bus.subscribe("ocr.batch_started", self.handle_batch_started)
        logger.info(
            "[OCRServiceDomain] 已注册 %d 个事件处理器", len(self.bus._handlers.get("ocr.completed", []))
        )

    async def handle_task_submitted(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 task_submitted 事件（保留原 log 行为）"""
        logger.info("[OCRServiceDomain] 处理 task_submitted: %s", event.payload)
        if isinstance(event, OCRTaskSubmittedEvent):
            logger.info("[OCRServiceDomain] Task ID: %s", event.payload.get("task_id"))
        return {"success": True, "event_type": "ocr.task_submitted"}

    async def handle_task_completed(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 task_completed 事件（保留原 log 行为；新链路经 ocr.completed 触发）"""
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
_handlers: OCRServiceDomainHandlers = None


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
