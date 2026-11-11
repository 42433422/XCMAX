"""Existing system roles receive scoped agent defaults without rewriting custom RBAC."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa


def migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_11_agent_permissions.py"
    spec = spec_from_file_location("agent_permissions_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_is_idempotent_and_preserves_custom_roles_and_grants(tmp_path, monkeypatch):
    module = migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'roles.sqlite3'}")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE permissions (id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, module TEXT, description TEXT)",
            "CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT UNIQUE, is_system BOOLEAN)",
            "CREATE TABLE role_permissions (role_id INTEGER, permission_id INTEGER, PRIMARY KEY (role_id, permission_id))",
            "INSERT INTO roles VALUES (1, 'user', TRUE), (2, 'operator', TRUE), (3, 'admin', TRUE), (4, 'viewer', TRUE), (5, 'custom', FALSE)",
            "INSERT INTO permissions VALUES (11, 'Custom memory name', 'memory_v2.write', 'memory', 'keep'), (12, 'Custom access', 'custom.access', 'custom', 'keep')",
            "INSERT INTO role_permissions VALUES (1, 11), (4, 12), (5, 12)",
        ):
            connection.execute(sa.text(statement))
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        module.upgrade()
        module.upgrade()
        module.downgrade()
        permissions = connection.execute(sa.text("SELECT code FROM permissions")).scalars().all()
        expected = {
            "memory_v2.write",
            "tool.sales.query",
            "tool.reports.export",
            "tool.reports.sales_summary",
            "employee.list",
            "employee.execute",
            "tool.excel_analysis.read",
        }
        assert set(permissions) == expected | {"custom.access"}
        assignments = connection.execute(
            sa.text(
                "SELECT role_id, code FROM role_permissions JOIN permissions ON permission_id = id"
            )
        ).all()
        assert set(assignments) == {(role, code) for role in (1, 2, 3) for code in expected} | {
            (4, "custom.access"),
            (5, "custom.access"),
        }
        assert connection.execute(
            sa.text("SELECT name, description FROM permissions WHERE code='memory_v2.write'")
        ).one() == ("Custom memory name", "keep")
        # A deployment may intentionally replace a standard role with a custom role.
        connection.execute(sa.text("DELETE FROM role_permissions WHERE role_id=2"))
        connection.execute(sa.text("UPDATE roles SET is_system=FALSE WHERE id=2"))
        module.upgrade()
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM role_permissions WHERE role_id=2")
            ).scalar_one()
            == 0
        )
    engine.dispose()


def test_missing_rbac_tables_cannot_be_stamped_as_migrated(tmp_path, monkeypatch):
    module = migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    with engine.begin() as connection:
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="RBAC tables required"):
            module.upgrade()
    engine.dispose()
