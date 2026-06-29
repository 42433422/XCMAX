# CI SSOT: generated from config/neuro_bus_events.yaml — DO NOT EDIT BY HAND
# 改事件契约请编辑该 yaml 后运行: python scripts/dev/neuro_bus_events_ssot.py generate --apply

"""NeuroBus event-type constants (derived from SSOT, zero business deps).

Key invariant: every constant is a plain str (NOT Enum). Usage like
    bus.subscribe(RunEvents.CREATED, handler)
is byte-identical to
    bus.subscribe("run.created", handler)
so existing string-equality call sites are unaffected.
"""
from __future__ import annotations
from typing import Literal

# ─── Stream: agent_run ──────────────────────────────────────────

class ArtifactEvents:
    ARTIFACT_ATTACHED = "artifact.attached"

class BillingEvents:
    BILLING_DEBITED = "billing.debited"
    BILLING_INSUFFICIENT_BALANCE = "billing.insufficient_balance"
    BILLING_DEBIT_FAILED = "billing.debit_failed"
    BILLING_RECORDED = "billing.recorded"
    BILLING_RECORD_FAILED = "billing.record_failed"
    BILLING_REFUNDED = "billing.refunded"
    BILLING_REFUND_PENDING = "billing.refund_pending"
    BILLING_REFUND_RECORDED = "billing.refund_recorded"
    BILLING_REFUND_FAILED = "billing.refund_failed"

class BudgetEvents:
    BUDGET_EXCEEDED = "budget.exceeded"  # terminal

class DatasetEvents:
    DATASET_INGESTED = "dataset.ingested"
    DATASET_INGEST_FAILED = "dataset.ingest_failed"

class LLMEvents:
    LLM_COMPLETED = "llm.completed"
    LLM_FAILED = "llm.failed"

class MemoryEvents:
    MEMORY_RECALLED = "memory.recalled"
    MEMORY_FAILED = "memory.failed"

class ObservationEvents:
    OBSERVATION_RECORDED = "observation.recorded"

class PlannerEvents:
    PLANNER_STARTED = "planner.started"
    PLANNER_COMPLETED = "planner.completed"
    PLANNER_BLOCKED = "planner.blocked"  # terminal

class RagEvents:
    RAG_RETRIEVED = "rag.retrieved"
    RAG_FAILED = "rag.failed"

class RunEvents:
    RUN_CREATED = "run.created"  # sla_tier=conscious
    RUN_COMPLETED = "run.completed"  # terminal
    RUN_FAILED = "run.failed"  # terminal
    RUN_CONTINUE_IGNORED = "run.continue_ignored"

class StepEvents:
    STEP_BLOCKED = "step.blocked"
    STEP_WAITING_USER = "step.waiting_user"
    STEP_APPROVED = "step.approved"
    STEP_REPAIR_APPLIED = "step.repair_applied"
    STEP_RETRY_SCHEDULED = "step.retry_scheduled"
    STEP_LLM_REPAIR_REQUESTED = "step.llm_repair_requested"
    STEP_LLM_REPAIR_FAILED = "step.llm_repair_failed"
    STEP_REPAIR_REJECTED = "step.repair_rejected"

class ToolEvents:
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

# ─── Stream: neuro_bus ──────────────────────────────────────────

class AiEvents:
    AI_INTENT_RECOGNIZED = "ai.intent_recognized"  # sla_tier=reflex
    AI_RESPONSE_GENERATED = "ai.response_generated"  # sla_tier=subconscious
    AI_CONVERSATION_STARTED = "ai.conversation_started"
    AI_CONVERSATION_ENDED = "ai.conversation_ended"
    AI_FEEDBACK_RECEIVED = "ai.feedback_received"
    AI_CONTEXT_UPDATED = "ai.context_updated"

class AuthEvents:
    AUTH_USER_LOGIN = "auth.user_login"
    AUTH_USER_LOGOUT = "auth.user_logout"
    AUTH_USER_REGISTERED = "auth.user_registered"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_PERMISSION_GRANTED = "auth.permission_granted"
    AUTH_PERMISSION_REVOKED = "auth.permission_revoked"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_TOKEN_REFRESHED = "auth.token_refreshed"

class ConversationEvents:
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_MESSAGE_ADDED = "conversation.message_added"
    CONVERSATION_ENDED = "conversation.ended"
    CONVERSATION_ASSIGNED = "conversation.assigned"
    CONVERSATION_TAGGED = "conversation.tagged"
    CONVERSATION_EXPORTED = "conversation.exported"

