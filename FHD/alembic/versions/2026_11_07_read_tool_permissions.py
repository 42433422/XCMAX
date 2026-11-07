"""AI 员工只读业务工具所需的销售/报表查看权限。

Revision ID: 2026_11_07_read_tool_permissions
Revises: 2026_11_06_purchase_unit_version
Create Date: 2026-11-07
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_11_07_read_tool_permissions"
down_revision: str | Sequence[str] | None = "2026_11_06_purchase_unit_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = ("user", "viewer", "operator", "admin")
_PERMISSIONS = (("sales.view", "查看销售订单", "sales"), ("report.view", "查看经营报表", "report"))


def upgrade() -> None:
    bind = op.get_bind()
    if not {"permissions", "roles", "role_permissions"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        return
    select_id = sa.text("SELECT id FROM permissions WHERE code = :code")
    for code, name, module in _PERMISSIONS:
        if bind.execute(select_id, {"code": code}).scalar() is None:
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (name, code, description, module, created_at) "
                    "VALUES (:name, :code, '', :module, :created_at)"
                ),
                {"name": name, "code": code, "module": module, "created_at": datetime.utcnow()},
            )
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.name IN :roles AND p.code = :code AND NOT EXISTS ("
                "SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
            ).bindparams(sa.bindparam("roles", expanding=True)),
            {"roles": list(_ROLES), "code": code},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, _, _ in _PERMISSIONS]
    expanding = sa.bindparam("codes", expanding=True)
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN :codes)"
        ).bindparams(expanding),
        {"codes": codes},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(expanding),
        {"codes": codes},
    )
