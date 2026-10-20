"""Permission catalog migration never changes roles or payment data."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa


def _migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/2026_10_20_payment_refund_permission.py"
    )
    spec = spec_from_file_location("refund_permission_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refund_catalog_seed_is_idempotent_and_never_grants(tmp_path, monkeypatch):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'catalog.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE permissions (id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, module TEXT, description TEXT)"
            )
        )
        connection.execute(
            sa.text("CREATE TABLE role_permissions (role_id INTEGER, permission_id INTEGER)")
        )
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, name, code) VALUES (1, 'Existing', 'existing.read')"
            )
        )
        connection.execute(sa.text("INSERT INTO role_permissions VALUES (7, 1)"))
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        module.upgrade()
        connection.execute(
            sa.text("UPDATE permissions SET name='Custom name' WHERE code='model_payment.refund'")
        )
        module.upgrade()
        module.downgrade()
        assert connection.execute(
            sa.text("SELECT name FROM permissions WHERE code='model_payment.refund'")
        ).all() == [("Custom name",)]
        assert connection.execute(sa.text("SELECT * FROM role_permissions")).all() == [(7, 1)]
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == 2
    engine.dispose()


def test_missing_permission_table_cannot_silently_stamp_success(tmp_path, monkeypatch):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    with engine.begin() as connection:
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="permissions table required"):
            module.upgrade()
    engine.dispose()
