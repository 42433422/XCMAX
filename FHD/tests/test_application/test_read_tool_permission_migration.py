"""Withdraw blanket grants without deleting migration history or existing access."""

import importlib.util
from pathlib import Path

import pytest


def _revision():
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_07_read_tool_permissions.py"
    )
    spec = importlib.util.spec_from_file_location("withdrawn_read_grants", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_revision_keeps_chain_without_database_access(monkeypatch, direction):
    from alembic import op

    def forbidden(*args, **kwargs):
        raise AssertionError("withdrawn grants must not access the database")

    monkeypatch.setattr(op, "get_bind", forbidden)
    monkeypatch.setattr(op, "execute", forbidden)
    migration = _revision()
    assert migration.revision == "2026_11_07_read_tool_permissions"
    assert migration.down_revision == "2026_11_06_purchase_unit_version"
    getattr(migration, direction)()


def test_non_admin_roles_do_not_gain_sales_or_report_by_default():
    from app.db.models.permission import DEFAULT_ROLES

    for role in DEFAULT_ROLES:
        if role["name"] != "admin":
            assert {"sales.view", "report.view"}.isdisjoint(role["permissions"])


def test_business_roles_can_query_and_create_sales_orders():
    from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES

    codes = {item["code"] for item in DEFAULT_PERMISSIONS}
    assert {"tool.sales.query", "tool.sales.create_order"} <= codes
    for role in DEFAULT_ROLES:
        granted = set(role["permissions"])
        if role["name"] in {"user", "operator", "admin"}:
            assert {"tool.sales.query", "tool.sales.create_order"} <= granted
        else:
            assert {"tool.sales.query", "tool.sales.create_order"}.isdisjoint(granted)
