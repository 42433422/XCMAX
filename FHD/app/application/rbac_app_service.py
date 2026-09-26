"""持久化角色权限操作；自定义角色按租户命名空间隔离。"""

from __future__ import annotations

import re
from typing import Any, NoReturn, cast

from sqlalchemy import select

from app.application.tenant_rbac_policy import TENANT_PERMISSION_CODES, owner_permission_for_user, role_belongs_to_user
from app.db.models.permission import DEFAULT_PERMISSIONS, Permission, Role
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.db.session import get_host_db
from app.errors import AppError, ErrorCode

_TENANT_ROLE = re.compile(r"^tenant:(\d+):(.*)$", re.DOTALL)


def _fail(message: str, status: int = 400) -> NoReturn:
    raise AppError(ErrorCode.VALIDATION_ERROR, message, status_code=status)


def _role_key(name: str, tenant_id: int | None) -> str:
    display_name = str(name or "").strip()
    if not display_name or len(display_name) > 64 or any(ord(ch) < 32 for ch in display_name):
        _fail("角色名称须为 1–64 个可见字符")
    return f"tenant:{tenant_id}:{display_name}" if tenant_id is not None else display_name


def _tenant_role(role: Role, tenant_id: int | None) -> bool:
    match = _TENANT_ROLE.match(role.name or "")
    return tenant_id is None or bool(match and int(match.group(1)) == tenant_id)


def _role_data(role: Role) -> dict[str, Any]:
    match = _TENANT_ROLE.match(role.name or "")
    return {
        "id": role.id,
        "key": role.name,
        "name": match.group(2) if match else role.name,
        "description": role.description or "",
        "is_system": bool(role.is_system),
        "permissions": [
            {
                "id": permission.id,
                "code": permission.code,
                "name": permission.name,
                "description": permission.description or "",
                "module": permission.module or "",
            }
            for permission in sorted(role.permissions, key=lambda item: item.code)
        ],
    }


def _visible_role(db, role_id: int, tenant_id: int | None) -> Role:
    role = cast(Role | None, db.query(Role).filter(Role.id == role_id).first())
    if role is None or not _tenant_role(role, tenant_id):
        _fail("角色不存在", 404)
    return role


def _resolve_permissions(db, codes: list[str] | None, tenant_id: int | None = None) -> list[Permission]:
    requested = sorted({str(code).strip() for code in (codes or []) if str(code).strip()})
    if not requested:
        return []
    if tenant_id is not None and not set(requested).issubset(TENANT_PERMISSION_CODES):
        _fail("租户角色不能包含平台级权限", 403)
    found = cast(
        list[Permission], db.query(Permission).filter(Permission.code.in_(requested)).all()
    )
    if {item.code for item in found} != set(requested):
        _fail("权限列表包含未知权限")
    return found


