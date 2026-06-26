"""Branch-coverage tests for app.fastapi_routes.mod_store_routes.

Targets the missing branches identified by coverage:
  - Lines 212-230:  _remote_rows (async iter, empty mid skip, hidden skip, HTTPException)
  - Line 258->260:  _map_market_catalog_page hint truthy branch
  - Lines 295-313:  _combined_rows full flow
  - Lines 388-457:  _install_from_catalog all branches
  - Lines 537->559, 561->560: mod_store_details fallback + match
  - Lines 744-758:  _ensure_host_foundation_employee_on_disk
  - Lines 762-787:  _install_host_foundation_internal
  - Lines 836->833, 838->833, 843->840: mod_store_bootstrap_edition_pack loop branches

Monkeypatching strategy: because the dependency modules are thin stubs
registered in sys.modules (not real package trees), we patch them via
``sys.modules["<name>"].<attr>`` rather than via dotted-string paths.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Module-level stubs: inject thin fake modules so the import chain works
# even when heavy infrastructure is absent.
# ---------------------------------------------------------------------------


def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


for _pkg in [
    "app",
    "app.application",
    "app.shell",
    "app.utils",
    "app.mod_sdk",
    "app.infrastructure",
    "app.infrastructure.mods",
    "app.enterprise",
]:
    _ensure_stub(_pkg)

_op_errors_mod = _ensure_stub(
    "app.utils.operational_errors",
    {
        "RECOVERABLE_ERRORS": (
            OSError,
            ValueError,
            RuntimeError,
            ImportError,
            KeyError,
            AttributeError,
            TypeError,
            LookupError,
            ConnectionError,
            TimeoutError,
        ),
    },
)

_catalog_app_mod = _ensure_stub(
    "app.application.mod_store_catalog_app",
    {
        "catalog_base_url": lambda: "https://catalog.example.com",
        "catalog_get_json": AsyncMock(return_value={}),
        "catalog_download_to": AsyncMock(return_value=None),
        "fetch_market_catalog_page": AsyncMock(return_value={"items": [], "total": 0}),
        "iter_catalog_packages": MagicMock(),
        "normalize_package_zip_path": lambda p: p,
        "sync_modstore_library_to_local": AsyncMock(
            return_value={"success": True, "message": "ok", "data": {}}
        ),
        "is_public_catalog_row": lambda row: True,
        "market_item_to_package_row": lambda raw: raw,
    },
)

_shell_mod = _ensure_stub(
    "app.shell.mods_catalog",
    {"list_mod_items": MagicMock(return_value=[])},
)

_hf_mod = _ensure_stub(
    "app.mod_sdk.host_foundation",
    {
        "HOST_FOUNDATION_EMPLOYEE_PACK_ID": "xcagi-host-foundation-employee",
        "host_foundation_catalog_row": lambda installed=False: {
            "id": "xcagi-host-foundation-employee",
            "name": "Host Foundation",
            "version": "1.0.0",
            "author": "XCAGI",
            "description": "",
            "is_installed": installed,
            "source": "remote",
            "catalog_base_url": "https://catalog.example.com",
            "public_listing": False,
        },
        "is_host_foundation_pack_installed": MagicMock(return_value=False),
        "is_infrastructure_mod_hidden_from_store": MagicMock(return_value=False),
        "catalog_store_collection": MagicMock(return_value=""),
        "inject_aux_employee_pack_rows": MagicMock(),
        "is_host_foundation_employee_pack": MagicMock(return_value=False),
        "is_aux_employee_pack_mod_id": MagicMock(return_value=False),
        "install_aux_employee_pack_from_repo_seed": MagicMock(return_value=(True, "ok")),
        "materialize_host_foundation_bridges": MagicMock(
            return_value={"ready": True, "installed_count": 1, "expected_count": 1}
        ),
    },
)

_industry_seed_mod = _ensure_stub(
    "app.mod_sdk.industry_seed",
    {
        "install_industry_seed_with_fallback": AsyncMock(
            return_value={"success": True, "message": "installed"}
        )
    },
)

_cds_mod = _ensure_stub(
    "app.mod_sdk.customer_delivery_seed",
    {
        "install_customer_delivery_seed_package": AsyncMock(
            return_value={"success": True, "message": "delivered"}
        )
    },
)

_emp_rt_mod = _ensure_stub(
    "app.mod_sdk.employee_runtime",
    {"refresh_employee_pack_runtime": MagicMock(return_value={"refreshed": True})},
)

_ed_policy_mod = _ensure_stub(
    "app.mod_sdk.edition_policy",
    {"resolve_edition": MagicMock(return_value="generic")},
)

_ed_bootstrap_mod = _ensure_stub(
    "app.mod_sdk.edition_bootstrap",
    {
        "bootstrap_edition_pack": AsyncMock(
            return_value={"ready": True, "installed_count": 1, "expected_count": 1}
        )
    },
)

_prod_skus_mod = _ensure_stub(
    "app.mod_sdk.product_skus",
    {"assert_bootstrap_edition_allowed": MagicMock(return_value=None)},
)

_entitlements_mod = _ensure_stub(
    "app.enterprise.mod_entitlements",
    {
        "enterprise_mod_filter_active": MagicMock(return_value=False),
        "sync_entitlements_from_request": AsyncMock(return_value=None),
        "get_cached_entitled_client_mod_ids": MagicMock(return_value=set()),
    },
)

_mm_mock = MagicMock(
    install_mod_package=MagicMock(return_value=(True, "installed", None)),
    uninstall_mod=MagicMock(return_value=(True, "uninstalled")),
)
_mod_manager_mod = _ensure_stub(
    "app.infrastructure.mods.mod_manager",
    {"get_mod_manager": MagicMock(return_value=_mm_mock)},
)
_emp_registry_mod = _ensure_stub(
    "app.infrastructure.mods.employee_registry",
    {
        "get_employee_registry": MagicMock(
            return_value=MagicMock(
                mods_root="/tmp/mods",
                install_from_package=MagicMock(return_value=(True, "ok")),
            )
        ),
        "employees_root": MagicMock(return_value="/tmp/employees"),
    },
)
_ensure_stub(
    "app.infrastructure.mods.artifact_constants",
    {"ARTIFACT_EMPLOYEE_PACK": "employee_pack"},
)
_ensure_stub(
    "app.infrastructure.mods.artifact_package",
    {"peek_artifact": MagicMock(return_value="mod")},
)

# ---------------------------------------------------------------------------
# Import the module under test (AFTER stubs are in place)
# ---------------------------------------------------------------------------
import app.fastapi_routes.mod_store_routes as _mod  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_stub(module_name: str, attr: str, value: Any) -> Any:
    mod = sys.modules[module_name]
    old = getattr(mod, attr, None)
    setattr(mod, attr, value)
    return old


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(_mod.router)
    return TestClient(app, raise_server_exceptions=False)


def _sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _patch_combined_rows(available=None, installed=None):
    available = available or []
    installed = installed or []
    return patch.object(_mod, "_combined_rows", AsyncMock(return_value=(available, installed)))


# ===========================================================================
# 1. _remote_rows — lines 212-230
# ===========================================================================


class TestRemoteRows:
    """Cover all branches of _remote_rows."""

    def test_empty_iter_returns_empty_list(self):
        """No packages from catalog → empty list."""

        async def _empty_iter():
            if False:
                yield {}

        with patch.object(_mod, "iter_catalog_packages", _empty_iter):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                result = _sync(_mod._remote_rows())
        assert result == []

    def test_row_with_empty_mid_skipped(self):
        """Branch: mid is empty → continue."""

        async def _iter():
            yield {"id": ""}
            yield {"id": "  "}
            yield {"id": "real-mod"}

        with patch.object(_mod, "iter_catalog_packages", _iter):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                result = _sync(_mod._remote_rows())
        assert len(result) == 1
        assert result[0]["id"] == "real-mod"

    def test_hidden_infra_mod_without_public_listing_skipped(self):
        """Branch: is_infrastructure_mod_hidden_from_store=True and no public_listing → skip."""

        async def _iter():
            yield {"id": "hidden-mod", "public_listing": False}
            yield {"id": "visible-mod", "public_listing": True}

        old = sys.modules["app.mod_sdk.host_foundation"].is_infrastructure_mod_hidden_from_store
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(
            side_effect=lambda mid: mid == "hidden-mod"
        )
        try:
            with patch.object(_mod, "iter_catalog_packages", _iter):
                with patch.object(_mod, "_installed_by_id", return_value={}):
                    result = _sync(_mod._remote_rows())
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old
        ids = [r["id"] for r in result]
        assert "hidden-mod" not in ids
        assert "visible-mod" in ids

    def test_hidden_infra_mod_with_public_listing_included(self):
        """Branch: hidden but public_listing=True → included."""

        async def _iter():
            yield {"id": "hidden-listed", "public_listing": True}

        old = sys.modules["app.mod_sdk.host_foundation"].is_infrastructure_mod_hidden_from_store
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(return_value=True)
        try:
            with patch.object(_mod, "iter_catalog_packages", _iter):
                with patch.object(_mod, "_installed_by_id", return_value={}):
                    result = _sync(_mod._remote_rows())
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old
        assert len(result) == 1
        assert result[0]["id"] == "hidden-listed"

    def test_http_exception_caught_returns_empty(self):
        """Branch: HTTPException from iter → caught, return empty."""

        async def _iter():
            raise HTTPException(status_code=503, detail="catalog down")
            yield {}  # never reached

        with patch.object(_mod, "iter_catalog_packages", _iter):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                result = _sync(_mod._remote_rows())
        assert result == []


# ===========================================================================
# 2. _map_market_catalog_page — hint truthy branch (258->260)
# ===========================================================================


class TestMapMarketCatalogPageHintBranch:
    """Cover the hint truthy branch at line 258->260."""

    def test_hint_truthy_sets_store_collection(self):
        """When collection_hint is truthy, info['store_collection'] = hint."""
        sys.modules["app.application.mod_store_catalog_app"].is_public_catalog_row = MagicMock(
            return_value=True
        )
        sys.modules[
            "app.application.mod_store_catalog_app"
        ].market_item_to_package_row = MagicMock(
            return_value={"id": "p1", "commerce": {"collection": "from_commerce"}}
        )
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value=""
        )
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = _sync(
                _mod._map_market_catalog_page(
                    {"items": [{"id": "p1"}], "total": 1},
                    collection_hint="hint_value",
                )
            )
        assert len(items) == 1
        assert items[0]["store_collection"] == "hint_value"

    def test_hint_empty_falls_back_to_commerce_collection(self):
        """When collection_hint is empty, use commerce collection."""
        sys.modules["app.application.mod_store_catalog_app"].is_public_catalog_row = MagicMock(
            return_value=True
        )
        sys.modules[
            "app.application.mod_store_catalog_app"
        ].market_item_to_package_row = MagicMock(
            return_value={"id": "p1", "commerce": {"collection": "commerce_coll"}}
        )
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value=""
        )
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = _sync(
                _mod._map_market_catalog_page(
                    {"items": [{"id": "p1"}], "total": 1},
                    collection_hint="",
                )
            )
        assert len(items) == 1
        assert items[0]["store_collection"] == "commerce_coll"


# ===========================================================================
# 3. _combined_rows — lines 295-313
# ===========================================================================


class TestCombinedRows:
    """Cover the full _combined_rows flow."""

    def test_merges_remote_and_installed(self):
        """Remote rows + installed-only rows are merged."""
        remote_rows = [{"id": "r1", "source": "remote"}, {"id": "r2", "source": "remote"}]
        installed_map = {
            "r1": {"id": "r1", "source": "local", "is_installed": True},
            "i1": {"id": "i1", "source": "local", "is_installed": True},
        }
        with (
            patch.object(_mod, "_installed_by_id", return_value=installed_map),
            patch.object(_mod, "_remote_rows", AsyncMock(return_value=remote_rows)),
            patch.object(_mod, "_inject_host_foundation_row") as mock_inject,
            patch(
                "app.mod_sdk.host_foundation.inject_aux_employee_pack_rows"
            ) as mock_aux,
        ):
            available, installed_visible = _sync(_mod._combined_rows())
        # r1 already in remote (seen), i1 is new
        ids = [r["id"] for r in available]
        assert "r1" in ids
        assert "r2" in ids
        assert "i1" in ids
        # installed_visible includes all installed (none hidden by default stub)
        installed_ids = [r["id"] for r in installed_visible]
        assert "r1" in installed_ids
        assert "i1" in installed_ids
        mock_inject.assert_called_once()
        mock_aux.assert_called_once()

    def test_hidden_installed_mod_excluded_from_installed_visible(self):
        """Hidden infra mod excluded from installed_visible list."""
        remote_rows = []
        installed_map = {
            "hidden-1": {"id": "hidden-1", "source": "local", "is_installed": True},
            "visible-1": {"id": "visible-1", "source": "local", "is_installed": True},
        }
        old = sys.modules["app.mod_sdk.host_foundation"].is_infrastructure_mod_hidden_from_store
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(
            side_effect=lambda mid: mid == "hidden-1"
        )
        try:
            with (
                patch.object(_mod, "_installed_by_id", return_value=installed_map),
                patch.object(_mod, "_remote_rows", AsyncMock(return_value=remote_rows)),
                patch.object(_mod, "_inject_host_foundation_row"),
                patch("app.mod_sdk.host_foundation.inject_aux_employee_pack_rows"),
            ):
                available, installed_visible = _sync(_mod._combined_rows())
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old
        # hidden-1 not added to available (already not in seen, but hidden)
        avail_ids = [r["id"] for r in available]
        assert "hidden-1" not in avail_ids
        assert "visible-1" in avail_ids
        # hidden-1 excluded from installed_visible
        vis_ids = [r["id"] for r in installed_visible]
        assert "hidden-1" not in vis_ids
        assert "visible-1" in vis_ids


# ===========================================================================
# 4. _install_from_catalog — lines 388-457
# ===========================================================================


class TestInstallFromCatalog:
    """Cover all branches of _install_from_catalog."""

    def test_host_foundation_pack_delegates_to_internal(self):
        """Branch: is_host_foundation_employee_pack=True → _install_host_foundation_internal."""
        old = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_employee_pack
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_employee_pack = MagicMock(
            return_value=True
        )
        try:
            with patch.object(
                _mod,
                "_install_host_foundation_internal",
                AsyncMock(
                    return_value=_mod.ModStoreInstallResult(
                        success=True, message="hf installed"
                    )
                ),
            ) as mock_internal:
                result = _sync(_mod._install_from_catalog("hf-pack", "1.0"))
            mock_internal.assert_called_once_with(edition=None)
            assert result.success is True
        finally:
            sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_employee_pack = old

    def test_aux_employee_pack_ok_returns_success(self):
        """Branch: is_aux_employee_pack_mod_id=True, ok=True → return success."""
        old_aux = sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id
        old_seed = sys.modules[
            "app.mod_sdk.host_foundation"
        ].install_aux_employee_pack_from_repo_seed
        sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id = MagicMock(
            return_value=True
        )
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].install_aux_employee_pack_from_repo_seed = MagicMock(
            return_value=(True, "aux seeded")
        )
        try:
            result = _sync(_mod._install_from_catalog("aux-pack", "1.0", activate=False))
        finally:
            sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id = old_aux
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].install_aux_employee_pack_from_repo_seed = old_seed
        assert result.success is True
        assert result.message == "aux seeded"
        assert result.data == {"id": "aux-pack"}

    def test_aux_employee_pack_fail_falls_through_to_catalog(self):
        """Branch: is_aux_employee_pack_mod_id=True, ok=False → falls through."""
        old_aux = sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id
        old_seed = sys.modules[
            "app.mod_sdk.host_foundation"
        ].install_aux_employee_pack_from_repo_seed
        sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id = MagicMock(
            return_value=True
        )
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].install_aux_employee_pack_from_repo_seed = MagicMock(
            return_value=(False, "seed failed")
        )
        try:
            with patch.object(_mod, "catalog_get_json", AsyncMock(
                return_value={"versions": [{"version": "2.0"}]}
            )):
                with patch.object(_mod, "catalog_download_to", AsyncMock()):
                    with patch(
                        "app.infrastructure.mods.artifact_package.peek_artifact",
                        return_value="mod",
                    ):
                        with patch(
                            "app.infrastructure.mods.mod_manager.get_mod_manager"
                        ) as mock_mgr:
                            mock_mgr.return_value.install_mod_package.return_value = (
                                True,
                                "ok",
                                None,
                            )
                            result = _sync(
                                _mod._install_from_catalog("aux-pack", "", activate=True)
                            )
        finally:
            sys.modules["app.mod_sdk.host_foundation"].is_aux_employee_pack_mod_id = old_aux
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].install_aux_employee_pack_from_repo_seed = old_seed
        assert result.success is True

    def test_empty_pkg_id_raises_400(self):
        """Branch: not pkg_id → raise HTTPException 400."""
        with pytest.raises(HTTPException) as exc_info:
            _sync(_mod._install_from_catalog("", "1.0"))
        assert exc_info.value.status_code == 400
        assert "pkg_id" in exc_info.value.detail

    def test_empty_version_fetches_from_catalog_dict_row(self):
        """Branch: not version → fetch versions, rows[0] is dict."""
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(return_value={"versions": [{"version": "3.5"}]}),
            ),
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
        ):
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", None)
            result = _sync(_mod._install_from_catalog("my-mod", "", activate=True))
        assert result.success is True

    def test_empty_version_fetches_from_catalog_string_row(self):
        """Branch: not version → fetch versions, rows[0] is string (not dict)."""
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(return_value={"versions": ["4.0"]}),
            ),
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
        ):
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", None)
            result = _sync(_mod._install_from_catalog("my-mod", "", activate=True))
        assert result.success is True

    def test_empty_version_after_fetch_raises_400(self):
        """Branch: version still empty after fetch → raise 400."""
        with patch.object(
            _mod,
            "catalog_get_json",
            AsyncMock(return_value={"versions": []}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _sync(_mod._install_from_catalog("my-mod", "", activate=True))
        assert exc_info.value.status_code == 400
        assert "version" in exc_info.value.detail

    def test_employee_pack_artifact_installs_via_registry(self):
        """Branch: peek_artifact == ARTIFACT_EMPLOYEE_PACK → install via employee_registry."""
        with (
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="employee_pack",
            ),
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry"
            ) as mock_reg,
        ):
            mock_reg.return_value.install_from_package.return_value = (True, "emp installed")
            result = _sync(_mod._install_from_catalog("my-mod", "1.0", activate=True))
        assert result.success is True
        assert result.message == "emp installed"

    def test_mod_artifact_installs_via_mod_manager_with_metadata(self):
        """Branch: mod artifact → install via mod_manager with dataclass metadata."""
        metadata = MagicMock()
        with (
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
            patch("dataclasses.is_dataclass", return_value=True),
            patch("dataclasses.asdict", return_value={"meta": "data"}),
        ):
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", metadata)
            result = _sync(_mod._install_from_catalog("my-mod", "1.0", activate=True))
        assert result.success is True
        assert result.data == {"meta": "data"}

    def test_mod_artifact_installs_via_mod_manager_without_metadata(self):
        """Branch: mod artifact → install via mod_manager, metadata is None."""
        with (
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
        ):
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", None)
            result = _sync(_mod._install_from_catalog("my-mod", "1.0", activate=False))
        assert result.success is True
        assert result.data is None

    def test_finally_cleans_up_temp_files(self):
        """Branch: finally block deletes temp files."""
        with (
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.path.exists", return_value=True),
            patch("os.unlink") as mock_unlink,
        ):
            mock_tmp.return_value.name = "/tmp/fake.zip"
            mock_tmp.return_value.close = MagicMock()
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", None)
            result = _sync(_mod._install_from_catalog("my-mod", "1.0"))
        assert result.success is True
        mock_unlink.assert_called()

    def test_finally_swallows_oserror_on_cleanup(self):
        """Branch: finally block OSError on unlink is swallowed."""
        with (
            patch.object(_mod, "catalog_download_to", AsyncMock()),
            patch(
                "app.infrastructure.mods.artifact_package.peek_artifact",
                return_value="mod",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mgr,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.path.exists", return_value=True),
            patch("os.unlink", side_effect=OSError("permission denied")),
        ):
            mock_tmp.return_value.name = "/tmp/fake.zip"
            mock_tmp.return_value.close = MagicMock()
            mock_mgr.return_value.install_mod_package.return_value = (True, "ok", None)
            result = _sync(_mod._install_from_catalog("my-mod", "1.0"))
        # Should not raise despite OSError in cleanup
        assert result.success is True


# ===========================================================================
# 5. mod_store_details — fallback branches (537->559, 561->560)
# ===========================================================================


class TestModStoreDetailsFallback:
    """Cover the fallback branches in mod_store_details."""

    def test_empty_versions_list_falls_through_to_local(self):
        """Branch: versions list is empty → falls through to combined_rows."""
        rows = [
            {
                "id": "local-mod",
                "name": "Local",
                "version": "1.0",
                "author": "A",
                "description": "D",
                "source": "local",
                "catalog_base_url": "",
            }
        ]
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(return_value={"versions": []}),
            ),
            _patch_combined_rows(available=rows),
        ):
            with _make_client() as client:
                resp = client.get("/mod/local-mod/details")
        assert resp.status_code == 200
        assert resp.json()["data"]["source"] == "local"

    def test_versions_not_list_falls_through_to_local(self):
        """Branch: versions is not a list → falls through."""
        rows = [
            {
                "id": "local-mod",
                "name": "Local",
                "version": "1.0",
                "author": "A",
                "description": "D",
                "source": "local",
                "catalog_base_url": "",
            }
        ]
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(return_value={"versions": "not-a-list"}),
            ),
            _patch_combined_rows(available=rows),
        ):
            with _make_client() as client:
                resp = client.get("/mod/local-mod/details")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "local-mod"

    def test_for_loop_finds_matching_row(self):
        """Branch: 561->560 — for loop finds matching row in combined_rows."""
        rows = [
            {
                "id": "found-mod",
                "name": "Found",
                "version": "2.0",
                "author": "B",
                "description": "Found desc",
                "source": "local",
                "catalog_base_url": "https://x.com",
            }
        ]
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(side_effect=HTTPException(status_code=404, detail="not found")),
            ),
            _patch_combined_rows(available=rows),
        ):
            with _make_client() as client:
                resp = client.get("/mod/found-mod/details")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "found-mod"
        assert data["name"] == "Found"
        assert data["source"] == "local"

    def test_for_loop_no_match_raises_404(self):
        """Branch: for loop finds no match → 404."""
        rows = [{"id": "other-mod", "name": "Other", "version": "1.0", "author": "", "description": "", "source": "local", "catalog_base_url": ""}]
        with (
            patch.object(
                _mod,
                "catalog_get_json",
                AsyncMock(side_effect=HTTPException(status_code=404, detail="not found")),
            ),
            _patch_combined_rows(available=rows),
        ):
            with _make_client() as client:
                resp = client.get("/mod/missing-mod/details")
        assert resp.status_code == 404


# ===========================================================================
# 6. _ensure_host_foundation_employee_on_disk — lines 744-758
# ===========================================================================


class TestEnsureHostFoundationEmployeeOnDisk:
    """Cover all branches of _ensure_host_foundation_employee_on_disk."""

    def test_dest_already_exists_returns_early(self):
        """Branch: dest is dir → return (True, 'employee pack present')."""
        with (
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_reg,
            patch("app.infrastructure.mods.employee_registry.employees_root", return_value="/tmp/emp"),
            patch("os.path.isdir", return_value=True),
        ):
            mock_reg.return_value.mods_root = "/tmp/mods"
            result = _sync(_mod._ensure_host_foundation_employee_on_disk())
        assert result == (True, "employee pack present")

    def test_src_missing_returns_false(self):
        """Branch: src not a dir → return (False, '内置员工包目录缺失')."""
        with (
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_reg,
            patch("app.infrastructure.mods.employee_registry.employees_root", return_value="/tmp/emp"),
            patch("os.path.isdir", side_effect=lambda p: False),
        ):
            mock_reg.return_value.mods_root = "/tmp/mods"
            result = _sync(_mod._ensure_host_foundation_employee_on_disk())
        assert result[0] is False
        assert "内置员工包目录缺失" in result[1]

    def test_copytree_success(self):
        """Branch: src exists, copytree succeeds → (True, 'employee pack seeded')."""
        with (
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_reg,
            patch("app.infrastructure.mods.employee_registry.employees_root", return_value="/tmp/emp"),
            patch("os.path.isdir", side_effect=lambda p: p == "/tmp/mods/_employees/xcagi-host-foundation-employee"),
            patch("os.makedirs"),
            patch("shutil.copytree") as mock_copy,
        ):
            mock_reg.return_value.mods_root = "/tmp/mods"
            result = _sync(_mod._ensure_host_foundation_employee_on_disk())
        assert result == (True, "employee pack seeded")
        mock_copy.assert_called_once()


# ===========================================================================
# 7. _install_host_foundation_internal — lines 762-787
# ===========================================================================


class TestInstallHostFoundationInternal:
    """Cover all branches of _install_host_foundation_internal."""

    def test_ensure_fails_returns_failure(self):
        """Branch: _ensure_host_foundation_employee_on_disk fails → return failure."""
        with patch.object(
            _mod,
            "_ensure_host_foundation_employee_on_disk",
            AsyncMock(return_value=(False, "seed missing")),
        ):
            result = _sync(_mod._install_host_foundation_internal(edition=None))
        assert result.success is False
        assert result.message == "seed missing"

    def test_edition_normalized_to_generic_when_invalid(self):
        """Branch: edition not in valid set → 'generic'."""
        with (
            patch.object(
                _mod,
                "_ensure_host_foundation_employee_on_disk",
                AsyncMock(return_value=(True, "ok")),
            ),
            patch("app.mod_sdk.edition_policy.resolve_edition", return_value=""),
            patch("app.mod_sdk.host_foundation.materialize_host_foundation_bridges") as mock_mat,
        ):
            mock_mat.return_value = {"ready": True, "installed_count": 1, "expected_count": 1}
            result = _sync(_mod._install_host_foundation_internal(edition="INVALID"))
        assert result.success is True

    def test_materialize_raises_recoverable_error(self):
        """Branch: materialize_host_foundation_bridges raises RECOVERABLE_ERRORS."""
        with (
            patch.object(
                _mod,
                "_ensure_host_foundation_employee_on_disk",
                AsyncMock(return_value=(True, "ok")),
            ),
            patch("app.mod_sdk.host_foundation.materialize_host_foundation_bridges") as mock_mat,
        ):
            mock_mat.side_effect = RuntimeError("bridge fail")
            result = _sync(_mod._install_host_foundation_internal(edition="generic"))
        assert result.success is False
        assert "展开宿主 bridge 失败" in result.message
        assert result.data["edition"] == "generic"
        assert result.data["ready"] is False

    def test_data_ready_true_returns_success(self):
        """Branch: data.get('ready') is True → success=True."""
        with (
            patch.object(
                _mod,
                "_ensure_host_foundation_employee_on_disk",
                AsyncMock(return_value=(True, "ok")),
            ),
            patch("app.mod_sdk.host_foundation.materialize_host_foundation_bridges") as mock_mat,
        ):
            mock_mat.return_value = {
                "ready": True,
                "installed_count": 5,
                "expected_count": 5,
            }
            result = _sync(_mod._install_host_foundation_internal(edition="full"))
        assert result.success is True
        assert "已就绪" in result.message
        assert "5/5" in result.message

    def test_data_ready_false_returns_failure_with_missing(self):
        """Branch: data.get('ready') is False → success=False with missing_mod_ids."""
        with (
            patch.object(
                _mod,
                "_ensure_host_foundation_employee_on_disk",
                AsyncMock(return_value=(True, "ok")),
            ),
            patch("app.mod_sdk.host_foundation.materialize_host_foundation_bridges") as mock_mat,
        ):
            mock_mat.return_value = {
                "ready": False,
                "installed_count": 2,
                "expected_count": 5,
                "missing_mod_ids": ["mod-a", "mod-b", "mod-c"],
            }
            result = _sync(_mod._install_host_foundation_internal(edition="minimal"))
        assert result.success is False
        assert "2/5" in result.message
        assert "mod-a" in result.message


# ===========================================================================
# 8. mod_store_bootstrap_edition_pack — loop branches (836->833, 838->833, 843->840)
# ===========================================================================


class TestBootstrapEditionPackLoopBranches:
    """Cover the loop branches in mod_store_bootstrap_edition_pack."""

    def _set_resolve_edition(self, value="generic"):
        sys.modules["app.mod_sdk.edition_policy"].resolve_edition = MagicMock(return_value=value)

    def _set_assert_allowed(self, exc=None):
        if exc:
            sys.modules["app.mod_sdk.product_skus"].assert_bootstrap_edition_allowed = MagicMock(
                side_effect=exc
            )
        else:
            sys.modules["app.mod_sdk.product_skus"].assert_bootstrap_edition_allowed = MagicMock(
                return_value=None
            )

    def _set_bootstrap(self, data):
        sys.modules["app.mod_sdk.edition_bootstrap"].bootstrap_edition_pack = AsyncMock(
            return_value=data
        )

    def test_catalog_row_status_not_failed_skipped(self):
        """Branch 836->833: catalog row status not in ('catalog_failed','missing') → skip."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 1,
                "expected_count": 3,
                "catalog": [
                    {"mod_id": "ok-mod", "status": "installed"},
                    {"mod_id": "fail-mod", "status": "catalog_failed"},
                ],
                "seed": [],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        body = resp.json()
        assert body["success"] is False
        assert "fail-mod" in body["message"]
        assert "ok-mod" not in body["message"]

    def test_catalog_non_dict_row_skipped(self):
        """Branch 838->833: catalog row is not dict → continue."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 1,
                "catalog": ["not-a-dict", None, 42],
                "seed": [],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200

    def test_seed_row_status_not_failed_skipped(self):
        """Branch 843->840: seed row status not in ('missing','error') → skip."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 2,
                "catalog": [],
                "seed": [
                    {"mod_id": "ok-seed", "status": "installed"},
                    {"mod_id": "err-seed", "status": "error"},
                ],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        body = resp.json()
        assert "err-seed" in body["message"]
        assert "ok-seed" not in body["message"]

    def test_seed_mod_id_already_in_failed_ids_not_re_added(self):
        """Branch 845: seed mid already in failed_ids → not re-added."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 2,
                "catalog": [
                    {"mod_id": "dup-mod", "status": "missing"},
                ],
                "seed": [
                    {"mod_id": "dup-mod", "status": "error"},
                    {"mod_id": "new-mod", "status": "missing"},
                ],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        body = resp.json()
        # dup-mod should appear only once in the hint (first 8)
        msg = body["message"]
        assert msg.count("dup-mod") == 1
        assert "new-mod" in msg

    def test_seed_empty_mod_id_skipped(self):
        """Branch: seed row with empty mod_id → not added."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 1,
                "catalog": [],
                "seed": [
                    {"mod_id": "", "status": "error"},
                    {"mod_id": "   ", "status": "missing"},
                ],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        body = resp.json()
        assert body["success"] is False
        # No failed ids in message hint
        assert "：" not in body["message"] or body["message"].endswith("）")

    def test_ready_true_no_loop(self):
        """Branch: ready=True → skip loop entirely."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {"ready": True, "installed_count": 3, "expected_count": 3, "catalog": [], "seed": []}
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        body = resp.json()
        assert body["success"] is True
        assert "装齐" in body["message"]


# ===========================================================================
# 9. mod_store_install route — activate flag branches
# ===========================================================================


class TestInstallRouteActivateFlag:
    """Cover the activate flag parsing in mod_store_install."""

    def test_activate_false_string(self):
        """Branch: activate='false' → activate=False."""
        with patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        ) as mock_install:
            with _make_client() as client:
                resp = client.post("/install", json={"pkg_id": "m1", "version": "1.0", "activate": "false"})
        assert resp.status_code == 200
        args, kwargs = mock_install.call_args
        assert kwargs.get("activate") is False

    def test_activate_zero_string(self):
        """Branch: activate='0' → activate=False."""
        with patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        ) as mock_install:
            with _make_client() as client:
                resp = client.post("/install", json={"pkg_id": "m1", "version": "1.0", "activate": "0"})
        assert resp.status_code == 200
        args, kwargs = mock_install.call_args
        assert kwargs.get("activate") is False

    def test_activate_no_string(self):
        """Branch: activate='no' → activate=False."""
        with patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        ) as mock_install:
            with _make_client() as client:
                resp = client.post("/install", json={"pkg_id": "m1", "version": "1.0", "activate": "no"})
        assert resp.status_code == 200
        args, kwargs = mock_install.call_args
        assert kwargs.get("activate") is False

    def test_activate_true_default(self):
        """Branch: activate not specified → default True."""
        with patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        ) as mock_install:
            with _make_client() as client:
                resp = client.post("/install", json={"pkg_id": "m1", "version": "1.0"})
        assert resp.status_code == 200
        args, kwargs = mock_install.call_args
        assert kwargs.get("activate") is True

    def test_mod_id_alias_for_pkg_id(self):
        """Branch: mod_id used as alias for pkg_id."""
        with patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        ) as mock_install:
            with _make_client() as client:
                resp = client.post("/install", json={"mod_id": "alias-mod", "version": "2.0"})
        assert resp.status_code == 200
        args, kwargs = mock_install.call_args
        assert args[0] == "alias-mod" or kwargs.get("pkg_id") == "alias-mod"


# ===========================================================================
# 10. mod_store_install_host_foundation route — additional branches
# ===========================================================================


class TestInstallHostFoundationRouteDeep:
    """Cover deeper branches of install-host-foundation route."""

    def test_edition_query_param_forwarded(self):
        """Edition query param is forwarded to _install_host_foundation_internal."""
        with patch.object(
            _mod,
            "_install_host_foundation_internal",
            AsyncMock(
                return_value=_mod.ModStoreInstallResult(
                    success=True, message="ok", data={"ready": True}
                )
            ),
        ) as mock_internal:
            with _make_client() as client:
                resp = client.post("/install-host-foundation?edition=full")
        assert resp.status_code == 200
        mock_internal.assert_called_once_with("full")

    def test_none_edition_forwarded(self):
        """No edition query param → None forwarded."""
        with patch.object(
            _mod,
            "_install_host_foundation_internal",
            AsyncMock(
                return_value=_mod.ModStoreInstallResult(
                    success=False, message="fail", data=None
                )
            ),
        ) as mock_internal:
            with _make_client() as client:
                resp = client.post("/install-host-foundation")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        mock_internal.assert_called_once_with(None)


# ===========================================================================
# 11. mod_store_bootstrap_edition_pack — edition resolution branches
# ===========================================================================


class TestBootstrapEditionPackEditionResolution:
    """Cover edition resolution branches."""

    def test_edition_from_resolve_edition_when_not_provided(self):
        """Branch: edition=None → uses resolve_edition()."""
        sys.modules["app.mod_sdk.edition_policy"].resolve_edition = MagicMock(return_value="minimal")
        sys.modules["app.mod_sdk.product_skus"].assert_bootstrap_edition_allowed = MagicMock(
            return_value=None
        )
        sys.modules["app.mod_sdk.edition_bootstrap"].bootstrap_edition_pack = AsyncMock(
            return_value={"ready": True, "installed_count": 1, "expected_count": 1}
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_edition_whitespace_stripped(self):
        """Branch: edition has whitespace → stripped and lowered."""
        sys.modules["app.mod_sdk.edition_policy"].resolve_edition = MagicMock(return_value="generic")
        sys.modules["app.mod_sdk.product_skus"].assert_bootstrap_edition_allowed = MagicMock(
            return_value=None
        )
        sys.modules["app.mod_sdk.edition_bootstrap"].bootstrap_edition_pack = AsyncMock(
            return_value={"ready": True, "installed_count": 1, "expected_count": 1}
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=  GENERIC  ")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_permission_error_detail_forwarded(self):
        """Branch: PermissionError → 400 with detail."""
        sys.modules["app.mod_sdk.edition_policy"].resolve_edition = MagicMock(return_value="generic")
        sys.modules["app.mod_sdk.product_skus"].assert_bootstrap_edition_allowed = MagicMock(
            side_effect=PermissionError("edition not allowed for this SKU")
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=full")
        assert resp.status_code == 400
        assert "edition not allowed" in resp.json()["detail"]


# ===========================================================================
# 12. _remote_to_mod_info — additional edge cases
# ===========================================================================


class TestRemoteToModInfoEdgeCases:
    """Cover additional edge cases in _remote_to_mod_info."""

    def test_pkg_id_fallback_when_no_id(self):
        """Branch: id missing → uses pkg_id."""
        info = _mod._remote_to_mod_info({"pkg_id": "from-pkg"}, set())
        assert info["id"] == "from-pkg"
        assert info["pkg_id"] == "from-pkg"

    def test_publisher_fallback_for_author(self):
        """Branch: author missing → uses publisher."""
        info = _mod._remote_to_mod_info({"id": "m1", "publisher": "PubCo"}, set())
        assert info["author"] == "PubCo"

    def test_commerce_seller_fallback_for_author(self):
        """Branch: author and publisher missing → uses commerce.seller."""
        info = _mod._remote_to_mod_info(
            {"id": "m1", "commerce": {"seller": "SellerInc"}}, set()
        )
        assert info["author"] == "SellerInc"

    def test_download_count_fallback_to_total_downloads(self):
        """Branch: download_count missing → uses total_downloads."""
        info = _mod._remote_to_mod_info({"id": "m1", "total_downloads": 999}, set())
        assert info["download_count"] == 999

    def test_total_downloads_fallback_to_download_count(self):
        """Branch: total_downloads missing → uses download_count."""
        info = _mod._remote_to_mod_info({"id": "m1", "download_count": 42}, set())
        assert info["total_downloads"] == 42

    def test_created_at_fallback_to_updated_at(self):
        """Branch: created_at missing → uses updated_at."""
        info = _mod._remote_to_mod_info({"id": "m1", "updated_at": "2025-01-01"}, set())
        assert info["created_at"] == "2025-01-01"

    def test_license_passed_through(self):
        """Branch: license field passed through."""
        info = _mod._remote_to_mod_info({"id": "m1", "license": "MIT"}, set())
        assert info["license"] == "MIT"

    def test_sha256_passed_through(self):
        """Branch: sha256 field passed through."""
        info = _mod._remote_to_mod_info({"id": "m1", "sha256": "abc123"}, set())
        assert info["sha256"] == "abc123"

    def test_artifact_defaults_to_mod(self):
        """Branch: artifact missing → defaults to 'mod'."""
        info = _mod._remote_to_mod_info({"id": "m1"}, set())
        assert info["artifact"] == "mod"

    def test_public_listing_false_by_default(self):
        """Branch: public_listing missing → False."""
        info = _mod._remote_to_mod_info({"id": "m1"}, set())
        assert info["public_listing"] is False


# ===========================================================================
# 13. _inject_host_foundation_row — additional branches
# ===========================================================================


class TestInjectHostFoundationRowDeep:
    """Cover additional branches in _inject_host_foundation_row."""

    _HF_ID = "xcagi-host-foundation-employee"

    def test_installed_from_installed_ids(self):
        """Branch: HF pack in installed_ids → installed=True."""
        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        old_installed = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(return_value=False)
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed = MagicMock(
            return_value=False
        )
        try:
            available = [{"id": "other"}]
            _mod._inject_host_foundation_row(available, {self._HF_ID})
            assert available[0]["id"] == self._HF_ID
            assert available[0]["is_installed"] is True
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed

    def test_installed_from_is_host_foundation_pack_installed(self):
        """Branch: is_host_foundation_pack_installed()=True → installed=True."""
        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        old_installed = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(return_value=False)
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed = MagicMock(
            return_value=True
        )
        try:
            available = []
            _mod._inject_host_foundation_row(available, set())
            assert available[0]["id"] == self._HF_ID
            assert available[0]["is_installed"] is True
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed

    def test_hf_pack_not_removed_from_list(self):
        """Branch: HF pack itself is not removed during cleanup loop."""
        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        old_installed = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(return_value=True)
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed = MagicMock(
            return_value=False
        )
        try:
            available = [{"id": self._HF_ID, "public_listing": False}]
            _mod._inject_host_foundation_row(available, set())
            # HF pack should still be present (not removed even though hidden)
            ids = [r["id"] for r in available]
            assert self._HF_ID in ids
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed
