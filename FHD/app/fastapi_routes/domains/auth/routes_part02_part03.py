"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


@_facade().router.delete("/api/users/{user_id}")
def users_delete(user_id: int, user=_facade().Depends(_facade()._require_admin)):
    if user.id == user_id:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().SELF_DELETE, "不能删除自己"), status_code=400
        )
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    result = user_service.delete_user(user_id)
    if not result.get("success"):
        return _facade().JSONResponse(result, status_code=400)
    return result
