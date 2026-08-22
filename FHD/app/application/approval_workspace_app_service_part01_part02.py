# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


def submit_request(
    request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    """提交一个新的审批请求；按 ``flow_key`` 找到流程并定位首个有效节点。"""
    flow_key = str(body.get("flow_key") or "").strip()
    business_type = str(body.get("business_type") or "general").strip()
    title = str(body.get("title") or "").strip()
    if not flow_key or not title:
        raise _facade().HTTPException(status_code=400, detail="flow_key 与 title 为必填项")
    actor = _facade()._resolve_actor(request, x_user_id, fallback=body.get("applicant_id"))
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail="请先登录")
    business_id = body.get("business_id")
    business_data = body.get("business_data")
    description = str(body.get("description") or "").strip() or None
    applicant_name = str(body.get("applicant_name") or "").strip() or None
    applicant_department = str(body.get("applicant_department") or "").strip() or None
    priority = str(body.get("priority") or "normal").strip() or "normal"
    with _facade().get_db() as db:
        flow = (
            db.query(_facade().ApprovalFlow)
            .filter(
                _facade().ApprovalFlow.flow_key == flow_key,
                _facade().ApprovalFlow.is_active == True,
            )
            .first()
        )
        if not flow:
            return _facade().JSONResponse(
                {"success": False, "message": f"未找到启用的审批流程：{flow_key}", "data": None},
                status_code=404,
            )
        nodes = _facade()._ordered_nodes(db, flow.id)
        if not nodes:
            return _facade().JSONResponse(
                {"success": False, "message": "审批流程未配置任何启用节点", "data": None},
                status_code=400,
            )
        first_node = nodes[0]
        req = _facade().ApprovalRequest(
            request_no=_facade()._generate_request_no(),
            flow_id=flow.id,
            business_type=business_type,
            business_id=int(business_id)
            if isinstance(business_id, (int, str)) and str(business_id).isdigit()
            else None,
            business_data=_facade().json.dumps(business_data, ensure_ascii=False)
            if business_data
            else None,
            applicant_id=actor,
            applicant_name=applicant_name,
            applicant_department=applicant_department,
            title=title,
            description=description,
            current_node_id=first_node.id,
            current_node_order=first_node.node_order,
            status=_facade().ApprovalStatus.PENDING.value,
            priority=priority,
        )
        db.add(req)
        db.flush()
        _facade()._audit(
            db,
            actor=actor,
            action="approval.submit",
            payload={
                "request_id": req.id,
                "request_no": req.request_no,
                "flow_id": flow.id,
                "flow_key": flow.flow_key,
                "business_type": business_type,
                "business_id": req.business_id,
                "first_node_id": first_node.id,
            },
        )
        db.commit()
        db.refresh(req)
        return {"success": True, "data": _facade()._request_to_dict(req, include_records=True)}


def _persist_ai_workflow_outcome(
    req: _facade().ApprovalRequest,
    *,
    status: str,
    success: bool,
    code: str,
    message: str,
    workflow_executed: bool,
    nodes_executed: int = 0,
    nodes_total: int = 0,
) -> None:
    """在调用方事务内把 AI 工作流执行结果写入请求 ``business_data``（原子真值）。

    只落白名单内的固定 ``code``/``message``；绝不落原始异常正文。由调用方随后统一
    ``db.commit()``，从而与请求终态（approved/cancelled）构成单一、真实、可重放拒绝的状态。
    """
    business_data = _facade().json.loads(req.business_data) if req.business_data else {}
    if not isinstance(business_data, dict):
        business_data = {}
    business_data["workflow_execution"] = {
        "status": status,
        "success": bool(success),
        "code": str(code or ""),
        "message": str(message or ""),
        "workflow_executed": bool(workflow_executed),
        "nodes_executed": _facade()._safe_workflow_node_count(nodes_executed),
        "nodes_total": _facade()._safe_workflow_node_count(nodes_total),
    }
    req.business_data = _facade().json.dumps(business_data, ensure_ascii=False, default=str)


