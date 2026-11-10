"""Database write paths for durable workflow approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.workflow.workflow_types import ApprovalRequest, PlanGraph


def persist_workflow_approval(
    request: ApprovalRequest,
    runtime_context: dict[str, Any] | None,
    *,
    flow_key: str,
    plan: PlanGraph | None = None,
    title: str | None = None,
) -> dict[str, Any] | None:
    """Persist an interactive approval and its resumable workflow snapshot."""
    from app.application.workflow import approval_persistence as facade

    try:
        from app.db.models.approval import ApprovalFlow, ApprovalFlowNode
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel
        from app.db.session import get_db
        from app.infrastructure.tenant_scope import current_tenant_id

        with get_db() as db:
            existing = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request.request_id)
                .first()
            )
            if existing is not None:
                applicant = facade._resolve_applicant(db, runtime_context)
                tenant_id = current_tenant_id()
                if (
                    applicant is None
                    or not tenant_id
                    or existing.tenant_id != tenant_id
                    or existing.applicant_id != applicant.id
                    or existing.status != "pending"
                    or existing.business_type != "workflow_tool"
                    or not facade._is_valid_plan_for_snapshot(plan)
                ):
                    raise RuntimeError("已有审批申请与当前身份或状态不一致")
                try:
                    data = facade.json.loads(existing.business_data or "{}")
                    snapshot = facade.json.loads(
                        facade.json.dumps(
                            facade._build_workflow_snapshot(request, runtime_context, plan),
                            ensure_ascii=False,
                            default=str,
                        )
                    )
                except (TypeError, ValueError):
                    raise RuntimeError("已有审批申请快照无效") from None
                stored_snapshot = data.get(facade.SNAPSHOT_KEY) if isinstance(data, dict) else None
                if isinstance(stored_snapshot, dict):
                    stored_snapshot = dict(stored_snapshot)
                    for key in ("agent_run_id", "approved_step_id", "observed_run_id"):
                        stored_snapshot.pop(key, None)
                        snapshot.pop(key, None)
                if not isinstance(data, dict) or any(
                    (
                        stored_snapshot != snapshot,
                        data.get("plan_id") != snapshot["plan_id"],
                        data.get("node_id") != request.node_id,
                        data.get("tool_id") != request.tool_id,
                        data.get("action") != request.action,
                        data.get("params") != snapshot["node"]["params"],
                    )
                ):
                    raise RuntimeError("已有审批申请与当前操作不一致")
                metadata = {
                    "id": int(existing.id),
                    "request_no": str(existing.request_no),
                    "approval_path": (
                        "/mod/xcagi-approval-bridge/approval-hub/workspace"
                        f"?request_no={existing.request_no}"
                    ),
                }
            else:
                applicant = facade._resolve_applicant(db, runtime_context)
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
                valid_plan = facade._is_valid_plan_for_snapshot(plan)
                persisted_plan_id = (
                    str(getattr(plan, "plan_id", "") or request.plan_id)
                    if valid_plan
                    else request.plan_id
                )
                business_data = {
                    "plan_id": persisted_plan_id,
                    "node_id": request.node_id,
                    "tool_id": request.tool_id,
                    "action": request.action,
                    "params": request.params or {},
                }
                if valid_plan:
                    business_data[facade.SNAPSHOT_KEY] = facade._build_workflow_snapshot(
                        request, runtime_context, plan
                    )
                persisted = ApprovalRequestModel(
                    request_no=request.request_id,
                    flow_id=int(flow.id),
                    business_type="workflow_tool",
                    business_data=facade.json.dumps(business_data, ensure_ascii=False, default=str),
                    applicant_id=int(applicant.id),
                    applicant_name=str(
                        applicant.display_name or applicant.username or applicant.id
                    ),
                    title=(
                        str(title or "").strip()
                        or f"智能对话写操作：{request.tool_id}.{request.action}"
                    ),
                    description=facade.json.dumps(
                        request.params or {}, ensure_ascii=False, default=str
                    )[:500],
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
                        facade.text(
                            "INSERT INTO ai_action_audit (actor, action, payload) "
                            "VALUES (:actor, :action, :payload)"
                        ),
                        {
                            "actor": str(applicant.id),
                            "action": "approval.submit_ai_workflow",
                            "payload": facade.json.dumps(
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
                except facade._APPROVAL_STORAGE_ERRORS:
                    facade.logger.warning("AI 审批提交审计写入失败")
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
        except facade.RECOVERABLE_ERRORS:
            facade.logger.debug("neuro_notify_approval_changed skipped")
        return metadata
    except facade._APPROVAL_STORAGE_ERRORS as exc:
        facade.logger.warning(
            "AI 审批持久化到 DB 失败 request_no=%s type=%s",
            request.request_id,
            type(exc).__name__,
        )
        return None


def mark_durable_outcome(
    request_id: str, *, success: bool, code: str = "", message: str = ""
) -> None:
    """Persist the bounded, terminal execution truth for a durable request."""
    from app.application.workflow import approval_persistence as facade
    from app.db.models.approval import ApprovalRequest as ApprovalRequestModel
    from app.db.models.approval import ApprovalStatus
    from app.db.session import get_db

    del message
    status = ApprovalStatus.APPROVED.value if success else ApprovalStatus.CANCELLED.value
    safe_code, safe_message = facade.canonical_workflow_outcome(success=success, code=code)
    try:
        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return
            if str(persisted.business_type or "").strip() != "workflow_tool":
                return
            business_data = (
                facade.json.loads(persisted.business_data) if persisted.business_data else {}
            )
            if not isinstance(business_data, dict):
                business_data = {}
            business_data["workflow_execution"] = {
                "status": status,
                "success": bool(success),
                "code": safe_code,
                "message": safe_message,
            }
            persisted.business_data = facade.json.dumps(
                business_data, ensure_ascii=False, default=str
            )
            persisted.status = status
            if not success:
                persisted.rejection_reason = facade.WORKFLOW_EXECUTION_FAILED_CODE
                try:
                    db.execute(
                        facade.text(
                            "INSERT INTO ai_action_audit (actor, action, payload) "
                            "VALUES (:actor, :action, :payload)"
                        ),
                        {
                            "actor": str(persisted.applicant_id or "").strip(),
                            "action": "approval.execute_ai_workflow_failed",
                            "payload": facade.json.dumps(
                                {
                                    "request_no": request_id,
                                    "code": safe_code,
                                    "message": safe_message,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                except facade._APPROVAL_STORAGE_ERRORS:
                    facade.logger.warning("AI 审批执行失败审计写入失败 request_no=%s", request_id)
            persisted.updated_at = datetime.now()
            db.commit()
    except facade._APPROVAL_STORAGE_ERRORS as exc:
        facade.logger.warning(
            "mark durable workflow outcome failed request_no=%s type=%s",
            request_id,
            type(exc).__name__,
        )