def _revoke_role_sessions(role_name: str) -> int:
    with get_host_db() as db:
        user_ids = select(User.id).where(User.role == role_name)
        result = (
            db.query(UserSession)
            .filter(UserSession.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        return int(result or 0)


class RbacAppService:
    """将 RBAC 路由请求持久化到与认证服务相同的角色、权限和用户表。"""

    def list_tenants(self) -> list[dict[str, Any]]:
        return []

    def list_data_scopes(self, tenant_id: int | None) -> list[dict[str, Any]]:
        return []

    def list_roles(self, tenant_id: int | None = None) -> list[dict[str, Any]]:
        with get_host_db() as db:
            query = db.query(Role)
            if tenant_id is not None:
                query = query.filter(Role.name.like(f"tenant:{tenant_id}:%"))
            return [_role_data(role) for role in query.order_by(Role.name).all() if _tenant_role(role, tenant_id)]

    def get_role(self, role_id: int, *, tenant_id: int | None = None) -> dict[str, Any]:
        with get_host_db() as db:
            return _role_data(_visible_role(db, role_id, tenant_id))

    def create_role(
        self,
        name: str,
        description: str | None,
        permissions: list[str],
        *,
        tenant_id: int | None = None,
    ) -> dict[str, Any]:
        key = _role_key(name, tenant_id)
        with get_host_db() as db:
            if db.query(Role.id).filter(Role.name == key).first():
                _fail("该租户已存在同名角色", 409)
            role = Role(name=key, description=str(description or "").strip(), is_system=False)
            role.permissions = _resolve_permissions(db, permissions, tenant_id)
            db.add(role)
            db.flush()
            return _role_data(role)

    def update_role(
        self,
        role_id: int,
        *,
        description: str | None = None,
        permissions: list[str] | None = None,
        tenant_id: int | None = None,
    ) -> dict[str, Any]:
        revoke_sessions = permissions is not None
        with get_host_db() as db:
            role = _visible_role(db, role_id, tenant_id)
            if role.is_system and tenant_id is not None:
                _fail("系统角色只能由平台管理端修改", 403)
            if description is not None:
                role.description = description.strip()
            if permissions is not None:
                if role.is_system:
                    _fail("系统角色的权限不可修改", 409)
                role.permissions = _resolve_permissions(db, permissions, tenant_id)
            role_name = role.name
            db.flush()
            data = _role_data(role)
        sessions_revoked = _revoke_role_sessions(role_name) if revoke_sessions else 0
        return {**data, "sessions_revoked": sessions_revoked}

    def delete_role(self, role_id: int, *, tenant_id: int | None = None) -> None:
        with get_host_db() as db:
            role = _visible_role(db, role_id, tenant_id)
            if role.is_system:
                _fail("系统角色不可删除", 409)
            with get_host_db() as host_db:
                assigned = host_db.query(User.id).filter(User.role == role.name).first()
            if assigned:
                _fail("角色仍分配给用户，不能删除", 409)
            db.delete(role)

    def list_permissions(self, module: str | None = None, *, tenant_id: int | None = None) -> list[dict[str, Any]]:
        with get_host_db() as db:
            query = db.query(Permission)
            if module:
                query = query.filter(Permission.module == module)
            if tenant_id is not None:
                query = query.filter(Permission.code.in_(TENANT_PERMISSION_CODES))
            return [
                {
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "description": item.description or "",
                    "module": item.module or "",
                }
                for item in query.order_by(Permission.module, Permission.code).all()
            ]

    def create_permission(
        self, code: str, name: str, description: str | None, module: str | None
    ) -> dict[str, Any]:
        code, name = code.strip(), name.strip()
        if not code or not name:
            _fail("权限编码和名称不能为空")
        with get_host_db() as db:
            if db.query(Permission.id).filter(Permission.code == code).first():
                _fail("权限编码已存在", 409)
            item = Permission(
                code=code, name=name, description=description or "", module=module or ""
            )
            db.add(item)
            db.flush()
            return {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "description": item.description or "",
                "module": item.module or "",
            }

    def delete_permission(self, perm_id: int) -> None:
        with get_host_db() as db:
            item = db.query(Permission).filter(Permission.id == perm_id).first()
            if item is None:
                _fail("权限不存在", 404)
            if item.roles:
                _fail("权限仍分配给角色，不能删除", 409)
            db.delete(item)

    def list_users(self, tenant_id: int | None = None) -> list[dict[str, Any]]:
        with get_host_db() as db:
            query = db.query(User)
            if tenant_id is not None:
                query = query.filter(User.tenant_id == tenant_id)
            return [
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name or "",
                    "role": user.role,
                    "is_active": bool(user.is_active),
                }
                for user in query.order_by(User.id).all()
            ]

    def get_user_permissions(self, user_id: int, *, tenant_id: int | None = None) -> list[str]:
        with get_host_db() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if user is None or (tenant_id is not None and user.tenant_id != tenant_id):
                _fail("用户不存在", 404)
            role_name = user.role
            if role_name == "admin" and user.tier == "admin" and user.tenant_id is None:
                return [code for (code,) in db.query(Permission.code).all()]
            role = db.query(Role).filter(Role.name == role_name).first()
            codes = [permission.code for permission in role.permissions] if role else []
            if _TENANT_ROLE.match(role_name):
                codes = [code for code in codes if code in TENANT_PERMISSION_CODES] if role_belongs_to_user(role_name, user.tenant_id) else []
            if owner_permission_for_user(user) and "tenant.manage_roles" not in codes:
                codes.append("tenant.manage_roles")
            return codes

    def assign_user_role(
        self, user_id: int, role: str, *, tenant_id: int | None = None
    ) -> dict[str, Any]:
        user_role = role.strip()
        with get_host_db() as db:
            role_obj = db.query(Role).filter(Role.name == user_role).first()
            if role_obj is None or not _tenant_role(role_obj, tenant_id):
                _fail("角色不存在", 404)
            if tenant_id is not None and role_obj.name == "admin":
                _fail("租户管理员不能分配平台管理员角色", 403)
            role_data = _role_data(role_obj)
        with get_host_db() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if user is None or (tenant_id is not None and user.tenant_id != tenant_id):
                _fail("用户不存在", 404)
            current_role = user.role
            if current_role != user_role:
                user.role = user_role
                revoked = int(
                    db.query(UserSession)
                    .filter(UserSession.user_id == user.id)
                    .delete(synchronize_session=False)
                    or 0
                )
            else:
                revoked = 0
            user_id = user.id
        return {
            "user_id": user_id,
            "role": user_role,
            "display_role": role_data["name"],
            "sessions_revoked": revoked,
        }

    def seed_missing_permissions(self) -> list[str]:
        added: list[str] = []
        with get_host_db() as db:
            present = {code for (code,) in db.query(Permission.code).all()}
            for seed in DEFAULT_PERMISSIONS:
                if seed["code"] in present:
                    continue
                db.add(Permission(**seed))
                added.append(seed["code"])
            db.flush()
        return added


_service: RbacAppService | None = None


def get_rbac_app_service() -> RbacAppService:
    global _service
    if _service is None:
        _service = RbacAppService()
    return _service
