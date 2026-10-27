"""Existing-only identity and grants for the explicit guarded serving profile."""

from __future__ import annotations

import os

from sqlalchemy import inspect


def enabled() -> bool:
    return os.environ.get("XCAGI_OWNED_SOURCE_PROFILE") == "guarded-host-v1"


def validate_auth_schema(bind) -> None:
    """Read schema metadata, never create tables, repair columns, or seed grants."""
    from app.db.models import Permission, Role, Tenant, User, UserSession, role_permissions

    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table in (
        User.__table__,
        UserSession.__table__,
        Permission.__table__,
        Role.__table__,
        Tenant.__table__,
        role_permissions,
    ):
        if table.name not in tables or not set(table.columns.keys()).issubset(
            {column["name"] for column in inspector.get_columns(table.name)}
        ):
            raise RuntimeError("guarded authentication requires existing complete schema")


def existing_permissions(user) -> list[str]:
    """Use current durable role membership, including for platform administrators."""
    from app.application.tenant_rbac_policy import (
        TENANT_PERMISSION_CODES,
        is_tenant_role,
        role_belongs_to_user,
    )
    from app.db.models import Role, User
    from app.db.session import get_host_db

    with get_host_db() as db:
        validate_auth_schema(db.connection())
        current = db.get(User, user.id)
        if current is None or not current.is_active:
            raise RuntimeError("guarded authentication account is unavailable")
        role = db.query(Role).filter(Role.name == current.role).first()
        codes = [permission.code for permission in role.permissions] if role else []
        if is_tenant_role(current.role):
            return (
                [code for code in codes if code in TENANT_PERMISSION_CODES]
                if role_belongs_to_user(current.role, current.tenant_id)
                else []
            )
        return codes
