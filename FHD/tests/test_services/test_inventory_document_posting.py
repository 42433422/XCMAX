"""Document replay is unique; fulfillment and legacy movement history are not."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db.models import InventoryLedger, InventoryTransaction, SalesOrderItem, Warehouse
from app.domain.shared_services.inventory_service import InventoryService
from tests.test_services.test_erp_schema_migration import _alembic_config
from tests.test_services.test_erp_schema_migration import _db_url as _db_url
from tests.test_services.test_fulfillment_service import _seed_order
from tests.test_services.test_fulfillment_service import env as env


@pytest.mark.parametrize("split", ["warehouse", "item", "batch", "partial"])
def test_legitimate_order_movements_are_not_document_replays(env, split):
    order, item, product, warehouse = _seed_order(env)
    inv = InventoryService()
    second_warehouse, second_item, batch = warehouse.id, item.id, None
    with env["test_db"]() as db:
        if split == "warehouse":
            extra = Warehouse(code="WH-SECOND", name="Second", status="active")
            db.add(extra)
            db.flush()
            second_warehouse = extra.id
        if split == "item":
            extra_item = SalesOrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                quantity=10,
                amount=0,
            )
            db.add(extra_item)
            db.flush()
            second_item = extra_item.id
    if split in {"warehouse", "batch"}:
        batch = "B-SECOND" if split == "batch" else None
        assert inv.inventory_in(product.id, second_warehouse, 100, batch_no=batch)["success"]
    assert inv.deduct_for_order(
        product.id, warehouse.id, 3, sales_order_id=order.id, sales_order_item_id=item.id
    )["success"]
    assert inv.deduct_for_order(
        product.id,
        second_warehouse,
        4,
        sales_order_id=order.id,
        sales_order_item_id=second_item,
        batch_no=batch,
    )["success"]
    with env["test_db"]() as db:
        moves = db.query(InventoryTransaction).filter_by(transaction_type="out").all()
        assert len(moves) == 2
        assert all(not move.document_posting for move in moves)
        initial = 200 if split in {"warehouse", "batch"} else 100
        assert sum(row.quantity for row in db.query(InventoryLedger)) == initial - 7


def test_real_document_replay_does_not_deduct_and_database_rejects_duplicate(env):
    order, _item, product, warehouse = _seed_order(env)
    inv = InventoryService()
    args = {
        "product_id": product.id,
        "warehouse_id": warehouse.id,
        "quantity": 5,
        "reference_type": "document",
        "reference_id": order.id,
    }
    assert inv.inventory_out(**args)["success"]
    replay = inv.inventory_out(**args)
    assert replay["success"] and replay["data"]["already_posted"]
    with env["test_db"]() as db:
        posted = db.query(InventoryTransaction).filter_by(document_posting=True).one()
        values = {
            c.name: getattr(posted, c.name) for c in posted.__table__.columns if c.name != "id"
        }
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(InventoryTransaction(**values))
            db.flush()
        assert db.query(InventoryTransaction).filter_by(document_posting=True).count() == 1
        assert db.query(InventoryLedger).one().quantity == 95


@pytest.mark.parametrize(
    "old_head", ["2026_11_11_business_ref_unique", "2026_11_11_delivery_merge"]
)
@pytest.mark.parametrize("draft_index", [False, True])
def test_upgrade_preserves_legacy_rows_and_repairs_draft_index(_db_url, old_head, draft_index):
    config = _alembic_config()
    command.upgrade(config, old_head)
    engine = sa.create_engine(_db_url)
    with engine.begin() as conn:
        # Old revisions bootstrap today's metadata on fresh DBs: remove future-only
        # schema here to model a real already-stamped pre-upgrade database.
        conn.exec_driver_sql("DROP INDEX IF EXISTS uq_inventory_out_business_ref")
        if "document_posting" in {
            c["name"] for c in sa.inspect(conn).get_columns("inventory_transactions")
        }:
            conn.exec_driver_sql("ALTER TABLE inventory_transactions DROP COLUMN document_posting")
        conn.exec_driver_sql(
            "INSERT INTO products (id,name,unit,is_active,tenant_id) VALUES (700,'kept','item',1,1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO warehouses (id,code,name,status,tenant_id) VALUES (700,'kept','kept','active',1)"
        )
        insert = "INSERT INTO inventory_transactions (id,tenant_id,product_id,warehouse_id,transaction_type,quantity,reference_type,reference_id,transaction_date) VALUES (?,1,700,700,'out',-3,'legacy',700,'2026-11-11')"
        for identifier in range(1, 2 if draft_index else 3):
            conn.exec_driver_sql(insert, (identifier,))
        if draft_index:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_inventory_out_business_ref ON inventory_transactions (tenant_id,product_id,transaction_type,reference_type,reference_id) WHERE transaction_type='out' AND reference_type IS NOT NULL AND reference_id IS NOT NULL"
            )
        before = conn.exec_driver_sql(
            "SELECT id,quantity,reference_type,reference_id FROM inventory_transactions ORDER BY id"
        ).all()
    command.upgrade(config, "2026_11_15_stock_posting_key")
    with engine.begin() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT id,quantity,reference_type,reference_id FROM inventory_transactions ORDER BY id"
            ).all()
            == before
        )
        assert (
            conn.exec_driver_sql(
                "SELECT count(*) FROM inventory_transactions WHERE document_posting"
            ).scalar_one()
            == 0
        )
        # Legitimate historical duplicates remain untouched; new claims are unique.
        claimed = "INSERT INTO inventory_transactions (tenant_id,product_id,warehouse_id,transaction_type,quantity,reference_type,reference_id,transaction_date,document_posting) VALUES (1,700,700,'out',-1,'document',701,'2026-11-15',1)"
        conn.exec_driver_sql(claimed)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.exec_driver_sql(claimed)
        predicate = next(
            i
            for i in sa.inspect(conn).get_indexes("inventory_transactions")
            if i["name"] == "uq_inventory_out_business_ref"
        )
        assert "document_posting" in str(predicate["dialect_options"]["sqlite_where"])
    command.downgrade(config, "2026_11_15_delivery_ref_merge")
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT id,quantity,reference_type,reference_id FROM inventory_transactions WHERE reference_type='legacy' ORDER BY id"
            ).all()
            == before
        )
    engine.dispose()
