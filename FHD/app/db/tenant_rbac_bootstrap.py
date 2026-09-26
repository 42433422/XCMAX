"""Desktop schema compatibility for persisted tenant RBAC state."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.models.tenant import Tenant
from app.db.models.tenant_invitation import TenantInvitation


def ensure_tenant_rbac_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "tenants" not in tables:
        Base.metadata.create_all(engine, tables=[Tenant.__table__], checkfirst=True)
    elif "owner_user_id" not in {column["name"] for column in inspector.get_columns("tenants")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tenants ADD COLUMN owner_user_id INTEGER"))
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tenants_owner_user_id ON tenants (owner_user_id)"))
    Base.metadata.create_all(engine, tables=[TenantInvitation.__table__], checkfirst=True)
