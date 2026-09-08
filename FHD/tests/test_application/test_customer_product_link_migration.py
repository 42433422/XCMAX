import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_link_migration_preserves_legacy_units_and_enforces_references():
    path = Path(__file__).parents[2] / "alembic/versions/2026_09_09_customer_product_links.py"
    spec = importlib.util.spec_from_file_location("link_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT)")
        connection.exec_driver_sql("CREATE TABLE purchase_units (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO products VALUES (1, '公司A')")
        connection.exec_driver_sql("INSERT INTO purchase_units VALUES (1)")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            connection.exec_driver_sql(
                "INSERT INTO customer_product_links (tenant_id,purchase_unit_id,product_id) VALUES (1,1,1)"
            )
            for values in ["(1,1,1)", "(1,1,999)", "(NULL,1,1)"]:
                with pytest.raises(sa.exc.IntegrityError):
                    with connection.begin_nested():
                        connection.exec_driver_sql(
                            "INSERT INTO customer_product_links (tenant_id,purchase_unit_id,product_id) VALUES "
                            + values
                        )
            assert connection.exec_driver_sql("SELECT unit FROM products").scalar_one() == "公司A"
            module.downgrade()
            assert "customer_product_links" not in sa.inspect(connection).get_table_names()
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM products").scalar_one() == 1
    engine.dispose()
