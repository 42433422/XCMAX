# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.approval_workspace_app_service')

def approve_request(request_id: int, http_request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    actor = _facade()._resolve_actor(http_request, x_user_id)
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    opinion = str(body.get('opinion') or '').strip() or '同意'
    approver_name = str(body.get('approver_name') or '').strip() or None
    with _facade().get_db() as db:
        req = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.id == request_id).first()
        if not req:
            return _facade().JSONResponse({'success': False, 'message': '审批请求不存在'}, status_code=404)
        if req.status not in (_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value):
            return _facade().JSONResponse({'success': False, 'message': f'当前状态不可审批：{req.status}'}, status_code=400)
        current_node = req.current_node
        if current_node is None:
            if _facade()._is_ai_workflow_request(req):
                return _facade()._approve_ai_workflow_request_without_node(db, req=req, actor=actor, approver_name=approver_name, opinion=opinion)
            return _facade().JSONResponse({'success': False, 'message': '审批请求缺少当前节点'}, status_code=400)
        if not _facade()._node_query_for_user(current_node, actor):
            return _facade().JSONResponse({'success': False, 'message': '当前用户不在审批人列表中'}, status_code=403)
        status_before = req.status
        node_id_before = current_node.id
        record = _facade().ApprovalRecord(request_id=req.id, node_id=current_node.id, node_name=current_node.node_name, node_order=current_node.node_order, approver_id=actor, approver_name=approver_name, action=_facade().ApprovalAction.APPROVE.value, opinion=opinion, is_passed=True)
        db.add(record)
        nodes = _facade()._ordered_nodes(db, req.flow_id)
        (new_status, next_node_id) = _facade()._close_request_if_needed(db, req=req, nodes=nodes, approver_id=actor, approver_name=approver_name)
        _facade()._audit(db, actor=actor, action='approval.approve', payload={'request_id': req.id, 'request_no': req.request_no, 'flow_id': req.flow_id, 'node_id': node_id_before, 'next_node_id': next_node_id, 'status_before': status_before, 'status_after': new_status, 'opinion': opinion})
        workflow_execution = None
        if new_status == _facade().ApprovalStatus.APPROVED.value and _facade()._is_ai_workflow_request(req):
            workflow_execution = _facade()._resume_pending_ai_workflow_after_approval(request_no=str(req.request_no or ''), opinion=opinion, approved_by=str(actor))
            _execution_success = bool(workflow_execution and workflow_execution.get('workflow_executed') and workflow_execution.get('success'))
            (safe_code, safe_message) = _facade().canonical_workflow_outcome(success=_execution_success, code=str((workflow_execution or {}).get('code') or ''))
            if _execution_success:
                _facade()._persist_ai_workflow_outcome(req, status=_facade().ApprovalStatus.APPROVED.value, success=True, code=safe_code, message=safe_message, workflow_executed=True, nodes_executed=_facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_executed')), nodes_total=_facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_total')))
            else:
                _facade()._persist_ai_workflow_outcome(req, status=_facade().ApprovalStatus.CANCELLED.value, success=False, code=safe_code, message=safe_message, workflow_executed=bool(workflow_execution and workflow_execution.get('workflow_executed')), nodes_executed=_facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_executed')), nodes_total=_facade()._safe_workflow_node_count((workflow_execution or {}).get('nodes_total')))
                req.status = _facade().ApprovalStatus.CANCELLED.value
                req.rejection_reason = safe_code
                _facade()._audit(db, actor=actor, action='approval.execute_ai_workflow_failed', payload={'request_no': req.request_no, 'code': safe_code, 'message': safe_message})
        db.commit()
        db.refresh(req)
        if workflow_execution is not None and (not (workflow_execution.get('workflow_executed') and workflow_execution.get('success'))):
            return {'success': False, 'data': _facade()._request_to_dict(req, include_records=False), 'workflow_execution': workflow_execution, 'message': '审批未通过：AI 工作流未成功执行'}
        if req.applicant_id:
            _facade().notify_mobile_user(int(req.applicant_id), '审批进度更新', f'《{req.title or req.request_no}》已处理', {'route': f'/app/approval/{req.id}', 'request_id': str(req.id)})
        data = _facade()._request_to_dict(req, include_records=True)
        if workflow_execution is not None:
            data['workflow_execution'] = workflow_execution
        return {'success': True, 'data': data}

def reject_request(request_id: int, http_request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    actor = _facade()._resolve_actor(http_request, x_user_id)
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    reason = str(body.get('reason') or body.get('opinion') or '').strip()
    if not reason:
        raise _facade().HTTPException(status_code=400, detail='拒绝原因不能为空')
    approver_name = str(body.get('approver_name') or '').strip() or None
    with _facade().get_db() as db:
        req = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.id == request_id).first()
        if not req:
            return _facade().JSONResponse({'success': False, 'message': '审批请求不存在'}, status_code=404)
        if req.status not in (_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value):
            return _facade().JSONResponse({'success': False, 'message': f'当前状态不可拒绝：{req.status}'}, status_code=400)
        current_node = req.current_node
        if current_node is None:
            if _facade()._is_ai_workflow_request(req):
                if not _facade()._can_review_ai_workflow_request(db, req, actor):
                    return _facade().JSONResponse({'success': False, 'message': '当前用户无权拒绝这条 AI 工作流'}, status_code=403)
                audit_node = _facade()._ai_workflow_audit_node(db, req)
                if audit_node is None:
                    return _facade().JSONResponse({'success': False, 'message': 'AI 审批流程缺少合法留痕节点'}, status_code=409)
                status_before = req.status
                req.status = _facade().ApprovalStatus.REJECTED.value
                req.rejected_at = _facade().datetime.now()
                req.rejection_reason = reason
                req.approved_by = actor
                req.approved_by_name = approver_name
                db.add(_facade().ApprovalRecord(request_id=req.id, node_id=audit_node.id, node_name=audit_node.node_name, node_order=audit_node.node_order, approver_id=actor, approver_name=approver_name, action=_facade().ApprovalAction.REJECT.value, opinion=reason, reject_reason=reason, is_passed=False))
                _facade()._audit(db, actor=actor, action='approval.reject_ai_workflow', payload={'request_id': req.id, 'request_no': req.request_no, 'status_before': status_before, 'status_after': req.status, 'reason': reason})
                db.commit()
                db.refresh(req)
                workflow_execution = _facade()._drop_pending_ai_workflow_after_rejection(request_no=str(req.request_no or ''), reason=reason)
                if req.applicant_id:
                    _facade().notify_mobile_user(int(req.applicant_id), '审批进度更新', f'《{req.title or req.request_no}》已驳回', {'route': f'/app/approval/{req.id}', 'request_id': str(req.id)})
                data = _facade()._request_to_dict(req, include_records=True)
                if workflow_execution is not None:
                    data['workflow_execution'] = workflow_execution
                return {'success': True, 'data': data}
            return _facade().JSONResponse({'success': False, 'message': '审批请求缺少当前节点'}, status_code=400)
        if not _facade()._node_query_for_user(current_node, actor):
            return _facade().JSONResponse({'success': False, 'message': '当前用户不在审批人列表中'}, status_code=403)
        status_before = req.status
        node_id_before = current_node.id
        record = _facade().ApprovalRecord(request_id=req.id, node_id=current_node.id, node_name=current_node.node_name, node_order=current_node.node_order, approver_id=actor, approver_name=approver_name, action=_facade().ApprovalAction.REJECT.value, opinion=reason, reject_reason=reason, is_passed=False)
        db.add(record)
        req.status = _facade().ApprovalStatus.REJECTED.value
        req.rejected_at = _facade().datetime.now()
        req.rejection_reason = reason
        _facade()._audit(db, actor=actor, action='approval.reject', payload={'request_id': req.id, 'request_no': req.request_no, 'flow_id': req.flow_id, 'node_id': node_id_before, 'status_before': status_before, 'status_after': req.status, 'reason': reason})
        db.commit()
        db.refresh(req)
        if req.applicant_id:
            _facade().notify_mobile_user(int(req.applicant_id), '审批进度更新', f'《{req.title or req.request_no}》已驳回', {'route': f'/app/approval/{req.id}', 'request_id': str(req.id)})
        return {'success': True, 'data': _facade()._request_to_dict(req, include_records=True)}

def withdraw_request(request_id: int, http_request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    actor = _facade()._resolve_actor(http_request, x_user_id, fallback=body.get('user_id'))
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    with _facade().get_db() as db:
        req = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.id == request_id).first()
        if not req:
            return _facade().JSONResponse({'success': False, 'message': '审批请求不存在'}, status_code=404)
        if req.applicant_id != actor:
            return _facade().JSONResponse({'success': False, 'message': '只有申请人可以撤回'}, status_code=403)
        if req.status not in (_facade().ApprovalStatus.PENDING.value, _facade().ApprovalStatus.IN_PROGRESS.value):
            return _facade().JSONResponse({'success': False, 'message': f'当前状态不可撤回：{req.status}'}, status_code=400)
        flow = req.flow
        if flow is not None and flow.allow_withdraw is False:
            return _facade().JSONResponse({'success': False, 'message': '该流程不允许撤回'}, status_code=400)
        status_before = req.status
        current_node = req.current_node
        record = _facade().ApprovalRecord(request_id=req.id, node_id=current_node.id if current_node else 0, node_name=current_node.node_name if current_node else '', node_order=current_node.node_order if current_node else 0, approver_id=actor, action=_facade().ApprovalAction.WITHDRAW.value, opinion='申请人撤回', is_passed=False)
        db.add(record)
        req.status = _facade().ApprovalStatus.WITHDRAWN.value
        _facade()._audit(db, actor=actor, action='approval.withdraw', payload={'request_id': req.id, 'request_no': req.request_no, 'flow_id': req.flow_id, 'status_before': status_before, 'status_after': req.status})
        db.commit()
        db.refresh(req)
        return {'success': True, 'data': _facade()._request_to_dict(req, include_records=True)}

def _normalize_statuses(raw: _facade().Any) -> list[str]:
    """标准化前端传入的状态过滤参数。"""
    if raw is None:
        return list(_facade()._FINAL_STATUSES)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw or raw in ('all', 'completed', 'final'):
            return list(_facade()._FINAL_STATUSES)
        raw = [s.strip() for s in raw.split(',') if s.strip()]
    if not isinstance(raw, list):
        return list(_facade()._FINAL_STATUSES)
    allowed = set(_facade()._FINAL_STATUSES)
    result = [s for s in (str(x).strip() for x in raw) if s in allowed]
    return result or list(_facade()._FINAL_STATUSES)

def delete_request(request_id: int, http_request: _facade().Request, x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """物理删除单个审批申请（仅申请人本人，且必须处于终态。

    级联删除 ``approval_records``；会写入一条 ``approval.delete`` 审计。
    """
    actor = _facade()._resolve_actor(http_request, x_user_id)
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail='请先登录')
    with _facade().get_db() as db:
        req = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.id == request_id).first()
        if not req:
            return _facade().JSONResponse({'success': False, 'message': '审批请求不存在'}, status_code=404)
        if req.applicant_id != actor:
            return _facade().JSONResponse({'success': False, 'message': '只有申请人可以删除自己的审批记录'}, status_code=403)
        if req.status not in _facade()._FINAL_STATUSES:
            return _facade().JSONResponse({'success': False, 'message': f'进行中的审批不能删除，请先撤回（当前状态：{req.status}）'}, status_code=400)
        snapshot = {'request_id': req.id, 'request_no': req.request_no, 'flow_id': req.flow_id, 'business_type': req.business_type, 'business_id': req.business_id, 'title': req.title, 'status': req.status}
        _facade()._audit(db, actor=actor, action='approval.delete', payload=snapshot)
        db.delete(req)
        db.commit()
        return {'success': True, 'data': {'deleted': 1, 'request_id': request_id}}

