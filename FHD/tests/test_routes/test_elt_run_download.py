"""Run exports use the real download service and owner/tenant/RBAC boundaries."""

import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.application.elt import service_targets
from app.application.elt.result_export import write_xlsx_result
from app.application.elt.service_support import dump_json
from app.db.models.elt import EltRun, EltUpload
from app.fastapi_routes import elt
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_routes.test_elt_sources import source_client as source_client


@pytest.fixture
def download_store(request, monkeypatch):
    store = request.getfixturevalue("source_client")
    monkeypatch.setattr(service_targets, "get_app_data_dir", lambda: str(store.root))
    run_id = "download-regression"
    path = store.root / "elt" / "exports" / f"elt-{run_id}.xlsx"
    receipt = write_xlsx_result(
        path,
        columns=[{"key": "amount", "label": "金额", "type": "money"}],
        rows=[{"amount": "12.50"}],
        sheet_name="合成结果",
        notes=[],
    )
    with tenant_scope(1), store.factory() as db:
        db.add(
            EltUpload(
                id="download-upload",
                tenant_id=1,
                owner_user_id=7,
                file_name="synthetic.csv",
                suffix=".csv",
                size_bytes=1,
                sha256="0" * 64,
                storage_path=str(store.root / "unused"),
            )
        )
        db.flush()
        db.add(
            EltRun(
                id=run_id,
                tenant_id=1,
                owner_user_id=7,
                upload_id="download-upload",
                target_type="export_xlsx",
                status="completed",
                file_sha256="0" * 64,
                receipt_json=dump_json(receipt),
            )
        )
        db.commit()
    store.download_url = f"/api/elt/runs/{run_id}/download"
    store.export_bytes = path.read_bytes()
    store.receipt = receipt
    return store


def test_download_returns_complete_xlsx_with_read_permission(download_store):
    store = download_store
    store.actor.permissions = {"elt.read"}  # No execute or admin permission needed.
    response = store.client.get(store.download_url)
    assert response.status_code == 200, response.text
    assert response.content == store.export_bytes
    assert int(response.headers["content-length"]) == len(store.export_bytes)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert hashlib.sha256(response.content).hexdigest() == store.receipt["sha256"]
    book = load_workbook(BytesIO(response.content))
    try:
        assert book.active["A2"].value == 12.5
    finally:
        book.close()


@pytest.mark.parametrize("owner,tenant", [(8, 1), (7, 2)])
def test_download_hides_other_owner_and_tenant(download_store, owner, tenant):
    store = download_store
    store.actor.user = SimpleNamespace(id=owner, tenant_id=tenant, is_active=True)
    response = store.client.get(store.download_url)
    assert response.status_code == 404, response.text
    assert store.export_bytes not in response.content


def test_download_requires_login(download_store):
    download_store.actor.user = None
    assert download_store.client.get(download_store.download_url).status_code == 401


def test_download_requires_read_grant(download_store):
    download_store.actor.permissions = set()
    assert download_store.client.get(download_store.download_url).status_code == 403


@pytest.mark.parametrize("damage", ["changed", "missing_digest"])
def test_download_rejects_unverified_artifact(download_store, damage):
    store = download_store
    path = store.root / "elt" / "exports" / store.receipt["file_name"]
    if damage == "changed":
        path.write_bytes(b"different artifact, same run")
    else:
        with tenant_scope(1), store.factory() as db:
            run = db.get(EltRun, "download-regression")
            run.receipt_json = dump_json({"file_name": path.name})
            db.commit()
    response = store.client.get(store.download_url)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ELT_EXPORT_UNVERIFIED"
    assert path.is_file()  # Preserve evidence; never regenerate and relabel a changed result.


def test_download_sends_verified_snapshot_if_result_is_replaced(download_store, monkeypatch):
    store = download_store
    service = elt.get_elt_service()
    original = service.download_content
    streams = []

    def replace_after_verification(db, **kwargs):
        content, name = original(db, **kwargs)
        streams.append(content)
        (store.root / "elt" / "exports" / name).write_bytes(b"changed after verification")
        return content, name

    monkeypatch.setattr(service, "download_content", replace_after_verification)
    response = store.client.get(store.download_url)
    assert response.status_code == 200
    assert response.content == store.export_bytes
    assert response.headers["cache-control"] == "private, no-store"
    assert all(stream.closed for stream in streams)


def test_download_rejects_oversize_without_reading_entire_artifact(download_store, monkeypatch):
    monkeypatch.setattr(service_targets, "MAX_FILE_BYTES", 128)
    response = download_store.client.get(download_store.download_url)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ELT_EXPORT_TOO_LARGE"


@pytest.mark.parametrize("rolled", [False, True])
async def test_download_closes_snapshot_when_client_disconnects_before_body(rolled):
    from tempfile import SpooledTemporaryFile

    from starlette.requests import ClientDisconnect

    content = SpooledTemporaryFile(max_size=1024, mode="w+b")
    content.write(b"verified snapshot")
    if rolled:
        content.rollover()
    response = elt._attachment_response(content, "result.csv")

    async def send(_event):
        raise OSError("client disconnected before response body")

    async def receive():
        return {"type": "http.disconnect"}

    try:
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert content.closed
    finally:
        content.close()
