"""Existing databases gain only the intended built-in sales permission."""

import importlib.util
import logging
from pathlib import Path

import pytest
import sqlalchemy as sa


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_11_sales_create_perm.py"
    spec = importlib.util.spec_from_file_location("sales_permission_upgrade", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("custom_name", ["user", "operator", "admin", "custom"])
def test_existing_role_upgrade_is_scoped_and_idempotent(monkeypatch, custom_name):
    from alembic import op
    from app.db.models.permission import Permission, Role, role_permissions

    engine = sa.create_engine("sqlite://")
    for table in (Permission.__table__, Role.__table__, role_permissions):
        table.create(engine)
    with engine.begin() as conn:
        conn.execute(
            Role.__table__.insert(),
            [
                {"id": index, "name": name, "is_system": name != custom_name}
                for index, name in enumerate(("user", "operator", "admin", "viewer", "custom"), 1)
            ],
        )
        conn.execute(
            Permission.__table__.insert(), {"id": 1, "name": "existing", "code": "existing"}
        )
        conn.execute(role_permissions.insert(), {"role_id": 1, "permission_id": 1})
        monkeypatch.setattr(op, "get_bind", lambda: conn)
        migration = _migration()
        assert migration.down_revision == "2026_11_11_agent_permissions"
        migration.upgrade()
        migration.upgrade()
        grants = (
            conn.execute(
                sa.text(
                    "SELECT r.name FROM roles r JOIN role_permissions rp ON r.id=rp.role_id "
                    "JOIN permissions p ON p.id=rp.permission_id WHERE p.code='tool.sales.create_order'"
                )
            )
            .scalars()
            .all()
        )
        assert set(grants) == {"user", "operator", "admin"} - {custom_name}
        assert len(grants) == len({"user", "operator", "admin"} - {custom_name})
        before = conn.execute(sa.select(role_permissions)).all()
        migration.downgrade()
        assert conn.execute(sa.select(role_permissions)).all() == before
        assert (1, 1) in before
    engine.dispose()


@pytest.mark.parametrize("custom_name", ["user", "operator", "admin"])
def test_sqlite_seed_preserves_custom_grants_and_updates_system_roles(custom_name):
    from sqlalchemy.orm import Session

    from app.db.bootstrap.seeding import seed_rbac
    from app.db.models.permission import DEFAULT_ROLES, Permission, Role, role_permissions

    engine = sa.create_engine("sqlite://")
    for table in (Permission.__table__, Role.__table__, role_permissions):
        table.create(engine)
    with Session(engine) as session:
        explicit = Permission(name="Explicit", code="custom.explicit")
        session.add(Role(name=custom_name, is_system=False, permissions=[explicit]))
        session.add(Role(name="viewer", is_system=True, permissions=[explicit]))
        session.commit()
    for _ in range(2):
        seed_rbac(engine, logger=logging.getLogger(__name__))
    with Session(engine) as session:
        roles = {
            role.name: {perm.code for perm in role.permissions} for role in session.query(Role)
        }
        assert roles[custom_name] == {"custom.explicit"}
        for default in DEFAULT_ROLES:
            if default["name"] != custom_name:
                assert set(default["permissions"]) <= roles[default["name"]]
        assert "custom.explicit" in roles["viewer"]
        assert "tool.sales.create_order" not in roles["viewer"]
    engine.dispose()


def test_delivery_merge_preserves_both_upgrade_histories():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["2026_11_15_delivery_ref_merge"]
    head = scripts.get_revision(scripts.get_current_head())
    assert set(head.down_revision) == {
        "2026_11_11_delivery_merge",
        "2026_11_11_business_ref_unique",
    }
    assert scripts.get_revision("2026_11_11_business_ref_unique").down_revision == (
        "2026_11_11_agent_permissions"
    )
    merge = scripts.get_revision("2026_11_11_delivery_merge")
    assert set(merge.down_revision) == {
        "2026_11_11_sales_create_perm",
        "2026_11_11_etl_source_slice",
    }
    for parent in merge.down_revision:
        assert scripts.get_revision(parent).down_revision == "2026_11_11_agent_permissions"
