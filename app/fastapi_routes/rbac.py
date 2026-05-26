"""
权限/角色管理 API 路由 (RBAC)

提供角色和权限的 CRUD、用户-角色分配，以及权限定义的扩展。
现有用户 CRUD 保留在 legacy_auth.py (/api/users)。

端点前缀：/api/rbac
需要：admin.manage_users 权限（管理员专用）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.legacy_helpers import _require_login_user, _require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rbac", tags=["rbac"])


# ── 角色管理 ─────────────────────────────────────────────────────


@router.get("/roles")
def rbac_roles_list(request: Request):
    """列出所有角色及其权限列表。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Role
    from app.db.session import get_db

    with get_db() as db:
        roles = db.query(Role).order_by(Role.name).all()
        return {
            "success": True,
            "data": [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "is_system": r.is_system,
                    "permissions": [p.code for p in r.permissions],
                }
                for r in roles
            ],
        }


@router.get("/roles/{role_id}")
def rbac_role_get(request: Request, role_id: int):
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Role
    from app.db.session import get_db

    with get_db() as db:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return JSONResponse({"success": False, "message": "角色不存在"}, status_code=404)
        return {
            "success": True,
            "data": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "is_system": role.is_system,
                "permissions": [
                    {"id": p.id, "code": p.code, "name": p.name, "module": p.module}
                    for p in role.permissions
                ],
            },
        }


@router.post("/roles")
def rbac_role_create(request: Request, body: dict = Body(default_factory=dict)):
    """创建自定义角色。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission, Role
    from app.db.session import get_db

    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"success": False, "message": "角色名不能为空"}, status_code=400)

    with get_db() as db:
        if db.query(Role).filter(Role.name == name).first():
            return JSONResponse({"success": False, "message": "角色名已存在"}, status_code=409)

        role = Role(
            name=name,
            description=body.get("description", ""),
            is_system=False,
        )
        perm_codes = body.get("permissions", [])
        if perm_codes:
            perms = db.query(Permission).filter(Permission.code.in_(perm_codes)).all()
            role.permissions = perms

        db.add(role)
        db.commit()
        db.refresh(role)
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "permissions": [p.code for p in role.permissions],
                },
            },
            status_code=201,
        )


@router.put("/roles/{role_id}")
def rbac_role_update(request: Request, role_id: int, body: dict = Body(default_factory=dict)):
    """更新角色描述和权限列表。系统角色只允许修改描述。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission, Role
    from app.db.session import get_db

    with get_db() as db:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return JSONResponse({"success": False, "message": "角色不存在"}, status_code=404)

        if "description" in body:
            role.description = body["description"]

        if "permissions" in body and not role.is_system:
            perm_codes = body["permissions"]
            perms = db.query(Permission).filter(Permission.code.in_(perm_codes)).all()
            role.permissions = perms
        elif "permissions" in body and role.is_system:
            return JSONResponse(
                {"success": False, "message": "系统角色权限不允许修改"}, status_code=403
            )

        db.commit()
        db.refresh(role)
        return {
            "success": True,
            "data": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [p.code for p in role.permissions],
            },
        }


@router.delete("/roles/{role_id}")
def rbac_role_delete(request: Request, role_id: int):
    """删除自定义角色（系统角色不可删除）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Role, User
    from app.db.session import get_db

    with get_db() as db:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            return JSONResponse({"success": False, "message": "角色不存在"}, status_code=404)
        if role.is_system:
            return JSONResponse({"success": False, "message": "系统内置角色不允许删除"}, status_code=403)

        users_with_role = db.query(User).filter(User.role == role.name).count()
        if users_with_role:
            return JSONResponse(
                {"success": False, "message": f"角色正在使用中（{users_with_role} 名用户），无法删除"},
                status_code=409,
            )

        db.delete(role)
        db.commit()
        return {"success": True, "message": "角色已删除"}


# ── 权限管理 ─────────────────────────────────────────────────────


@router.get("/permissions")
def rbac_permissions_list(
    request: Request, module: str | None = Query(default=None)
):
    """列出所有权限，可按模块过滤。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(Permission)
        if module:
            q = q.filter(Permission.module == module)
        perms = q.order_by(Permission.module, Permission.code).all()
        return {
            "success": True,
            "data": [
                {"id": p.id, "name": p.name, "code": p.code, "description": p.description, "module": p.module}
                for p in perms
            ],
        }


@router.post("/permissions")
def rbac_permission_create(request: Request, body: dict = Body(default_factory=dict)):
    """创建新权限定义（扩展系统权限集）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission
    from app.db.session import get_db

    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        return JSONResponse({"success": False, "message": "code 和 name 不能为空"}, status_code=400)

    with get_db() as db:
        if db.query(Permission).filter(Permission.code == code).first():
            return JSONResponse({"success": False, "message": "权限 code 已存在"}, status_code=409)
        perm = Permission(
            name=name,
            code=code,
            description=body.get("description", ""),
            module=body.get("module", "custom"),
        )
        db.add(perm)
        db.commit()
        db.refresh(perm)
        return JSONResponse(
            {"success": True, "data": {"id": perm.id, "name": perm.name, "code": perm.code}},
            status_code=201,
        )


@router.delete("/permissions/{perm_id}")
def rbac_permission_delete(request: Request, perm_id: int):
    """删除权限（同时从所有角色中解除绑定）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission
    from app.db.session import get_db

    with get_db() as db:
        perm = db.query(Permission).filter(Permission.id == perm_id).first()
        if not perm:
            return JSONResponse({"success": False, "message": "权限不存在"}, status_code=404)
        db.delete(perm)
        db.commit()
        return {"success": True, "message": "权限已删除"}


# ── 用户-角色 ────────────────────────────────────────────────────


@router.get("/users/{user_id}/permissions")
def rbac_user_permissions(request: Request, user_id: int):
    """查询指定用户的有效权限（通过 role 字段解析）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import User
    from app.db.session import get_db

    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"success": False, "message": "用户不存在"}, status_code=404)
        from app.application.auth_app_service import get_auth_app_service

        perms = get_auth_app_service().get_user_permissions(user)
        return {
            "success": True,
            "data": {
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "permissions": perms,
            },
        }


@router.put("/users/{user_id}/role")
def rbac_user_assign_role(
    request: Request, user_id: int, body: dict = Body(default_factory=dict)
):
    """将用户分配到指定角色（修改 User.role 字段）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Role, User
    from app.db.session import get_db

    role_name = (body.get("role") or "").strip()
    if not role_name:
        return JSONResponse({"success": False, "message": "role 不能为空"}, status_code=400)

    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"success": False, "message": "用户不存在"}, status_code=404)

        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            return JSONResponse({"success": False, "message": "角色不存在"}, status_code=404)

        user.role = role.name
        db.commit()
        return {
            "success": True,
            "data": {"user_id": user.id, "username": user.username, "role": user.role},
        }


# ── 权限种子补全 ─────────────────────────────────────────────────


@router.post("/seed-missing-permissions")
def rbac_seed_permissions(request: Request):
    """补全缺失的系统权限定义（幂等；仅新增不覆盖）。"""
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.db.models import Permission
    from app.db.session import get_db

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

    added = []
    with get_db() as db:
        for pd in new_perms:
            if not db.query(Permission).filter(Permission.code == pd["code"]).first():
                perm = Permission(
                    name=pd["name"], code=pd["code"], module=pd["module"], description=""
                )
                db.add(perm)
                added.append(pd["code"])
        db.commit()

    return {"success": True, "added": added, "message": f"新增 {len(added)} 条权限定义"}
