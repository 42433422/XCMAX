"""Market file and graph products use their actual delivery storage."""

import json
import uuid
import hashlib

from modstore_server.auth_service import decode_access_token
from modstore_server import catalog_store
from modstore_server.models import CatalogItem, User, get_session_factory


def test_admin_market_upload_download_and_corruption(
    client, auth_headers, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    token = auth_headers["Authorization"].split()[-1]
    user_id = int(decode_access_token(token)["sub"])
    with get_session_factory()() as db:
        db.query(User).filter(User.id == user_id).one().is_admin = True
        db.commit()
    pkg_id = f"market-storage-{uuid.uuid4().hex[:10]}"
    raw = b"PK\x03\x04market-test-archive"
    uploaded = client.post(
        "/api/admin/catalog",
        headers=auth_headers,
        data={
            "pkg_id": pkg_id,
            "version": "1.0.0",
            "name": pkg_id,
            "industry": pkg_id,
            "is_public": "true",
        },
        files={"file": ("test.xcmod", raw, "application/zip")},
    )
    assert uploaded.status_code == 200, uploaded.text
    item_id = uploaded.json()["id"]
    archive = tmp_path / "catalog" / "files" / uploaded.json()["stored_filename"]
    assert archive.read_bytes() == raw
    listing = client.get("/api/market/catalog", params={"q": pkg_id}).json()
    assert listing["total"] == 1
    assert pkg_id in client.get("/api/market/facets").json()["industries"]
    assert client.get(f"/api/market/catalog/{item_id}").status_code == 200
    download = client.get(
        f"/api/market/catalog/{item_id}/download", headers=auth_headers
    )
    assert download.status_code == 200 and download.content == raw
    archive.write_bytes(b"corrupted")
    assert client.get("/api/market/catalog", params={"q": pkg_id}).json()["total"] == 0
    assert pkg_id not in client.get("/api/market/facets").json()["industries"]
    assert client.get(f"/api/market/catalog/{item_id}").status_code == 404
    assert (
        client.post(
            f"/api/market/catalog/{item_id}/buy", headers=auth_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/market/catalog/{item_id}/download", headers=auth_headers
        ).status_code
        == 404
    )


def test_graph_template_needs_snapshot_not_archive(client, auth_headers):
    pkg_id = f"graph-template-{uuid.uuid4().hex[:10]}"
    with get_session_factory()() as db:
        item = CatalogItem(
            pkg_id=pkg_id,
            version="1.0.0",
            name=pkg_id,
            artifact="workflow_template",
            is_public=True,
            compliance_status="approved",
            price=0,
            graph_snapshot=json.dumps({"nodes": [{"local_id": 1}], "edges": []}),
        )
        db.add(item)
        db.commit()
        item_id = item.id
    assert client.get("/api/market/catalog", params={"q": pkg_id}).json()["total"] == 1
    assert client.get(f"/api/market/catalog/{item_id}").status_code == 200
    assert (
        client.post(
            f"/api/market/catalog/{item_id}/buy", headers=auth_headers
        ).status_code
        == 200
    )
    with get_session_factory()() as db:
        db.query(CatalogItem).filter(
            CatalogItem.id == item_id
        ).one().graph_snapshot = "{}"
        db.commit()
    assert client.get("/api/market/catalog", params={"q": pkg_id}).json()["total"] == 0


def test_legacy_market_file_is_read_until_controlled_migration(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "persistent"))
    monkeypatch.setattr(
        catalog_store, "__file__", str(tmp_path / "legacy" / "catalog_store.py")
    )
    old_dir = tmp_path / "legacy" / "market_files"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "original.xcmod"
    old_file.write_bytes(b"original published bytes")
    digest = hashlib.sha256(old_file.read_bytes()).hexdigest()
    assert catalog_store.market_archive_path(old_file.name, digest) == old_file
    migrated = tmp_path / "persistent" / "market_files" / old_file.name
    migrated.parent.mkdir(parents=True)
    migrated.write_bytes(old_file.read_bytes())
    canonical = tmp_path / "persistent" / "files" / old_file.name
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"same name, different package")
    monkeypatch.setattr(
        catalog_store, "__file__", str(tmp_path / "new" / "catalog_store.py")
    )
    assert catalog_store.market_archive_path(old_file.name, digest) == migrated
    migrated.write_bytes(b"modified published bytes")
    assert catalog_store.market_archive_path(old_file.name, digest) is None