class CustomerEvents:
    CUSTOMER_REGISTERED = "customer.registered"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_DEACTIVATED = "customer.deactivated"
    CUSTOMER_PURCHASE_UNIT_BOUND = "customer.purchase_unit_bound"
    CUSTOMER_PREFERENCE_UPDATED = "customer.preference_updated"
    CUSTOMER_CREDIT_LIMIT_CHANGED = "customer.credit_limit_changed"

class InventoryEvents:
    INVENTORY_STOCK_CHANGED = "inventory.stock_changed"
    INVENTORY_LOW_STOCK_ALERT = "inventory.low_stock_alert"
    INVENTORY_STOCK_IN = "inventory.stock_in"
    INVENTORY_STOCK_OUT = "inventory.stock_out"
    INVENTORY_TRANSFER = "inventory.transfer"
    INVENTORY_CHECK_COMPLETED = "inventory.check_completed"

class MaterialEvents:
    MATERIAL_CREATED = "material.created"
    MATERIAL_UPDATED = "material.updated"
    MATERIAL_STOCK_IN = "material.stock_in"
    MATERIAL_STOCK_OUT = "material.stock_out"
    MATERIAL_LOW_STOCK_ALERT = "material.low_stock_alert"
    MATERIAL_SUPPLIER_CHANGED = "material.supplier_changed"

class OcrEvents:
    OCR_TASK_SUBMITTED = "ocr.task_submitted"
    OCR_TASK_STARTED = "ocr.task_started"
    OCR_TASK_COMPLETED = "ocr.task_completed"
    OCR_TASK_FAILED = "ocr.task_failed"
    OCR_RESULT_VALIDATED = "ocr.result_validated"
    OCR_BATCH_COMPLETED = "ocr.batch_completed"

class OrderEvents:
    ORDER_SUBMITTED = "order.submitted"
    ORDER_PAID = "order.paid"
    ORDER_PAYMENT_FAILED = "order.payment_failed"
    ORDER_FULFILLED = "order.fulfilled"
    ORDER_SHIPPED = "order.shipped"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_REFUNDED = "order.refunded"
    ORDER_ITEM_UPDATED = "order.item_updated"
    ORDER_STATUS_CHANGED = "order.status_changed"

class PaymentEvents:
    PAYMENT_CREATED = "payment.created"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    PAYMENT_METHOD_CHANGED = "payment.method_changed"
    PAYMENT_NOTIFICATION_SENT = "payment.notification_sent"

class PrintEvents:
    PRINT_JOB_SUBMITTED = "print.job_submitted"
    PRINT_JOB_STARTED = "print.job_started"
    PRINT_JOB_COMPLETED = "print.job_completed"
    PRINT_JOB_FAILED = "print.job_failed"
    PRINT_PRINTER_STATUS_CHANGED = "print.printer_status_changed"
    PRINT_LABEL_REQUESTED = "print.label_requested"

class ProductEvents:
    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"
    PRODUCT_DELETED = "product.deleted"
    PRODUCT_IMPORTED = "product.imported"
    PRODUCT_PRICE_CHANGED = "product.price_changed"
    PRODUCT_CACHE_INVALIDATED = "product.cache_invalidated"

class ShipmentEvents:
    SHIPMENT_CREATED = "shipment.created"
    SHIPMENT_ITEM_ADDED = "shipment.item_added"
    SHIPMENT_PRINTED = "shipment.printed"
    SHIPMENT_CANCELLED = "shipment.cancelled"
    SHIPMENT_DELETED = "shipment.deleted"
    SHIPMENT_EXPORTED = "shipment.exported"
    SHIPMENT_INVENTORY_DEDUCTED = "shipment.inventory_deducted"

class WechatEvents:
    WECHAT_MESSAGE_RECEIVED = "wechat.message_received"
    WECHAT_MESSAGE_SENT = "wechat.message_sent"
    WECHAT_CONTACT_ADDED = "wechat.contact_added"
    WECHAT_CONTACT_UPDATED = "wechat.contact_updated"
    WECHAT_TASK_CREATED = "wechat.task_created"
    WECHAT_TASK_COMPLETED = "wechat.task_completed"
    WECHAT_LOGIN_STATUS_CHANGED = "wechat.login_status_changed"

# ─── Stream: application_bridge ──────────────────────────────────────────

class HttpBridgeEvents:
    HTTP_REQUEST_STARTED = "http.request.started"
    HTTP_REQUEST_COMPLETED = "http.request.completed"
    HTTP_REQUEST_FAILED = "http.request.failed"

