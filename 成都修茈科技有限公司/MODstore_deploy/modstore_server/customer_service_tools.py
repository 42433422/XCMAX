# mypy: disable-error-code="arg-type, assignment"
"""受控 AI 客服动作工具层。

这里不让模型直接碰业务表；编排器只产生标准化 action，再由本模块做权限、
幂等、审计和结果落库。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import text
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
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
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
    except RECOVERABLE_ERRORS:
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


_FORBIDDEN_ACTION_TYPES = frozenset(
    {
        "admin.grant",
        "admin.promote",
        "role.grant_admin",
        "user.set_admin",
        "privilege.escalate",
    }
)


def _approval_already_settled(action: CustomerServiceAction) -> bool:
    """拒绝和已经消耗过的审批不能靠改回 pending 再执行一次。"""
    request = json_loads(action.request_json, {})
    approval = request.get("approval") if isinstance(request, dict) else None
    decided = str(approval.get("decision") or "") if isinstance(approval, dict) else ""
    prior = json_loads(action.result_json, {})
    consumed = str(request.get("consumed_approval_id") or "") if isinstance(request, dict) else ""
    rejected = (
        action.status == "rejected"
        or str(action.error or "") == "approval_rejected"
        or (action.status == "failed" and str(action.error or "").startswith("approval_rejected"))
    )
    already = rejected or action.status in {"completed", "skipped", "pending_execution"}
    already = (
        already or bool(consumed) or (isinstance(prior, dict) and bool(prior.get("approval_id")))
    )
    if not already:
        return False
    if rejected or decided == "rejected":
        action.status = "rejected"
        action.error = "approval_rejected"
        return True
    if action.status in {"completed", "skipped", "pending_execution"}:
        return True
    executed = isinstance(prior, dict) and prior.get("executed") is True
    action.status = "completed" if executed else "pending_execution"
    return True


def execute_action(db: Session, action: CustomerServiceAction, user: User) -> CustomerServiceAction:
    if _approval_already_settled(action):
        return action
    action_type = str(action.action_type or "").strip().lower()
    # 硬闸：任何提权/管理员动作一律拒绝执行（即使误建 action）
    if (
        action_type in _FORBIDDEN_ACTION_TYPES
        or "grant_admin" in action_type
        or action_type.endswith(".set_admin")
        or "privilege.escalate" in action_type
    ):
        action.status = "failed"
        action.error = "forbidden: customer service cannot grant admin or escalate privileges"
        action.result_json = json_dumps(
            {"ok": False, "message": "拒绝执行：客服通道禁止提权/开通管理员"}
        )
        action.updated_at = datetime.now(UTC)
        audit(
            db,
            event_type="action_forbidden",
            ticket_id=action.ticket_id,
            actor=user,
            detail={
                "action_type": action.action_type,
                "reason": "privilege_escalation",
            },
        )
        return action
    request = json_loads(action.request_json, {})
    if action_type == "ticket.apply_change":
        return _execute_gated_change(db, action, user, request)
    action.status = "running"
    action.updated_at = datetime.now(UTC)
    try:
        if action.action_type == "ticket.diagnose":
            result = _diagnose_ticket(db, action, request)
        elif action.action_type == "ticket.read":
            result = _read_ticket(db, action, request)
        elif action.action_type == "ticket.observe_status":
            result = _observe_status(db, action, request)
        elif action.action_type == "ticket.verify":
            result = _verify_ticket(db, action, request)
        elif action.action_type == "ticket.assign":
            result = _assign_employee(db, action, request)
        elif action.action_type == "account.lookup":
            result = _lookup_account(db, action, request)
        elif action.action_type == "tool.registry":
            result = _read_tool_registry(db, action, request)
        elif action.action_type == "ticket.report_diagnosis":
            result = _report_diagnosis(db, action, request)
        elif action.action_type == "refund.apply":
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
            result = {
                "ok": False,
                "executed": False,
                "message": f"未注册工具，拒绝执行：{action.action_type}",
                "code": "tool_unregistered",
            }
        action.status = "completed" if result.get("ok") else "failed"
        action.result_json = json_dumps(result)
        action.error = "" if result.get("ok") else str(result.get("message") or "动作执行失败")
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - 动作失败需写审计，不向外抛破坏会话
        action.status = "failed"
        action.error = str(exc)
        action.result_json = json_dumps({"ok": False, "message": str(exc)})
    action.updated_at = datetime.now(UTC)
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


def _reject_tool(message: str, code: str) -> dict[str, Any]:
    return {"ok": False, "executed": False, "message": message, "code": code}


def _diagnose_ticket(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    """读取工单原记录。成功结果来自数据库行，不用固定成功文案代替。"""
    from modstore_server.models_cs import CustomerServiceTicket

    if request.get("granted") is False:
        return _reject_tool("员工无权调用该工具", "tool_forbidden")
    path = str(request.get("file_path") or "")
    if path and (".." in path or path.startswith(("/", "\\")) or ":\\" in path):
        return _reject_tool("非法路径，拒绝执行", "illegal_path")
    try:
        ticket_id = int(request.get("ticket_id"))
    except (TypeError, ValueError):
        return _reject_tool("工单编号缺失或类型错误", "invalid_ticket_id")
    if ticket_id <= 0 or ticket_id != int(action.ticket_id or 0):
        return _reject_tool("工单编号与当前任务不一致", "ticket_mismatch")
    row = db.get(CustomerServiceTicket, ticket_id)
    if row is None:
        return _reject_tool("工单不存在或不属于当前用户", "ticket_missing")
    owner = request.get("user_id")
    if owner not in (None, "") and int(owner) != int(row.user_id or 0):
        return _reject_tool("用户与工单不一致", "user_mismatch")
    return {
        "ok": True,
        "executed": True,
        "tool": "ticket.diagnose",
        "ticket_id": int(row.id),
        "ticket_no": row.ticket_no,
        "intent": row.intent,
        "title": row.title,
        "summary": (row.summary or "")[:500],
        "status": row.status,
        "user_id": int(row.user_id or 0),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _employee_denied(request: dict[str, Any], tool: str) -> dict[str, Any] | None:
    if request.get("granted") is False:
        return _reject_tool("员工无权调用该工具", "tool_forbidden")
    from modstore_server.customer_ticket_loop import employee_can

    if not employee_can(str(request.get("employee_id") or ""), tool):
        return _reject_tool("员工不具备该工具能力", "tool_forbidden")
    return None


def _owned_ticket(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> tuple[Any, dict[str, Any] | None]:
    from modstore_server.models_cs import CustomerServiceTicket

    path = str(request.get("file_path") or "")
    if path and (".." in path or path.startswith(("/", "\\")) or ":\\" in path):
        return None, _reject_tool("非法路径，拒绝执行", "illegal_path")
    try:
        ticket_id = int(request.get("ticket_id"))
    except (TypeError, ValueError):
        return None, _reject_tool("工单编号缺失或类型错误", "invalid_ticket_id")
    if ticket_id <= 0 or ticket_id != int(action.ticket_id or 0):
        return None, _reject_tool("工单编号与当前任务不一致", "ticket_mismatch")
    row = db.get(CustomerServiceTicket, ticket_id)
    if row is None:
        return None, _reject_tool("工单不存在或不属于当前用户", "ticket_missing")
    owner = request.get("user_id")
    if owner not in (None, "") and int(owner) != int(row.user_id or 0):
        return None, _reject_tool("用户与工单不一致", "user_mismatch")
    return row, None


def _read_ticket(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    denied = _employee_denied(request, "ticket.read")
    if denied:
        return denied
    row, error = _owned_ticket(db, action, request)
    if error:
        return error
    return {
        "ok": True,
        "executed": True,
        "tool": "ticket.read",
        "ticket_id": int(row.id),
        "ticket_no": row.ticket_no,
        "intent": row.intent,
        "status": row.status,
        "user_id": int(row.user_id or 0),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _observe_status(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    denied = _employee_denied(request, "ticket.observe_status")
    if denied:
        return denied
    if not str(request.get("ticket_no") or "").strip():
        return _reject_tool("缺少前序读取的工单号", "missing_dependency")
    row, error = _owned_ticket(db, action, request)
    if error:
        return error
    if str(row.ticket_no or "") != str(request.get("ticket_no")):
        return _reject_tool("前序工单号与数据库记录不一致", "ticket_mismatch")
    return {
        "ok": True,
        "executed": True,
        "tool": "ticket.observe_status",
        "ticket_id": int(row.id),
        "ticket_no": row.ticket_no,
        "status": row.status,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _verify_ticket(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    """第二次读取原单。只有编号、分类和用户都对得上，才算核验通过。"""
    denied = _employee_denied(request, "ticket.verify")
    if denied:
        return denied
    row, error = _owned_ticket(db, action, request)
    if error:
        return error
    matched = (
        str(row.ticket_no or "") == str(request.get("ticket_no") or "")
        and str(row.intent or "") == str(request.get("intent") or "")
        and int(row.user_id or 0) == int(request.get("user_id") or 0)
        and request.get("fail_verify") is not True
    )
    return {
        "ok": matched,
        "executed": True,
        "matched": matched,
        "tool": "ticket.verify",
        "ticket_id": int(row.id),
        "ticket_no": row.ticket_no,
        "intent": row.intent,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _assign_employee(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    from modstore_server.customer_ticket_loop import employee_lane

    denied = _employee_denied(request, "ticket.assign")
    if denied:
        return denied
    _row, error = _owned_ticket(db, action, request)
    if error:
        return error
    employee_id = str(request.get("employee_id") or "")
    if request.get("online") is False:
        return _reject_tool("负责员工不在线，任务保留待重派", "employee_offline")
    if not employee_lane(employee_id, str(request.get("lane") or "")):
        return _reject_tool("员工职责与工单不符", "employee_unqualified")
    return {
        "ok": True,
        "executed": True,
        "tool": "ticket.assign",
        "employee_id": employee_id,
        "lane": request.get("lane"),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _lookup_account(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    denied = _employee_denied(request, "account.lookup")
    if denied:
        return denied
    row, error = _owned_ticket(db, action, request)
    if error:
        return error
    account = db.get(User, int(row.user_id or 0))
    if account is None:
        return _reject_tool("账户记录不存在", "account_missing")
    return {
        "ok": True,
        "executed": True,
        "mutated": False,
        "tool": "account.lookup",
        "ticket_no": row.ticket_no,
        "user_id": int(account.id),
        "username": account.username,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _read_tool_registry(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    from modstore_server.customer_ticket_loop import TOOLS

    denied = _employee_denied(request, "tool.registry")
    if denied:
        return denied
    _row, error = _owned_ticket(db, action, request)
    if error:
        return error
    employee_id = str(request.get("employee_id") or "")
    published = sorted(TOOLS.get(employee_id, ()))
    return {
        "ok": True,
        "executed": True,
        "tool": "tool.registry",
        "employee_id": employee_id,
        "tools": published,
        "registered": "tool.registry" in published,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _report_diagnosis(
    db: Session, action: CustomerServiceAction, request: dict[str, Any]
) -> dict[str, Any]:
    """用前序诊断读到的工单号再核对一次原单，参数对不上就拒绝。"""
    from modstore_server.models_cs import CustomerServiceTicket

    if request.get("granted") is False:
        return _reject_tool("员工无权调用该工具", "tool_forbidden")
    ticket_no = str(request.get("ticket_no") or "").strip()
    try:
        ticket_id = int(request.get("ticket_id"))
    except (TypeError, ValueError):
        return _reject_tool("缺少前序诊断给出的工单编号", "invalid_ticket_id")
    if not ticket_no or ticket_id != int(action.ticket_id or 0):
        return _reject_tool("诊断参数不完整或工单不一致", "invalid_parameter")
    row = db.get(CustomerServiceTicket, ticket_id)
    if row is None or str(row.ticket_no or "") != ticket_no:
        return _reject_tool("前序工单号与数据库记录不一致", "ticket_mismatch")
    return {
        "ok": True,
        "executed": True,
        "tool": "ticket.report_diagnosis",
        "ticket_id": int(row.id),
        "ticket_no": row.ticket_no,
        "intent": row.intent,
        "diagnosis": (f"已核对工单 {row.ticket_no}，分类 {row.intent}，当前状态 {row.status}"),
        "observed_at": datetime.now(UTC).isoformat(),
    }


# 真正改业务数据的执行器。没有登记时，审批通过只表示允许执行，不表示已经执行。
_GATED_EXECUTORS: dict[str, Any] = {}


def register_gated_change_executor(name: str, executor: Any) -> None:
    _GATED_EXECUTORS[str(name)] = executor


def _gated_execution(request: dict[str, Any]) -> dict[str, Any] | None:
    change = request.get("change")
    key = change if isinstance(change, str) else ""
    executor = _GATED_EXECUTORS.get(key)
    if executor is None:
        return None
    outcome = executor(request)
    return outcome if isinstance(outcome, dict) else None


def begin_immediate_write(db: Session) -> None:
    """SQLite 的延迟事务会让两个读锁互相卡住。写入前先拿保留锁。"""
    if db.in_transaction():
        return
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def claim_gated_decision(
    db: Session, action: CustomerServiceAction, user: User, request: dict[str, Any]
) -> CustomerServiceAction:
    """把等待中的审批一次写成终态。拒绝不能再变回 pending。"""
    if str(action.status or "") != "waiting_approval":
        raise HTTPException(409, "只有等待审批的操作可以批准或拒绝")
    return _settle_gated_change(db, action, user, request, claim=True)


def _settle_gated_change(
    db: Session,
    action: CustomerServiceAction,
    user: User,
    request: dict[str, Any],
    *,
    claim: bool,
) -> CustomerServiceAction:
    begin_immediate_write(db)
    approval = request.get("approval") if isinstance(request.get("approval"), dict) else {}
    decision = str(approval.get("decision") or "")
    now = datetime.now(UTC)
    if "ticket_status" not in request:
        from modstore_server.models_cs import CustomerServiceTicket

        ticket = db.get(CustomerServiceTicket, action.ticket_id)
        request["ticket_status"] = str(ticket.status or "") if ticket is not None else ""
        request["ticket_lock_version"] = int(getattr(ticket, "lock_version", 0) or 0)
    if str(action.status or "") == "rejected" or str(action.error or "") == "approval_rejected":
        db.rollback()
        raise HTTPException(409, "审批已拒绝，不能再次决定")
    consumed = str(request.get("consumed_approval_id") or "")
    if consumed and (claim or decision):
        db.rollback()
        raise HTTPException(409, "这张审批已经处理过，不能再次决定")
    approval_id = str(approval.get("id") or "").strip()
    run_executor = False
    if decision == "rejected":
        request["consumed_approval_id"] = approval_id or "rejected"
        new_status = "rejected"
        error = "approval_rejected"
        result = {
            "ok": False,
            "executed": False,
            "approval_granted": False,
            "business_executed": False,
            "verified": False,
            "message": "审批已拒绝，敏感操作未执行",
        }
    elif decision != "approved" or not approval_id:
        new_status = "waiting_approval"
        error = ""
        result = {
            "ok": False,
            "executed": False,
            "approval_granted": False,
            "business_executed": False,
            "verified": False,
            "message": "等待人工审批",
            "state": "waiting_approval",
        }
    else:
        # 先占住这张审批，赢下版本锁之后才调用业务执行器。
        request["consumed_approval_id"] = approval_id
        new_status = "pending_execution"
        error = ""
        result = {
            "ok": False,
            "executed": False,
            "approval_granted": True,
            "business_executed": False,
            "verified": False,
            "message": "审批已通过，业务执行器未完成核验，操作未执行",
            "tool": "ticket.apply_change",
            "approval_id": approval_id,
            "change": request.get("change"),
            "observed_at": now.isoformat(),
        }
        run_executor = True
    expected_version = int(getattr(action, "lock_version", 0) or 0)
    expected_status = str(action.status or "pending")
    if claim and expected_status not in {"waiting_approval", "pending"}:
        db.rollback()
        raise HTTPException(409, "只有等待审批的操作可以批准或拒绝")
    values = {
        "status": new_status,
        "error": error,
        "request_json": json_dumps(request),
        "result_json": json_dumps(result),
        "updated_at": now,
        "lock_version": expected_version + 1,
    }
    changed = (
        db.query(CustomerServiceAction)
        .filter(
            CustomerServiceAction.id == action.id,
            CustomerServiceAction.status == expected_status,
            CustomerServiceAction.lock_version == expected_version,
        )
        .update(values, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "这张审批已经处理过，不能再次决定")
    db.refresh(action)
    if run_executor:
        outcome = _gated_execution(request)
        verified = bool(outcome and outcome.get("ok") is True and outcome.get("verified") is True)
        if outcome is not None:
            owned = expected_version + 1
            if verified:
                result = {
                    "ok": True,
                    "executed": True,
                    "approval_granted": True,
                    "business_executed": True,
                    "verified": True,
                    "tool": "ticket.apply_change",
                    "approval_id": approval_id,
                    "change": request.get("change"),
                    "observed_at": now.isoformat(),
                }
                follow_status = "completed"
            else:
                result["business_executed"] = True
                result["verified"] = False
                follow_status = "pending_execution"
            follow = (
                db.query(CustomerServiceAction)
                .filter(
                    CustomerServiceAction.id == action.id,
                    CustomerServiceAction.lock_version == owned,
                )
                .update(
                    {
                        "status": follow_status,
                        "result_json": json_dumps(result),
                        "updated_at": datetime.now(UTC),
                        "lock_version": owned + 1,
                    },
                    synchronize_session=False,
                )
            )
            if follow != 1:
                db.rollback()
                raise HTTPException(409, "这张审批已经处理过，不能再次决定")
            db.refresh(action)
    audit(
        db,
        event_type="action_executed",
        ticket_id=action.ticket_id,
        actor=user,
        detail={
            "action_id": action.id,
            "action_type": action.action_type,
            "status": action.status,
            "approval_decision": decision or "pending",
        },
    )
    return action


def _execute_gated_change(
    db: Session, action: CustomerServiceAction, user: User, request: dict[str, Any]
) -> CustomerServiceAction:
    """写入类动作必须先有一次性审批。没有核验过的业务执行器时不算已执行。"""
    approval = request.get("approval") if isinstance(request.get("approval"), dict) else {}
    decision = str(approval.get("decision") or "")
    return _settle_gated_change(db, action, user, request, claim=bool(decision))


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
        .filter(CustomerServiceIntegration.enabled.is_(True))
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
    return {
        "ok": True,
        "catalog_id": item.id,
        "compliance_status": item.compliance_status,
    }


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
