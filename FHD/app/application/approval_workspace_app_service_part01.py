# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.approval_workspace_app_service')

def _allow_x_user_id_header() -> bool:
    """测试/e2e 专用；生产环境不信任自报 X-User-ID。"""
    return _facade().os.environ.get('FHD_ALLOW_X_USER_ID_HEADER', '').strip().lower() in {'1', 'true', 'yes'}

def _resolve_actor(request: _facade().Request, x_user_id: str | None=None, fallback: int | None=None) -> int | None:
    """优先从登录会话解析操作人；测试模式可回退 X-User-ID。"""
    from app.infrastructure.auth.dependencies import resolve_session_user
    user = resolve_session_user(request)
    if user is not None and getattr(user, 'id', None) is not None:
        return int(user.id)
    if _facade()._allow_x_user_id_header() and x_user_id and str(x_user_id).strip().isdigit():
        return int(str(x_user_id).strip())
    if fallback is not None:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return None
    return None

def _audit(db, *, actor: int | None, action: str, payload: dict) -> None:
    """写入 ``ai_action_audit``：跨业务的 DB 操作轨迹。"""
    try:
        db.execute(_facade().text('INSERT INTO ai_action_audit (actor, action, payload) VALUES (:actor, :action, :payload)'), {'actor': str(actor) if actor is not None else None, 'action': action, 'payload': _facade().json.dumps(payload, ensure_ascii=False, default=str)})
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('ai_action_audit 写入失败 action=%s type=%s', action, type(exc).__name__)

def _generate_request_no() -> str:
    """生成审批单号，例如 ``APR20260419-AB12CD``。"""
    return f"APR{_facade().datetime.now().strftime('%Y%m%d')}-{_facade().secrets.token_hex(3).upper()}"

def _node_query_for_user(node: _facade().ApprovalFlowNode, user_id: int) -> bool:
    """判断 ``user_id`` 是否在节点的审批人列表中。"""
    if not node or not node.approver_ids:
        return False
    try:
        ids = _facade().json.loads(node.approver_ids) if isinstance(node.approver_ids, str) else node.approver_ids
    except (ValueError, TypeError):
        return False
    if not isinstance(ids, list):
        return False
    try:
        return int(user_id) in [int(x) for x in ids if x is not None]
    except (TypeError, ValueError):
        return False

def _ordered_nodes(db, flow_id: int) -> list[_facade().ApprovalFlowNode]:
    return _facade().cast('list[ApprovalFlowNode]', db.query(_facade().ApprovalFlowNode).filter(_facade().ApprovalFlowNode.flow_id == flow_id, _facade().ApprovalFlowNode.is_active == True).order_by(_facade().ApprovalFlowNode.node_order.asc()).all())

def _is_ai_workflow_request(req: _facade().ApprovalRequest) -> bool:
    return str(getattr(req, 'business_type', '') or '').strip() == _facade().AI_WORKFLOW_BUSINESS_TYPE

def _can_review_ai_workflow_request(db, req: _facade().ApprovalRequest, actor: int) -> bool:
    if int(req.applicant_id or 0) == int(actor):
        return True
    user = db.query(_facade().User).filter(_facade().User.id == int(actor), _facade().User.is_active == True).first()
    return str(getattr(user, 'role', '') or '').strip().lower() in {'admin', 'superadmin', 'super_admin', 'owner'}

def _ai_workflow_audit_node(db, req: _facade().ApprovalRequest) -> _facade().ApprovalFlowNode | None:
    return _facade().cast('ApprovalFlowNode | None', db.query(_facade().ApprovalFlowNode).filter(_facade().ApprovalFlowNode.flow_id == req.flow_id, _facade().ApprovalFlowNode.is_active == True).order_by(_facade().ApprovalFlowNode.node_order.asc()).first())

def _has_pending_ai_workflow(request_no: str | None) -> bool:
    approval_request_id = str(request_no or '').strip()
    if not approval_request_id:
        return False
    try:
        from app.application.workflow import get_approval_service
        from app.application.workflow.approval_persistence import load_durable_workflow_snapshot
        if bool(get_approval_service().get_pending_workflow(approval_request_id)):
            return True
        return load_durable_workflow_snapshot(approval_request_id, allow_terminal=False) is not None
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning('check pending AI workflow failed request_no=%s', approval_request_id)
        return False

