"""RBAC application service — routes must not access ORM directly."""

from __future__ import annotations

from typing import Any

from app.db.models import DataScope, Permission, Role, Tenant, User
from app.db.session import get_db
from app.errors import AppError, ErrorCode


class RbacApplicationService:
    def list_tenants(self) -> list[dict[str, Any]]:
        with get_db() as db:
            rows = db.query(Tenant).filter(Tenant.is_active.is_(True)).order_by(Tenant.code).all()
            return [{"id": t.id, "code": t.code, "name": t.name} for t in rows]

    def list_data_scopes(self, tenant_id: int) -> list[dict[str, Any]]:
        with get_db() as db:
            rows = (
                db.query(DataScope)
                .filter(DataScope.tenant_id == tenant_id)
                .order_by(DataScope.resource_type)
                .all()
            )
            return [
                {
                    "id": s.id,
                    "tenant_id": s.tenant_id,
                    "resource_type": s.resource_type,
                    "scope_json": s.scope_json,
                }
                for s in rows
            ]

    def list_roles(self, tenant_id: int | None = None) -> list[dict[str, Any]]:
        with get_db() as db:
            q = db.query(Role)
            if tenant_id is not None:
                q = q.filter((Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)))
            roles = q.order_by(Role.name).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "tenant_id": r.tenant_id,
                    "description": r.description,
                    "is_system": r.is_system,
                    "permissions": [p.code for p in r.permissions],
                }
                for r in roles
            ]

    def get_role(self, role_id: int) -> dict[str, Any]:
        with get_db() as db:
            role = db.query(Role).filter(Role.id == role_id).first()
            if not role:
                raise AppError(ErrorCode.VALIDATION_ERROR, "角色不存在", status_code=404)
            return {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "is_system": role.is_system,
                "permissions": [
                    {"id": p.id, "code": p.code, "name": p.name, "module": p.module}
                    for p in role.permissions
                ],
            }

    def create_role(
        self,
        name: str,
        description: str = "",
        permissions: list[str] | None = None,
        tenant_id: int | None = None,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "角色名不能为空", status_code=400)
        with get_db() as db:
            dup_q = db.query(Role).filter(Role.name == name)
            if tenant_id is None:
                dup_q = dup_q.filter(Role.tenant_id.is_(None))
            else:
                dup_q = dup_q.filter(Role.tenant_id == tenant_id)
            if dup_q.first():
                raise AppError(ErrorCode.VALIDATION_ERROR, "角色名已存在", status_code=409)
            role = Role(name=name, description=description, is_system=False, tenant_id=tenant_id)
            if permissions:
                perms = db.query(Permission).filter(Permission.code.in_(permissions)).all()
                role.permissions = perms
            db.add(role)
            db.commit()
            db.refresh(role)
            return {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [p.code for p in role.permissions],
            }

    def update_role(
        self,
        role_id: int,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            role = db.query(Role).filter(Role.id == role_id).first()
            if not role:
                raise AppError(ErrorCode.VALIDATION_ERROR, "角色不存在", status_code=404)
            if description is not None:
                role.description = description
            if permissions is not None:
                if role.is_system:
                    raise AppError(
                        ErrorCode.AUTH_PERMISSION_DENIED, "系统角色权限不允许修改", status_code=403
                    )
                perms = db.query(Permission).filter(Permission.code.in_(permissions)).all()
                role.permissions = perms
            db.commit()
            db.refresh(role)
            return {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [p.code for p in role.permissions],
            }

    def delete_role(self, role_id: int) -> None:
        with get_db() as db:
            role = db.query(Role).filter(Role.id == role_id).first()
            if not role:
                raise AppError(ErrorCode.VALIDATION_ERROR, "角色不存在", status_code=404)
            if role.is_system:
                raise AppError(
                    ErrorCode.AUTH_PERMISSION_DENIED, "系统内置角色不允许删除", status_code=403
                )
            users_with_role = db.query(User).filter(User.role == role.name).count()
            if users_with_role:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"角色正在使用中（{users_with_role} 名用户），无法删除",
                    status_code=409,
                )
            db.delete(role)
            db.commit()

    def list_permissions(self, module: str | None = None) -> list[dict[str, Any]]:
        with get_db() as db:
            q = db.query(Permission)
            if module:
                q = q.filter(Permission.module == module)
            perms = q.order_by(Permission.module, Permission.code).all()
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "code": p.code,
                    "description": p.description,
                    "module": p.module,
                }
                for p in perms
            ]

    def create_permission(
        self, code: str, name: str, description: str = "", module: str = "custom"
    ) -> dict[str, Any]:
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "code 和 name 不能为空", status_code=400)
        with get_db() as db:
            if db.query(Permission).filter(Permission.code == code).first():
                raise AppError(ErrorCode.VALIDATION_ERROR, "权限 code 已存在", status_code=409)
            perm = Permission(name=name, code=code, description=description, module=module)
            db.add(perm)
            db.commit()
            db.refresh(perm)
            return {"id": perm.id, "name": perm.name, "code": perm.code}

    def delete_permission(self, perm_id: int) -> None:
        with get_db() as db:
            perm = db.query(Permission).filter(Permission.id == perm_id).first()
            if not perm:
                raise AppError(ErrorCode.VALIDATION_ERROR, "权限不存在", status_code=404)
            db.delete(perm)
            db.commit()

    def get_user_permissions(self, user_id: int) -> dict[str, Any]:
        with get_db() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise AppError(ErrorCode.VALIDATION_ERROR, "用户不存在", status_code=404)
            from app.application.auth_app_service import get_auth_app_service

            perms = get_auth_app_service().get_user_permissions(user)
            return {
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "permissions": perms,
            }

    def assign_user_role(self, user_id: int, role_name: str) -> dict[str, Any]:
        role_name = role_name.strip()
        if not role_name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "role 不能为空", status_code=400)
        with get_db() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise AppError(ErrorCode.VALIDATION_ERROR, "用户不存在", status_code=404)
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                raise AppError(ErrorCode.VALIDATION_ERROR, "角色不存在", status_code=404)
            user.role = role.name
            db.commit()
            return {"user_id": user.id, "username": user.username, "role": user.role}

    def seed_missing_permissions(self) -> list[str]:
        new_perms = [
            {"name": "查看库存", "code": "inventory.view", "module": "inventory"},
            {"name": "编辑库存", "code": "inventory.edit", "module": "inventory"},
            {"name": "库存入库", "code": "inventory.in", "module": "inventory"},
            {"name": "库存出库", "code": "inventory.out", "module": "inventory"},
            {"name": "查看采购", "code": "purchase.view", "module": "purchase"},
            {"name": "创建采购订单", "code": "purchase.create", "module": "purchase"},
            {"name": "审批采购订单", "code": "purchase.approve", "module": "purchase"},
            {"name": "管理供应商", "code": "purchase.suppliers", "module": "purchase"},
            {"name": "查看财务", "code": "finance.view", "module": "finance"},
            {"name": "编辑财务凭证", "code": "finance.edit", "module": "finance"},
            {"name": "查看报表", "code": "report.view", "module": "report"},
            {"name": "导出报表", "code": "report.export", "module": "report"},
        ]
        added: list[str] = []
        with get_db() as db:
            for pd in new_perms:
                if not db.query(Permission).filter(Permission.code == pd["code"]).first():
                    db.add(
                        Permission(
                            name=pd["name"],
                            code=pd["code"],
                            module=pd["module"],
                            description="",
                        )
                    )
                    added.append(pd["code"])
            db.commit()
        return added


def get_rbac_app_service() -> RbacApplicationService:
    from app.di.registry import get_service_registry

    return get_service_registry().rbac_application_service


def reset_rbac_app_service() -> None:
    """Test teardown — drop cached RBAC service on registry reset."""
    pass