# ─── Aggregate ──────────────────────────────────────────────────
ALL_EVENT_TYPES: frozenset[str] = frozenset({
    "ai.context_updated",
    "ai.conversation_ended",
    "ai.conversation_started",
    "ai.feedback_received",
    "ai.intent_recognized",
    "ai.response_generated",
    "artifact.attached",
    "auth.login_failed",
    "auth.password_changed",
    "auth.permission_granted",
    "auth.permission_revoked",
    "auth.token_refreshed",
    "auth.user_login",
    "auth.user_logout",
    "auth.user_registered",
    "billing.debit_failed",
    "billing.debited",
    "billing.insufficient_balance",
    "billing.record_failed",
    "billing.recorded",
    "billing.refund_failed",
    "billing.refund_pending",
    "billing.refund_recorded",
    "billing.refunded",
    "budget.exceeded",
    "conversation.assigned",
    "conversation.created",
    "conversation.ended",
    "conversation.exported",
    "conversation.message_added",
    "conversation.tagged",
    "customer.credit_limit_changed",
    "customer.deactivated",
    "customer.preference_updated",
    "customer.purchase_unit_bound",
    "customer.registered",
    "customer.updated",
    "dataset.ingest_failed",
    "dataset.ingested",
    "http.request.completed",
    "http.request.failed",
    "http.request.started",
    "inventory.check_completed",
    "inventory.low_stock_alert",
    "inventory.stock_changed",
    "inventory.stock_in",
    "inventory.stock_out",
    "inventory.transfer",
    "llm.completed",
    "llm.failed",
    "material.created",
    "material.low_stock_alert",
    "material.stock_in",
    "material.stock_out",
    "material.supplier_changed",
    "material.updated",
    "memory.failed",
    "memory.recalled",
    "observation.recorded",
    "ocr.batch_completed",
    "ocr.result_validated",
    "ocr.task_completed",
    "ocr.task_failed",
    "ocr.task_started",
    "ocr.task_submitted",
    "order.cancelled",
    "order.fulfilled",
    "order.item_updated",
    "order.paid",
    "order.payment_failed",
    "order.refunded",
    "order.shipped",
    "order.status_changed",
    "order.submitted",
    "payment.completed",
    "payment.created",
    "payment.failed",
    "payment.method_changed",
    "payment.notification_sent",
    "payment.refunded",
    "planner.blocked",
    "planner.completed",
    "planner.started",
    "print.job_completed",
    "print.job_failed",
    "print.job_started",
    "print.job_submitted",
    "print.label_requested",
    "print.printer_status_changed",
    "product.cache_invalidated",
    "product.created",
    "product.deleted",
    "product.imported",
    "product.price_changed",
    "product.updated",
    "rag.failed",
    "rag.retrieved",
    "run.completed",
    "run.continue_ignored",
    "run.created",
    "run.failed",
    "shipment.cancelled",
    "shipment.created",
    "shipment.deleted",
    "shipment.exported",
    "shipment.inventory_deducted",
    "shipment.item_added",
    "shipment.printed",
    "step.approved",
    "step.blocked",
    "step.llm_repair_failed",
    "step.llm_repair_requested",
    "step.repair_applied",
    "step.repair_rejected",
    "step.retry_scheduled",
    "step.waiting_user",
    "tool.completed",
    "tool.failed",
    "tool.started",
    "wechat.contact_added",
    "wechat.contact_updated",
    "wechat.login_status_changed",
    "wechat.message_received",
    "wechat.message_sent",
    "wechat.task_completed",
    "wechat.task_created",
})

AGENT_RUN_EVENT_TYPES: frozenset[str] = frozenset({
    "artifact.attached",
    "billing.debit_failed",
    "billing.debited",
    "billing.insufficient_balance",
    "billing.record_failed",
    "billing.recorded",
    "billing.refund_failed",
    "billing.refund_pending",
    "billing.refund_recorded",
    "billing.refunded",
    "budget.exceeded",
    "dataset.ingest_failed",
    "dataset.ingested",
    "llm.completed",
    "llm.failed",
    "memory.failed",
    "memory.recalled",
    "observation.recorded",
    "planner.blocked",
    "planner.completed",
    "planner.started",
    "rag.failed",
    "rag.retrieved",
    "run.completed",
    "run.continue_ignored",
    "run.created",
    "run.failed",
    "step.approved",
    "step.blocked",
    "step.llm_repair_failed",
    "step.llm_repair_requested",
    "step.repair_applied",
    "step.repair_rejected",
    "step.retry_scheduled",
    "step.waiting_user",
    "tool.completed",
    "tool.failed",
    "tool.started",
})

TERMINAL_AGENT_RUN_EVENT_TYPES: frozenset[str] = frozenset({
    "budget.exceeded",
    "planner.blocked",
    "run.completed",
    "run.failed",
})

