"""
权限/角色管理 API 路由 (RBAC)

提供租户角色/权限管理和租户内用户角色分配。

端点前缀：/api/rbac
租户角色仅限经过市场认证的企业管理员；平台权限定义仅限平台管理员。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.application.rbac_app_service import get_rbac_app_service
from app.errors import AppError
from app.infrastructure.auth.dependencies import get_logged_in_user, session_id_from_request
from app.schemas.rbac_schema import PermissionCreate, RoleCreate, RoleUpdate, UserRoleAssign

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rbac", tags=["rbac"])

def _require_platform_admin(request: Request):
    user = get_logged_in_user(request)
    if user.role != "admin" or user.tier != "admin" or user.tenant_id is not None:
        raise HTTPException(status_code=403, detail="仅平台管理员可管理全局权限")
    return user


def _require_rbac_manager(request: Request):
    user = get_logged_in_user(request)
    if user.role == "admin" and user.tier == "admin" and user.tenant_id is None:
        return user
    from app.application.facades.session_facade import get_auth_service
    from app.application.session_account_meta import load_session_account_meta

    meta = load_session_account_meta(session_id_from_request(request)) or {}
    verified = (
        user.role != "admin"
        and user.tenant_id is not None
        and user.market_user_id is not None
        and meta.get("market_is_enterprise") is True
        and not meta.get("market_is_admin")
        and meta.get("impersonating_market_user_id") is None
        and meta.get("market_user_id") == user.market_user_id
    )
    if not verified or not get_auth_service().has_permission(user, "tenant.manage_roles"):
        raise HTTPException(status_code=403, detail="当前企业账号无角色管理权限")
    return user


def _tenant_scope(request: Request, user) -> int | None:
    tenant_id = int(user.tenant_id) if user.tenant_id is not None else None
    if tenant_id is None and not (user.role == "admin" and user.tier == "admin"):
        raise HTTPException(status_code=403, detail="缺少企业租户范围")
    return tenant_id


def _handle_app_error(err: AppError) -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": err.message, "error_code": err.code.value},
        status_code=err.status_code,
    )


# ── 角色管理 ─────────────────────────────────────────────────────


@router.get("/tenants")
def rbac_tenants_list(_user=Depends(_require_platform_admin)):
    """列出活跃租户（平台管理员）。"""
    return {"success": True, "data": get_rbac_app_service().list_tenants()}


@router.get("/tenants/{tenant_id}/data-scopes")
def rbac_tenant_data_scopes(tenant_id: int, _user=Depends(_require_platform_admin)):
    return {"success": True, "data": get_rbac_app_service().list_data_scopes(tenant_id)}


@router.get("/roles")
def rbac_roles_list(request: Request, _user=Depends(_require_rbac_manager)):
    """列出所有角色及其权限列表。"""
    tenant_id = _tenant_scope(request, _user)
    return {"success": True, "data": get_rbac_app_service().list_roles(tenant_id=tenant_id)}


@router.get("/roles/{role_id}")
def rbac_role_get(role_id: int, request: Request, _user=Depends(_require_rbac_manager)):
    try:
        return {
            "success": True,
            "data": get_rbac_app_service().get_role(
                role_id, tenant_id=_tenant_scope(request, _user)
            ),
        }
    except AppError as exc:
        return _handle_app_error(exc)


@router.post("/roles")
def rbac_role_create(body: RoleCreate, request: Request, _user=Depends(_require_rbac_manager)):
    """创建自定义角色。"""
    try:
        data = get_rbac_app_service().create_role(
            body.name,
            body.description,
            body.permissions,
            tenant_id=_tenant_scope(request, _user),
        )
        return JSONResponse({"success": True, "data": data}, status_code=201)
    except AppError as exc:
        return _handle_app_error(exc)


@router.put("/roles/{role_id}")
def rbac_role_update(
    role_id: int, body: RoleUpdate, request: Request, _user=Depends(_require_rbac_manager)
):
    """更新角色描述和权限列表。系统角色只允许修改描述。"""
    try:
        data = get_rbac_app_service().update_role(
            role_id,
            description=body.description,
            permissions=body.permissions,
            tenant_id=_tenant_scope(request, _user),
        )
        return {"success": True, "data": data}
    except AppError as exc:
        return _handle_app_error(exc)


@router.delete("/roles/{role_id}")
def rbac_role_delete(role_id: int, request: Request, _user=Depends(_require_rbac_manager)):
    """删除自定义角色（系统角色不可删除）。"""
    try:
        get_rbac_app_service().delete_role(role_id, tenant_id=_tenant_scope(request, _user))
        return {"success": True, "message": "角色已删除"}
    except AppError as exc:
        return _handle_app_error(exc)


# ── 权限管理 ─────────────────────────────────────────────────────


@router.get("/permissions")
def rbac_permissions_list(
    request: Request,
    _user=Depends(_require_rbac_manager),
    module: str | None = Query(default=None),
):
    """列出所有权限，可按模块过滤。"""
    return {"success": True, "data": get_rbac_app_service().list_permissions(module, tenant_id=_tenant_scope(request, _user))}


@router.post("/permissions")
def rbac_permission_create(body: PermissionCreate, request: Request, _user=Depends(_require_platform_admin)):
    """创建新权限定义（扩展系统权限集）。"""
    try:
        if _tenant_scope(request, _user) is not None:
            return JSONResponse(
                {"success": False, "message": "只有平台管理端可以扩展全局权限"}, status_code=403
            )
        data = get_rbac_app_service().create_permission(
            body.code, body.name, body.description, body.module
        )
        return JSONResponse({"success": True, "data": data}, status_code=201)
    except AppError as exc:
        return _handle_app_error(exc)


@router.delete("/permissions/{perm_id}")
def rbac_permission_delete(perm_id: int, request: Request, _user=Depends(_require_platform_admin)):
    """删除权限（同时从所有角色中解除绑定）。"""
    try:
        if _tenant_scope(request, _user) is not None:
            return JSONResponse(
                {"success": False, "message": "只有平台管理端可以删除全局权限"}, status_code=403
            )
        get_rbac_app_service().delete_permission(perm_id)
        return {"success": True, "message": "权限已删除"}
    except AppError as exc:
        return _handle_app_error(exc)


# ── 用户-角色 ────────────────────────────────────────────────────


@router.get("/users")
def rbac_users_list(request: Request, _user=Depends(_require_rbac_manager)):
    return {
        "success": True,
        "data": get_rbac_app_service().list_users(tenant_id=_tenant_scope(request, _user)),
    }


@router.get("/users/{user_id}/permissions")
def rbac_user_permissions(user_id: int, request: Request, _user=Depends(_require_rbac_manager)):
    """查询指定用户的有效权限（通过 role 字段解析）。"""
    try:
        return {
            "success": True,
            "data": get_rbac_app_service().get_user_permissions(
                user_id, tenant_id=_tenant_scope(request, _user)
            ),
        }
    except AppError as exc:
        return _handle_app_error(exc)


@router.put("/users/{user_id}/role")
def rbac_user_assign_role(
    user_id: int, body: UserRoleAssign, request: Request, _user=Depends(_require_rbac_manager)
):
    """将用户分配到指定角色（修改 User.role 字段）。"""
    try:
        data = get_rbac_app_service().assign_user_role(
            user_id, body.role, tenant_id=_tenant_scope(request, _user)
        )
        return {"success": True, "data": data}
    except AppError as exc:
        return _handle_app_error(exc)


# ── 权限种子补全 ─────────────────────────────────────────────────


@router.post("/seed-missing-permissions")
def rbac_seed_permissions(request: Request, _user=Depends(_require_platform_admin)):
    """补全缺失的系统权限定义（幂等；仅新增不覆盖）。"""
    if _tenant_scope(request, _user) is not None:
        return JSONResponse(
            {"success": False, "message": "只有平台管理端可以补全全局权限"}, status_code=403
        )
    added = get_rbac_app_service().seed_missing_permissions()
    return {"success": True, "added": added, "message": f"新增 {len(added)} 条权限定义"}


@router.post("/invitations")
def rbac_invite_member(
    request: Request, body: dict = Body(default_factory=dict), _user=Depends(_require_rbac_manager)
):
    """Issue a one-use code to a named market account; only the owner may invite."""
    from app.application.tenant_rbac_app_service import (
        TenantIdentityError,
        create_tenant_invitation,
    )

    tenant_id = _tenant_scope(request, _user)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="平台账号不能从租户入口邀请成员")
    try:
        data = create_tenant_invitation(
            inviter_user_id=int(_user.id), tenant_id=tenant_id,
            target_username=str(body.get("target_username") or ""),
        )
        return JSONResponse({"success": True, "data": data}, status_code=201)
    except TenantIdentityError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
