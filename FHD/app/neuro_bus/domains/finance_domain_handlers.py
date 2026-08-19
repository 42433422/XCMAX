"""
Finance Domain Event Handlers

财务领域事件处理器（端到端编排链路第 3 段）：
- ``finance.approval_requested``：消费 inventory handler 推送的审批请求，调用
  ``ApprovalService.create_approval_request`` 创建审批单；成功后发布
  ``finance.approval_created``，失败发布 ``finance.approval_failed``。
- ``finance.approval_completed``：消费审批完成的回调（approved/rejected），
  调用 ``PurchaseService.update_inbound_approval_status`` 更新入库单状态；
  成功发布 ``finance.approval_archived``，失败发布
  ``finance.approval_completion_failed``。

设计要点：
- 所有 handler 必须 try/except，绝不抛出异常崩溃 NeuroBus dispatch loop。
- ``PurchaseService`` 通过模块级占位 + 延迟导入模式，便于测试 patch（参考
  ``inventory_domain_handlers.py`` 同模式），同时规避 ``app.services`` 包级
  循环导入。
- ``get_approval_service`` 来自 ``app.application.workflow.approval_service``，
  无循环导入风险，可在模块级直接导入。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 模块级占位：测试通过 patch("...PurchaseService") 替换；生产环境在 handler 内延迟导入。
# app.services 包存在循环导入，不能在模块加载时直接 from app.services.purchase_service import ...
PurchaseService = None
get_approval_service = None


@dataclass
class _FallbackWorkflowNode:
    node_id: str
    tool_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"
    idempotent: bool = False
    description: str = ""
    depends_on: list[str] = field(default_factory=list)


def _resolve_approval_service():
    """返回 ``get_approval_service``：优先复用模块级打补丁，必要时延迟导入。"""
    global get_approval_service
    if get_approval_service is not None:
        return get_approval_service
    from app.application.workflow.approval_service import (
        get_approval_service as _get_approval_service,
    )

    get_approval_service = _get_approval_service
    return _get_approval_service


# ---------------------------------------------------------------------------
# 工具：发布事件（模块级，便于在异步 handler 中调用）
# ---------------------------------------------------------------------------
def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "FinanceServiceDomain",
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


def _resolve_purchase_service_cls():
    """返回 ``PurchaseService`` 类：优先模块级（测试 patch），其次延迟导入。"""
    cls = PurchaseService
    if cls is not None:
        return cls
    # 生产环境：延迟导入（app.services 包此时应已完成初始化）
    from app.services.purchase_service import PurchaseService as _LazyPS

    return _LazyPS


# ---------------------------------------------------------------------------
# Handler: finance.approval_requested → create_approval_request
# ---------------------------------------------------------------------------
async def handle_approval_requested(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``finance.approval_requested``：调用 ApprovalService 创建审批单。

    流程：
    1. 从 event payload 构造 ``WorkflowNode``（tool_id=business_type, action="approve"）
    2. 生成 ``plan_id``（finance-{business_id}-{uuid4}）
    3. 调用 ``ApprovalService.create_approval_request(plan_id, node)``
    4. 成功 → 发布 ``finance.approval_created``（带 approval_id / business_id）
    5. 失败 → 发布 ``finance.approval_failed``（带 error / business_id）

    任何异常都被捕获，绝不抛出。
    """
    payload = dict(event.payload or {})
    business_type = payload.get("business_type") or "general"
    business_id = payload.get("business_id")
    amount = float(payload.get("amount") or 0)
    applicant_id = payload.get("applicant_id")
    inbound_no = payload.get("inbound_no") or ""
    supplier_id = payload.get("supplier_id")

    logger.info(
        "[FinanceServiceDomain] 处理 approval_requested: business_type=%s business_id=%s amount=%s",
        business_type,
        business_id,
        amount,
    )

    # 构造 WorkflowNode：business_type 作为 tool_id，business 信息存 params
    node = _FallbackWorkflowNode(
        node_id=f"approval-{business_type}-{business_id}",
        tool_id=business_type,
        action="approve",
        params={
            "business_id": business_id,
            "amount": amount,
            "applicant_id": applicant_id,
            "inbound_no": inbound_no,
            "supplier_id": supplier_id,
        },
        risk="medium" if amount > 1000 else "low",
        idempotent=True,
        description=f"自动审批请求: {business_type} #{business_id}",
    )

    plan_id = f"finance-{business_type}-{business_id or 'x'}-{uuid.uuid4().hex[:8]}"

    try:
        approval_service_factory: Callable[..., Any] = _resolve_approval_service()
        approval_service = approval_service_factory()
        request = approval_service.create_approval_request(plan_id, node)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("[FinanceServiceDomain] create_approval_request 失败: %s", exc)
        _publish_event(
            "finance.approval_failed",
            {
                "business_type": business_type,
                "business_id": business_id,
                "error": str(exc),
                "stage": "create_approval_request",
            },
            source="FinanceServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "create_approval_request",
            "business_id": business_id,
        }

    # request 可能是 ApprovalRequest dataclass 或 MagicMock（测试）
    approval_id = getattr(request, "request_id", None) or str(getattr(request, "id", "") or "")
    status_value = ""
    status_attr = getattr(request, "status", None)
    if status_attr is not None:
        status_value = getattr(status_attr, "value", None) or str(status_attr) or ""

    approval_event_id = _publish_event(
        "finance.approval_created",
        {
            "approval_id": approval_id,
            "business_type": business_type,
            "business_id": business_id,
            "amount": amount,
            "applicant_id": applicant_id,
            "plan_id": plan_id,
            "status": status_value or "pending",
        },
        source="FinanceServiceDomain",
    )

    logger.info(
        "[FinanceServiceDomain] 审批单已创建 approval_id=%s business_id=%s event_id=%s",
        approval_id,
        business_id,
        approval_event_id,
    )

    return {
        "success": True,
        "approval_id": approval_id,
        "plan_id": plan_id,
        "business_id": business_id,
        "approval_event_id": approval_event_id,
    }


