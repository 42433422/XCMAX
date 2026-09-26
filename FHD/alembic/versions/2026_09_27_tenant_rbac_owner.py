"""Persist tenant ownership and one-use market identity invitations."""

import sqlalchemy as sa
from alembic import op

revision = "2026_09_27_tenant_rbac_owner"
down_revision = "2026_09_08_agent_approval"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "owner_user_id" not in {item["name"] for item in inspector.get_columns("tenants")}:
        op.add_column("tenants", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_tenants_owner_user_id", "tenants", ["owner_user_id"], if_not_exists=True)
    if not inspector.has_table("tenant_invitations"):
        op.create_table(
            "tenant_invitations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("inviter_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("target_username", sa.String(128), nullable=False),
            sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("accepted_market_user_id", sa.Integer(), nullable=True),
        )
    op.create_index("ix_tenant_invitations_tenant_id", "tenant_invitations", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_tenant_invitations_token_sha256", "tenant_invitations", ["token_sha256"], if_not_exists=True)
    op.execute(
        "INSERT INTO permissions (name, code, description, module) "
        "SELECT '管理本企业角色', 'tenant.manage_roles', '', 'tenant' "
        "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'tenant.manage_roles')"
    )


def downgrade():
    op.drop_index("ix_tenant_invitations_token_sha256", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_tenant_id", table_name="tenant_invitations")
    op.drop_table("tenant_invitations")
    op.drop_index("ix_tenants_owner_user_id", table_name="tenants")
    op.drop_column("tenants", "owner_user_id")
