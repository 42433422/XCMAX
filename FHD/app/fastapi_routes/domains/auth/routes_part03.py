# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.domains.auth.routes')

@_facade().router.post('/api/users/{user_id}/reset-password')
def users_reset_password(user_id: int, body: dict=_facade().Body(default_factory=dict), _user=_facade().Depends(_facade()._require_admin)):
    from app.application.auth_app_service import get_auth_app_service
    new_password = body.get('new_password', '')
    if not new_password:
        return _facade().JSONResponse(_facade().error_envelope(_facade().MISSING_PASSWORD, '新密码不能为空'), status_code=400)
    if len(new_password) < 6:
        return _facade().JSONResponse(_facade().error_envelope(_facade().WEAK_PASSWORD, '密码至少6个字符'), status_code=400)
    auth_app_service = get_auth_app_service()
    result = auth_app_service.reset_password(user_id, new_password)
    if not result['success']:
        return _facade().JSONResponse(result, status_code=400)
    return result
