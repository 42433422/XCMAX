"""Functional authorization checks for mounted Windows knowledge and ETL routes."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import dataset_access
from app.fastapi_routes.excel_extract import router as excel_router
from app.fastapi_routes.knowledge_v1 import router as knowledge_router
from app.infrastructure.auth import dependencies
from app.infrastructure.auth import shipment_etl_access_gate as shipment_gate
from app.legacy.routes.shipment_etl_compat import router as old_etl_router


def _client(router, prefix: str = "") -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def enterprise_desktop(monkeypatch):
    monkeypatch.setattr(dataset_access, "is_desktop_mode", lambda: True)
    monkeypatch.setattr(dataset_access, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(shipment_gate, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")


def test_desktop_forged_dataset_admin_headers_cannot_list_datasets(
    enterprise_desktop, monkeypatch
) -> None:
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: None)
    response = _client(knowledge_router).get(
        "/api/knowledge/v1/datasets",
        headers={
            "X-Dataset-Actor-ID": "attacker",
            "X-Dataset-Tenant-ID": "victim",
            "X-Dataset-Admin": "true",
        },
    )
    assert response.status_code == 401


def test_desktop_role_without_dataset_permission_cannot_list_datasets(
    enterprise_desktop, monkeypatch
) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="tenant:23:restricted", is_active=True)
    monkeypatch.setattr(dataset_access, "get_logged_in_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: False),
    )
    response = _client(knowledge_router).get("/api/knowledge/v1/datasets")
    assert response.status_code == 403


def test_desktop_read_only_role_cannot_ingest_dataset_document(
    enterprise_desktop, monkeypatch
) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="tenant:23:reader", is_active=True)
    monkeypatch.setattr(dataset_access, "get_logged_in_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda _user, code: code == "dataset.read"),
    )
    response = _client(knowledge_router).post(
        "/api/knowledge/v1/datasets/private/documents",
        json={"source": "private.txt", "text": "should not ingest"},
    )
    assert response.status_code == 403


def test_desktop_tenant_without_membership_cannot_query_legacy_knowledge(
    enterprise_desktop, monkeypatch
) -> None:
    user = SimpleNamespace(id=8, tenant_id=None, role="user", is_active=True)
    monkeypatch.setattr(dataset_access, "get_logged_in_user", lambda _request: user)
    response = _client(knowledge_router).post(
        "/api/knowledge/v1/query", json={"query": "private customer data"}
    )
    assert response.status_code == 403


def test_desktop_tenant_can_query_its_own_legacy_knowledge(enterprise_desktop, monkeypatch) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="user", is_active=True)
    monkeypatch.setattr(dataset_access, "get_logged_in_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: True),
    )
    chunk = SimpleNamespace(text="tenant-23-only", chunk_index=0, score=1.0, source="t")
    monkeypatch.setattr(
        "app.fastapi_routes.knowledge_v1._index.query", lambda *_args, **_kwargs: [chunk]
    )
    response = _client(knowledge_router).post(
        "/api/knowledge/v1/query", json={"query": "private customer data"}
    )
    assert response.status_code == 200
    assert "tenant-23-only" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/excel/data/shipment-etl/preview",
        "/api/excel/data/shipment-etl/execute",
        "/api/excel/data/shipment-etl/batch-execute",
    ],
)
def test_desktop_tenant_cannot_run_unscoped_shipment_etl(
    enterprise_desktop, monkeypatch, path: str
) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="user", is_active=True)
    monkeypatch.setattr(dependencies, "get_logged_in_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: True),
    )
    response = _client(excel_router).post(path, data={"file_path": "other-user.xlsx"})
    assert response.status_code == 403


def test_dormant_compat_etl_fails_closed_when_mounted(enterprise_desktop, monkeypatch) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="user", is_active=True)
    monkeypatch.setattr(dependencies, "get_logged_in_user", lambda _request: user)
    response = _client(old_etl_router, prefix="/api/legacy").post(
        "/api/legacy/shipment-etl/execute", data={"notes_json": "[]"}
    )
    assert response.status_code == 403


def test_desktop_tenant_ocr_preview_is_not_blocked_as_unscoped(
    enterprise_desktop, monkeypatch
) -> None:
    user = SimpleNamespace(id=8, tenant_id=23, role="user", is_active=True)
    monkeypatch.setattr(dependencies, "get_logged_in_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: True),
    )
    preview = _client(excel_router).post(
        "/api/excel/data/shipment-etl/ocr-preview", data={"file_path": "missing.png"}
    )
    assert preview.status_code != 403
    execute = _client(excel_router).post(
        "/api/excel/data/shipment-etl/execute", data={"file_path": "other-user.xlsx"}
    )
    assert execute.status_code == 403


def test_desktop_shipment_etl_requires_session_even_with_user_header(
    enterprise_desktop, monkeypatch
) -> None:
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: None)
    response = _client(excel_router).post(
        "/api/excel/data/shipment-etl/execute",
        data={"notes_json": "[]"},
        headers={"X-User-ID": "8"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "tenant,allowed,status", [(None, True, 403), (23, False, 403), (23, True, 200)]
)
def test_mod_shipment_routes_keep_permission_and_file_tenant_scope(
    tmp_path, monkeypatch, tenant, allowed, status
):
    from pathlib import Path

    from app.fastapi_routes import shipment_orders
    from app.infrastructure.mods.mod_manager import import_mod_backend_py
    from app.infrastructure.tenant_scope import current_tenant_id

    user = SimpleNamespace(id=8, tenant_id=tenant, role="user", is_active=True)
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda *_args: allowed),
    )
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    for tid in (23, 24):
        folder = tmp_path / "tenants" / str(tid) / "shipment_outputs"
        folder.mkdir(parents=True)
        (folder / "note.xlsx").write_bytes(str(tid).encode())
    (tmp_path / "tenants" / "24" / "shipment_outputs" / "private.xlsx").write_bytes(b"other tenant")
    calls = []
    monkeypatch.setattr(
        shipment_orders,
        "shipment_generate",
        lambda request, body: calls.append(current_tenant_id()) or {"success": True},
    )
    mod = import_mod_backend_py(
        str(Path(__file__).resolve().parents[2] / "mods" / "xcagi-erp-domain-bridge"),
        "xcagi-erp-domain-bridge",
        "blueprints",
    )
    app = FastAPI()
    mod.register_fastapi_routes(app, "xcagi-erp-domain-bridge")
    client = TestClient(app)
    base = "/api/mod/xcagi-erp-domain-bridge/shipment"
    generated = client.post(
        base + "/generate", json={"user_id": 999, "tenant_id": 24}, headers={"X-User-ID": "999"}
    )
    assert generated.status_code == status
    download = client.get(base + "/download/note.xlsx", headers={"X-Tenant-ID": "24"})
    assert download.status_code == status
    if status == 200:
        assert calls == [23] and download.content == b"23"
        assert client.get(base + "/download/private.xlsx").status_code == 404
        assert client.get(base + "/download/%2e%2e%5cprivate.xlsx").status_code == 400
    else:
        assert calls == []
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: None)
    assert client.get(base + "/download/note.xlsx").status_code == 401
