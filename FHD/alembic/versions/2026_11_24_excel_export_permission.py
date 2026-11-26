"""为内置普通业务角色补齐 Excel 导出权限。"""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_excel_export"
down_revision = "2026_11_21_enterprise_cognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    code = "tool.excel_analysis.export"
    bind.execute(
        sa.text(
            "INSERT INTO permissions (name, code, module, description) "
            "SELECT :name, CAST(:code AS VARCHAR), 'reports', '' "
            "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = CAST(:code AS VARCHAR))"
        ),
        {"name": "导出 Excel 表格", "code": code},
    )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            "WHERE r.is_system = TRUE AND r.name = 'user' AND p.code = :code "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        ),
        {"code": code},
    )


def downgrade() -> None:
    # 无法区分迁移授予与管理员显式授予，保留既有绑定。
    pass
