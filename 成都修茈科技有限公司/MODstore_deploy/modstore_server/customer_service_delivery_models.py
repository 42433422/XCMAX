# mypy: disable-error-code="arg-type"
"""Request models and evidence helpers for customer custom delivery."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from modstore_server.customer_service_tools import json_loads
from modstore_server.models_cs import CustomerServiceTicket


class CustomDeliveryCreateBody(BaseModel):
    kind: str = Field(..., pattern="^(module|employee|bundle)$")
    title: str = Field(..., min_length=2, max_length=128)
    requirements: str = Field(..., min_length=8, max_length=12000)
    acceptance_criteria: str = Field(..., min_length=4, max_length=6000)
    suggested_id: str | None = Field(None, max_length=64)


class CustomDeliveryDecisionBody(BaseModel):
    action: str = Field(..., pattern="^(accept|rework)$")
    note: str = Field(default="", max_length=4000)


class CustomDeliveryInstallReceiptBody(BaseModel):
    artifact_kind: str = Field(..., pattern="^(module|employee)$")
    artifact_id: str = Field(..., min_length=1, max_length=128)
    installed_version: str = Field(default="", max_length=64)
    host: str = Field(default="XCAGI", max_length=128)
    receipt_token: str = Field(..., min_length=16, max_length=128)


class CustomDeliveryPaymentCheckoutBody(BaseModel):
    pay_channel: str = Field(default="alipay", pattern="^(alipay|wechat)$")


class CustomDeliveryCrmUpdateBody(BaseModel):
    section: Literal["assignment", "quote", "contract", "payment"]
    status: str = Field(default="", max_length=32)
    owner_name: str = Field(default="", max_length=128)
    number: str = Field(default="", max_length=128)
    amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", max_length=8)
    reference: str = Field(default="", max_length=512)
    valid_until: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=2000)


def custom_delivery_crm(evidence: dict[str, Any]) -> dict[str, Any]:
    raw_value = evidence.get("crm")
    raw: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}

    def _section(name: str) -> dict[str, Any]:
        value = raw.get(name)
        return value if isinstance(value, dict) else {}

    assignment = _section("assignment")
    quote = _section("quote")
    contract = _section("contract")
    payment = _section("payment")
    return {
        "assignment": {
            "status": (
                "assigned" if str(assignment.get("owner_name") or "").strip() else "unassigned"
            ),
            **assignment,
        },
        "quote": {
            "status": "draft",
            **quote,
        },
        "contract": {
            "status": "draft",
            **contract,
        },
        "payment": {
            "status": "unpaid",
            **payment,
        },
    }


def custom_delivery_pricing_mode(evidence: dict[str, Any]) -> str:
    terms = evidence.get("delivery_terms")
    terms = terms if isinstance(terms, dict) else {}
    value = str(terms.get("pricing_mode") or "").strip()
    return value if value in {"initial_included", "post_delivery_addon"} else "legacy"


def custom_delivery_commerce_blockers(evidence: dict[str, Any]) -> list[str]:
    pricing_mode = custom_delivery_pricing_mode(evidence)
    if pricing_mode == "initial_included":
        return []
    crm = custom_delivery_crm(evidence)
    blockers: list[str] = []
    if crm["assignment"].get("status") != "assigned":
        blockers.append("未指派交付负责人")
    accepted_quote_statuses = (
        {"accepted"} if pricing_mode == "post_delivery_addon" else {"accepted", "waived"}
    )
    if crm["quote"].get("status") not in accepted_quote_statuses:
        blockers.append("报价尚未确认")
    if pricing_mode == "legacy" and crm["contract"].get("status") not in {
        "signed",
        "waived",
    }:
        blockers.append("合同尚未签署")
    accepted_payment_statuses = (
        {"paid"} if pricing_mode == "post_delivery_addon" else {"paid", "waived"}
    )
    if crm["payment"].get("status") not in accepted_payment_statuses:
        blockers.append("款项尚未结清")
    return blockers


def custom_delivery_evidence(ticket: CustomerServiceTicket) -> dict[str, Any]:
    evidence = json_loads(ticket.evidence_json, {})
    return evidence if isinstance(evidence, dict) else {}


def custom_delivery_brief(evidence: dict[str, Any], rework_note: str = "") -> str:
    kind_labels = {
        "module": "定制业务模块",
        "employee": "定制 AI 员工",
        "bundle": "定制 Mod + AI 员工",
    }
    parts = [
        f"交付类型：{kind_labels.get(str(evidence.get('kind') or ''), '客户定制')}",
        f"需求名称：{str(evidence.get('title') or '').strip()}",
        f"需求说明：{str(evidence.get('requirements') or '').strip()}",
        f"验收标准：{str(evidence.get('acceptance_criteria') or '').strip()}",
        "产物必须通过工作台内置的沙箱、工作流和质量门，不得用占位实现冒充交付。",
    ]
    if rework_note:
        parts.append(f"本轮返工意见：{rework_note.strip()}")
    return "\n\n".join(parts)
