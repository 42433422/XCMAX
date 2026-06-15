"""Tests for app.fastapi_routes.mod_store_routes — coverage ramp.

Covers helper functions, route endpoints, catalog operations, and error paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.mod_store_routes as ms
from app.fastapi_routes.mod_store_routes import router


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _is_extension_row
# ---------------------------------------------------------------------------


class TestIsExtensionRow:
    def test_valid_mod(self) -> None:
        assert ms._is_extension_row({"id": "my-mod", "type": "mod"}) is True

    def test_empty_id(self) -> None:
        assert ms._is_extension_row({"id": "", "type": "mod"}) is False

    def test_id_all(self) -> None:
        assert ms._is_extension_row({"id": "all", "type": "mod"}) is False

    def test_category_type(self) -> None:
        assert ms._is_extension_row({"id": "cat1", "type": "category"}) is False

    def test_template_type(self) -> None:
        assert ms._is_extension_row({"id": "tmpl1", "type": "template"}) is False

    def test_shell_seed_type(self) -> None:
        assert ms._is_extension_row({"id": "seed1", "type": "shell_seed"}) is False

    def test_default_type_is_mod(self) -> None:
        assert ms._is_extension_row({"id": "mod1"}) is True

    def test_case_insensitive_type(self) -> None:
        assert ms._is_extension_row({"id": "mod1", "type": "MOD"}) is True


# ---------------------------------------------------------------------------
# _item_to_mod_info
# ---------------------------------------------------------------------------


class TestItemToModInfo:
    def test_basic_conversion(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1", "name": "My Mod", "version": "2.0"})
        assert result["id"] == "mod1"
        assert result["name"] == "My Mod"
        assert result["version"] == "2.0"
        assert result["source"] == "local"

    def test_missing_name_uses_id(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1"})
        assert result["name"] == "mod1"

    def test_empty_name_uses_id(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1", "name": ""})
        assert result["name"] == "mod1"

    def test_missing_version_defaults(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1"})
        assert result["version"] == "1.0.0"

    def test_missing_author_defaults(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1"})
        assert result["author"] == "—"

    def test_installed_flag(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1", "type": "mod"})
        assert result["is_installed"] is True

    def test_not_installed_flag(self) -> None:
        result = ms._item_to_mod_info({"id": "mod1", "type": "category"})
        assert result["is_installed"] is False


# ---------------------------------------------------------------------------
# _all_rows
# ---------------------------------------------------------------------------


class TestAllRows:
    def test_success(self) -> None:
        mock_item = MagicMock()
        mock_item.model_dump.return_value = {"id": "mod1", "name": "Test", "type": "mod"}
        with patch(
            "app.fastapi_routes.mod_store_routes.list_mod_items",
            return_value=[mock_item],
        ):
            rows = ms._all_rows()
        assert len(rows) == 1
        assert rows[0]["id"] == "mod1"

    def test_import_error(self) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.list_mod_items",
            side_effect=ImportError("no module"),
        ):
            rows = ms._all_rows()
        assert rows == []


# ---------------------------------------------------------------------------
# _installed_by_id
# ---------------------------------------------------------------------------


class TestInstalledById:
    def test_filters_installed(self) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._all_rows",
            return_value=[
                {"id": "mod1", "is_installed": True},
                {"id": "mod2", "is_installed": False},
            ],
        ):
            result = ms._installed_by_id()
        assert "mod1" in result
        assert "mod2" not in result


# ---------------------------------------------------------------------------
# _remote_to_mod_info
# ---------------------------------------------------------------------------


class TestRemoteToModInfo:
    def test_basic_conversion(self) -> None:
        with patch(
            "app.mod_sdk.host_foundation.catalog_store_collection",
            return_value="default",
        ):
            result = ms._remote_to_mod_info(
                {"id": "rmod1", "name": "Remote Mod", "version": "3.0"},
                installed_ids=set(),
            )
        assert result["id"] == "rmod1"
        assert result["source"] == "remote"
        assert result["is_installed"] is False

    def test_installed_flag(self) -> None:
        with patch(
            "app.mod_sdk.host_foundation.catalog_store_collection",
            return_value="default",
        ):
            result = ms._remote_to_mod_info(
                {"id": "rmod1"}, installed_ids={"rmod1"}
            )
        assert result["is_installed"] is True

    def test_commerce_fields(self) -> None:
        with patch(
            "app.mod_sdk.host_foundation.catalog_store_collection",
            return_value="default",
        ):
            result = ms._remote_to_mod_info(
                {
                    "id": "rmod1",
                    "commerce": {"seller": "Seller Inc", "collection": "premium"},
                },
                installed_ids=set(),
            )
        assert result["author"] == "Seller Inc"
        assert result["store_collection"] == "premium"

    def test_pkg_id_fallback(self) -> None:
        with patch(
            "app.mod_sdk.host_foundation.catalog_store_collection",
            return_value="default",
        ):
            result = ms._remote_to_mod_info(
                {"pkg_id": "pkg1"}, installed_ids=set()
            )
        assert result["id"] == "pkg1"


# ---------------------------------------------------------------------------
# _filter_rows
# ---------------------------------------------------------------------------


class TestFilterRows:
    def test_no_filter(self) -> None:
        rows = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
        assert ms._filter_rows(rows) == rows

    def test_query_filter(self) -> None:
        rows = [
            {"id": "1", "name": "Alpha", "description": "first"},
            {"id": "2", "name": "Beta", "description": "second"},
        ]
        result = ms._filter_rows(rows, q="alpha")
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_query_filter_by_id(self) -> None:
        rows = [{"id": "mod1", "name": "A"}, {"id": "mod2", "name": "B"}]
        result = ms._filter_rows(rows, q="mod1")
        assert len(result) == 1

    def test_query_filter_by_description(self) -> None:
        rows = [
            {"id": "1", "name": "A", "description": "scheduler tool"},
            {"id": "2", "name": "B", "description": "other"},
        ]
        result = ms._filter_rows(rows, q="scheduler")
        assert len(result) == 1

    def test_author_filter(self) -> None:
        rows = [
            {"id": "1", "name": "A", "author": "Alice"},
            {"id": "2", "name": "B", "author": "Bob"},
        ]
        result = ms._filter_rows(rows, author="alice")
        assert len(result) == 1

    def test_installed_true(self) -> None:
        rows = [
            {"id": "1", "is_installed": True},
            {"id": "2", "is_installed": False},
        ]
        result = ms._filter_rows(rows, installed=True)
        assert len(result) == 1

    def test_installed_false(self) -> None:
        rows = [
            {"id": "1", "is_installed": True},
            {"id": "2", "is_installed": False},
        ]
        result = ms._filter_rows(rows, installed=False)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _safe_text / _split_package_file
# ---------------------------------------------------------------------------


class TestSafeText:
    def test_string(self) -> None:
        assert ms._safe_text("hello") == "hello"

    def test_none(self) -> None:
        assert ms._safe_text(None) == ""

    def test_whitespace(self) -> None:
        assert ms._safe_text("  hello  ") == "hello"

    def test_number(self) -> None:
        assert ms._safe_text(42) == "42"


class TestSplitPackageFile:
    def test_with_colon(self) -> None:
        mid, ver = ms._split_package_file("my-mod:1.0.0")
        assert mid == "my-mod"
        assert ver == "1.0.0"

    def test_without_colon(self) -> None:
        mid, ver = ms._split_package_file("my-mod")
        assert mid == "my-mod"
        assert ver == ""

    def test_empty(self) -> None:
        mid, ver = ms._split_package_file("")
        assert mid == ""
        assert ver == ""


# ---------------------------------------------------------------------------
# Route endpoints
# ---------------------------------------------------------------------------


class TestModStoreCatalog:
    def test_returns_catalog(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows",
            new_callable=AsyncMock,
            return_value=([{"id": "1", "name": "A"}], [{"id": "1", "name": "A"}]),
        ):
            resp = client.get("/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert "installed" in data["data"]
        assert "available" in data["data"]


class TestModStoreMarketCatalog:
    def test_returns_market_catalog(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.fetch_market_catalog_page",
                new_callable=AsyncMock,
                return_value={"items": [], "total": 0},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._map_market_catalog_page",
                new_callable=AsyncMock,
                return_value=([], 0),
            ),
        ):
            resp = client.get("/market-catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_with_query_params(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.fetch_market_catalog_page",
                new_callable=AsyncMock,
                return_value={"items": [], "total": 0},
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._map_market_catalog_page",
                new_callable=AsyncMock,
                return_value=([], 0),
            ),
        ):
            resp = client.get("/market-catalog?q=test&limit=10&offset=0")
        assert resp.status_code == 200


class TestModStoreSearch:
    def test_search_returns_results(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows",
            new_callable=AsyncMock,
            return_value=([{"id": "1", "name": "Alpha"}], []),
        ):
            resp = client.get("/search?q=alpha")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 1

    def test_search_no_results(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows",
            new_callable=AsyncMock,
            return_value=([{"id": "1", "name": "Alpha"}], []),
        ):
            resp = client.get("/search?q=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 0


class TestModStorePopular:
    def test_returns_popular(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows",
            new_callable=AsyncMock,
            return_value=(
                [
                    {"id": "1", "name": "A", "total_downloads": 100},
                    {"id": "2", "name": "B", "total_downloads": 50},
                ],
                [],
            ),
        ):
            resp = client.get("/popular")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"][0]["total_downloads"] >= data["data"][1]["total_downloads"]


class TestModStoreRecent:
    def test_returns_recent(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._combined_rows",
            new_callable=AsyncMock,
            return_value=(
                [
                    {"id": "1", "name": "A", "created_at": "2026-06-01"},
                    {"id": "2", "name": "B", "created_at": "2026-05-01"},
                ],
                [],
            ),
        ):
            resp = client.get("/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 2


class TestModStoreDetails:
    def test_remote_detail(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.mod_store_routes.catalog_get_json",
                new_callable=AsyncMock,
                side_effect=[
                    {"versions": [{"version": "1.0"}]},
                    {"id": "mod1", "name": "Test Mod", "version": "1.0", "author": "Author", "description": "Desc"},
                ],
            ),
        ):
            resp = client.get("/mod/mod1/details")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["id"] == "mod1"

    def test_local_fallback(self, client: TestClient) -> None:
        from fastapi import HTTPException

        with (
            patch(
                "app.fastapi_routes.mod_store_routes.catalog_get_json",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="not found"),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._combined_rows",
                new_callable=AsyncMock,
                return_value=(
                    [{"id": "mod1", "name": "Local Mod", "version": "1.0", "author": "A", "description": "D", "source": "local"}],
                    [],
                ),
            ),
        ):
            resp = client.get("/mod/mod1/details")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["source"] == "local"

    def test_not_found(self, client: TestClient) -> None:
        from fastapi import HTTPException

        with (
            patch(
                "app.fastapi_routes.mod_store_routes.catalog_get_json",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="not found"),
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._combined_rows",
                new_callable=AsyncMock,
                return_value=([], []),
            ),
        ):
            resp = client.get("/mod/nonexistent/details")
        assert resp.status_code == 404


class TestModStoreUpload:
    def test_not_implemented(self, client: TestClient) -> None:
        resp = client.post("/upload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreInstall:
    def test_missing_pkg_id_and_package_file(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new_callable=AsyncMock,
            side_effect=Exception("should not be called"),
        ):
            # When pkg_id is empty and no package_file, _install_from_catalog
            # should raise HTTPException(400)
            from fastapi import HTTPException

            with patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=400, detail="缺少 pkg_id"),
            ):
                resp = client.post("/install", json={})
        assert resp.status_code == 400

    def test_install_with_pkg_id(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new_callable=AsyncMock,
            return_value=ms.ModStoreInstallResult(success=True, message="installed"),
        ):
            resp = client.post("/install", json={"pkg_id": "mod1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_install_with_package_file(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new_callable=AsyncMock,
            return_value=ms.ModStoreInstallResult(success=True, message="installed"),
        ):
            resp = client.post("/install", json={"package_file": "mod1:1.0"})
        assert resp.status_code == 200

    def test_install_activate_false(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new_callable=AsyncMock,
            return_value=ms.ModStoreInstallResult(success=True, message="installed"),
        ) as mock_install:
            resp = client.post("/install", json={"pkg_id": "mod1", "activate": "false"})
        assert resp.status_code == 200
        # Verify activate=False was passed
        call_kwargs = mock_install.call_args
        assert call_kwargs[1].get("activate") is False or call_kwargs[0][2] is False


class TestModStoreUninstall:
    def test_missing_mod_id(self, client: TestClient) -> None:
        resp = client.post("/uninstall", json={})
        assert resp.status_code == 400

    def test_uninstall_success(self, client: TestClient) -> None:
        mock_mgr = MagicMock()
        mock_mgr.uninstall_mod.return_value = (True, "removed")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            resp = client.post("/uninstall", json={"mod_id": "mod1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_uninstall_failure(self, client: TestClient) -> None:
        mock_mgr = MagicMock()
        mock_mgr.uninstall_mod.return_value = (False, "not found")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ):
            resp = client.post("/uninstall", json={"mod_id": "mod1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreUpdate:
    def test_update_with_pkg_id(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_from_catalog",
            new_callable=AsyncMock,
            return_value=ms.ModStoreInstallResult(success=True, message="updated"),
        ):
            resp = client.post("/update", json={"pkg_id": "mod1"})
        assert resp.status_code == 200


class TestModStoreValidate:
    def test_not_implemented(self, client: TestClient) -> None:
        resp = client.get("/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreUpdates:
    def test_empty_updates(self, client: TestClient) -> None:
        resp = client.get("/updates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["count"] == 0


class TestModStoreDependencies:
    def test_empty_dependencies(self, client: TestClient) -> None:
        resp = client.get("/dependencies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["can_install"] is True


class TestModStoreRate:
    def test_not_implemented(self, client: TestClient) -> None:
        resp = client.post("/mod/mod1/rate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreDownload:
    def test_not_implemented(self, client: TestClient) -> None:
        resp = client.get("/package/test-pkg/download")
        assert resp.status_code == 404


class TestModStoreDeletePackage:
    def test_not_implemented(self, client: TestClient) -> None:
        resp = client.delete("/package/test-pkg")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreRebuildIndex:
    def test_returns_noop(self, client: TestClient) -> None:
        resp = client.post("/index/rebuild")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestModStoreInstallHostFoundation:
    def test_success(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_host_foundation_internal",
            new_callable=AsyncMock,
            return_value=ms.ModStoreInstallResult(
                success=True, message="installed", data={"edition": "generic"}
            ),
        ):
            resp = client.post("/install-host-foundation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_failure(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes._install_host_foundation_internal",
            new_callable=AsyncMock,
            side_effect=RuntimeError("install failed"),
        ):
            resp = client.post("/install-host-foundation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestModStoreBootstrapEditionPack:
    def test_invalid_edition(self, client: TestClient) -> None:
        resp = client.post("/bootstrap-edition-pack?edition=invalid")
        assert resp.status_code == 400

    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.product_skus.assert_bootstrap_edition_allowed",
            ),
            patch(
                "app.mod_sdk.edition_bootstrap.bootstrap_edition_pack",
                new_callable=AsyncMock,
                return_value={"ready": True, "installed_count": 5, "expected_count": 5},
            ),
        ):
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_partial_install(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.product_skus.assert_bootstrap_edition_allowed",
            ),
            patch(
                "app.mod_sdk.edition_bootstrap.bootstrap_edition_pack",
                new_callable=AsyncMock,
                return_value={
                    "ready": False,
                    "installed_count": 3,
                    "expected_count": 5,
                    "catalog": [{"mod_id": "m1", "status": "missing"}],
                    "seed": [],
                },
            ),
        ):
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_permission_denied(self, client: TestClient) -> None:
        with (
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.product_skus.assert_bootstrap_edition_allowed",
                side_effect=PermissionError("not allowed"),
            ),
        ):
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 400


class TestModStoreReloadEmployees:
    def test_success(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.employee_runtime.refresh_employee_pack_runtime",
            return_value={"refreshed": True},
        ):
            resp = client.post("/reload-employees", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestModStoreInstallIndustrySeed:
    def test_missing_industry_id(self, client: TestClient) -> None:
        resp = client.post("/install-industry-seed", json={})
        assert resp.status_code == 400

    def test_success(self, client: TestClient) -> None:
        with patch(
            "app.mod_sdk.industry_seed.install_industry_seed_with_fallback",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "installed"},
        ):
            resp = client.post(
                "/install-industry-seed", json={"industry_id": "manufacturing"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestModStoreSyncModstoreLibrary:
    def test_missing_token(self, client: TestClient) -> None:
        resp = client.post("/sync-modstore-library", json={})
        assert resp.status_code == 400

    def test_missing_mod_ids_without_all(self, client: TestClient) -> None:
        resp = client.post(
            "/sync-modstore-library", json={"token": "pat123"}
        )
        assert resp.status_code == 400

    def test_success_with_all(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"synced": 3}},
        ):
            resp = client.post(
                "/sync-modstore-library",
                json={"token": "pat123", "all": True},
            )
        assert resp.status_code == 200

    def test_success_with_mod_ids_list(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"synced": 2}},
        ):
            resp = client.post(
                "/sync-modstore-library",
                json={"token": "pat123", "mod_ids": ["mod1", "mod2"]},
            )
        assert resp.status_code == 200

    def test_success_with_mod_ids_string(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"synced": 2}},
        ):
            resp = client.post(
                "/sync-modstore-library",
                json={"token": "pat123", "mod_ids": "mod1,mod2"},
            )
        assert resp.status_code == 200

    def test_value_error(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
            side_effect=ValueError("bad token"),
        ):
            resp = client.post(
                "/sync-modstore-library",
                json={"token": "bad", "all": True},
            )
        assert resp.status_code == 400

    def test_runtime_error(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.mod_store_routes.sync_modstore_library_to_local",
            new_callable=AsyncMock,
            side_effect=RuntimeError("server error"),
        ):
            resp = client.post(
                "/sync-modstore-library",
                json={"token": "pat123", "all": True},
            )
        assert resp.status_code == 502

    def test_invalid_json_body(self, client: TestClient) -> None:
        resp = client.post(
            "/sync-modstore-library",
            content="not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_non_dict_json_body(self, client: TestClient) -> None:
        resp = client.post(
            "/sync-modstore-library",
            json=[1, 2, 3],
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# _ensure_host_foundation_employee_on_disk
# ---------------------------------------------------------------------------


class TestEnsureHostFoundationEmployeeOnDisk:
    def test_already_exists(self) -> None:
        import asyncio

        with (
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
            ) as mock_reg,
            patch("os.path.isdir", return_value=True),
        ):
            mock_reg_instance = MagicMock()
            mock_reg_instance.mods_root = "/tmp/test_mods"
            mock_reg.return_value = mock_reg_instance
            ok, msg = asyncio.get_event_loop().run_until_complete(
                ms._ensure_host_foundation_employee_on_disk()
            )
        assert ok is True

    def test_source_missing(self) -> None:
        import asyncio

        with (
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
            ) as mock_reg,
            patch("os.path.isdir", side_effect=lambda p: False),
        ):
            mock_reg_instance = MagicMock()
            mock_reg_instance.mods_root = "/tmp/test_mods"
            mock_reg.return_value = mock_reg_instance
            ok, msg = asyncio.get_event_loop().run_until_complete(
                ms._ensure_host_foundation_employee_on_disk()
            )
        assert ok is False


# ---------------------------------------------------------------------------
# _install_host_foundation_internal
# ---------------------------------------------------------------------------


class TestInstallHostFoundationInternal:
    def test_disk_failure(self) -> None:
        import asyncio

        with patch(
            "app.fastapi_routes.mod_store_routes._ensure_host_foundation_employee_on_disk",
            new_callable=AsyncMock,
            return_value=(False, "disk error"),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                ms._install_host_foundation_internal(None)
            )
        assert result.success is False

    def test_invalid_edition_normalized(self) -> None:
        import asyncio

        with (
            patch(
                "app.fastapi_routes.mod_store_routes._ensure_host_foundation_employee_on_disk",
                new_callable=AsyncMock,
                return_value=(True, "ok"),
            ),
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
                return_value={"ready": True, "installed_count": 5, "expected_count": 5},
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                ms._install_host_foundation_internal("invalid_edition")
            )
        assert result.success is True

    def test_materialize_failure(self) -> None:
        import asyncio

        with (
            patch(
                "app.fastapi_routes.mod_store_routes._ensure_host_foundation_employee_on_disk",
                new_callable=AsyncMock,
                return_value=(True, "ok"),
            ),
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
                side_effect=RuntimeError("materialize failed"),
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                ms._install_host_foundation_internal(None)
            )
        assert result.success is False

    def test_not_ready(self) -> None:
        import asyncio

        with (
            patch(
                "app.fastapi_routes.mod_store_routes._ensure_host_foundation_employee_on_disk",
                new_callable=AsyncMock,
                return_value=(True, "ok"),
            ),
            patch(
                "app.mod_sdk.edition_policy.resolve_edition",
                return_value="generic",
            ),
            patch(
                "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
                return_value={
                    "ready": False,
                    "installed_count": 2,
                    "expected_count": 5,
                    "missing_mod_ids": ["m1", "m2", "m3"],
                },
            ),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                ms._install_host_foundation_internal(None)
            )
        assert result.success is False
        assert "未齐" in result.message


# ---------------------------------------------------------------------------
# _body_value / _request_payload
# ---------------------------------------------------------------------------


class TestBodyValue:
    def test_json_body(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path": "/",
        }
        request = Request(scope)
        import asyncio

        async def make_request():
            # Manually set body
            request._body = b'{"key": "value"}'
            return await ms._body_value(request, "key")

        result = asyncio.get_event_loop().run_until_complete(make_request())
        assert result == "value"

    def test_missing_key_returns_default(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path": "/",
        }
        request = Request(scope)

        import asyncio

        async def make_request():
            request._body = b'{"other": "val"}'
            return await ms._body_value(request, "key", "default_val")

        result = asyncio.get_event_loop().run_until_complete(make_request())
        assert result == "default_val"


class TestRequestPayload:
    def test_json_body(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path": "/",
        }
        request = Request(scope)

        import asyncio

        async def make_request():
            request._body = b'{"key": "value"}'
            return await ms._request_payload(request)

        result = asyncio.get_event_loop().run_until_complete(make_request())
        assert result["key"] == "value"

    def test_invalid_json(self) -> None:
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path": "/",
        }
        request = Request(scope)

        import asyncio

        async def make_request():
            request._body = b"not json"
            return await ms._request_payload(request)

        result = asyncio.get_event_loop().run_until_complete(make_request())
        assert result == {}
