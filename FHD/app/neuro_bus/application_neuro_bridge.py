"""
Application / Services 层与 NeuroBus 的同步桥接（无 asyncio 依赖）。

在 ``XCAGI_NEURO_INTENT`` 关闭时全部短路为 no-op。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _stack_on() -> bool:
    try:
        from app.neuro_bus.integrations.intent_integration import is_neuro_stack_enabled

        return is_neuro_stack_enabled()
    except RECOVERABLE_ERRORS:
        return False


def _publish(event_type: str, payload: dict[str, Any], domain: str) -> bool:
    if not _stack_on():
        return False
    try:
        from app.mod_sdk.neuro_bus_runtime import publish_neuro_event_runtime

        return publish_neuro_event_runtime(event_type, payload, domain)
    except RECOVERABLE_ERRORS:
        logger.debug("application_neuro_bridge publish failed", exc_info=True)
        return False


def publish_neuro_event(event_type: str, payload: dict[str, Any], domain: str = "global") -> bool:
    """HTTP 中间件等外部入口使用的同步发布。"""
    return _publish(event_type, payload, domain)


_APPLICATION_SERVICE_DOMAIN: tuple[tuple[str, str], ...] = (
    ("ShipmentApplicationService", "order"),
    ("ProductImportApplicationService", "product"),
    ("UnitProductsImportService", "product"),
    ("ProductApplicationService", "product"),
    ("PrintApplicationService", "print"),
    ("TemplateApplicationService", "print"),
    ("OCRApplicationService", "ocr"),
    ("WechatTaskApplicationService", "wechat"),
    ("WechatContactApplicationService", "wechat"),
    ("CustomerApplicationService", "customer"),
    ("UserApplicationService", "customer"),
    ("UserPreferenceApplicationService", "customer"),
    ("AuthApplicationService", "safety"),
    ("MaterialApplicationService", "product"),
    ("ExcelVectorIngestApplicationService", "ai_service"),
    ("ExcelVectorSearchApplicationService", "ai_service"),
    ("ExtractLogApplicationService", "ai_service"),
    ("FileAnalysisService", "ai_service"),
    ("UserMemoryVectorIngestApplicationService", "ai_service"),
    ("UserMemoryRagApplicationService", "ai_service"),
    ("ApprovalService", "safety"),
)


def resolve_application_domain(service_class_name: str) -> str:
    for cls_name, dom in _APPLICATION_SERVICE_DOMAIN:
        if cls_name == service_class_name:
            return dom
    return "ai_service"


def neuro_trace_app_service_call(
    service_name: str,
    method: str,
    phase: str,
    *,
    duration_ms: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Application 层通用 trace（phase=start|end|error）。"""
    payload: dict[str, Any] = {
        "service": service_name,
        "method": method,
        "phase": phase,
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 4)
    if error:
        payload["error"] = error[:500]
    if extra:
        for k, v in list(extra.items())[:24]:
            if isinstance(v, (str, int, float, bool)) or v is None:
                payload[str(k)[:64]] = v
            else:
                payload[str(k)[:64]] = str(type(v).__name__)
    _publish("application.service.trace", payload, resolve_application_domain(service_name))


