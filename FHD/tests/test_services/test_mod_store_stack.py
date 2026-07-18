"""MOD 商店迁移栈：catalog_client、zip 规范化、路由装配。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mod_store_routes import router as mod_store_router
from app.services import catalog_client
from app.services.mod_zip_normalize import normalize_package_zip_path


def test_catalog_base_url_default():
    assert catalog_client.catalog_base_url().startswith("http")


@pytest.mark.asyncio
async def test_catalog_http_client_ignores_environment_proxy():
    import app.infrastructure.mods.catalog_client as catalog_client_impl

    response = MagicMock(status_code=200)
    response.json.return_value = {"items": []}
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.infrastructure.mods.catalog_client.httpx.AsyncClient",
        return_value=context,
    ) as constructor:
        result = await catalog_client_impl._http_get_json("https://xiu-ci.com/api/market/catalog")

    assert result == {"items": []}
    assert constructor.call_args.kwargs["trust_env"] is False


def test_normalize_package_zip_passes_through_when_manifest_at_root(tmp_path: Path):
    zpath = tmp_path / "m.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("readme.txt", b"x")
    assert normalize_package_zip_path(str(zpath)) == str(zpath)


def test_normalize_package_zip_flattens_single_top_folder(tmp_path: Path):
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("myid/manifest.json", "{}")
        zf.writestr("myid/foo.txt", b"hi")
    out = normalize_package_zip_path(str(inner))
    assert out != str(inner)
    with zipfile.ZipFile(out, "r") as zf2:
        names = set(zf2.namelist())
    assert "manifest.json" in names
    Path(out).unlink(missing_ok=True)


def test_mod_store_market_catalog_proxy(monkeypatch: pytest.MonkeyPatch):
    import sys

    async def _fake_market(**kwargs):
        assert kwargs.get("collection") == "office_employee_aux_pack_1"
        return {
            "items": [
                {
                    "pkg_id": "chart-bar-employee",
                    "version": "1.0.0",
                    "name": "柱状图员工",
                    "artifact": "employee_pack",
                    "price": 0,
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(
        "app.fastapi_routes.mod_store_routes.fetch_market_catalog_page",
        _fake_market,
    )

    # Restore pass-through implementations in case another test file has overwritten them
    # on the stub/real app.application.mod_store_catalog_app module.
    _ca = sys.modules.get("app.application.mod_store_catalog_app")
    if _ca is not None:
        monkeypatch.setattr(_ca, "market_item_to_package_row", lambda raw: raw)
        monkeypatch.setattr(_ca, "is_public_catalog_row", lambda row: bool(row))

    app = FastAPI()
    app.include_router(mod_store_router, prefix="/api/mod-store")
    client = TestClient(app)
    r = client.get(
        "/api/mod-store/market-catalog"
        "?collection=office_employee_aux_pack_1&artifact=employee_pack&material_category=ai_employee"
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["id"] == "chart-bar-employee"
    assert body["data"]["items"][0]["store_collection"] == "office_employee_aux_pack_1"


def test_mod_store_catalog_mount(monkeypatch: pytest.MonkeyPatch):
    async def _empty_remote():
        if False:  # pragma: no cover
            yield {}

    monkeypatch.setattr(
        "app.fastapi_routes.mod_store_routes.iter_catalog_packages",
        _empty_remote,
    )

    app = FastAPI()
    app.include_router(mod_store_router, prefix="/api/mod-store")
    client = TestClient(app)
    r = client.get("/api/mod-store/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert "data" in body
    assert "installed" in body["data"]
    assert "available" in body["data"]
