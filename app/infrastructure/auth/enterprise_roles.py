"""企业 RBAC 基线：admin / operator / viewer 与权限码映射。"""
from __future__ import annotations

from typing import Final

ROLE_ADMIN: Final[str] = "admin"
ROLE_OPERATOR: Final[str] = "operator"
ROLE_VIEWER: Final[str] = "viewer"

ENTERPRISE_ROLES: Final[tuple[str, ...]] = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)

# 角色 → 附加权限码（在 user.role 之上叠加）
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset({"admin.manage_users", "admin.system", "rbac.manage"}),
    ROLE_OPERATOR: frozenset(
        {"shipment.write", "inventory.write", "finance.read", "approval.submit"}
    ),
    ROLE_VIEWER: frozenset({"shipment.read", "inventory.read", "finance.read"}),
}


def normalize_enterprise_role(role: str | None) -> str:
    r = (role or ROLE_VIEWER).strip().lower()
    return r if r in ENTERPRISE_ROLES else ROLE_VIEWER


def permissions_for_role(role: str | None) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(normalize_enterprise_role(role), ROLE_PERMISSIONS[ROLE_VIEWER])


def role_has_permission(role: str | None, permission_code: str) -> bool:
    return permission_code in permissions_for_role(role)