def _next_node(nodes: list[_facade().ApprovalFlowNode], current_order: int) -> _facade().ApprovalFlowNode | None:
    for n in nodes:
        if n.node_order > current_order:
            return n
    return None

def _request_to_dict(req: _facade().ApprovalRequest, *, include_records: bool=False) -> dict[str, _facade().Any]:
    """统一序列化（含 ``records`` 时间线，便于详情视图渲染）。"""
    base = req.to_dict()
    business_data = base.get('business_data')
    if isinstance(business_data, dict) and isinstance(business_data.get('workflow_execution'), dict):
        base['workflow_execution'] = business_data['workflow_execution']
    if _facade()._is_ai_workflow_request(req) and (not getattr(req, 'current_node', None)):
        base['is_ai_workflow_approval'] = True
        base['current_node_name'] = base.get('current_node_name') or _facade().AI_WORKFLOW_NODE_NAME
        base['current_approvers'] = base.get('current_approvers') or []
    if include_records:
        records = sorted(req.records or [], key=lambda r: r.action_time or _facade().datetime.min) if req.records else []
        base['records'] = [r.to_dict() for r in records]
    return base

def list_requests(approver_id: int | None=_facade().Query(default=None), applicant_id: int | None=_facade().Query(default=None), status: str | None=_facade().Query(default=None), business_type: str | None=_facade().Query(default=None), page: int=_facade().Query(default=1, ge=1), page_size: int=_facade().Query(default=50, ge=1, le=500)):
    """列表接口：支持按申请人 / 当前审批人 / 状态过滤。"""
    with _facade().get_db() as db:
        query = db.query(_facade().ApprovalRequest)
        if applicant_id is not None:
            query = query.filter(_facade().ApprovalRequest.applicant_id == applicant_id)
        if status:
            query = query.filter(_facade().ApprovalRequest.status == status)
        else:
            query = query.filter(_facade().ApprovalRequest.status.in_([_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value, _facade().ApprovalStatus.APPROVED.value, _facade().ApprovalStatus.REJECTED.value, _facade().ApprovalStatus.WITHDRAWN.value, _facade().ApprovalStatus.CANCELLED.value]))
        if business_type:
            query = query.filter(_facade().ApprovalRequest.business_type == business_type)
        query = query.order_by(_facade().ApprovalRequest.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result: list[dict[str, _facade().Any]] = []
        for req in items:
            data = _facade()._request_to_dict(req, include_records=False)
            if approver_id is not None:
                node = req.current_node
                if _facade()._is_ai_workflow_request(req) and (not node):
                    if req.status not in (_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value):
                        continue
                    if not _facade()._has_pending_ai_workflow(req.request_no):
                        continue
                    if not _facade()._can_review_ai_workflow_request(db, req, approver_id):
                        continue
                    data['current_node_name'] = _facade().AI_WORKFLOW_NODE_NAME
                    data['current_approvers'] = [int(approver_id)]
                    result.append(data)
                    continue
                if not node or not _facade()._node_query_for_user(node, approver_id):
                    continue
                if req.status not in (_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value):
                    continue
            result.append(data)
        return {'success': True, 'data': result, 'pagination': {'page': page, 'page_size': page_size, 'total': total, 'returned': len(result)}}

def cleanup_requests(request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """批量清理已完成的审批记录。

    Body 参数::

        {
          "statuses": ["approved", "rejected", "withdrawn", "cancelled"],
                              # 或 "all" / "completed"；默认全部终态
          "before_days": 0,    # 仅清理 N 天之前的记录；0/不传表示不限
          "scope": "self",    # "self" 仅清理本人（默认）；其他值暂不支持
          "dry_run": false    # true 时只返回待清理数量，不真正删除
        }
    """
    actor = _facade()._resolve_actor(request, x_user_id, fallback=body.get('user_id'))
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    statuses = _facade()._normalize_statuses(body.get('statuses') or body.get('status'))
    dry_run = bool(body.get('dry_run', False))
    before_days_raw = body.get('before_days')
    before_days: int | None
    try:
        before_days = int(before_days_raw) if before_days_raw not in (None, '', 0) else None
    except (TypeError, ValueError):
        before_days = None
    if before_days is not None and before_days < 0:
        before_days = None
    scope = str(body.get('scope') or 'self').strip() or 'self'
    if scope != 'self':
        return _facade().JSONResponse({'success': False, 'message': f'暂不支持的清理范围：{scope}'}, status_code=400)
    with _facade().get_db() as db:
        query = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.applicant_id == actor, _facade().ApprovalRequest.status.in_(statuses))
        if before_days is not None:
            from datetime import timedelta
            cutoff = _facade().datetime.now() - timedelta(days=before_days)
            query = query.filter(_facade().ApprovalRequest.created_at < cutoff)
        items = query.all()
        matched = len(items)
        if dry_run or matched == 0:
            return {'success': True, 'data': {'matched': matched, 'deleted': 0, 'dry_run': dry_run, 'statuses': statuses, 'before_days': before_days}}
        ids = [req.id for req in items]
        nos = [req.request_no for req in items]
        _facade()._audit(db, actor=actor, action='approval.cleanup', payload={'count': matched, 'statuses': statuses, 'before_days': before_days, 'request_ids': ids[:500], 'request_nos': nos[:500]})
        for req in items:
            db.delete(req)
        db.commit()
        return {'success': True, 'data': {'matched': matched, 'deleted': matched, 'dry_run': False, 'statuses': statuses, 'before_days': before_days}}

def get_request_detail(request_id: int):
    with _facade().get_db() as db:
        req = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.id == request_id).first()
        if not req:
            return _facade().JSONResponse({'success': False, 'message': '审批请求不存在', 'data': None}, status_code=404)
        return {'success': True, 'data': _facade()._request_to_dict(req, include_records=True)}