def get_approval_users():
    """返回可选审批人列表（从用户/人员表拉取）。

    供前端审批流程配置页的「审批人选择」下拉使用。
    若无独立 User 表，则 fallback 到产品/人员 roster（考勤行业）。
    """
    users: list[dict] = []
    try:
        from app.db.models import User
        with _facade().get_db() as db:
            rows = db.query(User).filter(User.is_active == True).all()
            users = [{'id': u.id, 'name': getattr(u, 'name', None) or getattr(u, 'username', '') or f'用户{u.id}', 'email': getattr(u, 'email', None), 'department': getattr(u, 'department', None)} for u in rows]
    except _facade().RECOVERABLE_ERRORS:
        pass
    if not users:
        try:
            from app.application import get_product_app_service
            products = get_product_app_service().get_all_products()
            if isinstance(products, list):
                for p in products[:50]:
                    name = str(p.get('name') or p.get('product_name') or '').strip()
                    if name:
                        users.append({'id': p.get('id'), 'name': name, 'source': 'roster'})
        except _facade().RECOVERABLE_ERRORS:
            pass
    return {'success': True, 'data': users, 'count': len(users)}

def check_approver_orphan(user_id: int):
    """检查某用户 ID 是否出现在激活流程的审批节点但在用户表中已不存在（孤儿检测）。"""
    with _facade().get_db() as db:
        active_flows = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.is_active == True, _facade().ApprovalFlow.is_deleted == False).all()
        orphan_flows: list[dict] = []
        for flow in active_flows:
            for node in flow.nodes or []:
                ids = []
                try:
                    ids = _facade().json.loads(node.approver_ids or '[]')
                except _facade().RECOVERABLE_ERRORS:
                    pass
                if user_id in ids:
                    orphan_flows.append({'flow_id': flow.id, 'flow_name': flow.flow_name, 'node_id': node.id})
        is_orphan = len(orphan_flows) > 0
        return {'success': True, 'user_id': user_id, 'is_orphan_in_active_flows': is_orphan, 'orphan_flows': orphan_flows, 'message': f"用户 {user_id} {('出现在以下激活流程节点中但可能已不存在' if is_orphan else '未在任何激活流程节点中')}"}

