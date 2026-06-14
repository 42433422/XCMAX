"""RBAC 应用服务 — 角色/权限管理。"""

from __future__ import annotations

from typing import Any


class RbacAppService:
    def list_tenants(self) -> list[dict[str, Any]]:
        return []

    def list_data_scopes(self, tenant_id: str | None) -> list[dict[str, Any]]:
        return []

    def list_roles(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return []

    def get_role(self, role_id: int) -> dict[str, Any]:
        return {"id": role_id}

    def create_role(
        self,
        name: str,
        description: str | None,
        permissions: list[str],
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return {"name": name, "description": description, "permissions": permissions}

    def update_role(
        self,
        role_id: int,
        *,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        return {"id": role_id, "description": description, "permissions": permissions}

    def delete_role(self, role_id: int) -> None:
        return None

    def list_permissions(self, module: str | None = None) -> list[dict[str, Any]]:
        return []

    def create_permission(
        self,
        code: str,
        name: str,
        description: str | None,
        module: str | None,
    ) -> dict[str, Any]:
        return {"code": code, "name": name, "description": description, "module": module}

    def delete_permission(self, perm_id: int) -> None:
        return None

    def get_user_permissions(self, user_id: int) -> list[str]:
        return []

    def assign_user_role(self, user_id: int, role: str) -> dict[str, Any]:
        return {"user_id": user_id, "role": role}

    def seed_missing_permissions(self) -> list[str]:
        return []


_service: RbacAppService | None = None


def get_rbac_app_service() -> RbacAppService:
    global _service
    if _service is None:
        _service = RbacAppService()
    return _service
