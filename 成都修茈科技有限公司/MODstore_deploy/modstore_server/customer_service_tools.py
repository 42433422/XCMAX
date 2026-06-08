"""受控 AI 客服动作工具层。

这里不让模型直接碰业务表；编排器只产生标准化 action，再由本模块做权限、
幂等、审计和结果落库。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server import payment_orders, webhook_dispatcher
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS
from modstore_server.llm_model_gates import upsert_l3_proposal
from modstore_server.models import CatalogComplaint, CatalogItem, RefundRequest, User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceIntegration,
)
from modstore_server.openapi_connector_runtime import call_generated_operation
from modstore_server.workflow_engine import workflow_engine


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_loads(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return default


def audit(
    db: Session,
    *,
    event_type: str,
    detail: Dict[str, Any],
    actor: Optional[User] = None,
    ticket_id: Optional[int] = None,
    session_id: Optional[int] = None,
    actor_type: str = "ai",
) -> CustomerServiceAuditLog:
    row = CustomerServiceAuditLog(
        ticket_id=ticket_id,
        session_id=session_id,
        actor_user_id=getattr(actor, "id", None),
        actor_type=actor_type,
        event_type=event_type,
        detail_json=json_dumps(detail),
    )
    db.add(row)
    return row


def enqueue_customer_service_event(
    db: Session,
    event_type: str,
    aggregate_id: str,
    payload: Dict[str, Any],
) -> None:
    try:
        webhook_dispatcher.enqueue_event(
            db,
            event_type,
            aggregate_id,
            payload,
            source="modstore-customer-service",
        )
    except Exception:
        # 事件系统不能阻断客服主交易，审计表仍保留事实。
        audit(
            db,
            event_type="event_enqueue_failed",
            detail={"event_type": event_type, "aggregate_id": aggregate_id},
            actor_type="system",
        )


def build_action(
    db: Session,
    *,
    ticket_id: int,
    user_id: int,
    action_type: str,
    target_type: str = "",
    target_id: str = "",
    request: Optional[Dict[str, Any]] = None,
    decision_id: Optional[int] = None,
) -> CustomerServiceAction:
    key = f"{ticket_id}:{action_type}:{target_type}:{target_id}"
    existing = (
        db.query(CustomerServiceAction).filter(CustomerServiceAction.idempotency_key == key).first()
    )
    if existing:
        return existing
    row = CustomerServiceAction(
        ticket_id=ticket_id,
        decision_id=decision_id,
        user_id=user_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        request_json=json_dumps(request or {}),
        idempotency_key=key,
    )
    db.add(row)
    db.flush()
    return row


def execute_action(db: Session, action: CustomerServiceAction, user: User) -> CustomerServiceAction:
    if action.status in {"completed", "skipped"}:
        return action
    action.status = "running"
    action.updated_at = datetime.now(timezone.utc)
    request = json_loads(action.request_json, {})
    try:
        if action.action_type == "refund.apply":
            result = _apply_refund(db, action, user, request)
        elif action.action_type == "catalog.complaint.create":
            result = _create_catalog_complaint(db, action, user, request)
        elif action.action_type == "catalog.compliance.review":
            result = _mark_catalog_for_review(db, action, request)
        elif action.action_type == "workflow.execute":
            result = _execute_workflow(action, user, request)
        elif action.action_type == "openapi.operation":
            result = _execute_openapi_operation(action, user, request)
        elif action.action_type == "llm.model_capability.propose":
            result = _llm_model_capability_propose(db, action, user, request)
        else:
            result = {"ok": True, "message": "已记录客服处理建议"}
        action.status = "completed" if result.get("ok") else "failed"
        action.result_json = json_dumps(result)
        action.error = "" if result.get("ok") else str(result.get("message") or "动作执行失败")
    except Exception as exc:  # noqa: BLE001 - 动作失败需写审计，不向外抛破坏会话
        action.status = "failed"
        action.error = str(exc)
        action.result_json = json_dumps({"ok": False, "message": str(exc)})
    action.updated_at = datetime.now(timezone.utc)
    audit(
        db,
        event_type="action_executed",
        ticket_id=action.ticket_id,
        actor=user,
        detail={
            "action_id": action.id,
            "action_type": action.action_type,
            "status": action.status,
            "target_type": action.target_type,
            "target_id": action.target_id,
        },
    )
    return action


def execute_matching_integrations(
    db: Session,
    *,
    ticket_id: int,
    decision_id: int,
    user: User,
    scenario: str,
    payload: Dict[str, Any],
) -> list[CustomerServiceAction]:
    rows = (
        db.query(CustomerServiceIntegration)
        .filter(CustomerServiceIntegration.enabled == True)
        .filter(CustomerServiceIntegration.scenario.in_([scenario, "general"]))
        .order_by(CustomerServiceIntegration.id.asc())
        .all()
    )
    actions: list[CustomerServiceAction] = []
    for integration in rows:
        config = json_loads(integration.config_json, {})
        if config.get("auto_invoke") is False:
            continue
        if integration.integration_type == "workflow" and integration.workflow_id:
            action = build_action(
                db,
                ticket_id=ticket_id,
                decision_id=decision_id,
                user_id=user.id,
                action_type="workflow.execute",
                target_type="workflow",
                target_id=str(integration.workflow_id),
                request={"input_data": payload, "integration_id": integration.id},
            )
        elif integration.integration_type == "openapi" and integration.connector_id:
            operation_id = str(config.get("operation_id") or "").strip()
            if not operation_id:
                continue
            action = build_action(
                db,
                ticket_id=ticket_id,
                decision_id=decision_id,
                user_id=user.id,
                action_type="openapi.operation",
                target_type="openapi",
                target_id=f"{integration.connector_id}:{operation_id}",
                request={
                    "connector_id": integration.connector_id,
                    "operation_id": operation_id,
                    "params": config.get("params") or {},
                    "body": {**(config.get("body") or {}), "customer_service": payload},
                    "integration_id": integration.id,
                },
            )
        else:
            continue
        db.flush()
        execute_action(db, action, user)
        actions.append(action)
    return actions


def _apply_refund(
    db: Session,
    action: CustomerServiceAction,
    user: User,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    order_no = str(request.get("order_no") or action.target_id or "").strip()
    reason = str(request.get("reason") or "AI 客服自动受理退款").strip()
    if not order_no:
        return {"ok": False, "message": "缺少订单号"}
    order = payment_orders.find(order_no)
    if not order or int(order.get("user_id") or 0) != int(user.id):
        return {"ok": False, "message": "订单不存在或不属于当前用户"}
    if str(order.get("status") or "").lower() != "paid":
        return {"ok": False, "message": "只有已支付订单可申请退款"}
    existing = db.query(RefundRequest).filter(RefundRequest.order_no == order_no).first()
    if existing:
        return {
            "ok": True,
            "refund_id": existing.id,
            "status": existing.status,
            "message": "退款申请已存在",
        }
    amount = float(order.get("total_amount") or 0)
    row = RefundRequest(
        user_id=user.id,
        order_no=order_no,
        amount=amount,
        reason=reason[:1000],
        status="pending",
    )
    db.add(row)
    db.flush()
    return {"ok": True, "refund_id": row.id, "status": row.status, "amount": amount}


def _create_catalog_complaint(
    db: Session,
    action: CustomerServiceAction,
    user: User,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    catalog_id = int(request.get("catalog_id") or action.target_id or 0)
    if catalog_id <= 0:
        return {"ok": False, "message": "缺少商品 ID"}
    item = db.query(CatalogItem).filter(CatalogItem.id == catalog_id).first()
    if not item:
        return {"ok": False, "message": "商品不存在"}
    row = CatalogComplaint(
        catalog_id=catalog_id,
        user_id=user.id,
        complaint_type=str(request.get("complaint_type") or "other")[:32],
        reason=str(request.get("reason") or "AI 客服自动受理投诉")[:2000],
        evidence_json=json_dumps(request.get("evidence") or {}),
        status="pending",
    )
    db.add(row)
    db.flush()
    return {"ok": True, "complaint_id": row.id, "status": row.status}


def _mark_catalog_for_review(
    db: Session,
    action: CustomerServiceAction,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    catalog_id = int(request.get("catalog_id") or action.target_id or 0)
    if catalog_id <= 0:
        return {"ok": False, "message": "缺少商品 ID"}
    item = db.query(CatalogItem).filter(CatalogItem.id == catalog_id).first()
    if not item:
        return {"ok": False, "message": "商品不存在"}
    item.compliance_status = str(request.get("compliance_status") or "reviewing")[:32]
    item.delist_reason = str(request.get("reason") or item.delist_reason or "")[:2000]
    return {"ok": True, "catalog_id": item.id, "compliance_status": item.compliance_status}


def _execute_workflow(
    action: CustomerServiceAction, user: User, request: Dict[str, Any]
) -> Dict[str, Any]:
    workflow_id = int(action.target_id or request.get("workflow_id") or 0)
    if workflow_id <= 0:
        return {"ok": False, "message": "缺少工作流 ID"}
    output = workflow_engine.execute_workflow(
        workflow_id,
        input_data=request.get("input_data") or {},
        user_id=user.id,
    )
    return {"ok": True, "workflow_id": workflow_id, "output": output}


def _llm_model_capability_propose(
    db: Session,
    action: CustomerServiceAction,
    user: User,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    provider = str(request.get("provider") or "").strip().lower()
    model = str(request.get("model") or "").strip()
    if provider not in KNOWN_PROVIDERS:
        return {"ok": False, "message": "厂商 id 不在支持列表中"}
    if not model:
        return {"ok": False, "message": "缺少 model"}
    row = upsert_l3_proposal(
        db,
        user_id=user.id,
        provider=provider,
        model=model,
        ticket_id=action.ticket_id,
        notes=str(request.get("reason") or request.get("notes") or "")[:2000],
    )
    return {
        "ok": True,
        "capability_id": row.id,
        "message": "已提交模型扩展申请（L3），管理员审核完成前平台代付仍受定价策略限制。",
    }


def _execute_openapi_operation(
    action: CustomerServiceAction, user: User, request: Dict[str, Any]
) -> Dict[str, Any]:
    connector_id = int(request.get("connector_id") or 0)
    operation_id = str(request.get("operation_id") or "").strip()
    if connector_id <= 0 or not operation_id:
        return {"ok": False, "message": "缺少 OpenAPI 连接器或 operation_id"}
    result = call_generated_operation(
        connector_id=connector_id,
        user_id=user.id,
        operation_id=operation_id,
        params=request.get("params") or {},
        body=request.get("body"),
        source="customer_service",
    )
    return {"ok": bool(result.get("ok")), "openapi": result}
