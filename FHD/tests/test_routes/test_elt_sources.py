"""ELT source HTTP contracts use isolated SQLite, storage and real RBAC gates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl import service_history, service_uploads
from app.application.etl.archive_store import create_original
from app.db.db_base import Base
from app.db.models.etl import EtlRun, EtlUpload
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion
from app.db.session import get_db_dependency
from app.fastapi_routes import etl
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
    for tenant in (1, 2):
        with tenant_scope(tenant), factory() as db:
            db.add(EtlArchiveQuota(tenant_id=tenant, limit_bytes=1024 * 1024, reserved_bytes=0))
            db.commit()
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
    from app.application.etl import archive_store
    from app.utils.path_io import path_utils

    if hasattr(sources, "get_app_data_dir"):
        monkeypatch.setattr(sources, "get_app_data_dir", lambda: str(tmp_path))
    archive_root = tmp_path / "business-archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(path_utils, "get_desktop_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(path_utils, "get_business_archive_dir", lambda **_: str(archive_root))
    monkeypatch.setattr(archive_store, "get_business_archive_dir", lambda **_: str(archive_root))
    monkeypatch.setattr(archive_store, "default_archive_root", lambda: archive_root)

    app = FastAPI()

    @app.middleware("http")
    async def request_tenant(request, call_next):
        with tenant_scope(actor.user.tenant_id if actor.user is not None else None):
            return await call_next(request)

    def isolated_db():
        with factory() as db:
            yield db
            db.commit()

    app.dependency_overrides[get_db_dependency] = isolated_db
    app.include_router(etl.sources_router)
    app.include_router(etl.router)
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, actor=actor, factory=factory, root=tmp_path)
    finally:
        engine.dispose()


def create_source(store, content=ORIGINAL, request_key=None):
    response = store.client.post(
        "/api/elt/sources",
        data={"request_key": request_key or str(uuid4())},
        files={"file": ("未分类资料.csv", content, "text/csv")},
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
        data={"expected_version": 1, "request_key": str(uuid4())},
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
        assert source["revision"]["status"] == "ready"
        original = store.client.get(f"{revision_path(source)}/content")
        assert original.status_code == 200
        assert original.content == content
        assert original.headers["content-type"] == "application/octet-stream"
        assert original.headers["content-disposition"].startswith("attachment;")
        assert original.headers["x-content-type-options"] == "nosniff"
        assert original.headers["cache-control"] == "private, no-store"
        assert "storage_path" not in revision.text
    with tenant_scope(1), store.factory() as db:
        assert db.query(EtlRun).count() == db.query(EtlUpload).count() == 0
        assert db.query(EtlArchiveVersion).count() == 2


def test_download_streams_verified_snapshot_when_original_changes(source_client, monkeypatch):
    store = source_client
    source = create_source(store)
    service = etl.get_etl_service()
    get_verified_content = service.get_source_content
    snapshots = []

    def change_original_after_verification(db, **kwargs):
        snapshot, file_name = get_verified_content(db, **kwargs)
        snapshots.append(snapshot)
        version = db.get(EtlArchiveVersion, source["revision"]["id"])
        Path(version.storage_path).write_bytes(CORRECTION)
        return snapshot, file_name

    monkeypatch.setattr(service, "get_source_content", change_original_after_verification)
    response = store.client.get(f"{revision_path(source)}/content")
    assert response.status_code == 200
    assert response.content == ORIGINAL
    assert hashlib.sha256(response.content).hexdigest() == source["revision"]["sha256"]
    assert len(snapshots) == 1 and snapshots[0].closed
    with tenant_scope(1), store.factory() as db:
        version = db.get(EtlArchiveVersion, source["revision"]["id"])
        assert Path(version.storage_path).read_bytes() == CORRECTION


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
        data={"expected_version": 1, "request_key": str(uuid4())},
        files={"file": ("other.csv", CORRECTION, "text/csv")},
    )
    assert denied.status_code == 404
    own_source = create_source(store)
    assert own_source["id"] != source["id"]
    assert own_source["revision"]["id"] != source["revision"]["id"]
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
        ("/api/elt/sources", {"request_key": str(uuid4())}),
        (
            f"/api/elt/sources/{source['id']}/revisions",
            {"expected_version": 1, "request_key": str(uuid4())},
        ),
    ):
        denied = store.client.post(path, data=data, files={"file": ("new.csv", ORIGINAL)})
        assert denied.status_code == 403
    store.actor.permissions = set()
    assert store.client.get(revision_path(source)).status_code == 403
    assert store.client.get(f"{revision_path(source)}/content").status_code == 403
    store.actor.user = None
    assert store.client.get(revision_path(source)).status_code == 401
    assert (
        store.client.post(
            "/api/elt/sources",
            data={"request_key": str(uuid4())},
            files={"file": ("new.csv", ORIGINAL)},
        ).status_code
        == 401
    )


@pytest.mark.parametrize("disabled", ["flag", "edition"])
def test_sources_reuse_enterprise_feature_gate(source_client, monkeypatch, disabled):
    if disabled == "flag":
        monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "0")
    else:
        monkeypatch.setattr(etl, "resolve_product_sku", lambda: "personal")
    response = source_client.client.post(
        "/api/elt/sources",
        data={"request_key": str(uuid4())},
        files={"file": ("data.csv", ORIGINAL, "text/csv")},
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
            path,
            data={"expected_version": expected, "request_key": str(uuid4())},
            files={"file": ("new.csv", CORRECTION)},
        )
        assert response.status_code == 422
    assert (
        store.client.post(
            path,
            data={"expected_version": 2, "request_key": str(uuid4())},
            files={"file": ("new.csv", CORRECTION)},
        ).status_code
        == 409
    )
    assert store.client.get(f"{revision_path(first)}/content").content == ORIGINAL
    with tenant_scope(1), store.factory() as db:
        assert db.query(EtlArchiveVersion).count() == 1
        assert db.query(EtlUpload).count() == 0


def test_sources_require_configured_archive_quota(source_client):
    store = source_client
    store.actor.user = SimpleNamespace(id=7, tenant_id=3, is_active=True)
    response = store.client.post(
        "/api/elt/sources",
        data={"request_key": str(uuid4())},
        files={"file": ("unfunded.csv", ORIGINAL)},
    )
    assert response.status_code == 409, response.text
    with tenant_scope(3), store.factory() as db:
        assert db.query(EtlArchiveAsset).count() == db.query(EtlArchiveVersion).count() == 0
    assert not (store.root / "business-archive" / "3").exists()


def test_request_key_replay_reuses_archive_identity_and_quota(source_client):
    store = source_client
    request_key = str(uuid4())
    first = create_source(store, request_key=request_key)
    assert create_source(store, request_key=request_key) == first
    append_request = str(uuid4())
    revisions = []
    for _ in range(2):
        response = store.client.post(
            f"/api/elt/sources/{first['id']}/revisions",
            data={"expected_version": 1, "request_key": append_request},
            files={"file": ("revision.csv", CORRECTION)},
        )
        assert response.status_code == 201, response.text
        revisions.append(response.json()["data"])
    assert revisions[0] == revisions[1]
    with tenant_scope(1), store.factory() as db:
        assert db.query(EtlArchiveAsset).count() == 1
        assert db.query(EtlArchiveVersion).count() == 2
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(ORIGINAL) + len(CORRECTION)
        assert db.query(EtlUpload).count() == db.query(EtlRun).count() == 0


def test_existing_archive_original_is_readable_without_reupload(source_client):
    store = source_client
    with tenant_scope(1), store.factory() as db:
        archived = create_original(
            db,
            owner=7,
            name="existing.csv",
            body=ORIGINAL,
            root=store.root / "business-archive",
            request_key=str(uuid4()),
        )
        asset_id, version_id = archived.asset_id, archived.id
    response = store.client.get(f"/api/elt/sources/{asset_id}")
    assert response.status_code == 200, response.text
    source = response.json()["data"]
    assert source["name"] == source["revision"]["file_name"] == "existing.csv"
    assert source["revision"]["id"] == version_id
    assert store.client.get(f"{revision_path(source)}/content").content == ORIGINAL
    with tenant_scope(1), store.factory() as db:
        assert db.query(EtlArchiveVersion).count() == 1
        assert db.get(EtlArchiveQuota, 1).reserved_bytes == len(ORIGINAL)
        assert db.query(EtlUpload).count() == db.query(EtlRun).count() == 0


@pytest.mark.parametrize("request_key", [None, "", "x" * 81])
def test_source_request_key_is_required_and_bounded(source_client, request_key):
    response = source_client.client.post(
        "/api/elt/sources",
        data={} if request_key is None else {"request_key": request_key},
        files={"file": ("source.csv", ORIGINAL)},
    )
    assert response.status_code == 422


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
        assert db.query(EtlArchiveVersion).count() == db.query(EtlRun).count() == 0
