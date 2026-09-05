# mypy: disable-error-code="arg-type"
"""Request models and evidence helpers for customer custom delivery."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from modstore_server.customer_service_tools import json_dumps, json_loads
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
    receipt_id: str = Field(default="", max_length=128)
    stage: Literal["installed", "running", "verification_failed"] = "installed"
    package_sha256: str = Field(default="", max_length=64)
    client_instance_id: str = Field(default="", max_length=128)
    host_sha: str = Field(default="", max_length=40)
    runtime_files_sha256: str = Field(default="", max_length=64)
    business_verification: dict[str, Any] = Field(default_factory=dict)


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
        "Mod 前端须提供 frontend/src/index.js，export mount(container, sdk)，使用宿主参数 sdk.version=1、sdk.modId、sdk.route、sdk.signal、sdk.request(path,init)、sdk.navigate(path)，返回卸载函数，禁止外部 import；manifest.frontend.runtime 声明 sdk_version=1、source=frontend/src/index.js、entry=frontend/runtime/index.js。禁止依赖宿主编译 glob 的 Vue 路由。",
        "每个产物须声明 manifest.delivery_verification={handler:'verify_delivery',case_id:'固定业务用例标识'}；在 backend_entry_module 实现 verify_delivery(request)，用隔离样例验证原业务并返回 passed 和非空 observations，禁止写客户数据或返回占位成功。正式交付必须通过共享编译器和受信 Ed25519 签包器。",
        "私有员工源仍为 employee_pack，必须提供 backend/employees 下明确的 run(payload,ctx)，以 ctx.workspace_root/owner_id/user_id 访问当前账号工作区；不得依赖全局员工安装、进程全局名单或启动触发器。业务探针须在临时目录实际执行该 run 并核对输出内容，不能只核对导入、路由或健康。正式交付会保留员工源并封装为账号绑定 Mod，由相同安装与业务回执闭环验证。",
    ]
    if rework_note:
        parts.append(f"本轮返工意见：{rework_note.strip()}")
    if evidence.get("runtime_failure"):
        parts.append(f"客户宿主真实验证失败证据：{json_dumps(evidence['runtime_failure'])[:6000]}")
    return "\n\n".join(parts)
