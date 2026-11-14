"""Grant sales creation to built-in business roles on existing installations."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_sales_create_perm"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None

# Freeze this revision's catalog: later application defaults must not change it.
PERMISSIONS = (("tool.sales.create_order", "创建销售订单", "sales"),)


def upgrade():
    bind = op.get_bind()
    if not {"permissions", "roles", "role_permissions"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        raise RuntimeError("RBAC tables required before agent permission migration")
    for code, name, module in PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (name, code, module, description) "
                "SELECT :name, :code, :module, '' "
                "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = :code)"
            ),
            {"name": name, "code": code, "module": module},
        )
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                "WHERE r.is_system = TRUE AND r.name IN ('user', 'operator', 'admin') "
                "AND p.code = :code AND NOT EXISTS "
                "(SELECT 1 FROM role_permissions rp "
                "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
            ),
            {"code": code},
        )


def downgrade():
    # Later explicit grants have no provenance distinguishing them from defaults.
    # Keep the catalog and assignments instead of revoking legitimate access.
    pass
