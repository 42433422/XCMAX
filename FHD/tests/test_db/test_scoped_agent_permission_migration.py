"""Frozen grants are additive, scoped to built-in roles, and safe to rerun."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa

CODES = {
    "memory_v2.write",
    "tool.sales.query",
    "tool.reports.export",
    "tool.reports.sales_summary",
    "employee.list",
    "employee.execute",
    "tool.excel_analysis.read",
}


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_11_agent_permissions.py"
    spec = spec_from_file_location("scoped_agent_permission_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(connection):
    connection.execute(
        sa.text(
            "CREATE TABLE permissions (id INTEGER PRIMARY KEY, name TEXT, code TEXT UNIQUE, "
            "module TEXT, description TEXT)"
        )
    )
    connection.execute(
        sa.text("CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT UNIQUE, is_system BOOLEAN)")
    )
    connection.execute(
        sa.text(
            "CREATE TABLE role_permissions (role_id INTEGER, permission_id INTEGER, "
            "PRIMARY KEY (role_id, permission_id))"
        )
    )


def _grants(connection):
    return set(
        connection.execute(
            sa.text(
                "SELECT r.name, p.code FROM role_permissions rp "
                "JOIN roles r ON r.id=rp.role_id JOIN permissions p ON p.id=rp.permission_id"
            )
        )
    )


def test_grants_only_seven_codes_to_existing_system_roles(tmp_path, monkeypatch):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'roles.sqlite3'}")
    with engine.begin() as connection:
        _schema(connection)
        for role_id, name in enumerate(("user", "operator", "admin", "viewer", "custom"), 1):
            connection.execute(
                sa.text("INSERT INTO roles VALUES (:id, :name, :system)"),
                {"id": role_id, "name": name, "system": name != "custom"},
            )
        connection.execute(
            sa.text(
                "INSERT INTO permissions VALUES (1, 'Keep custom label', 'memory_v2.write', 'custom', 'keep')"
            )
        )
        connection.execute(sa.text("INSERT INTO role_permissions VALUES (1, 1), (4, 1), (5, 1)"))
        before = _grants(connection)
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        module.upgrade()
        module.upgrade()
        module.downgrade()
        assert _grants(connection) == before | {
            (role, code) for role in ("user", "operator", "admin") for code in CODES
        }
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == 7
        assert connection.execute(
            sa.text("SELECT name, module, description FROM permissions WHERE id=1")
        ).one() == ("Keep custom label", "custom", "keep")
    engine.dispose()


@pytest.mark.parametrize("name", ["user", "operator", "admin", "viewer", "custom"])
def test_non_system_roles_and_absent_default_roles_stay_unchanged(tmp_path, monkeypatch, name):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'custom.sqlite3'}")
    with engine.begin() as connection:
        _schema(connection)
        connection.execute(sa.text("INSERT INTO roles VALUES (1, :name, FALSE)"), {"name": name})
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        module.upgrade()
        assert _grants(connection) == set()
        assert connection.execute(sa.text("SELECT name FROM roles")).all() == [(name,)]
    engine.dispose()


@pytest.mark.parametrize("missing", ["permissions", "roles", "role_permissions"])
def test_missing_rbac_table_does_not_silently_succeed(tmp_path, monkeypatch, missing):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'missing.sqlite3'}")
    with engine.begin() as connection:
        _schema(connection)
        sa.Table(missing, sa.MetaData(), autoload_with=connection).drop(connection)
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="RBAC tables required"):
            module.upgrade()
        if missing != "permissions":
            assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == 0
    engine.dispose()


def test_revision_and_grant_scope_are_frozen():
    module = _migration()
    assert module.revision == "2026_11_11_agent_permissions"
    assert len(module.revision) <= 32
    assert module.down_revision == "2026_11_07_read_tool_permissions"
    assert {code for code, _, _ in module.PERMISSIONS} == CODES
    assert len(module.PERMISSIONS) == 7


def test_partial_grant_failure_rolls_back_the_transaction(tmp_path, monkeypatch):
    module = _migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'rollback.sqlite3'}")
    with engine.begin() as connection:
        _schema(connection)
        connection.execute(
            sa.text("INSERT INTO roles VALUES (1, 'user', TRUE), (2, 'admin', TRUE)")
        )
        connection.execute(
            sa.text(
                "CREATE TRIGGER reject_grant BEFORE INSERT ON role_permissions "
                "WHEN NEW.role_id=2 BEGIN SELECT RAISE(ABORT, 'reject grant'); END"
            )
        )
    with pytest.raises(sa.exc.IntegrityError, match="reject grant"):
        with engine.begin() as connection:
            monkeypatch.setattr(module.op, "get_bind", lambda: connection)
            module.upgrade()
    with engine.connect() as connection:
        assert _grants(connection) == set()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one() == 0
    engine.dispose()
