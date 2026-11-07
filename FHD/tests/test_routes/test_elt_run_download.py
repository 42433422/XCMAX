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
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_routes.test_elt_sources import source_client


@pytest.fixture
def download_store(source_client, monkeypatch):  # noqa: F811
    store = source_client
    monkeypatch.setattr(service_targets, "get_app_data_dir", lambda: str(store.root))
    run_id = "download-regression"
    path = store.root / "etl" / "exports" / f"etl-{run_id}.xlsx"
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
    store.actor.permissions = {"etl.read"}  # No execute or admin permission needed.
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
