"""One customer name per tenant, so a lost idempotency claim cannot insert twice."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_purchase_unit_name"
down_revision = "2026_11_11_etl_source_slice"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchase_units"):
        return
    names = {item["name"] for item in inspector.get_unique_constraints("purchase_units")}
    if "uq_purchase_units_tenant_name" in names:
        return
    duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM purchase_units GROUP BY tenant_id, unit_name HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        return
    with op.batch_alter_table("purchase_units") as batch:
        batch.create_unique_constraint("uq_purchase_units_tenant_name", ["tenant_id", "unit_name"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchase_units"):
        return
    names = {item["name"] for item in inspector.get_unique_constraints("purchase_units")}
    if "uq_purchase_units_tenant_name" not in names:
        return
    with op.batch_alter_table("purchase_units") as batch:
        batch.drop_constraint("uq_purchase_units_tenant_name", type_="unique")