EventType = Literal[
    "ai.context_updated",
    "ai.conversation_ended",
    "ai.conversation_started",
    "ai.feedback_received",
    "ai.intent_recognized",
    "ai.response_generated",
    "artifact.attached",
    "auth.login_failed",
    "auth.password_changed",
    "auth.permission_granted",
    "auth.permission_revoked",
    "auth.token_refreshed",
    "auth.user_login",
    "auth.user_logout",
    "auth.user_registered",
    "billing.debit_failed",
    "billing.debited",
    "billing.insufficient_balance",
    "billing.record_failed",
    "billing.recorded",
    "billing.refund_failed",
    "billing.refund_pending",
    "billing.refund_recorded",
    "billing.refunded",
    "budget.exceeded",
    "conversation.assigned",
    "conversation.created",
    "conversation.ended",
    "conversation.exported",
    "conversation.message_added",
    "conversation.tagged",
    "customer.credit_limit_changed",
    "customer.deactivated",
    "customer.preference_updated",
    "customer.purchase_unit_bound",
    "customer.registered",
    "customer.updated",
    "dataset.ingest_failed",
    "dataset.ingested",
    "http.request.completed",
    "http.request.failed",
    "http.request.started",
    "inventory.check_completed",
    "inventory.low_stock_alert",
    "inventory.stock_changed",
    "inventory.stock_in",
    "inventory.stock_out",
    "inventory.transfer",
    "llm.completed",
    "llm.failed",
    "material.created",
    "material.low_stock_alert",
    "material.stock_in",
    "material.stock_out",
    "material.supplier_changed",
    "material.updated",
    "memory.failed",
    "memory.recalled",
    "observation.recorded",
    "ocr.batch_completed",
    "ocr.result_validated",
    "ocr.task_completed",
    "ocr.task_failed",
    "ocr.task_started",
    "ocr.task_submitted",
    "order.cancelled",
    "order.fulfilled",
    "order.item_updated",
    "order.paid",
    "order.payment_failed",
    "order.refunded",
    "order.shipped",
    "order.status_changed",
    "order.submitted",
    "payment.completed",
    "payment.created",
    "payment.failed",
    "payment.method_changed",
    "payment.notification_sent",
    "payment.refunded",
    "planner.blocked",
    "planner.completed",
    "planner.started",
    "print.job_completed",
    "print.job_failed",
    "print.job_started",
    "print.job_submitted",
    "print.label_requested",
    "print.printer_status_changed",
    "product.cache_invalidated",
    "product.created",
    "product.deleted",
    "product.imported",
    "product.price_changed",
    "product.updated",
    "rag.failed",
    "rag.retrieved",
    "run.completed",
    "run.continue_ignored",
    "run.created",
    "run.failed",
    "shipment.cancelled",
    "shipment.created",
    "shipment.deleted",
    "shipment.exported",
    "shipment.inventory_deducted",
    "shipment.item_added",
    "shipment.printed",
    "step.approved",
    "step.blocked",
    "step.llm_repair_failed",
    "step.llm_repair_requested",
    "step.repair_applied",
    "step.repair_rejected",
    "step.retry_scheduled",
    "step.waiting_user",
    "tool.completed",
    "tool.failed",
    "tool.started",
    "wechat.contact_added",
    "wechat.contact_updated",
    "wechat.login_status_changed",
    "wechat.message_received",
    "wechat.message_sent",
    "wechat.task_completed",
    "wechat.task_created",
]

AgentRunEventType = Literal[
    "artifact.attached",
    "billing.debit_failed",
    "billing.debited",
    "billing.insufficient_balance",
    "billing.record_failed",
    "billing.recorded",
    "billing.refund_failed",
    "billing.refund_pending",
    "billing.refund_recorded",
    "billing.refunded",
    "budget.exceeded",
    "dataset.ingest_failed",
    "dataset.ingested",
    "llm.completed",
    "llm.failed",
    "memory.failed",
    "memory.recalled",
    "observation.recorded",
    "planner.blocked",
    "planner.completed",
    "planner.started",
    "rag.failed",
    "rag.retrieved",
    "run.completed",
    "run.continue_ignored",
    "run.created",
    "run.failed",
    "step.approved",
    "step.blocked",
    "step.llm_repair_failed",
    "step.llm_repair_requested",
    "step.repair_applied",
    "step.repair_rejected",
    "step.retry_scheduled",
    "step.waiting_user",
    "tool.completed",
    "tool.failed",
    "tool.started",
]

def is_known_event_type(s: str) -> bool:
    """Return True if s is a registered event type across all three streams."""
    return s in ALL_EVENT_TYPES

def is_agent_run_event_type(s: str) -> bool:
    """Return True if s is a registered agent_run stream event type."""
    return s in AGENT_RUN_EVENT_TYPES
