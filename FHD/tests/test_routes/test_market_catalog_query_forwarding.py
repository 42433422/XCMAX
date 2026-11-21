"""Catalog operations retain pagination/filter semantics through the host gateway."""

import asyncio
import io
import json
import logging
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from app.fastapi_routes.admin_control.market_gateway import MarketGateway


def test_catalog_query_reaches_upstream_without_changing_authorized_path():
    proxy = AsyncMock(return_value={"items": [], "total": 0})
    gateway = MarketGateway(errors=(), gate=None, proxy=proxy, maintenance=None, transport=None)
    query = b"limit=50&offset=100&status=pending&search=%E5%90%88%E5%90%8C"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/market/admin/catalog",
            "query_string": query,
            "headers": [],
        }
    )
    asyncio.run(gateway._xcmax_market_proxy_impl(request, "admin/catalog"))
    proxy.assert_awaited_once_with(
        request, "GET", "/api/admin/catalog?" + query.decode(), json_body=None
    )


def test_market_item_download_uses_authorized_market_route_not_public_record():
    from app.infrastructure.mods.catalog_client import market_item_to_package_row

    item = {"id": 42, "pkg_id": "market-only", "version": "1.0.0"}
    assert market_item_to_package_row(item)["download_url"] == "/api/market/catalog/42/download"
    item.pop("id")
    assert (
        market_item_to_package_row(item)["download_url"]
        == "/v1/packages/market-only/1.0.0/download"
    )


def test_template_catalog_preserves_identity_and_metadata_without_local_install():
    from app.fastapi_routes.mod_store.catalog import CatalogViews
    from app.fastapi_routes.mod_store.projection import remote_to_mod_info
    from app.infrastructure.mods.catalog_client import market_item_to_package_row
    from app.infrastructure.mods.catalog_visibility import is_public_catalog_row

    template = {
        "id": 42,
        "pkg_id": "support-template",
        "name": "客服流程",
        "version": "1.0.0",
        "artifact": "workflow_template",
        "is_public": True,
        "compliance_status": "approved",
        "price": 12.5,
        "template_category": "客服",
        "template_difficulty": "beginner",
        "install_count": 17,
    }
    mapped = market_item_to_package_row(template)
    assert mapped["download_url"] == ""
    assert not is_public_catalog_row(mapped)  # Not a downloadable local package.
    ports = SimpleNamespace(
        installed=lambda: {"support-template": {}, "worker": {}},
        remote_row=lambda row, installed: remote_to_mod_info(row, installed, base_url=lambda: ""),
    )
    catalog = CatalogViews(ports, logging.getLogger(__name__))
    rows, total = asyncio.run(catalog.map_market_catalog_page({"items": [template], "total": 1}))
    assert total == 1 and len(rows) == 1
    row = rows[0]
    assert {
        key: row[key]
        for key in (
            "catalog_id",
            "template_category",
            "template_difficulty",
            "install_count",
            "price",
        )
    } == {
        "catalog_id": 42,
        "template_category": "客服",
        "template_difficulty": "beginner",
        "install_count": 17,
        "price": 12.5,
    }
    assert row["id"] == "support-template" and row["commerce"]["price"] == 12.5
    assert row["package_file"] is None and row["download_url"] == ""
    assert row["is_installed"] is False
    employee = remote_to_mod_info(
        market_item_to_package_row(
            {
                "id": 43,
                "pkg_id": "worker",
                "version": "2.0.0",
                "artifact": "employee_pack",
            }
        ),
        {"worker"},
        base_url=lambda: "",
    )
    assert employee["catalog_id"] == 43 and employee["is_installed"] is True
    assert employee["download_url"] == "/api/market/catalog/43/download"
    assert employee["package_file"] == "worker:2.0.0"


@pytest.mark.parametrize(
    "override",
    [
        {"id": True},
        {"id": -1},
        {"id": "42"},
        {"compliance_status": "restricted"},
        {"compliance_status": None},
        {"is_public": False},
        {"is_public": None},
        {"version": "draft-1"},
        {"pkg_id": "security-secrets-guard"},
    ],
)
def test_market_template_proxy_rejects_invalid_or_hidden_rows(override):
    from app.fastapi_routes.mod_store.catalog import CatalogViews

    catalog = CatalogViews(SimpleNamespace(installed=lambda: {}), logging.getLogger(__name__))
    item = {
        "id": 42,
        "pkg_id": "support-template",
        "artifact": "workflow_template",
        "is_public": True,
        "compliance_status": "approved",
        **override,
    }
    item = {key: value for key, value in item.items() if value is not None}
    rows, _ = asyncio.run(catalog.map_market_catalog_page({"items": [item], "total": 1}))
    assert rows == []


@pytest.mark.parametrize("kind_field", ["artifact", "kind"])
def test_template_zip_upload_never_dispatches_to_local_package_installers(kind_field):
    from app.fastapi_routes.mod_store.packages import PackageInstaller
    from app.infrastructure.mods.artifact_package import peek_artifact

    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"id": "template", kind_field: "workflow_template"}),
        )
    mods, employees = Mock(), Mock()
    installer = PackageInstaller(
        get_json=AsyncMock(),
        download=AsyncMock(),
        normalize_catalog=lambda path: path,
        normalize_upload=lambda path: path,
        artifact=peek_artifact,
        mods=lambda: mods,
        employees=lambda: employees,
        foundation=AsyncMock(),
        logger=logging.getLogger(__name__),
    )
    upload = UploadFile(io.BytesIO(content.getvalue()), filename="template.zip")
    with pytest.raises(HTTPException) as error:
        asyncio.run(installer.upload(upload, activate=True))
    assert error.value.status_code == 400
    assert "工作流模板" in error.value.detail
    assert upload.file.closed and not mods.mock_calls and not employees.mock_calls
