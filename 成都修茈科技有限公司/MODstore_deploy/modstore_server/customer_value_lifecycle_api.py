"""Authenticated six-stage customer-value receipts.

Customers may attest their own successful usage and acceptance. Administrators
may attach measured outcome material, but deliberately have no route that can
create a customer acceptance receipt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, FiniteFloat

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.customer_value_evidence import (
    append_customer_value_receipt,
    classify_payment_order,
    load_authoritative_payment_orders,
)
from modstore_server.models import User

router = APIRouter(prefix="/api/customer-value", tags=["customer-value-lifecycle"])
admin_router = APIRouter(prefix="/api/admin/customer-value", tags=["admin-customer-value"])
# Optional-router loader includes ``open_router`` as the module's second router.
# The name is legacy loader terminology; this router is still admin-protected.
open_router = admin_router


@router.get("/deliveries")
def customer_deliveries(
    order_no: str = Query(min_length=4, max_length=96),
    customer_goal_id: str = Query(min_length=4, max_length=128),
    after: int = Query(0, ge=0),
    workflow_after: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from modstore_server.strategic_customer_delivery import list_customer_deliveries
    from modstore_server.workflow_customer_delivery_api import list_workflow_deliveries

    strategic = list_customer_deliveries(
        user, order_no=order_no, goal_id=customer_goal_id, after=after
    )
    workflows = list_workflow_deliveries(
        user, order_no=order_no, goal_id=customer_goal_id, after=workflow_after
    )
    return {
        "ok": True,
        **strategic,
        "items": [*strategic["items"], *workflows["items"]],
        "workflow_next_cursor": workflows["next_cursor"],
    }


@router.get("/workflow-deliveries")
def customer_workflow_deliveries(
    order_no: str = Query(min_length=4, max_length=96),
    customer_goal_id: str = Query(min_length=4, max_length=128),
    after: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from modstore_server.workflow_customer_delivery_api import list_workflow_deliveries

    return {
        "ok": True,
        **list_workflow_deliveries(user, order_no=order_no, goal_id=customer_goal_id, after=after),
    }


@router.get("/workflow-deliveries/{execution_id}/{artifact_id}")
def customer_workflow_delivery_download(
    execution_id: int,
    artifact_id: str,
    order_no: str = Query(min_length=4, max_length=96),
    customer_goal_id: str = Query(min_length=4, max_length=128),
    user: User = Depends(get_current_user),
) -> Response:
    from modstore_server.workflow_customer_delivery_api import download_workflow_delivery

    return download_workflow_delivery(
        user,
        execution_id=execution_id,
        artifact_id=artifact_id,
        order_no=order_no,
        goal_id=customer_goal_id,
    )


@router.get("/deliveries/{decision_id}/{opportunity_id}/{artifact_id}")
def customer_delivery_download(
    decision_id: str,
    opportunity_id: str,
    artifact_id: str,
    order_no: str = Query(min_length=4, max_length=96),
    customer_goal_id: str = Query(min_length=4, max_length=128),
    user: User = Depends(get_current_user),
) -> Response:
    from modstore_server.strategic_customer_delivery import download_customer_delivery

    return download_customer_delivery(
        user,
        decision_id=decision_id,
        opportunity_id=opportunity_id,
        artifact_id=artifact_id,
        order_no=order_no,
        goal_id=customer_goal_id,
    )


class UsageReceiptBody(BaseModel):
    receipt_kind: Literal["first_use", "reuse"]
    order_no: str = Field(..., min_length=4, max_length=96)
    customer_goal_id: str = Field(..., min_length=4, max_length=128)
    idempotency_key: str = Field(..., min_length=16, max_length=192)
    run_id: str = Field(..., min_length=8, max_length=192)
    task_type: str = Field(..., min_length=2, max_length=128)
    output_id: str = Field(..., min_length=4, max_length=256)
    output_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")
    occurred_at: datetime | None = None


class KpiAgreementReceiptBody(BaseModel):
    order_no: str = Field(..., min_length=4, max_length=96)
    customer_goal_id: str = Field(..., min_length=4, max_length=128)
    idempotency_key: str = Field(..., min_length=16, max_length=192)
    baseline: FiniteFloat = Field(..., strict=True)
    target: FiniteFloat = Field(..., strict=True)
    comparison: Literal["ge", "le"]
    unit: str = Field(..., min_length=1, max_length=64)
    measurement_window: str = Field(..., min_length=3, max_length=128)
    agreement_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")
    occurred_at: datetime | None = None


class AcceptanceReceiptBody(BaseModel):
    order_no: str = Field(..., min_length=4, max_length=96)
    customer_goal_id: str = Field(..., min_length=4, max_length=128)
    idempotency_key: str = Field(..., min_length=16, max_length=192)
    acceptance_id: str = Field(..., min_length=4, max_length=128)
    accepted_artifact_id: str = Field(..., min_length=4, max_length=256)
    artifact_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")
    customer_confirmed: bool = False
    signed_document_sha256: str = Field(default="", pattern="^$|^[0-9a-fA-F]{64}$")
    occurred_at: datetime | None = None


class OutcomeReceiptBody(BaseModel):
    order_no: str = Field(..., min_length=4, max_length=96)
    customer_goal_id: str = Field(..., min_length=4, max_length=128)
    idempotency_key: str = Field(..., min_length=16, max_length=192)
    outcome_id: str = Field(..., min_length=4, max_length=256)
    artifact_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")
    baseline: FiniteFloat = Field(..., strict=True)
    target: FiniteFloat = Field(..., strict=True)
    measured_value: FiniteFloat = Field(..., strict=True)
    comparison: Literal["ge", "le"]
    unit: str = Field(..., min_length=1, max_length=64)
    measurement_window: str = Field(..., min_length=3, max_length=128)
    source_material_summary: str = Field(..., min_length=8, max_length=512)
    source_material_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")
    occurred_at: datetime | None = None


def _authoritative_order(order_no: str, user_id: int | None = None) -> dict[str, Any]:
    source = load_authoritative_payment_orders(3650)
    if source.get("source_available") is not True or source.get("source_authoritative") is not True:
        raise HTTPException(503, "权威支付数据源不可用")
    wanted = order_no.strip()
    order = next(
        (
            dict(row)
            for row in source.get("orders") or []
            if isinstance(row, dict)
            and str(row.get("out_trade_no") or row.get("order_no") or "").strip() == wanted
        ),
        None,
    )
    eligible, reason = classify_payment_order(order or {})
    if order is None or not eligible:
        raise HTTPException(409, f"订单不是有效生产付款凭证: {reason}")
    if user_id is not None:
        try:
            owner_id = int(order.get("user_id") or 0)
        except (TypeError, ValueError):
            owner_id = 0
        if owner_id != int(user_id):
            raise HTTPException(403, "不能为其他客户的订单提交凭证")
    return order


def _customer_ref(order: dict[str, Any]) -> str:
    try:
        user_id = int(order.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        raise HTTPException(409, "付款凭证缺少客户账号归属")
    return f"paid-user:{user_id}"


def _trusted_occurred_at(value: datetime | None) -> datetime:
    received_at = datetime.now(UTC)
    if value is None:
        return received_at
    if value.tzinfo is None:
        raise HTTPException(422, "凭证时间必须包含时区")
    normalized = value.astimezone(UTC)
    if abs(received_at - normalized) > timedelta(minutes=15):
        raise HTTPException(422, "凭证时间与服务端相差超过 15 分钟")
    return normalized


@router.post("/kpi-agreements")
def record_kpi_agreement(
    body: KpiAgreementReceiptBody,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.is_admin or not user.is_enterprise:
        raise HTTPException(403, "仅真实企业客户账号可确认业务 KPI")
    order = _authoritative_order(body.order_no, int(user.id))
    try:
        result = append_customer_value_receipt(
            {
                "receipt_kind": "goal",
                "verification_status": "verified",
                "lifecycle_v2": True,
                "source_event_id": f"customer-goal:{int(user.id)}:{body.idempotency_key}",
                "customer_ref": _customer_ref(order),
                "customer_goal_id": body.customer_goal_id,
                "order_no": body.order_no,
                "occurred_at": _trusted_occurred_at(body.occurred_at),
                "environment": "production",
                "evidence": {
                    "baseline": body.baseline,
                    "target": body.target,
                    "comparison": body.comparison,
                    "unit": body.unit,
                    "measurement_window": body.measurement_window,
                    "agreement_sha256": body.agreement_sha256.lower(),
                    "customer_confirmed": True,
                    "actor_role": "customer",
                },
            },
            payment_order=order,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, **result}


@router.post("/usage-receipts")
def record_usage_receipt(
    body: UsageReceiptBody,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.is_admin or not user.is_enterprise:
        raise HTTPException(403, "仅真实企业客户账号可提交使用凭证")
    order = _authoritative_order(body.order_no, int(user.id))
    occurred_at = _trusted_occurred_at(body.occurred_at)
    from modstore_server.workflow_customer_delivery_api import validate_workflow_receipt

    validate_workflow_receipt(
        order=order,
        goal_id=body.customer_goal_id,
        artifact_id=body.output_id,
        artifact_sha256=body.output_sha256,
        occurred_at=occurred_at,
    )
    try:
        result = append_customer_value_receipt(
            {
                "receipt_kind": body.receipt_kind,
                "verification_status": "verified",
                "source_event_id": f"customer:{int(user.id)}:{body.idempotency_key}",
                "customer_ref": _customer_ref(order),
                "customer_goal_id": body.customer_goal_id,
                "order_no": body.order_no,
                "artifact_id": body.output_id,
                "occurred_at": occurred_at,
                "environment": "production",
                "evidence": {
                    "artifact_sha256": body.output_sha256.lower(),
                    "run_id": body.run_id,
                    "task_type": body.task_type,
                    "success": True,
                    "business_output": True,
                    "actor_role": "customer",
                },
            },
            payment_order=order,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, **result}


@router.post("/acceptance-receipts")
def record_acceptance_receipt(
    body: AcceptanceReceiptBody,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.is_admin or not user.is_enterprise:
        raise HTTPException(403, "管理员或非企业账号不能代替客户验收")
    if not body.customer_confirmed and not body.signed_document_sha256:
        raise HTTPException(422, "需要客户账号确认或客户签署文件摘要")
    order = _authoritative_order(body.order_no, int(user.id))
    occurred_at = _trusted_occurred_at(body.occurred_at)
    from modstore_server.workflow_customer_delivery_api import validate_workflow_receipt

    validate_workflow_receipt(
        order=order,
        goal_id=body.customer_goal_id,
        artifact_id=body.accepted_artifact_id,
        artifact_sha256=body.artifact_sha256,
        occurred_at=occurred_at,
    )
    try:
        result = append_customer_value_receipt(
            {
                "receipt_kind": "acceptance",
                "verification_status": "verified",
                "lifecycle_v2": True,
                "source_event_id": f"customer:{int(user.id)}:{body.idempotency_key}",
                "customer_ref": _customer_ref(order),
                "customer_goal_id": body.customer_goal_id,
                "order_no": body.order_no,
                "artifact_id": body.accepted_artifact_id,
                "acceptance_id": body.acceptance_id,
                "occurred_at": occurred_at,
                "environment": "production",
                "evidence": {
                    "artifact_sha256": body.artifact_sha256.lower(),
                    "customer_confirmed": body.customer_confirmed,
                    "signed_document_sha256": body.signed_document_sha256.lower(),
                    "actor_role": "customer",
                },
            },
            payment_order=order,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, **result}


@admin_router.post("/outcome-materials")
def record_outcome_material(
    body: OutcomeReceiptBody,
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    _ = _admin
    order = _authoritative_order(body.order_no)
    occurred_at = _trusted_occurred_at(body.occurred_at)
    from modstore_server.workflow_customer_delivery_api import validate_workflow_receipt

    validate_workflow_receipt(
        order=order,
        goal_id=body.customer_goal_id,
        artifact_id=body.outcome_id,
        artifact_sha256=body.artifact_sha256,
        occurred_at=occurred_at,
        outcome=body.model_dump(),
    )
    try:
        result = append_customer_value_receipt(
            {
                "receipt_kind": "outcome",
                "verification_status": "verified",
                "source_event_id": f"admin-outcome:{body.idempotency_key}",
                "customer_ref": _customer_ref(order),
                "customer_goal_id": body.customer_goal_id,
                "order_no": body.order_no,
                "artifact_id": body.outcome_id,
                "occurred_at": occurred_at,
                "environment": "production",
                "evidence": {
                    "artifact_sha256": body.artifact_sha256.lower(),
                    "baseline": body.baseline,
                    "target": body.target,
                    "measured_value": body.measured_value,
                    "comparison": body.comparison,
                    "unit": body.unit,
                    "measurement_window": body.measurement_window,
                    "source_material_summary": body.source_material_summary,
                    "source_material_sha256": body.source_material_sha256.lower(),
                    "actor_role": "admin_measurement",
                },
            },
            payment_order=order,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, **result}


__all__ = ["admin_router", "open_router", "router"]
