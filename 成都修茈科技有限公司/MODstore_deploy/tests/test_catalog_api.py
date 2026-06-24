"""Catalog /v1 路由冒烟（内存临时目录）。"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi")


def test_catalog_index_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    from modstore_server.catalog_store import load_store, save_store

    save_store({"packages": []})
    from fastapi.testclient import TestClient

    from modstore_server.app import app

    c = TestClient(app)
    r = c.get("/v1/index.json")
    assert r.status_code == 200
    assert r.json() == {"packages": []}


@pytest.mark.xfail(strict=False, reason="requires chromadb extra not installed in CI")
def test_catalog_upload_with_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    monkeypatch.setenv("MODSTORE_CATALOG_UPLOAD_TOKEN", "secret-test")
    monkeypatch.setattr(
        "modstore_server.package_sandbox_audit.run_package_audit_async",
        AsyncMock(
            return_value={
                "ok": True,
                "dimensions": {},
                "functional_tests": [],
                "summary": {"average": 100, "pass": True},
            }
        ),
    )
    monkeypatch.setattr(
        "modstore_server.catalog_api.insert_embedding",
        lambda *args, **kwargs: "",
    )
    from modstore_server.catalog_store import save_store

    save_store({"packages": []})

    # 最小 zip：含 manifest.json（mod）
    import io
    import zipfile

    from fastapi.testclient import TestClient

    from modstore_server.app import app

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "catalog-test-mod",
                    "name": "Test",
                    "version": "0.0.1",
                    "artifact": "mod",
                    "backend": {"entry": "blueprints", "init": "mod_init"},
                    "frontend": {"routes": "routes"},
                },
                ensure_ascii=False,
            ),
        )
        zf.writestr("backend/blueprints.py", "# stub\n")
        zf.writestr("backend/mod_init.py", "def mod_init():\n    pass\n")
        zf.writestr("frontend/routes.js", "export default []\n")
    buf.seek(0)

    c = TestClient(app)
    meta = json.dumps(
        {
            "id": "catalog-test-mod",
            "version": "0.0.1",
            "name": "Test",
            "artifact": "mod",
        },
        ensure_ascii=False,
    )
    r = c.post(
        "/v1/packages",
        headers={"Authorization": "Bearer secret-test"},
        data={"metadata": meta},
        files={"file": ("catalog-test-mod-0.0.1.xcmod", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    idx = c.get("/v1/index.json").json()
    assert len(idx["packages"]) == 1
    assert idx["packages"][0]["id"] == "catalog-test-mod"


def test_remove_package_deletes_json_and_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    from modstore_server.catalog_store import append_package, load_store, remove_package

    stub = tmp_path / "src.zip"
    stub.write_bytes(b"PK\x03\x04fake")
    append_package(
        {
            "id": "emp-del-test",
            "version": "1.0.0",
            "name": "Del",
            "artifact": "employee_pack",
        },
        stub,
    )
    data = load_store()
    assert len(data["packages"]) == 1
    fn = data["packages"][0].get("stored_filename")
    assert fn
    assert (tmp_path / "files" / str(fn)).is_file()

    n = remove_package("emp-del-test", version=None)
    assert n == 1
    assert load_store()["packages"] == []
    assert not (tmp_path / "files" / str(fn)).is_file()


def test_remove_package_matches_int_id_in_json(monkeypatch, tmp_path: Path):
    """packages.json 中 id 可能为数字，与 URL 中的字符串 pkg_id 应对齐。"""
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path))
    from modstore_server.catalog_store import load_store, remove_package, save_store

    save_store(
        {
            "packages": [
                {
                    "id": 42,
                    "version": "1.0.0",
                    "name": "IntId",
                    "artifact": "employee_pack",
                }
            ]
        }
    )
    assert len(load_store()["packages"]) == 1
    n = remove_package("42", version=None)
    assert n == 1
    assert load_store()["packages"] == []
