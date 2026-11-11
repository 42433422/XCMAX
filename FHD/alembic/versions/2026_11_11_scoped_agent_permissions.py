"""Upgrade the seven declared agent grants for existing built-in roles only."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_scoped_agent_perms"
down_revision = "2026_11_07_read_tool_permissions"
branch_labels = None
depends_on = None

# Freeze this migration's scope; later default changes must not expand upgrades.
PERMISSIONS = (
    ("memory_v2.write", "管理本人记忆", "memory"),
    ("tool.sales.query", "查询销售订单", "sales"),
    ("tool.reports.export", "导出报表", "reports"),
    ("tool.reports.sales_summary", "查询销售汇总", "reports"),
    ("employee.list", "查看员工", "employee"),
    ("employee.execute", "执行员工任务", "employee"),
    ("tool.excel_analysis.read", "读取表格", "reports"),
)


def upgrade():
    bind = op.get_bind()
    if not {"permissions", "roles", "role_permissions"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        raise RuntimeError("RBAC tables required before scoped agent permission migration")
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
                "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = :code "
                "WHERE r.is_system = TRUE AND r.name IN ('user', 'operator', 'admin') "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
                "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
            ),
            {"code": code},
        )


def downgrade():
    # Do not revoke grants that may predate this revision or be explicitly owned.
    pass
