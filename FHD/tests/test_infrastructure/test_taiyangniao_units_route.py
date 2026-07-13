from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.attendance_reference_data import attendance_unit_names
from app.fastapi_routes.domains.product import compat_routes


def test_host_attendance_units_merge_private_db_and_host_data(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "taiyangniao_pro.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE attendance_departments (department TEXT, main_department TEXT)")
        conn.execute("INSERT INTO attendance_departments VALUES ('研发部', '总部')")
        conn.execute("CREATE TABLE attendance_employees (department TEXT)")
        conn.execute("INSERT INTO attendance_employees VALUES ('生产部')")
    monkeypatch.setattr(
        "app.application.attendance_reference_data.resolve_mod_private_sqlite_path",
        lambda _name: db_path,
    )

    assert attendance_unit_names(
        {"success": True, "data": [{"name": "销售部"}, {"unit_name": "生产部"}]}
    ) == ["总部", "生产部", "研发部", "销售部"]


def test_shipment_units_route_returns_real_attendance_departments(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "taiyangniao.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE attendance_departments (department TEXT, main_department TEXT)")
        conn.execute("INSERT INTO attendance_departments VALUES ('研发部', '总部')")
        conn.execute("CREATE TABLE attendance_employees (department TEXT, main_department TEXT)")
        conn.execute("INSERT INTO attendance_employees VALUES ('生产部', '工厂')")

    monkeypatch.setattr(
        "app.application.attendance_reference_data.resolve_mod_private_sqlite_path",
        lambda _name: db_path,
    )
    monkeypatch.setattr(
        compat_routes,
        "_products_units_for_select",
        lambda: {"success": True, "data": [{"name": "销售部"}]},
    )

    app = FastAPI()
    app.include_router(compat_routes.router, prefix="/api")
    response = TestClient(app).get("/api/mod/taiyangniao-pro/shipment/shipment-records/units")

    assert response.status_code == 200
    assert response.json()["units"] == ["工厂", "总部", "生产部", "研发部", "销售部"]
