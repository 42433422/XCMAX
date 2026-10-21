"""Register the scoped refund action without granting it to any role."""

import sqlalchemy as sa

from alembic import op

revision = "2026_10_20_refund_permission"
down_revision = "2026_10_20_receipt_identity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("permissions"):
        raise RuntimeError("permissions table required before refund permission migration")
    bind.execute(
        sa.text(
            "INSERT INTO permissions (name, code, module, description) "
            "SELECT :name, :code, :module, :description "
            "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = :code)"
        ),
        {
            "name": "退款本人所属订单",
            "code": "model_payment.refund",
            "module": "payment",
            "description": "仅对本人且创建时租户一致的订单执行退款",
        },
    )


def downgrade():
    # Keep catalog metadata; deleting it could erase later explicit role grants.
    pass