def submit_request(request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """提交一个新的审批请求；按 ``flow_key`` 找到流程并定位首个有效节点。"""
    flow_key = str(body.get('flow_key') or '').strip()
    business_type = str(body.get('business_type') or 'general').strip()
    title = str(body.get('title') or '').strip()
    if not flow_key or not title:
        raise _facade().HTTPException(status_code=400, detail='flow_key 与 title 为必填项')
    actor = _facade()._resolve_actor(request, x_user_id, fallback=body.get('applicant_id'))
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    business_id = body.get('business_id')
    business_data = body.get('business_data')
    description = str(body.get('description') or '').strip() or None
    applicant_name = str(body.get('applicant_name') or '').strip() or None
    applicant_department = str(body.get('applicant_department') or '').strip() or None
    priority = str(body.get('priority') or 'normal').strip() or 'normal'
    with _facade().get_db() as db:
        flow = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.flow_key == flow_key, _facade().ApprovalFlow.is_active == True).first()
        if not flow:
            return _facade().JSONResponse({'success': False, 'message': f'未找到启用的审批流程：{flow_key}', 'data': None}, status_code=404)
        nodes = _facade()._ordered_nodes(db, flow.id)
        if not nodes:
            return _facade().JSONResponse({'success': False, 'message': '审批流程未配置任何启用节点', 'data': None}, status_code=400)
        first_node = nodes[0]
        req = _facade().ApprovalRequest(request_no=_facade()._generate_request_no(), flow_id=flow.id, business_type=business_type, business_id=int(business_id) if isinstance(business_id, (int, str)) and str(business_id).isdigit() else None, business_data=_facade().json.dumps(business_data, ensure_ascii=False) if business_data else None, applicant_id=actor, applicant_name=applicant_name, applicant_department=applicant_department, title=title, description=description, current_node_id=first_node.id, current_node_order=first_node.node_order, status=_facade().ApprovalStatus.PENDING.value, priority=priority)
        db.add(req)
        db.flush()
        _facade()._audit(db, actor=actor, action='approval.submit', payload={'request_id': req.id, 'request_no': req.request_no, 'flow_id': flow.id, 'flow_key': flow.flow_key, 'business_type': business_type, 'business_id': req.business_id, 'first_node_id': first_node.id})
        db.commit()
        db.refresh(req)
        return {'success': True, 'data': _facade()._request_to_dict(req, include_records=True)}