def neuro_trace_service_call(
    module: str,
    func_name: str,
    phase: str,
    *,
    duration_ms: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Services 层通用 trace。"""
    try:
        from app.neuro_bus.neuro_trace_config import is_neuro_service_layer_trace_enabled

        if not is_neuro_service_layer_trace_enabled():
            return
    except RECOVERABLE_ERRORS:
        pass
    if not _stack_on():
        return
    payload: dict[str, Any] = {"module": module, "function": func_name, "phase": phase}
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 4)
    if error:
        payload["error"] = error[:500]
    if extra:
        for k, v in list(extra.items())[:20]:
            if isinstance(v, (str, int, float, bool)) or v is None:
                payload[str(k)[:64]] = v
            else:
                payload[str(k)[:64]] = str(type(v).__name__)
    dom = "intent" if "intent" in module.lower() else "ai_service"
    _publish("service.module.trace", payload, dom)


def neuro_notify_chat_received(
    user_id: str,
    message: str,
    source: str | None = None,
) -> None:
    """AI 聊天应用服务：用户消息进入编排（Application 层）。"""
    _publish(
        "application.chat.received",
        {
            "user_id": user_id,
            "source": source,
            "message_preview": (message or "")[:500],
            "request_id": str(uuid.uuid4()),
        },
        domain="ai_service",
    )


def neuro_notify_chat_completed(
    user_id: str,
    user_message: str,
    response: dict[str, Any],
) -> None:
    """AI 聊天应用服务：单次编排返回前（含 workflow 早退）。"""
    ok = bool(response.get("success", True))
    _publish(
        "application.chat.completed",
        {
            "user_id": user_id,
            "success": ok,
            "action": response.get("action"),
            "message_preview": (user_message or "")[:200],
            "response_keys": list(response.keys())[:40],
        },
        domain="ai_service",
    )


def neuro_notify_conversation_message_saved(
    session_id: str,
    user_id: str,
    role: str,
    intent: str = "",
) -> None:
    """对话落库（Application / 持久化边界）。"""
    _publish(
        "application.conversation.message_saved",
        {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "intent": intent,
        },
        domain="ai_service",
    )


def neuro_notify_intent_resolved(user_id: str, intent_result: dict[str, Any]) -> None:
    """Services 层：一次意图识别结果已定（含 reflex / hybrid / unified）。"""
    _publish(
        "service.intent.resolved",
        {
            "user_id": user_id,
            "intent_source": intent_result.get("intent_source"),
            "primary_intent": intent_result.get("primary_intent")
            or intent_result.get("final_intent"),
            "tool_key": intent_result.get("tool_key"),
            "ai_mode": intent_result.get("ai_mode"),
        },
        domain="intent",
    )


def neuro_notify_ai_model_roundtrip(
    *,
    model: str,
    latency_ms: float,
    token_count: int = 0,
    user_id: str = "",
) -> None:
    """Services 层完成一次主模型推理后可选调用（轻量）。"""
    if not _stack_on():
        return
    try:
        from app.neuro_bus.domains.ai_service_domain import get_ai_service_domain

        get_ai_service_domain().emit_ai_completed(
            request_id=str(uuid.uuid4()),
            model=model,
            latency_ms=latency_ms,
            token_count=token_count,
        )
    except RECOVERABLE_ERRORS:
        logger.debug("neuro_notify_ai_model_roundtrip skipped", exc_info=True)


# --------------------------------------------------------------------------- #
# P2 NeuroBus 迁移：核心业务事件发布（2026-06-20）
# 将双轨/DB-only 服务的关键状态变更通过 NeuroBus 广播，提升采用率。
# --------------------------------------------------------------------------- #

def neuro_notify_customer_changed(
    action: str,
    customer_id: str | int = "",
    customer_name: str = "",
    tenant_id: str = "",
) -> None:
    """客户应用服务：PurchaseUnit 增删改后广播（action=created|updated|deleted）。"""
    _publish(
        "application.customer.changed",
        {
            "action": action,
            "customer_id": str(customer_id),
            "customer_name": (customer_name or "")[:120],
            "tenant_id": tenant_id,
        },
        domain="customer",
    )


def neuro_notify_user_authenticated(
    user_id: str,
    auth_method: str = "",
    success: bool = True,
) -> None:
    """认证应用服务：OIDC/密码登录结果（find-or-create / 更新登录信息后）。"""
    _publish(
        "application.auth.completed",
        {
            "user_id": str(user_id),
            "auth_method": auth_method,
            "success": success,
        },
        domain="safety",
    )


def neuro_notify_user_changed(
    action: str,
    user_id: str | int = "",
    username: str = "",
) -> None:
    """用户应用服务：User 增删改后广播（action=created|updated|deleted）。"""
    _publish(
        "application.user.changed",
        {
            "action": action,
            "user_id": str(user_id),
            "username": (username or "")[:120],
        },
        domain="customer",
    )


def neuro_notify_wechat_task_changed(
    action: str,
    task_id: str | int = "",
    status: str = "",
) -> None:
    """微信任务应用服务：WechatTask 创建/状态更新后广播。"""
    _publish(
        "application.wechat_task.changed",
        {
            "action": action,
            "task_id": str(task_id),
            "status": status,
        },
        domain="wechat",
    )


def neuro_notify_approval_changed(
    action: str,
    approval_id: str | int = "",
    flow_id: str | int = "",
    decision: str = "",
) -> None:
    """审批服务：审批请求创建/决议后广播（action=created|approved|rejected|timeout）。"""
    _publish(
        "application.approval.changed",
        {
            "action": action,
            "approval_id": str(approval_id),
            "flow_id": str(flow_id),
            "decision": decision,
        },
        domain="safety",
    )


def neuro_notify_products_imported(
    count: int = 0,
    customer_id: str = "",
    source: str = "",
) -> None:
    """单位产品导入服务：批量导入完成后广播。"""
    _publish(
        "application.products.imported",
        {
            "count": count,
            "customer_id": customer_id,
            "source": source,
        },
        domain="product",
    )


def neuro_notify_transaction_changed(
    action: str,
    transaction_id: str | int = "",
    amount: float = 0.0,
    txn_type: str = "",
) -> None:
    """财务应用服务：FinancialTransaction 增改后广播（action=created|updated）。"""
    _publish(
        "application.finance.transaction_changed",
        {
            "action": action,
            "transaction_id": str(transaction_id),
            "amount": amount,
            "txn_type": txn_type,
        },
        domain="finance",
    )


def neuro_notify_tenant_changed(
    action: str,
    tenant_id: str = "",
    tenant_name: str = "",
) -> None:
    """租户订阅服务：租户创建/更新后广播。"""
    _publish(
        "application.tenant.changed",
        {
            "action": action,
            "tenant_id": tenant_id,
            "tenant_name": (tenant_name or "")[:120],
        },
        domain="customer",
    )


def neuro_notify_im_message_sent(
    conversation_id: str | int = "",
    sender_id: str = "",
    message_type: str = "",
) -> None:
    """IM 应用服务：消息发送后广播。"""
    _publish(
        "application.im.message_sent",
        {
            "conversation_id": str(conversation_id),
            "sender_id": sender_id,
            "message_type": message_type,
        },
        domain="im",
    )
