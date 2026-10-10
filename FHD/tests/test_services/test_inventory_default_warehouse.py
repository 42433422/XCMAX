"""仓库初始化：新装 / 旧版升级后没有仓库时的幂等、按租户隔离的默认仓库。"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Warehouse
from app.infrastructure.tenant_scope import tenant_scope
from app.services.inventory_default_warehouse import (
    DEFAULT_WAREHOUSE_NAME,
    default_warehouse_code,
    ensure_default_warehouse,
    warehouse_setup_status,
)


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'wh.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _all_warehouses(factory):
    with factory() as db:
        rows = db.execute(
            Warehouse.__table__.select(), execution_options={"skip_tenant_filter": True}
        ).all()
        return [dict(r._mapping) for r in rows]


def test_creates_one_default_warehouse_for_the_tenant_and_is_idempotent(factory):
    with factory.begin() as db:
        assert warehouse_setup_status(db, 7) == {"initialized": False, "active_warehouses": 0}
        first, created = ensure_default_warehouse(db, 7)
        assert created is True
        assert (first.code, first.name, first.status, first.tenant_id) == (
            default_warehouse_code(7),
            DEFAULT_WAREHOUSE_NAME,
            "active",
            7,
        )
    with factory.begin() as db:
        again, created_again = ensure_default_warehouse(db, 7)
        assert created_again is False and again.code == default_warehouse_code(7)
        assert warehouse_setup_status(db, 7) == {"initialized": True, "active_warehouses": 1}
    assert len(_all_warehouses(factory)) == 1


def test_other_tenants_warehouses_are_neither_reused_nor_changed(factory):
    with tenant_scope(2), factory.begin() as db:
        db.add(Warehouse(code="MAIN-2", name="二号租户主仓", status="active"))
    with factory.begin() as db:
        warehouse, created = ensure_default_warehouse(db, 1)
        assert created is True and warehouse.tenant_id == 1
    rows = {r["code"]: r for r in _all_warehouses(factory)}
    assert rows["MAIN-2"]["tenant_id"] == 2 and rows["MAIN-2"]["status"] == "active"
    assert rows[default_warehouse_code(1)]["tenant_id"] == 1


def test_existing_active_warehouse_is_kept_without_creating_a_default(factory):
    with tenant_scope(3), factory.begin() as db:
        db.add(Warehouse(code="OWN-3", name="自建仓", status="active"))
    with factory.begin() as db:
        warehouse, created = ensure_default_warehouse(db, 3)
        assert created is False and warehouse.code == "OWN-3"
    assert [r["code"] for r in _all_warehouses(factory)] == ["OWN-3"]


def test_soft_deleted_default_is_reactivated_instead_of_violating_unique_code(factory):
    with factory.begin() as db:
        ensure_default_warehouse(db, 4)
    with tenant_scope(4), factory.begin() as db:
        db.query(Warehouse).update({"status": "deleted"})
    with factory.begin() as db:
        warehouse, created = ensure_default_warehouse(db, 4)
        assert created is True and warehouse.status == "active"
    assert len(_all_warehouses(factory)) == 1


def test_code_collision_with_another_tenant_gets_a_unique_code(factory):
    with tenant_scope(9), factory.begin() as db:
        db.add(Warehouse(code=default_warehouse_code(5), name="别家", status="deleted"))
    with factory.begin() as db:
        warehouse, created = ensure_default_warehouse(db, 5)
        assert created is True and warehouse.tenant_id == 5
        assert warehouse.code.startswith(default_warehouse_code(5) + "-")
    rows = {r["code"]: r for r in _all_warehouses(factory)}
    assert rows[default_warehouse_code(5)]["tenant_id"] == 9
    assert rows[default_warehouse_code(5)]["status"] == "deleted"


def test_missing_tenant_is_rejected(factory):
    with factory() as db, pytest.raises(ValueError):
        ensure_default_warehouse(db, None)


# ── HTTP：/api/inventory/setup/warehouse ─────────────────────────────


@pytest.fixture
def setup_client(factory, monkeypatch):
    from app.fastapi_routes import inventory as inventory_routes
    from app.infrastructure.auth import dependencies

    @contextmanager
    def business_session():
        with factory() as db:
            yield db
            db.commit()

    monkeypatch.setattr("app.db.session.get_db", business_session)
    state = {"user": None, "allowed": True}
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: state["user"])
    monkeypatch.setattr("app.mod_sdk.product_skus.resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: state["allowed"]),
    )
    app = FastAPI()
    app.include_router(inventory_routes.router)
    return TestClient(app, raise_server_exceptions=False), state


def test_setup_route_requires_login_tenant_and_permission(setup_client, factory):
    client, state = setup_client
    assert client.post("/api/inventory/setup/warehouse").status_code == 401
    state["user"] = SimpleNamespace(id=1, tenant_id=None, is_active=True)
    assert client.post("/api/inventory/setup/warehouse").status_code == 403
    state["user"] = SimpleNamespace(id=1, tenant_id=12, is_active=True)
    state["allowed"] = False
    assert client.post("/api/inventory/setup/warehouse").status_code == 403
    assert _all_warehouses(factory) == []


def test_setup_route_initializes_only_the_session_tenant(setup_client, factory):
    client, state = setup_client
    state["user"] = SimpleNamespace(id=1, tenant_id=12, is_active=True)
    status = client.get("/api/inventory/setup/warehouse")
    assert status.status_code == 200 and status.json()["data"]["initialized"] is False
    # 伪造的 tenant_id 请求体 / 头不能改变初始化目标
    created = client.post(
        "/api/inventory/setup/warehouse", json={"tenant_id": 99}, headers={"X-Tenant-ID": "99"}
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["data"]["created"] is True and body["data"]["name"] == DEFAULT_WAREHOUSE_NAME
    again = client.post("/api/inventory/setup/warehouse").json()
    assert again["data"]["created"] is False
    assert [(r["code"], r["tenant_id"]) for r in _all_warehouses(factory)] == [
        (default_warehouse_code(12), 12)
    ]
    assert client.get("/api/inventory/setup/warehouse").json()["data"]["initialized"] is True
