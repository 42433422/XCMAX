from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.application.workflow.types import ApprovalRequest
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _resolve_applicant(db, runtime_context: dict[str, Any] | None):
    from app.db.models.user import User

    context = runtime_context or {}
    raw = next(
        (
            context.get(key)
            for key in ("local_user_id", "actor_id", "user_id")
            if context.get(key) not in (None, "")
        ),
        None,
    )
    if raw is None:
        return None
    text_value = str(raw).strip()
    if text_value.isdigit():
        return db.query(User).filter(User.id == int(text_value), User.is_active == True).first()  # noqa: E712

    user = (
        db.query(User)
        .filter(User.username == text_value, User.is_active == True)  # noqa: E712
        .first()
    )
    if user is not None:
        return user
    matches = (
        db.query(User)
        .filter(
            (User.email == text_value) | (User.display_name == text_value),
            User.is_active == True,  # noqa: E712
        )
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def persist_workflow_approval(
    request: ApprovalRequest,
    runtime_context: dict[str, Any] | None,
    *,
    flow_key: str,
) -> dict[str, Any] | None:
    """Persist an interactive AI approval with complete foreign keys and audit linkage."""
    try:
        from app.db.models.approval import (
            ApprovalFlow,
            ApprovalFlowNode,
        )
        from app.db.models.approval import (
            ApprovalRequest as ApprovalRequestModel,
        )
        from app.db.session import get_db

        with get_db() as db:
            existing = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request.request_id)
                .first()
            )
            if existing is not None:
                metadata = {
                    "id": int(existing.id),
                    "request_no": str(existing.request_no),
                    "approval_path": (
                        "/mod/xcagi-approval-bridge/approval-hub/workspace"
                        f"?request_no={existing.request_no}"
                    ),
                }
            else:
                applicant = _resolve_applicant(db, runtime_context)
                if applicant is None:
                    raise RuntimeError("无法从当前登录会话解析审批申请人")
                flow = db.query(ApprovalFlow).filter(ApprovalFlow.flow_key == flow_key).first()
                if flow is None:
                    flow = ApprovalFlow(
                        flow_key=flow_key,
                        flow_name="AI 工作流逐笔审批",
                        description="桌面智能对话数据库写操作的逐笔人工审批",
                        business_type="workflow_tool",
                        node_type="serial",
                        allow_transfer=False,
                        allow_delegate=False,
                        allow_withdraw=True,
                        timeout_hours=48,
                        is_active=True,
                        is_deleted=False,
                        created_by=int(applicant.id),
                    )
                    db.add(flow)
                    db.flush()
                audit_node = (
                    db.query(ApprovalFlowNode)
                    .filter(
                        ApprovalFlowNode.flow_id == flow.id,
                        ApprovalFlowNode.node_name == "AI 工作流审批留痕",
                    )
                    .first()
                )
                if audit_node is None:
                    audit_node = ApprovalFlowNode(
                        flow_id=int(flow.id),
                        node_name="AI 工作流审批留痕",
                        node_order=1,
                        node_type="serial",
                        approver_type="applicant",
                        approver_ids=None,
                        min_approvals=1,
                        is_active=True,
                    )
                    db.add(audit_node)
                    db.flush()

                business_data = {
                    "plan_id": request.plan_id,
                    "node_id": request.node_id,
                    "tool_id": request.tool_id,
                    "action": request.action,
                    "params": request.params or {},
                }
                persisted = ApprovalRequestModel(
                    request_no=request.request_id,
                    flow_id=int(flow.id),
                    business_type="workflow_tool",
                    business_data=json.dumps(business_data, ensure_ascii=False, default=str),
                    applicant_id=int(applicant.id),
                    applicant_name=str(
                        applicant.display_name or applicant.username or applicant.id
                    ),
                    title=f"智能对话写操作：{request.tool_id}.{request.action}",
                    description=json.dumps(request.params or {}, ensure_ascii=False, default=str)[
                        :500
                    ],
                    current_node_id=None,
                    current_node_order=0,
                    status="pending",
                    priority="normal",
                    submitted_at=request.created_at or datetime.now(),
                    created_at=request.created_at or datetime.now(),
                )
                db.add(persisted)
                db.flush()
                try:
                    db.execute(
                        text(
                            "INSERT INTO ai_action_audit (actor, action, payload) "
                            "VALUES (:actor, :action, :payload)"
                        ),
                        {
                            "actor": str(applicant.id),
                            "action": "approval.submit_ai_workflow",
                            "payload": json.dumps(
                                {
                                    "approval_request_id": persisted.id,
                                    "request_no": persisted.request_no,
                                    "plan_id": request.plan_id,
                                    "node_id": request.node_id,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                except (*RECOVERABLE_ERRORS, SQLAlchemyError):
                    logger.warning("AI 审批提交审计写入失败", exc_info=True)
                metadata = {
                    "id": int(persisted.id),
                    "request_no": str(persisted.request_no),
                    "flow_id": int(flow.id),
                    "audit_node_id": int(audit_node.id),
                    "applicant_id": int(applicant.id),
                    "approval_path": (
                        "/mod/xcagi-approval-bridge/approval-hub/workspace"
                        f"?request_no={persisted.request_no}"
                    ),
                }

        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_approval_changed

            neuro_notify_approval_changed(
                "created",
                approval_id=request.request_id,
                flow_id=str(metadata.get("flow_id") or ""),
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_approval_changed skipped", exc_info=True)
        return metadata
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        logger.warning("AI 审批持久化到 DB 失败: %s", exc, exc_info=True)
        return None


def persist_agent_run_link(
    request_id: str,
    *,
    agent_run_id: str,
    approved_step_id: str,
) -> None:
    try:
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel
        from app.db.session import get_db

        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return
            business_data = json.loads(persisted.business_data) if persisted.business_data else {}
            business_data["agent_run_id"] = str(agent_run_id or "").strip()
            business_data["approved_step_id"] = str(approved_step_id or "").strip()
            persisted.business_data = json.dumps(business_data, ensure_ascii=False, default=str)
            db.commit()
    except (*RECOVERABLE_ERRORS, SQLAlchemyError):
        logger.warning("AI 审批关联 Agent Run 持久化失败", exc_info=True)