def _safe_workflow_node_count(value: _facade().Any) -> int:
    """Return a bounded non-negative count safe for persistence and UI output."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return min(max(count, 0), 10000)


def _close_request_if_needed(
    db,
    *,
    req: _facade().ApprovalRequest,
    nodes: list[_facade().ApprovalFlowNode],
    approver_id: int,
    approver_name: str | None,
) -> tuple[str, int | None]:
    """串行流程：推进到下一节点；若已到末节点则置为 ``approved``。"""
    next_node = _facade()._next_node(nodes, req.current_node_order or 0)
    if next_node is None:
        req.status = _facade().ApprovalStatus.APPROVED.value
        req.approved_at = _facade().datetime.now()
        req.approved_by = approver_id
        req.approved_by_name = approver_name
        req.current_node_id = None
        req.current_node_order = (req.current_node_order or 0) + 1
        return (_facade().ApprovalStatus.APPROVED.value, None)
    req.status = _facade().ApprovalStatus.IN_PROGRESS.value
    req.current_node_id = next_node.id
    req.current_node_order = next_node.node_order
    return (_facade().ApprovalStatus.IN_PROGRESS.value, next_node.id)


def _resume_pending_ai_workflow_after_approval(
    *, request_no: str, opinion: str, approved_by: str = ""
) -> dict[str, _facade().Any] | None:
    """工作台审批通过后，继续执行由 AI 工作流创建的 pending workflow。

    纯执行函数：只做内存态审批推进与实际工作流执行，**不做任何请求落库/状态持久化**。
    请求的终态（approved/cancelled + ``workflow_execution`` outcome + 审计）统一由
    调用方（``_approve_ai_workflow_request_without_node`` / ``approve_request``）在自身
    事务中写入并提交，避免与恢复器嵌套会话冲突导致原子真值被覆盖。

    优先内存快速路径；进程重启后内存缺失时，从 DB 严格加载持久化工作流快照并
    重建可执行计划后继续执行（fail-closed：快照缺失/畸形/终态/不匹配/已执行 → 不执行）。
    """
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.workflow import WorkflowEngine, get_approval_service
        from app.application.workflow.approval_persistence import (
            load_workflow_snapshot_for_execution,
        )
        from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval

        approval_service = get_approval_service()
        approved_in_memory = approval_service.approve(approval_request_id, opinion)
        workflow_data = approval_service.get_pending_workflow(approval_request_id)
        if not workflow_data:
            snapshot = load_workflow_snapshot_for_execution(approval_request_id)
            if snapshot is None:
                (safe_code, safe_message) = _facade().canonical_workflow_outcome(
                    success=False, code=_facade().WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE
                )
                return {
                    "workflow_executed": False,
                    "approval_request_id": approval_request_id,
                    "approved_in_memory": approved_in_memory,
                    "success": False,
                    "code": safe_code,
                    "message": safe_message,
                }
            workflow_data = snapshot
        plan_obj = workflow_data.get("plan")
        runtime_ctx = workflow_data.get("runtime_context", {})
        agent_run_id = str(workflow_data.get("agent_run_id") or "").strip()
        approved_step_id = str(workflow_data.get("approved_step_id") or "").strip()
        if agent_run_id:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().continue_run(
                agent_run_id,
                approved_by=approved_by,
                approved_step_id=approved_step_id,
                runtime_context=runtime_ctx,
            )
            approval_service.remove_pending_workflow(approval_request_id)
            if agent_run is None:
                (safe_code, safe_message) = _facade().canonical_workflow_outcome(
                    success=False, code=_facade().AGENT_RUN_UNAVAILABLE_CODE
                )
                return {
                    "workflow_executed": False,
                    "approval_request_id": approval_request_id,
                    "agent_run_id": agent_run_id,
                    "success": False,
                    "code": safe_code,
                    "message": safe_message,
                }
            _agent_success = agent_run.status == "completed"
            (_agent_code, _agent_message) = _facade().canonical_workflow_outcome(
                success=_agent_success,
                code=_facade().WORKFLOW_EXECUTION_SUCCESS_CODE
                if _agent_success
                else _facade().WORKFLOW_EXECUTION_FAILED_CODE,
            )
            return {
                "workflow_executed": True,
                "approval_request_id": approval_request_id,
                "agent_run_id": agent_run.run_id,
                "approved_in_memory": approved_in_memory,
                "success": _agent_success,
                "code": _agent_code,
                "plan_id": str(agent_run.plan_id or ""),
                "intent": str(agent_run.intent or ""),
                "message": _agent_message,
                "nodes_executed": len(
                    [step for step in agent_run.steps if step.status == "completed"]
                ),
                "nodes_total": len(agent_run.steps),
                "tool_call_ids": [call.call_id for call in agent_run.tool_calls],
            }
        if not plan_obj:
            approval_service.remove_pending_workflow(approval_request_id)
            (safe_code, safe_message) = _facade().canonical_workflow_outcome(
                success=False, code=_facade().WORKFLOW_PLAN_UNAVAILABLE_CODE
            )
            return {
                "workflow_executed": False,
                "approval_request_id": approval_request_id,
                "approved_in_memory": approved_in_memory,
                "success": False,
                "code": safe_code,
                "message": safe_message,
            }
        engine = WorkflowEngine(tool_dispatcher=_dispatch_tool_for_approval)
        run_result = engine.run(plan=plan_obj, runtime_context=runtime_ctx, max_retries=1)
        approval_service.remove_pending_workflow(approval_request_id)
        _engine_success = bool(run_result.success)
        (_engine_code, _engine_message) = _facade().canonical_workflow_outcome(
            success=_engine_success,
            code=_facade().WORKFLOW_EXECUTION_SUCCESS_CODE
            if _engine_success
            else _facade().WORKFLOW_EXECUTION_FAILED_CODE,
        )
        return {
            "workflow_executed": True,
            "approval_request_id": approval_request_id,
            "approved_in_memory": approved_in_memory,
            "success": _engine_success,
            "code": _engine_code,
            "plan_id": getattr(plan_obj, "plan_id", ""),
            "intent": getattr(plan_obj, "intent", ""),
            "message": _engine_message,
            "nodes_executed": len(run_result.node_results or []),
            "nodes_total": len(getattr(plan_obj, "nodes", []) or []),
            "node_results": [
                {
                    "node_id": item.node_id,
                    "tool_id": item.tool_id,
                    "action": item.action,
                    "success": bool(item.success),
                    "error": "node_execution_failed"
                    if bool(item.error) and (not bool(item.success))
                    else "",
                    "retries": int(getattr(item, "retries", 0) or 0),
                    "retryable": bool(getattr(item, "retryable", True)),
                    "recovery_hint": "retry_recommended"
                    if not bool(item.success) and bool(getattr(item, "retryable", True))
                    else "",
                }
                for item in (run_result.node_results or [])[:10]
            ],
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        (safe_code, safe_message) = _facade().canonical_workflow_outcome(
            success=False, code=_facade().WORKFLOW_EXECUTION_FAILED_CODE
        )
        _facade().logger.warning(
            "resume pending AI workflow after approval failed request_no=%s type=%s",
            approval_request_id,
            type(exc).__name__,
        )
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "success": False,
            "code": safe_code,
            "message": safe_message,
        }


def _drop_pending_ai_workflow_after_rejection(
    *, request_no: str, reason: str
) -> dict[str, _facade().Any] | None:
    """工作台拒绝 AI workflow 审批后，清理内存 pending workflow。"""
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.workflow import get_approval_service

        approval_service = get_approval_service()
        rejected_in_memory = approval_service.reject(approval_request_id, reason)
        workflow_data = approval_service.get_pending_workflow(approval_request_id)
        workflow_data = workflow_data if isinstance(workflow_data, dict) else {}
        agent_run_id = str(workflow_data.get("agent_run_id") or "").strip()
        cancelled_run_id = ""
        if agent_run_id:
            from app.application.agent_orchestrator import AgentOrchestrator

            cancelled = AgentOrchestrator().cancel_run(
                agent_run_id,
                requested_by="approval_rejected",
            )
            cancelled_run_id = str(getattr(cancelled, "run_id", "") or "")
        removed = approval_service.remove_pending_workflow(approval_request_id)
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "agent_run_id": cancelled_run_id or agent_run_id,
            "rejected_in_memory": rejected_in_memory,
            "discarded_pending_workflow": removed is not None,
            "success": False,
            "code": "approval_rejected",
            "message": "审批已拒绝，AI 工作流已取消",
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "drop pending AI workflow after rejection failed request_no=%s type=%s",
            approval_request_id,
            type(exc).__name__,
        )
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "success": False,
            "message": "审批已拒绝，但清理 AI 工作流失败",
        }
