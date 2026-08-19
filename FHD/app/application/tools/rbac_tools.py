"""RBAC（角色/权限）工具执行器。

直连 ``RbacAppService``，覆盖：
- ``create_role``：创建角色
- ``update_role``：更新角色描述/权限
- ``delete_role``：删除角色
- ``assign_role``：把用户分配到指定角色（按 role name）
- ``list_roles``：列出所有角色
- ``list_permissions``：列出所有权限定义
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _get_service():
    """获取 RbacAppService 单例。"""
    from app.application.rbac_app_service import get_rbac_app_service

    return get_rbac_app_service()


def create_role(args: dict[str, Any]) -> dict[str, Any]:
    """创建角色。

    Required args:
        name: 角色名称
        permissions: 权限 code 列表（如 ["admin.manage_users", "report.view"]）

    Optional args:
        description: 角色描述
        confirm: 写操作二次确认（默认 False）
    """
    name = str(args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    permissions = args.get("permissions") or []
    if not isinstance(permissions, list):
        return {"success": False, "error": "permissions must be a list"}
    permissions = [str(p).strip() for p in permissions if str(p).strip()]

    description = args.get("description")
    if description is not None:
        description = str(description)

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"创建角色 {name} 为写操作，请显式传 confirm=true 再调用",
            "name": name,
            "permissions": permissions,
        }

    try:
        svc = _get_service()
        data = svc.create_role(name, description, permissions)
        return {
            "success": True,
            "message": f"角色 {name} 已创建",
            "data": data,
            "name": name,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("create_role 失败: %s", e)
        return {"success": False, "error": str(e), "name": name}


def update_role(args: dict[str, Any]) -> dict[str, Any]:
    """更新角色描述/权限。

    Required args:
        role_id: 角色 ID

    Optional args:
        name: 当前 RbacAppService.update_role 不支持改名，仅作日志展示
        description: 新描述
        permissions: 新权限 code 列表
        confirm: 写操作二次确认（默认 False）
    """
    try:
        role_id = int(args.get("role_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "role_id is required and must be int"}

    description = args.get("description")
    if description is not None:
        description = str(description)

    permissions = args.get("permissions")
    if permissions is not None:
        if not isinstance(permissions, list):
            return {"success": False, "error": "permissions must be a list"}
        permissions = [str(p).strip() for p in permissions if str(p).strip()]

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"更新角色 {role_id} 为写操作，请显式传 confirm=true 再调用",
            "role_id": role_id,
            "preview": {
                "description": description,
                "permissions": permissions,
            },
        }

    try:
        svc = _get_service()
        data = svc.update_role(role_id, description=description, permissions=permissions)
        return {
            "success": True,
            "message": f"角色 {role_id} 已更新",
            "data": data,
            "role_id": role_id,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("update_role 失败: %s", e)
        return {"success": False, "error": str(e), "role_id": role_id}


def delete_role(args: dict[str, Any]) -> dict[str, Any]:
    """删除角色（系统角色不可删除）。

    Required args:
        role_id: 角色 ID

    Optional args:
        confirm: 高危操作二次确认（默认 False）
    """
    try:
        role_id = int(args.get("role_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "role_id is required and must be int"}

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"删除角色 {role_id} 为高危操作，请显式传 confirm=true 再调用",
            "role_id": role_id,
        }

    try:
        svc = _get_service()
        svc.delete_role(role_id)
        return {
            "success": True,
            "message": f"角色 {role_id} 已删除",
            "role_id": role_id,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("delete_role 失败: %s", e)
        return {"success": False, "error": str(e), "role_id": role_id}


def assign_role(args: dict[str, Any]) -> dict[str, Any]:
    """将用户分配到指定角色（按 role name 修改 User.role 字段）。

    Required args:
        user_id: 用户 ID
        role: 角色名称（与 UserRoleAssign schema 一致）

    Optional args:
        confirm: 写操作二次确认（默认 False）
    """
    try:
        user_id = int(args.get("user_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "user_id is required and must be int"}

    role = str(args.get("role") or args.get("role_name") or "").strip()
    if not role:
        return {"success": False, "error": "role is required"}

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"分配角色 {role} 给用户 {user_id} 为写操作，请显式传 confirm=true 再调用",
            "user_id": user_id,
            "role": role,
        }

    try:
        svc = _get_service()
        data = svc.assign_user_role(user_id, role)
        return {
            "success": True,
            "message": f"用户 {user_id} 已分配到角色 {role}",
            "data": data,
            "user_id": user_id,
            "role": role,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("assign_role 失败: %s", e)
        return {"success": False, "error": str(e), "user_id": user_id, "role": role}


def list_roles(args: dict[str, Any]) -> dict[str, Any]:
    """列出所有角色及其权限列表。

    Optional args:
        tenant_id: 租户 ID（可选）
    """
    tenant_id = args.get("tenant_id")
    if tenant_id is not None:
        tenant_id = str(tenant_id)

    try:
        svc = _get_service()
        data = svc.list_roles(tenant_id=tenant_id)
        return {
            "success": True,
            "data": data,
            "count": len(data) if isinstance(data, list) else 0,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("list_roles 失败: %s", e)
        return {"success": False, "error": str(e), "data": []}


def list_permissions(args: dict[str, Any]) -> dict[str, Any]:
    """列出所有权限定义，可按 module 过滤。

    Optional args:
        module: 模块名过滤
    """
    module = args.get("module")
    if module is not None:
        module = str(module).strip() or None

    try:
        svc = _get_service()
        data = svc.list_permissions(module)
        return {
            "success": True,
            "data": data,
            "count": len(data) if isinstance(data, list) else 0,
            "filter_module": module,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("list_permissions 失败: %s", e)
        return {"success": False, "error": str(e), "data": []}


__all__ = [
    "create_role",
    "update_role",
    "delete_role",
    "assign_role",
    "list_roles",
    "list_permissions",
]
