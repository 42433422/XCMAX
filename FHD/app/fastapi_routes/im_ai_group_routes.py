# ruff: noqa
"""Administrative AI-group chat routes."""
from __future__ import annotations
import importlib
import logging
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger('app.fastapi_routes.im_routes')
router = APIRouter()

def _facade():
    return importlib.import_module('app.fastapi_routes.im_routes')

def _ai_group_guard(request: Request):
    """复用 Codex 的管理端会话校验；通过返回 uid，否则返回 (None, denied)。"""
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        return denied
    finally:
        db.close()

@router.get('/api/admin/ai-groups')
def admin_ai_groups_list(request: Request, user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        groups = _facade().AiGroupChatService().list_groups(user_id=_facade()._uid(user))
        return {'success': True, 'groups': groups}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_groups_list')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.get('/api/admin/ai-groups/candidates')
def admin_ai_group_candidates(request: Request, user: CurrentUser=Depends(require_identified_user)):
    """可拉入群聊的 AI 员工候选（普通员工 + 超级员工）。

    供手机端建群/加成员的选人列表使用，覆盖全部 AI 员工。
    """
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        candidates = _facade().AiGroupChatService().list_member_candidates()
        return {'success': True, 'candidates': candidates}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_group_candidates')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.post('/api/admin/ai-groups')
def admin_ai_groups_create(request: Request, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = _facade().AiGroupChatService().create_group(user_id=_facade()._uid(user), name=str(body.get('name') or ''))
        return {'success': True, 'group': group}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_groups_create')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.get('/api/admin/ai-groups/{group_id}/messages')
def admin_ai_group_messages(request: Request, group_id: str, limit: int=Query(default=100, ge=1, le=300), user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        messages = _facade().AiGroupChatService().get_messages(user_id=_facade()._uid(user), group_id=group_id, limit=limit)
        return {'success': True, 'messages': messages}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_group_messages')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.post('/api/admin/ai-groups/{group_id}/messages')
async def admin_ai_group_post(request: Request, group_id: str, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        mentions = body.get('mentions')
        result = await _facade().AiGroupChatService().post_message(user_id=_facade()._uid(user), group_id=group_id, text=str(body.get('message') or ''), sender_name=str(body.get('sender_name') or '我'), mentions=mentions if isinstance(mentions, list) else None, dispatch=bool(body.get('dispatch')))
        return {'success': True, **result}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_group_post')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.post('/api/admin/ai-groups/{group_id}/members')
def admin_ai_group_add_member(request: Request, group_id: str, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = _facade().AiGroupChatService().add_member(user_id=_facade()._uid(user), group_id=group_id, member={'employee_id': str(body.get('employee_id') or ''), 'mod_id': str(body.get('mod_id') or ''), 'name': str(body.get('name') or ''), 'avatar': str(body.get('avatar') or ''), 'summary': str(body.get('summary') or '')})
        return {'success': True, 'group': group}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_group_add_member')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@router.delete('/api/admin/ai-groups/{group_id}/members/{employee_id}')
def admin_ai_group_remove_member(request: Request, group_id: str, employee_id: str, user: CurrentUser=Depends(require_identified_user)):
    denied = _facade()._ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = _facade().AiGroupChatService().remove_member(user_id=_facade()._uid(user), group_id=group_id, employee_id=employee_id)
        return {'success': True, 'group': group}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('admin_ai_group_remove_member')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