# ---------------------------------------------------------------------------
# Handler: finance.approval_completed → update_inbound_approval_status
# ---------------------------------------------------------------------------
async def handle_approval_completed(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``finance.approval_completed``：根据 decision 更新入库单审批状态。

    流程：
    1. 从 event payload 读取 decision（approved/rejected）+ business_id
    2. 调用 ``PurchaseService.update_inbound_approval_status(business_id, decision)``
    3. 成功 → 发布 ``finance.approval_archived``（带 business_id / decision）
    4. 失败 → 发布 ``finance.approval_completion_failed``（带 error / business_id）

    任何异常都被捕获，绝不抛出。
    """
    payload = dict(event.payload or {})
    approval_id = payload.get("approval_id") or ""
    business_type = payload.get("business_type") or "purchase_inbound"
    business_id = payload.get("business_id")
    decision = (payload.get("decision") or "").lower()
    approver_id = payload.get("approver_id")
    comment = payload.get("comment") or ""

    logger.info(
        "[FinanceServiceDomain] 处理 approval_completed: approval_id=%s business_id=%s decision=%s",
        approval_id,
        business_id,
        decision,
    )

    if decision not in {"approved", "rejected"}:
        logger.warning("[FinanceServiceDomain] 未知 decision=%s，跳过入库单状态更新", decision)
        _publish_event(
            "finance.approval_completion_failed",
            {
                "approval_id": approval_id,
                "business_id": business_id,
                "error": f"unknown decision: {decision}",
                "stage": "validate_decision",
            },
            source="FinanceServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": f"unknown decision: {decision}",
            "business_id": business_id,
        }

    # 解析 PurchaseService 类（支持测试 patch）
    try:
        purchase_service_cls = _resolve_purchase_service_cls()
    except RECOVERABLE_ERRORS as exc:
        logger.exception("[FinanceServiceDomain] PurchaseService 延迟导入失败: %s", exc)
        _publish_event(
            "finance.approval_completion_failed",
            {
                "approval_id": approval_id,
                "business_id": business_id,
                "error": f"PurchaseService import failed: {exc}",
                "stage": "import",
            },
            source="FinanceServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "import",
            "business_id": business_id,
        }

    try:
        service = purchase_service_cls()
        result = service.update_inbound_approval_status(business_id, decision)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 — 任何异常都不能崩溃总线
        logger.exception("[FinanceServiceDomain] update_inbound_approval_status 抛异常: %s", exc)
        _publish_event(
            "finance.approval_completion_failed",
            {
                "approval_id": approval_id,
                "business_id": business_id,
                "decision": decision,
                "error": str(exc),
                "stage": "update_inbound",
            },
            source="FinanceServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "update_inbound",
            "business_id": business_id,
        }

    if not result.get("success"):
        error_msg = result.get("message") or "update_inbound_approval_status returned failure"
        logger.warning(
            "[FinanceServiceDomain] update_inbound_approval_status 业务失败: %s",
            error_msg,
        )
        _publish_event(
            "finance.approval_completion_failed",
            {
                "approval_id": approval_id,
                "business_id": business_id,
                "decision": decision,
                "error": error_msg,
                "stage": "business",
            },
            source="FinanceServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": error_msg,
            "stage": "business",
            "business_id": business_id,
        }

    archived_event_id = _publish_event(
        "finance.approval_archived",
        {
            "approval_id": approval_id,
            "business_type": business_type,
            "business_id": business_id,
            "decision": decision,
            "approver_id": approver_id,
            "comment": comment,
            "status": result.get("status", decision),
        },
        source="FinanceServiceDomain",
    )

    logger.info(
        "[FinanceServiceDomain] 审批完成已归档 business_id=%s decision=%s event_id=%s",
        business_id,
        decision,
        archived_event_id,
    )

    return {
        "success": True,
        "business_id": business_id,
        "decision": decision,
        "approval_id": approval_id,
        "archived_event_id": archived_event_id,
    }


# ---------------------------------------------------------------------------
# 注册入口（向后兼容类形态，与 inventory/ocr 等域一致）
# ---------------------------------------------------------------------------
class FinanceServiceDomainHandlers:
    """Finance 领域事件处理器（向后兼容类）"""

    def __init__(self):
        self.bus = get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("finance.approval_requested", handle_approval_requested)
        self.bus.subscribe("finance.approval_completed", handle_approval_completed)
        logger.info(
            "[FinanceServiceDomain] 已注册 %d 个事件处理器",
            len(self.bus._handlers.get("finance.approval_requested", []))
            + len(self.bus._handlers.get("finance.approval_completed", [])),
        )


_handlers: FinanceServiceDomainHandlers | None = None


def get_finance_handlers() -> FinanceServiceDomainHandlers:
    """获取领域处理器单例"""
    global _handlers
    if _handlers is None:
        _handlers = FinanceServiceDomainHandlers()
    return _handlers


def register_finance_domain_handlers(bus):
    """注册所有 Finance 领域事件处理器到 NeuroBus"""
    handlers = get_finance_handlers()
    handlers.register()
    logger.info("[FinanceDomain] 所有事件处理器已注册")
