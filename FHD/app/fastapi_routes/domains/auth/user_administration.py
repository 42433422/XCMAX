"""Host user administration behind the existing admin.manage_users dependency."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi.responses import JSONResponse

from app.db.models.user import User
from app.http.error_codes import (
    CREATE_FAILED,
    INVALID_INPUT,
    INVALID_ROLE,
    MISSING_PASSWORD,
    NOT_FOUND,
    SELF_DELETE,
    UPDATE_FAILED,
    WEAK_PASSWORD,
    error_envelope,
)

from app.domain.auth.ports import (
    JsonObject,
    PasswordBackend,
    RouteResult,
    UserDirectory,
)


@dataclass(frozen=True)
class UserAdministration:
    directory: Callable[[], UserDirectory]
    backend: Callable[[], PasswordBackend]

    def list(self, include_inactive: str, _user: User) -> RouteResult:
        user_service = self.directory()
        users = user_service.list_users(skip=0, limit=100)
        if include_inactive.lower() != "true":
            users = [u for u in users if u.get("is_active", True)]
        return {"success": True, "data": {"users": users, "count": len(users)}}

    def get(self, user_id: int, _user: User) -> RouteResult:
        user_service = self.directory()
        user = user_service.get_user(user_id)
        if not user:
            return JSONResponse(error_envelope(NOT_FOUND, "用户不存在"), status_code=404)
        return {"success": True, "data": {"user": user}}

    def create(self, body: JsonObject, _user: User) -> RouteResult:
        username = (body.get("username") or "").strip()
        password = body.get("password", "")
        if not username or not password:
            return JSONResponse(
                error_envelope(INVALID_INPUT, "用户名和密码不能为空"), status_code=400
            )
        if len(password) < 6:
            return JSONResponse(error_envelope(WEAK_PASSWORD, "密码至少6个字符"), status_code=400)
        role = body.get("role", "viewer")
        if role not in ["viewer", "operator", "admin"]:
            return JSONResponse(error_envelope(INVALID_ROLE, "无效的角色"), status_code=400)
        user_service = self.directory()
        result = user_service.create_user(
            username=username,
            password=password,
            display_name=body.get("display_name", ""),
            email=body.get("email", ""),
            role=role,
        )
        if not result["success"]:
            return JSONResponse(
                error_envelope(
                    CREATE_FAILED, str(result.get("error") or result.get("message") or "创建失败")
                ),
                status_code=400,
            )
        return JSONResponse({"success": True, "data": {"user": result["user"]}}, status_code=201)

    def update(self, user_id: int, body: JsonObject, _user: User) -> RouteResult:
        role = body.get("role")
        if role and role not in ["viewer", "operator", "admin"]:
            return JSONResponse(error_envelope(INVALID_ROLE, "无效的角色"), status_code=400)
        user_service = self.directory()
        result = user_service.update_user(
            user_id=user_id,
            display_name=body.get("display_name"),
            email=body.get("email"),
            role=role,
            is_active=body.get("is_active"),
        )
        if not result["success"]:
            return JSONResponse(
                error_envelope(
                    UPDATE_FAILED, str(result.get("error") or result.get("message") or "更新失败")
                ),
                status_code=400,
            )
        return {"success": True, "data": {"user": result["user"]}}

    def delete(self, user_id: int, user: User) -> RouteResult:
        if user.id == user_id:
            return JSONResponse(error_envelope(SELF_DELETE, "不能删除自己"), status_code=400)
        user_service = self.directory()
        result = user_service.delete_user(user_id)
        if not result.get("success"):
            return JSONResponse(result, status_code=400)
        return result

    def reset_password(self, user_id: int, body: JsonObject, _user: User) -> RouteResult:
        new_password = body.get("new_password", "")
        if not new_password:
            return JSONResponse(error_envelope(MISSING_PASSWORD, "新密码不能为空"), status_code=400)
        if len(new_password) < 6:
            return JSONResponse(error_envelope(WEAK_PASSWORD, "密码至少6个字符"), status_code=400)
        auth_app_service = self.backend()
        result = auth_app_service.reset_password(user_id, new_password)
        if not result["success"]:
            return JSONResponse(result, status_code=400)
        return result
