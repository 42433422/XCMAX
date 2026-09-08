"""API bridge to shipped ETL workers and SQL, using isolated generated business data."""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call
from app.application.etl.adviser import EtlRowAdviser
from app.application.etl.service import EtlService
from app.db.base import Base
from app.db.models.etl import EtlUpload  # registers the ETL tables
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.user import User
from app.db.session import get_db_dependency
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_aiopen_api_artifacts import export_app as export_app
from tests.test_application.test_aiopen_api_execution import application as application
from tests.test_application.test_aiopen_api_execution import caller
from tests.test_application.test_aiopen_api_execution import host as host


@pytest.fixture
def etl_app(export_app, application, host, monkeypatch, tmp_path):
    from app.fastapi_routes import etl

    app, content = export_app
    _, factories = application
    factory = factories["host-business"]
    for scoped_factory in factories.values():
        engine = scoped_factory.kw["bind"]
        Base.metadata.create_all(
            engine,
            tables=[
                table
                for name, table in Base.metadata.tables.items()
                if name.startswith("etl_")
                or name in {"products", "shipment_records", "sales_orders"}
            ],
        )
    with host.begin() as db:
        for owner in (3, 4, 5):
            db.get(User, owner).role = "admin"
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    from app.request_active_mod_ctx import get_request_active_mod_id

    selected_factory = lambda: factories[get_request_active_mod_id() or "host-business"]
    monkeypatch.setattr("app.application.etl.service.SessionLocal", lambda: selected_factory()())
    monkeypatch.setattr(
        "app.application.etl.service_uploads.get_app_data_dir", lambda: str(tmp_path / "etl-data")
    )
    service = EtlService(adviser=EtlRowAdviser())
    monkeypatch.setattr(etl, "get_etl_service", lambda: service)
    monkeypatch.setitem(AIOPEN_STATE["whitelist"], "/api/etl", True)

    def database():
        with selected_factory()() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db_dependency] = database
    app.include_router(etl.router)
    with ThreadPoolExecutor(max_workers=2) as pool:
        monkeypatch.setattr("app.application.etl.service_preview.EXECUTOR", pool)
        monkeypatch.setattr("app.application.etl.service_execution.EXECUTOR", pool)
        yield app, content, factory
    app.dependency_overrides.clear()


def call(app, path, **args):
    result = _tool_api_call(app, {"path": path, **args})
    assert result["success"], result
    return result["data"]["data"]


def await_run(app, run_id, target):
    deadline = time.monotonic() + 15
    while True:
        data = call(app, f"/api/etl/runs/{run_id}")
        if data["status"] == target:
            return data
        assert data["status"] in {"queued", "previewing", "executing"}, data
        assert time.monotonic() < deadline, data
        time.sleep(0.05)


def test_owned_export_upload_preview_execute_deduplicate_and_rollback(etl_app):
    app, content, factory = etl_app
    with caller({"X-Session-ID": "login-3"}):
        export = _tool_api_call(app, {"path": "/api/test/export"})
        artifact = export["artifacts"][0]
        upload = call(
            app,
            "/api/etl/uploads",
            method="POST",
            form={"relative_path": "样例/客户.xlsx"},
            files=[{"field": "file", "artifact_id": artifact["artifact_id"]}],
        )
        with tenant_scope(7), factory() as db:
            row = db.get(EtlUpload, upload["upload_id"])
            assert row.owner_user_id == 3 and row.tenant_id == 7
            assert row.relative_path == "样例/客户.xlsx"
            assert Path(row.storage_path).read_bytes() == content
            assert db.query(PurchaseUnit).count() == 1
        preview = call(
            app,
            "/api/etl/runs/preview",
            method="POST",
            body={"upload_id": upload["upload_id"], "target_type": "customers"},
        )
        run_id = preview["id"]
        preview = await_run(app, run_id, "preview_ready")
        assert preview["summary"]["new"] == 200 and preview["summary"]["error"] == 0, preview
        with tenant_scope(7), factory() as db:
            assert db.query(PurchaseUnit).count() == 1
        denied = _tool_api_call(
            app,
            {
                "path": f"/api/etl/runs/{run_id}/execute",
                "method": "POST",
                "body": {"confirmed": False},
            },
        )
        assert not denied["success"]
    for login in ("login-4", "login-5"):
        with caller({"X-Session-ID": login}):
            assert not _tool_api_call(app, {"path": f"/api/etl/runs/{run_id}"})["success"]
            assert not _tool_api_call(
                app,
                {
                    "path": f"/api/etl/runs/{run_id}/execute",
                    "method": "POST",
                    "body": {"confirmed": True},
                },
            )["success"]
    with caller({"X-Session-ID": "login-3"}):
        call(app, f"/api/etl/runs/{run_id}/execute", method="POST", body={"confirmed": True})
        completed = await_run(app, run_id, "completed")
        assert completed["summary"]["executed"] == 200, completed
        customers = _tool_api_call(app, {"path": "/api/customers/list?per_page=500"})
        assert customers["success"] and len(customers["data"]["data"]) == 201, customers
        duplicate = call(
            app,
            "/api/etl/runs/preview",
            method="POST",
            body={"upload_id": upload["upload_id"], "target_type": "customers"},
        )
        duplicate = await_run(app, duplicate["id"], "preview_ready")
        assert duplicate["summary"]["new"] == 0 and duplicate["summary"]["skip"] == 200, duplicate
        call(
            app, f"/api/etl/runs/{duplicate['id']}/execute", method="POST", body={"confirmed": True}
        )
        await_run(app, duplicate["id"], "completed")
        with tenant_scope(7), factory() as db:
            assert db.query(PurchaseUnit).count() == 201
        rollback = call(app, f"/api/etl/runs/{run_id}/rollback", method="POST")
        assert rollback["rollback_status"] == "completed", rollback
        customers = _tool_api_call(app, {"path": "/api/customers/list"})
        assert len(customers["data"]["data"]) == 1
    with tenant_scope(8), factory() as db:
        assert db.query(PurchaseUnit).count() == 1
        assert db.get(PurchaseUnit, 8).unit_name == "host-business-8"
