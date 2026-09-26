"""Tenant role capabilities are a deliberately small subset of host permissions."""

from __future__ import annotations

from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_host_db

# These API families enforce the authenticated user id on every resource and
# tenant scope on writes. Other legacy business permissions are not grantable
# until their route-level authorization has the same guarantee.
TENANT_PERMISSION_CODES = frozenset(
    {
        "tenant.manage_roles",
        "etl.read",
        "etl.template.manage",
        "etl.execute",
        "etl.rollback",
        "etl.target.manage",
    }
)


def is_tenant_role(role_name: str) -> bool:
    return str(role_name or "").startswith("tenant:")


def role_belongs_to_user(role_name: str, tenant_id: int | None) -> bool:
    if not is_tenant_role(role_name):
        return True
    parts = role_name.split(":", 2)
    return len(parts) == 3 and tenant_id is not None and parts[1] == str(tenant_id)


def owner_permission_for_user(user: User) -> bool:
    if not getattr(user, "tenant_id", None) or not getattr(user, "market_user_id", None):
        return False
    with get_host_db() as db:
        return (
            db.query(Tenant.id)
            .filter(Tenant.id == int(user.tenant_id), Tenant.owner_user_id == int(user.id))
            .first()
            is not None
        )
