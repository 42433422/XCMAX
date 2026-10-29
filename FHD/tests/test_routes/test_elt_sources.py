"""ELT source HTTP contracts use isolated SQLite, storage and real RBAC gates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl import service_history, service_uploads
from app.db.db_base import Base
from app.db.models.etl import EltSourceRevision, EtlRun, EtlUpload
from app.db.session import get_db_dependency
from app.fastapi_routes import elt, etl
from app.infrastructure.auth import dependencies
from app.infrastructure.tenant_scope import tenant_scope

ORIGINAL = "姓名,未知符号\n同名员工,√ 2\n".encode()
CORRECTION = "姓名,未知符号\n同名员工,?\n".encode()


@pytest.fixture
def source_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sources.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    actor = SimpleNamespace(
        user=SimpleNamespace(id=7, tenant_id=1, is_active=True),
        permissions={"etl.read", "etl.execute"},
    )
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "1")
    monkeypatch.setattr(etl, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(dependencies, "resolve_session_user", lambda _request: actor.user)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda _user, code: code in actor.permissions),
    )
    monkeypatch.setattr(service_uploads, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(service_history, "get_app_data_dir", lambda: str(tmp_path))
    from app.application.elt import sources

    if hasattr(sources, "get_app_data_dir"):
        monkeypatch.setattr(sources, "get_app_data_dir", lambda: str(tmp_path))

    app = FastAPI()

    @app.middleware("http")
    async def request_tenant(request, call_next):
        with tenant_scope(actor.user.tenant_id if actor.user is not None else None):
            return await call_next(request)

    def isolated_db():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db_dependency] = isolated_db
    app.include_router(elt.router)
    app.include_router(etl.router)
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, actor=actor, factory=factory, root=tmp_path)
    finally:
        engine.dispose()


def create_source(store, content=ORIGINAL):
    response = store.client.post(
        "/api/elt/sources", files={"file": ("未分类资料.csv", content, "text/csv")}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def revision_path(source):
    return f"/api/elt/sources/{source['id']}/revisions/{source['revision']['id']}"


def test_sources_preserve_versions_originals_and_never_create_business_runs(source_client):
    store = source_client
    first = create_source(store)
    response = store.client.post(
        f"/api/elt/sources/{first['id']}/revisions",
        data={"expected_version": 1},
        files={"file": ("修正资料.csv", CORRECTION, "text/html")},
    )
    assert response.status_code == 201, response.text
    second = response.json()["data"]
    assert second["current_version"] == 2
    assert second["revision"]["id"] != first["revision"]["id"]
    assert store.client.get(f"/api/elt/sources/{first['id']}").json()["data"] == second
    versions = store.client.get(f"/api/elt/sources/{first['id']}/revisions").json()["data"]
    assert {item["version"] for item in versions} == {1, 2}
    for source, content in ((first, ORIGINAL), (second, CORRECTION)):
        revision = store.client.get(revision_path(source))
        assert revision.status_code == 200
        assert revision.json()["data"] == source["revision"]
        assert source["revision"]["sha256"] == hashlib.sha256(content).hexdigest()
        original = store.client.get(f"{revision_path(source)}/content")
        assert original.status_code == 200
        assert original.content == content
        assert original.headers["content-type"] == "application/octet-stream"
        assert original.headers["content-disposition"].startswith("attachment;")
        assert original.headers["x-content-type-options"] == "nosniff"
        assert original.headers["cache-control"] == "private, no-store"
        assert "storage_path" not in revision.text
    with tenant_scope(1), store.factory() as db:
        assert db.query(EtlRun).count() == 0
        assert all(upload.expires_at is None for upload in db.query(EtlUpload).all())


def test_download_streams_verified_snapshot_when_original_changes(source_client, monkeypatch):
    store = source_client
    source = create_source(store)
    service = elt.get_etl_service()
    get_verified_content = service.get_source_content
    snapshots = []

    def change_original_after_verification(db, **kwargs):
        snapshot, file_name = get_verified_content(db, **kwargs)
        snapshots.append(snapshot)
        upload = db.get(EtlUpload, source["revision"]["upload_id"])
        Path(upload.storage_path).write_bytes(CORRECTION)
        return snapshot, file_name

    monkeypatch.setattr(service, "get_source_content", change_original_after_verification)
    response = store.client.get(f"{revision_path(source)}/content")
    assert response.status_code == 200
    assert response.content == ORIGINAL
    assert hashlib.sha256(response.content).hexdigest() == source["revision"]["sha256"]
    assert len(snapshots) == 1 and snapshots[0].closed
    with tenant_scope(1), store.factory() as db:
        upload = db.get(EtlUpload, source["revision"]["upload_id"])
        assert Path(upload.storage_path).read_bytes() == CORRECTION


@pytest.mark.parametrize("tenant,owner", [(2, 7), (1, 8)])
def test_source_routes_hide_other_tenants_and_owners(source_client, tenant, owner):
    store = source_client
    source = create_source(store)
    store.actor.user = SimpleNamespace(id=owner, tenant_id=tenant, is_active=True)
    paths = [
        f"/api/elt/sources/{source['id']}",
        f"/api/elt/sources/{source['id']}/revisions",
        revision_path(source),
        f"{revision_path(source)}/content",
    ]
    for path in paths:
        assert store.client.get(path).status_code == 404
    denied = store.client.post(
        f"/api/elt/sources/{source['id']}/revisions",
        data={"expected_version": 1},
        files={"file": ("other.csv", CORRECTION, "text/csv")},
    )
    assert denied.status_code == 404
    own_source = create_source(store)
    assert own_source["id"] != source["id"]
    assert own_source["revision"]["upload_id"] != source["revision"]["upload_id"]
    assert own_source["revision"]["sha256"] == source["revision"]["sha256"]


def test_revision_must_belong_to_requested_source(source_client):
    store = source_client
    first, second = create_source(store), create_source(store)
    path = f"/api/elt/sources/{first['id']}/revisions/{second['revision']['id']}"
    assert store.client.get(path).status_code == 404
    assert store.client.get(f"{path}/content").status_code == 404


def test_read_permission_allows_originals_but_never_creating_or_appending(source_client):
    store = source_client
    source = create_source(store)
    store.actor.permissions = {"etl.read"}
    assert store.client.get(f"{revision_path(source)}/content").status_code == 200
    for path, data in (
        ("/api/elt/sources", {}),
        (f"/api/elt/sources/{source['id']}/revisions", {"expected_version": 1}),
    ):
        denied = store.client.post(path, data=data, files={"file": ("new.csv", ORIGINAL)})
        assert denied.status_code == 403
    store.actor.permissions = set()
    assert store.client.get(revision_path(source)).status_code == 403
    assert store.client.get(f"{revision_path(source)}/content").status_code == 403
    store.actor.user = None
    assert store.client.get(revision_path(source)).status_code == 401
    assert (
        store.client.post("/api/elt/sources", files={"file": ("new.csv", ORIGINAL)}).status_code
        == 401
    )


@pytest.mark.parametrize("disabled", ["flag", "edition"])
def test_sources_reuse_enterprise_feature_gate(source_client, monkeypatch, disabled):
    if disabled == "flag":
        monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "0")
    else:
        monkeypatch.setattr(etl, "resolve_product_sku", lambda: "personal")
    response = source_client.client.post(
        "/api/elt/sources", files={"file": ("data.csv", ORIGINAL, "text/csv")}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == (
        "ETL_CENTER_DISABLED" if disabled == "flag" else "ETL_ENTERPRISE_REQUIRED"
    )


def test_append_requires_positive_current_version_and_preserves_original_on_conflict(source_client):
    store = source_client
    first = create_source(store)
    path = f"/api/elt/sources/{first['id']}/revisions"
    for expected in (0, -1, "invalid"):
        response = store.client.post(
            path, data={"expected_version": expected}, files={"file": ("new.csv", CORRECTION)}
        )
        assert response.status_code == 422
    assert (
        store.client.post(
            path, data={"expected_version": 2}, files={"file": ("new.csv", CORRECTION)}
        ).status_code
        == 409
    )
    assert store.client.get(f"{revision_path(first)}/content").content == ORIGINAL
    with tenant_scope(1), store.factory() as db:
        assert db.query(EltSourceRevision).count() == db.query(EtlUpload).count() == 1


def test_legacy_upload_keeps_seven_day_retention_and_response_contract(source_client):
    store = source_client
    before = datetime.now(UTC)
    batch_id = "7af2693b-cf7c-4a15-af76-e725ee15470a"
    response = store.client.post(
        "/api/etl/uploads",
        files={"file": ("legacy.csv", ORIGINAL, "text/csv")},
        data={"batch_id": batch_id, "relative_path": "folder/legacy.csv"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["file_name"] == "legacy.csv" and data["batch_id"] == batch_id
    assert data["relative_path"] == "folder/legacy.csv"
    assert data["sha256"] == hashlib.sha256(ORIGINAL).hexdigest()
    with tenant_scope(1), store.factory() as db:
        upload = db.get(EtlUpload, data["upload_id"])
        assert upload is not None and upload.expires_at is not None
        expires = upload.expires_at.replace(tzinfo=UTC)
        assert before + timedelta(days=7) <= expires <= datetime.now(UTC) + timedelta(days=7)
        assert db.query(EltSourceRevision).count() == db.query(EtlRun).count() == 0
