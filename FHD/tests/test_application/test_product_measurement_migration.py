import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_measurement_migration_does_not_guess_customer_label_or_rewrite_units():
    path = Path(__file__).parents[2] / "alembic/versions/2026_09_09_product_measurement_unit.py"
    spec = importlib.util.spec_from_file_location("measurement_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT)")
        connection.exec_driver_sql("INSERT INTO products VALUES (1,'公司A'), (2,'桶')")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert connection.exec_driver_sql(
                "SELECT unit, measurement_unit FROM products ORDER BY id"
            ).all() == [("公司A", None), ("桶", None)]
            module.downgrade()
            assert connection.exec_driver_sql(
                "SELECT unit FROM products ORDER BY id"
            ).scalars().all() == ["公司A", "桶"]
    engine.dispose()