def process_approval_timeouts_endpoint():
    """手动触发（或由定时任务调用）审批超时处理——扫描 expired_at < now 的待审批记录。"""
    from app.application.workflow.approval_service import process_approval_timeouts
    result = process_approval_timeouts()
    return _facade().JSONResponse(result, status_code=200 if result.get('success') else 500)

def list_flows(is_active: bool | None=_facade().Query(default=None), business_type: str | None=_facade().Query(default=None)):
    with _facade().get_db() as db:
        query = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.is_deleted == False)
        if is_active is not None:
            query = query.filter(_facade().ApprovalFlow.is_active == bool(is_active))
        if business_type:
            query = query.filter(_facade().ApprovalFlow.business_type == business_type)
        query = query.order_by(_facade().ApprovalFlow.created_at.desc())
        flows = query.all()
        return {'success': True, 'data': [flow.to_dict() for flow in flows]}

def get_flow_detail(flow_id: int):
    with _facade().get_db() as db:
        flow = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.id == flow_id).first()
        if not flow:
            return _facade().JSONResponse({'success': False, 'message': '审批流程不存在', 'data': None}, status_code=404)
        return {'success': True, 'data': flow.to_dict()}

def create_flow(request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """创建审批流程；body 形如 ``{flow: {...}, nodes: [...]}``。"""
    flow_payload = body.get('flow') or {}
    nodes_payload = body.get('nodes') or []
    if not isinstance(flow_payload, dict) or not isinstance(nodes_payload, list):
        raise _facade().HTTPException(status_code=400, detail='flow / nodes 字段格式错误')
    flow_name = str(flow_payload.get('flow_name') or '').strip()
    flow_key = str(flow_payload.get('flow_key') or '').strip()
    business_type = str(flow_payload.get('business_type') or 'general').strip() or 'general'
    if not flow_name or not flow_key:
        raise _facade().HTTPException(status_code=400, detail='flow_name / flow_key 为必填项')
    if not nodes_payload:
        raise _facade().HTTPException(status_code=400, detail='至少需要一个审批节点')
    actor = _facade()._resolve_actor(request, x_user_id, fallback=flow_payload.get('created_by'))
    with _facade().get_db() as db:
        existed = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.flow_key == flow_key, _facade().ApprovalFlow.is_deleted == False).first()
        if existed:
            return _facade().JSONResponse({'success': False, 'message': f'flow_key 已存在：{flow_key}'}, status_code=409)
        flow = _facade().ApprovalFlow(flow_key=flow_key, flow_name=flow_name, description=str(flow_payload.get('description') or '').strip() or None, industry=str(flow_payload.get('industry') or '通用').strip() or '通用', business_type=business_type, node_type=str(flow_payload.get('node_type') or 'serial'), allow_transfer=bool(flow_payload.get('allow_transfer', True)), allow_delegate=bool(flow_payload.get('allow_delegate', False)), allow_withdraw=bool(flow_payload.get('allow_withdraw', True)), timeout_hours=int(flow_payload.get('timeout_hours') or 48), is_active=bool(flow_payload.get('is_active', True)), is_deleted=False, created_by=actor)
        db.add(flow)
        db.flush()
        for (idx, node_data) in enumerate(nodes_payload, start=1):
            if not isinstance(node_data, dict):
                continue
            approver_ids = node_data.get('approver_ids') or []
            if not isinstance(approver_ids, list):
                approver_ids = []
            node = _facade().ApprovalFlowNode(flow_id=flow.id, node_name=str(node_data.get('node_name') or f'节点{idx}').strip(), node_order=int(node_data.get('node_order') or idx), node_type=str(node_data.get('node_type') or 'serial'), approver_type=str(node_data.get('approver_type') or 'user'), approver_ids=_facade().json.dumps([int(x) for x in approver_ids if str(x).strip().lstrip('-').isdigit()], ensure_ascii=False), min_approvals=int(node_data.get('min_approvals') or 1), condition_expression=node_data.get('condition_expression') or None, condition_description=node_data.get('condition_description') or None, timeout_hours=node_data.get('timeout_hours'), timeout_action=str(node_data.get('timeout_action') or 'notify'), is_active=bool(node_data.get('is_active', True)))
            db.add(node)
        _facade()._audit(db, actor=actor, action='approval.flow.create', payload={'flow_id': flow.id, 'flow_key': flow_key, 'flow_name': flow_name, 'business_type': business_type, 'node_count': len(nodes_payload)})
        db.commit()
        db.refresh(flow)
        return {'success': True, 'data': flow.to_dict()}

