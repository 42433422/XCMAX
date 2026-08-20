# mypy: disable-error-code="arg-type"
"""Request models and evidence helpers for customer custom delivery."""

from __future__ import annotations

from typing import Any

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