def _persist_ai_workflow_outcome(req: _facade().ApprovalRequest, *, status: str, success: bool, code: str, message: str, workflow_executed: bool, nodes_executed: int=0, nodes_total: int=0) -> None:
    """在调用方事务内把 AI 工作流执行结果写入请求 ``business_data``（原子真值）。

    只落白名单内的固定 ``code``/``message``；绝不落原始异常正文。由调用方随后统一
    ``db.commit()``，从而与请求终态（approved/cancelled）构成单一、真实、可重放拒绝的状态。
    """
    business_data = _facade().json.loads(req.business_data) if req.business_data else {}
    if not isinstance(business_data, dict):
        business_data = {}
    business_data['workflow_execution'] = {'status': status, 'success': bool(success), 'code': str(code or ''), 'message': str(message or ''), 'workflow_executed': bool(workflow_executed), 'nodes_executed': _facade()._safe_workflow_node_count(nodes_executed), 'nodes_total': _facade()._safe_workflow_node_count(nodes_total)}
    req.business_data = _facade().json.dumps(business_data, ensure_ascii=False, default=str)

def _safe_workflow_node_count(value: _facade().Any) -> int:
    """Return a bounded non-negative count safe for persistence and UI output."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return min(max(count, 0), 10000)

def _close_request_if_needed(db, *, req: _facade().ApprovalRequest, nodes: list[_facade().ApprovalFlowNode], approver_id: int, approver_name: str | None) -> tuple[str, int | None]:
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

def _resume_pending_ai_workflow_after_approval(*, request_no: str, opinion: str, approved_by: str='') -> dict[str, _facade().Any] | None:
    """工作台审批通过后，继续执行由 AI 工作流创建的 pending workflow。

    纯执行函数：只做内存态审批推进与实际工作流执行，**不做任何请求落库/状态持久化**。
    请求的终态（approved/cancelled + ``workflow_execution`` outcome + 审计）统一由
    调用方（``_approve_ai_workflow_request_without_node`` / ``approve_request``）在自身
    事务中写入并提交，避免与恢复器嵌套会话冲突导致原子真值被覆盖。

    优先内存快速路径；进程重启后内存缺失时，从 DB 严格加载持久化工作流快照并
    重建可执行计划后继续执行（fail-closed：快照缺失/畸形/终态/不匹配/已执行 → 不执行）。
    """
    approval_request_id = str(request_no or '').strip()
    if not approval_request_id:
        return None
    try:
        from app.application.workflow import WorkflowEngine, get_approval_service
        from app.application.workflow.approval_persistence import load_workflow_snapshot_for_execution
        from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval
        approval_service = get_approval_service()
        approved_in_memory = approval_service.approve(approval_request_id, opinion)
        workflow_data = approval_service.get_pending_workflow(approval_request_id)
        if not workflow_data:
            snapshot = load_workflow_snapshot_for_execution(approval_request_id)
            if snapshot is None:
                (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=False, code=_facade().WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE)
                return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'approved_in_memory': approved_in_memory, 'success': False, 'code': safe_code, 'message': safe_message}
            workflow_data = snapshot
        plan_obj = workflow_data.get('plan')
        runtime_ctx = workflow_data.get('runtime_context', {})
        agent_run_id = str(workflow_data.get('agent_run_id') or '').strip()
        approved_step_id = str(workflow_data.get('approved_step_id') or '').strip()
        if agent_run_id:
            from app.application.agent_orchestrator import AgentOrchestrator
            agent_run = AgentOrchestrator().continue_run(agent_run_id, approved_by=approved_by, approved_step_id=approved_step_id, runtime_context=runtime_ctx)
            approval_service.remove_pending_workflow(approval_request_id)
            if agent_run is None:
                (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=False, code=_facade().AGENT_RUN_UNAVAILABLE_CODE)
                return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'agent_run_id': agent_run_id, 'success': False, 'code': safe_code, 'message': safe_message}
            _agent_success = agent_run.status == 'completed'
            (_agent_code, _agent_message) = _facade().canonical_workflow_outcome(success=_agent_success, code=_facade().WORKFLOW_EXECUTION_SUCCESS_CODE if _agent_success else _facade().WORKFLOW_EXECUTION_FAILED_CODE)
            return {'workflow_executed': True, 'approval_request_id': approval_request_id, 'agent_run_id': agent_run.run_id, 'approved_in_memory': approved_in_memory, 'success': _agent_success, 'code': _agent_code, 'plan_id': str(agent_run.plan_id or ''), 'intent': str(agent_run.intent or ''), 'message': _agent_message, 'nodes_executed': len([step for step in agent_run.steps if step.status == 'completed']), 'nodes_total': len(agent_run.steps), 'tool_call_ids': [call.call_id for call in agent_run.tool_calls]}
        if not plan_obj:
            approval_service.remove_pending_workflow(approval_request_id)
            (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=False, code=_facade().WORKFLOW_PLAN_UNAVAILABLE_CODE)
            return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'approved_in_memory': approved_in_memory, 'success': False, 'code': safe_code, 'message': safe_message}
        engine = WorkflowEngine(tool_dispatcher=_dispatch_tool_for_approval)
        run_result = engine.run(plan=plan_obj, runtime_context=runtime_ctx, max_retries=1)
        approval_service.remove_pending_workflow(approval_request_id)
        _engine_success = bool(run_result.success)
        (_engine_code, _engine_message) = _facade().canonical_workflow_outcome(success=_engine_success, code=_facade().WORKFLOW_EXECUTION_SUCCESS_CODE if _engine_success else _facade().WORKFLOW_EXECUTION_FAILED_CODE)
        return {'workflow_executed': True, 'approval_request_id': approval_request_id, 'approved_in_memory': approved_in_memory, 'success': _engine_success, 'code': _engine_code, 'plan_id': getattr(plan_obj, 'plan_id', ''), 'intent': getattr(plan_obj, 'intent', ''), 'message': _engine_message, 'nodes_executed': len(run_result.node_results or []), 'nodes_total': len(getattr(plan_obj, 'nodes', []) or []), 'node_results': [{'node_id': item.node_id, 'tool_id': item.tool_id, 'action': item.action, 'success': bool(item.success), 'error': 'node_execution_failed' if bool(item.error) and (not bool(item.success)) else '', 'retries': int(getattr(item, 'retries', 0) or 0), 'retryable': bool(getattr(item, 'retryable', True)), 'recovery_hint': 'retry_recommended' if not bool(item.success) and bool(getattr(item, 'retryable', True)) else ''} for item in (run_result.node_results or [])[:10]]}
    except _facade().RECOVERABLE_ERRORS as exc:
        (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=False, code=_facade().WORKFLOW_EXECUTION_FAILED_CODE)
        _facade().logger.warning('resume pending AI workflow after approval failed request_no=%s type=%s', approval_request_id, type(exc).__name__)
        return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'success': False, 'code': safe_code, 'message': safe_message}

def _drop_pending_ai_workflow_after_rejection(*, request_no: str, reason: str) -> dict[str, _facade().Any] | None:
    """工作台拒绝 AI workflow 审批后，清理内存 pending workflow。"""
    approval_request_id = str(request_no or '').strip()
    if not approval_request_id:
        return None
    try:
        from app.application.workflow import get_approval_service
        approval_service = get_approval_service()
        rejected_in_memory = approval_service.reject(approval_request_id, reason)
        removed = approval_service.remove_pending_workflow(approval_request_id)
        return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'rejected_in_memory': rejected_in_memory, 'discarded_pending_workflow': removed is not None, 'message': '审批已拒绝，AI 工作流已取消'}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('drop pending AI workflow after rejection failed request_no=%s type=%s', approval_request_id, type(exc).__name__)
        return {'workflow_executed': False, 'approval_request_id': approval_request_id, 'success': False, 'message': '审批已拒绝，但清理 AI 工作流失败'}

def _approve_ai_workflow_request_without_node(db, *, req: _facade().ApprovalRequest, actor: int, approver_name: str | None, opinion: str) -> dict[str, _facade().Any] | _facade().JSONResponse:
    """审批由 AI workflow 持久化、没有传统审批节点的请求。"""
    if not _facade()._can_review_ai_workflow_request(db, req, actor):
        return _facade().JSONResponse({'success': False, 'message': '当前用户无权审批这条 AI 工作流'}, status_code=403)
    if not _facade()._has_pending_ai_workflow(req.request_no):
        return _facade().JSONResponse({'success': False, 'message': 'AI 工作流运行态不存在或已过期，请重新发起任务'}, status_code=409)
    audit_node = _facade()._ai_workflow_audit_node(db, req)
    if audit_node is None:
        return _facade().JSONResponse({'success': False, 'message': 'AI 审批流程缺少合法留痕节点'}, status_code=409)
    workflow_execution = _facade()._resume_pending_ai_workflow_after_approval(request_no=str(req.request_no or ''), opinion=opinion, approved_by=str(actor))
    _execution_success = bool(workflow_execution and workflow_execution.get('success'))
    status_before = req.status
    terminal_status = _facade().ApprovalStatus.APPROVED.value if _execution_success else _facade().ApprovalStatus.CANCELLED.value
    (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=_execution_success, code=str((workflow_execution or {}).get('code') or ''))
    nodes_executed_count = _facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_executed'))
    nodes_total_count = _facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_total'))
    bounded_outcome = {'status': terminal_status, 'success': _execution_success, 'code': safe_code, 'message': safe_message, 'workflow_executed': bool(workflow_execution and workflow_execution.get('workflow_executed')), 'nodes_executed': nodes_executed_count, 'nodes_total': nodes_total_count}
    _facade()._persist_ai_workflow_outcome(req, status=terminal_status, success=_execution_success, code=safe_code, message=safe_message, workflow_executed=bool(workflow_execution and workflow_execution.get('workflow_executed')), nodes_executed=nodes_executed_count, nodes_total=nodes_total_count)
    req.status = terminal_status
    if _execution_success:
        req.approved_at = _facade().datetime.now()
        req.approved_by = actor
        req.approved_by_name = approver_name
        req.current_node_id = None
        req.current_node_order = (req.current_node_order or 0) + 1
        db.add(_facade().ApprovalRecord(request_id=req.id, node_id=audit_node.id, node_name=audit_node.node_name, node_order=audit_node.node_order, approver_id=actor, approver_name=approver_name, action=_facade().ApprovalAction.APPROVE.value, opinion=opinion, is_passed=True))
        _facade()._audit(db, actor=actor, action='approval.approve_ai_workflow', payload={'request_id': req.id, 'request_no': req.request_no, 'status_before': status_before, 'status_after': req.status, 'opinion': opinion})
    _facade()._audit(db, actor=actor, action='approval.execute_ai_workflow', payload={'request_id': req.id, 'request_no': req.request_no, 'workflow_execution_status': bounded_outcome['status'], 'workflow_execution_success': _execution_success, 'workflow_execution_code': safe_code, 'workflow_execution_message': bounded_outcome['message']})
    if not _execution_success:
        req.rejection_reason = _facade().WORKFLOW_EXECUTION_FAILED_CODE
        _facade()._audit(db, actor=actor, action='approval.execute_ai_workflow_failed', payload={'request_no': req.request_no, 'code': safe_code, 'message': bounded_outcome['message']})
    notification = _facade().completed_workflow_notification(req) if req.applicant_id else None
    db.commit()
    db.refresh(req)
    if _execution_success and notification is not None:
        _facade().notify_mobile_user(*notification)
    data = _facade()._request_to_dict(req, include_records=True)
    data['workflow_execution'] = bounded_outcome
    if not _execution_success:
        return _facade().JSONResponse({'success': False, 'data': data, 'message': '审批通过后 AI 工作流执行失败，审批已取消'}, status_code=409)
    return {'success': True, 'data': data}