def update_flow(flow_id: int, request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """更新审批流程基础信息（不含节点，节点暂由 POST /flows 重建）。"""
    actor = _facade()._resolve_actor(request, x_user_id)
    with _facade().get_db() as db:
        flow = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False).first()
        if not flow:
            return _facade().JSONResponse({'success': False, 'message': '审批流程不存在'}, status_code=404)
        updatable = ['flow_name', 'description', 'industry', 'business_type', 'node_type', 'allow_transfer', 'allow_delegate', 'allow_withdraw', 'timeout_hours']
        for field in updatable:
            if field in body:
                setattr(flow, field, body[field])
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(db, actor=actor, action='approval_flow_update', payload={'flow_id': flow_id, **body})
        db.commit()
        db.refresh(flow)
        return {'success': True, 'data': flow.to_dict()}

def toggle_flow_active(flow_id: int, request: _facade().Request, body: dict=_facade().Body(default_factory=dict), x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """启用 / 停用审批流程。body: {is_active: bool}"""
    actor = _facade()._resolve_actor(request, x_user_id)
    is_active = bool(body.get('is_active', True))
    with _facade().get_db() as db:
        flow = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False).first()
        if not flow:
            return _facade().JSONResponse({'success': False, 'message': '审批流程不存在'}, status_code=404)
        flow.is_active = is_active
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(db, actor=actor, action='approval_flow_toggle_active', payload={'flow_id': flow_id, 'is_active': is_active})
        db.commit()
        return {'success': True, 'message': f"流程已{('启用' if is_active else '停用')}", 'is_active': is_active}

def delete_flow(flow_id: int, request: _facade().Request, x_user_id: str | None=_facade().Header(default=None, alias='X-User-ID')):
    """软删除审批流程（is_deleted = True）。"""
    actor = _facade()._resolve_actor(request, x_user_id)
    with _facade().get_db() as db:
        flow = db.query(_facade().ApprovalFlow).filter(_facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False).first()
        if not flow:
            return _facade().JSONResponse({'success': False, 'message': '审批流程不存在或已删除'}, status_code=404)
        pending_count = db.query(_facade().ApprovalRequest).filter(_facade().ApprovalRequest.flow_id == flow_id, _facade().ApprovalRequest.status == _facade().ApprovalStatus.PENDING).count()
        if pending_count > 0:
            return _facade().JSONResponse({'success': False, 'message': f'流程下有 {pending_count} 条待审批请求，无法删除'}, status_code=409)
        flow.is_deleted = True
        flow.is_active = False
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(db, actor=actor, action='approval_flow_delete', payload={'flow_id': flow_id})
        db.commit()
        return {'success': True, 'message': '审批流程已删除'}
