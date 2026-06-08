"""Canonical MODstore domain event contracts.

The in-process NeuroBus and the cross-service business webhook use the same
event names and payload shapes. Keep this registry small and explicit so Python
and Java publishers do not drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventContract:
    name: str
    version: int
    aggregate: str
    required_payload: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


PAYMENT_PAID = "payment.paid"
PAYMENT_ORDER_PAID_LEGACY = "payment.order_paid"
WALLET_BALANCE_CHANGED = "wallet.balance_changed"
REFUND_APPROVED = "refund.approved"
REFUND_REJECTED = "refund.rejected"
REFUND_FAILED = "refund.failed"
EMPLOYEE_EXECUTION_COMPLETED = "employee.execution_completed"
WORKFLOW_EXECUTION_COMPLETED = "workflow.execution_completed"
WORKFLOW_EXECUTION_FAILED = "workflow.execution_failed"
CATALOG_PACKAGE_PUBLISHED = "catalog.package_published"
EMPLOYEE_PACK_REGISTERED = "employee.pack_registered"
WORKFLOW_SANDBOX_COMPLETED = "workflow.sandbox_completed"
WORKFLOW_EVENT_TRIGGER = "workflow.event_trigger"
LLM_QUOTA_CONSUMED = "llm.quota_consumed"
SUBSCRIPTION_RENEWED = "subscription.renewed"
SUBSCRIPTION_RENEWAL_FAILED = "subscription.renewal_failed"
INVOICE_CREATED = "invoice.created"
CATALOG_ITEM_PUBLISHED = "catalog.item_published"

EVENT_CONTRACTS: dict[str, EventContract] = {
    PAYMENT_PAID: EventContract(
        name=PAYMENT_PAID,
        version=1,
        aggregate="payment_order",
        required_payload=("out_trade_no", "user_id", "subject", "total_amount", "order_kind"),
        description="A payment order has been successfully paid and fulfilled.",
    ),
    WALLET_BALANCE_CHANGED: EventContract(
        name=WALLET_BALANCE_CHANGED,
        version=1,
        aggregate="wallet",
        required_payload=("user_id", "amount", "source_order_id", "transaction_type"),
        description="A user's wallet balance changed because of recharge, payment, or refund.",
    ),
    REFUND_APPROVED: EventContract(
        name=REFUND_APPROVED,
        version=1,
        aggregate="refund",
        required_payload=("refund_id", "order_no", "user_id", "amount", "status"),
        description="A refund request was approved and successfully refunded.",
    ),
    REFUND_REJECTED: EventContract(
        name=REFUND_REJECTED,
        version=1,
        aggregate="refund",
        required_payload=("refund_id", "order_no", "user_id", "amount", "status"),
        description="A refund request was rejected by an administrator.",
    ),
    REFUND_FAILED: EventContract(
        name=REFUND_FAILED,
        version=1,
        aggregate="refund",
        required_payload=("refund_id", "order_no", "user_id", "amount", "status"),
        description="A refund request was approved but downstream refund execution failed.",
    ),
    EMPLOYEE_EXECUTION_COMPLETED: EventContract(
        name=EMPLOYEE_EXECUTION_COMPLETED,
        version=1,
        aggregate="employee_execution",
        required_payload=("employee_id", "user_id", "task", "status"),
        description="An AI employee task finished (status=success/failure).",
    ),
    WORKFLOW_EXECUTION_COMPLETED: EventContract(
        name=WORKFLOW_EXECUTION_COMPLETED,
        version=1,
        aggregate="workflow_execution",
        required_payload=("workflow_id", "execution_id", "user_id", "status"),
        description="A workflow execution finished successfully.",
    ),
    WORKFLOW_EXECUTION_FAILED: EventContract(
        name=WORKFLOW_EXECUTION_FAILED,
        version=1,
        aggregate="workflow_execution",
        required_payload=("workflow_id", "execution_id", "user_id", "status"),
        description="A workflow execution ran but failed at runtime.",
    ),
    CATALOG_PACKAGE_PUBLISHED: EventContract(
        name=CATALOG_PACKAGE_PUBLISHED,
        version=1,
        aggregate="catalog_item",
        required_payload=("pkg_id", "author_id", "version", "artifact", "name"),
        description="A catalog package (e.g. employee_pack) was published to the store.",
    ),
    EMPLOYEE_PACK_REGISTERED: EventContract(
        name=EMPLOYEE_PACK_REGISTERED,
        version=1,
        aggregate="employee_pack",
        required_payload=("pack_id", "author_id", "mod_id", "version"),
        description="An employee pack was registered from a workflow manifest.",
    ),
    WORKFLOW_SANDBOX_COMPLETED: EventContract(
        name=WORKFLOW_SANDBOX_COMPLETED,
        version=1,
        aggregate="workflow_execution",
        required_payload=("workflow_id", "user_id", "status", "duration_ms"),
        description="A workflow sandbox run finished (success or failure).",
    ),
    WORKFLOW_EVENT_TRIGGER: EventContract(
        name=WORKFLOW_EVENT_TRIGGER,
        version=1,
        aggregate="workflow",
        required_payload=("workflow_id", "user_id"),
        description="Request asynchronous workflow execution driven by a domain event.",
    ),
    LLM_QUOTA_CONSUMED: EventContract(
        name=LLM_QUOTA_CONSUMED,
        version=1,
        aggregate="user_llm_credential",
        required_payload=("user_id", "provider", "model", "tokens", "cost"),
        description="LLM quota was consumed for a user request.",
    ),
    SUBSCRIPTION_RENEWED: EventContract(
        name=SUBSCRIPTION_RENEWED,
        version=1,
        aggregate="user_plan",
        required_payload=("user_id", "plan_id", "out_trade_no", "amount", "expires_at"),
        description="A subscription plan was automatically renewed and payment deducted from wallet.",
    ),
    SUBSCRIPTION_RENEWAL_FAILED: EventContract(
        name=SUBSCRIPTION_RENEWAL_FAILED,
        version=1,
        aggregate="user_plan",
        required_payload=("user_id", "plan_id", "reason"),
        description="A subscription auto-renewal failed (e.g. insufficient wallet balance).",
    ),
    INVOICE_CREATED: EventContract(
        name=INVOICE_CREATED,
        version=1,
        aggregate="invoice",
        required_payload=("invoice_id", "user_id", "order_no", "amount"),
        description="An invoice was created for a completed payment order.",
    ),
    CATALOG_ITEM_PUBLISHED: EventContract(
        name=CATALOG_ITEM_PUBLISHED,
        version=1,
        aggregate="catalog_item",
        required_payload=("item_id", "author_id", "name", "artifact"),
        description="A catalog item was published or made publicly available in the store.",
    ),
}

EVENT_ALIASES = {
    PAYMENT_ORDER_PAID_LEGACY: PAYMENT_PAID,
}


def canonical_event_name(event_name: str) -> str:
    return EVENT_ALIASES.get(event_name, event_name)


def event_version(event_name: str) -> int:
    contract = EVENT_CONTRACTS.get(canonical_event_name(event_name))
    return contract.version if contract else 1


def validate_payload(event_name: str, payload: dict[str, Any]) -> list[str]:
    contract = EVENT_CONTRACTS.get(canonical_event_name(event_name))
    if not contract:
        return []
    return [key for key in contract.required_payload if key not in payload]
