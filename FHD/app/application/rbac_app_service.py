"""RBAC 应用服务 — 角色/权限管理。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.errors import DatabaseError, ErrorCode
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RbacAppService:
    def __init__(self, *, db_factory: Callable[[], Any] | None = None) -> None:
        self._db_factory = db_factory

    def list_tenants(self) -> list[dict[str, Any]]:
        factory = self._db_factory or get_db
        try:
            with factory() as db:
                rows = (
                    db.query(Tenant)
                    .filter(Tenant.is_active.is_(True))
                    .order_by(Tenant.name.asc(), Tenant.id.asc())
                    .all()
                )
                return [
                    {
                        "id": int(row.id),
                        "tenant_id": str(row.id),
                        "code": str(row.code or ""),
                        "name": str(row.name or row.code or f"企业 {row.id}"),
                        "is_active": bool(row.is_active),
                        "plan_id": str(row.plan_id or ""),
                    }
                    for row in rows
                ]
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Tenant directory unavailable: %s", exc)
            raise DatabaseError(
                ErrorCode.DB_QUERY_FAILED,
                "企业目录暂时不可用",
                detail={"reason": type(exc).__name__},
            ) from exc

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
