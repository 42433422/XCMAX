# ruff: noqa
"""Administrative super-employee and factory-console IM routes."""
from __future__ import annotations
import importlib
import logging
from typing import Any
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger('app.fastapi_routes.im_routes')
router = APIRouter()

def _facade():
    return importlib.import_module('app.fastapi_routes.im_routes')

@router.get('/api/admin/codex-super-employee/messages')
def codex_super_employee_messages(request: Request, user: CurrentUser=Depends(require_identified_user), limit: int=Query(default=80, ge=1, le=200)):
    """管理端 Codex 超级员工软件内对话记录。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = _facade().CodexSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {'success': True, 'messages': messages}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('codex_super_employee_messages')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.post('/api/admin/codex-super-employee/messages')
def codex_super_employee_invoke(request: Request, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    """管理端 Codex 超级员工软件内调用入口。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get('message') or body.get('body') or '').strip()
        raw_context = body.get('context')
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        if not isinstance(body, dict):
            body = {}
        workspace_id = str((body or {}).get('workspace_id') or context.get('workspace_id') or 'xcmax')
        context = _facade().factory_context(workspace_id=workspace_id, base=context)
        result = _facade().CodexSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {'success': True, **result}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('codex_super_employee_invoke')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.get('/api/admin/claude-super-employee/messages')
def claude_super_employee_messages(request: Request, user: CurrentUser=Depends(require_identified_user), limit: int=Query(default=80, ge=1, le=200)):
    """管理端 Claude 超级员工软件内对话记录。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = _facade().ClaudeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {'success': True, 'messages': messages}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('claude_super_employee_messages')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.post('/api/admin/claude-super-employee/messages')
def claude_super_employee_invoke(request: Request, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    """管理端 Claude 超级员工软件内调用入口。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get('message') or body.get('body') or '').strip()
        raw_context = body.get('context')
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        if not isinstance(body, dict):
            body = {}
        workspace_id = str((body or {}).get('workspace_id') or context.get('workspace_id') or 'xcmax')
        context = _facade().factory_context(workspace_id=workspace_id, base=context)
        result = _facade().ClaudeSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {'success': True, **result}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('claude_super_employee_invoke')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.get('/api/admin/factory/workspaces')
def admin_factory_workspaces(request: Request, user: CurrentUser=Depends(require_identified_user)):
    """列出工厂可派工的项目 Workspace（仅平台管理端可见）。"""
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        items = [{'id': ws.id, 'label': ws.label, 'isolation': ws.isolation, 'default_branch': ws.default_branch, 'vcs_kind': ws.vcs_kind} for ws in _facade().get_workspace_registry().list()]
        return {'success': True, 'workspaces': items}
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('admin_factory_workspaces')
        return _facade().JSONResponse({'success': False, 'message': '加载项目列表失败'}, status_code=500)
    finally:
        db.close()

@router.get('/api/admin/factory/employees')
def admin_factory_employees(request: Request, user: CurrentUser=Depends(require_identified_user)):
    """列出工厂版超级员工身份（仅平台管理端可见；绝不进客户选人器）。

    每个工厂员工映射到底层工具的现有超级员工对话端点——管理端发消息时带
    ``context.workspace_id`` 选项目，路由侧自动铸造工厂授权并对该 Workspace 派工。
    """
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        tool_endpoint = {'Claude': '/api/admin/claude-super-employee/messages', 'Codex': '/api/admin/codex-super-employee/messages', 'Cursor': '/api/admin/cursor-super-employee/messages', 'Trae': '/api/admin/trae-super-employee/messages'}
        items = [{'id': meta.get('id'), 'display_name': meta.get('display_name'), 'display_tool': meta.get('display_tool'), 'avatar_letter': meta.get('avatar_letter'), 'summary': meta.get('summary'), 'scope': meta.get('scope'), 'endpoint': tool_endpoint.get(str(meta.get('display_tool') or ''))} for meta in _facade().assistant_ssot.factory_employees().values()]
        return {'success': True, 'employees': items}
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('admin_factory_employees')
        return _facade().JSONResponse({'success': False, 'message': '加载工厂员工失败'}, status_code=500)
    finally:
        db.close()

@router.get('/api/admin/cursor-super-employee/messages')
def cursor_super_employee_messages(request: Request, user: CurrentUser=Depends(require_identified_user), limit: int=Query(default=80, ge=1, le=200)):
    """管理端 Cursor 超级员工软件内对话记录。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = _facade().CursorSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {'success': True, 'messages': messages}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('cursor_super_employee_messages')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.post('/api/admin/cursor-super-employee/messages')
def cursor_super_employee_invoke(request: Request, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    """管理端 Cursor 超级员工软件内调用入口。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get('message') or body.get('body') or '').strip()
        raw_context = body.get('context')
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        result = _facade().CursorSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {'success': True, **result}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('cursor_super_employee_invoke')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.get('/api/admin/trae-super-employee/messages')
def trae_super_employee_messages(request: Request, user: CurrentUser=Depends(require_identified_user), limit: int=Query(default=80, ge=1, le=200)):
    """管理端 Trae 超级员工软件内对话记录。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = _facade().TraeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {'success': True, 'messages': messages}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('trae_super_employee_messages')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()

@router.post('/api/admin/trae-super-employee/messages')
def trae_super_employee_invoke(request: Request, body: dict=Body(default_factory=dict), user: CurrentUser=Depends(require_identified_user)):
    """管理端 Trae 超级员工软件内调用入口。"""
    uid = _facade()._uid(user)
    db = _facade().HostSessionLocal()
    try:
        denied = _facade()._require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get('message') or body.get('body') or '').strip()
        raw_context = body.get('context')
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        if not isinstance(body, dict):
            body = {}
        workspace_id = str((body or {}).get('workspace_id') or context.get('workspace_id') or 'xcmax')
        context = _facade().factory_context(workspace_id=workspace_id, base=context)
        result = _facade().TraeSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {'success': True, **result}
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('trae_super_employee_invoke')
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)
    finally:
        db.close()
