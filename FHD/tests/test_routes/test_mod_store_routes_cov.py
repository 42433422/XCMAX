from __future__ import annotations

"""Branch-coverage tests for app.fastapi_routes.mod_store_routes.

Targets the missing branches listed in the task and exercises every helper
function plus all route handlers via Starlette TestClient.

Monkeypatching strategy: because the dependency modules are thin stubs
registered in sys.modules (not real package trees), we patch them via
`sys.modules["<name>"].<attr>` rather than via dotted-string paths.
"""

import asyncio
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Module-level stubs: inject thin fake modules so the import chain works
# even when heavy infrastructure is absent.
# ---------------------------------------------------------------------------


def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = []  # mark as package so submodule imports don't raise "not a package"
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Parent package stubs (must come first so dotted children can be registered)
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

# --- operational_errors (needed at module level) ---
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

# --- catalog app ---
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

# --- shell mods catalog ---
_shell_mod = _ensure_stub(
    "app.shell.mods_catalog",
    {"list_mod_items": MagicMock(return_value=[])},
)

# --- host_foundation ---
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

# --- industry_seed ---
_industry_seed_mod = _ensure_stub(
    "app.mod_sdk.industry_seed",
    {
        "install_industry_seed_with_fallback": AsyncMock(
            return_value={"success": True, "message": "installed"}
        )
    },
)

# --- customer_delivery_seed ---
_cds_mod = _ensure_stub(
    "app.mod_sdk.customer_delivery_seed",
    {
        "install_customer_delivery_seed_package": AsyncMock(
            return_value={"success": True, "message": "delivered"}
        )
    },
)

# --- employee_runtime ---
_emp_rt_mod = _ensure_stub(
    "app.mod_sdk.employee_runtime",
    {"refresh_employee_pack_runtime": MagicMock(return_value={"refreshed": True})},
)

# --- edition_policy ---
_ed_policy_mod = _ensure_stub(
    "app.mod_sdk.edition_policy",
    {"resolve_edition": MagicMock(return_value="generic")},
)

# --- edition_bootstrap ---
_ed_bootstrap_mod = _ensure_stub(
    "app.mod_sdk.edition_bootstrap",
    {
        "bootstrap_edition_pack": AsyncMock(
            return_value={"ready": True, "installed_count": 1, "expected_count": 1}
        )
    },
)

# --- product_skus ---
_prod_skus_mod = _ensure_stub(
    "app.mod_sdk.product_skus",
    {"assert_bootstrap_edition_allowed": MagicMock(return_value=None)},
)

# --- enterprise mod_entitlements ---
_entitlements_mod = _ensure_stub(
    "app.enterprise.mod_entitlements",
    {
        "enterprise_mod_filter_active": MagicMock(return_value=False),
        "sync_entitlements_from_request": AsyncMock(return_value=None),
        "get_cached_entitled_client_mod_ids": MagicMock(return_value=set()),
    },
)

# --- infrastructure mods stubs ---
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
# Helpers for patching stub modules by direct attribute assignment
# ---------------------------------------------------------------------------


def _set_stub(module_name: str, attr: str, value: Any) -> Any:
    """Set an attribute on a stub module and return the old value."""
    mod = sys.modules[module_name]
    old = getattr(mod, attr, None)
    setattr(mod, attr, value)
    return old


# ---------------------------------------------------------------------------
# TestClient factory
# ---------------------------------------------------------------------------


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(_mod.router)
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# 1. Pure-Python helper: _is_extension_row
# ===========================================================================


class TestIsExtensionRow:
    def test_empty_id_returns_false(self):
        assert _mod._is_extension_row({}) is False

    def test_all_id_returns_false(self):
        assert _mod._is_extension_row({"id": "all"}) is False

    def test_ALL_upper_returns_false(self):
        assert _mod._is_extension_row({"id": "ALL"}) is False

    def test_category_type_returns_false(self):
        assert _mod._is_extension_row({"id": "x", "type": "category"}) is False

    def test_template_type_returns_false(self):
        assert _mod._is_extension_row({"id": "x", "type": "template"}) is False

    def test_shell_seed_type_returns_false(self):
        assert _mod._is_extension_row({"id": "x", "type": "shell_seed"}) is False

    def test_valid_mod_returns_true(self):
        assert _mod._is_extension_row({"id": "my-mod", "type": "mod"}) is True

    def test_no_type_defaults_to_mod_true(self):
        assert _mod._is_extension_row({"id": "my-mod"}) is True


# ===========================================================================
# 2. Pure-Python helper: _item_to_mod_info
# ===========================================================================


class TestItemToModInfo:
    def test_empty_fields_get_defaults(self):
        result = _mod._item_to_mod_info({})
        assert result["name"] == "未命名"
        assert result["version"] == "1.0.0"
        assert result["author"] == "—"
        assert result["description"] == ""
        assert result["source"] == "local"

    def test_populated_fields_pass_through(self):
        d = {
            "id": "foo",
            "name": "Foo Mod",
            "version": "2.3",
            "author": "Alice",
            "description": "Cool",
        }
        result = _mod._item_to_mod_info(d)
        assert result["id"] == "foo"
        assert result["name"] == "Foo Mod"
        assert result["version"] == "2.3"
        assert result["author"] == "Alice"
        assert result["description"] == "Cool"


# ===========================================================================
# 3. Pure-Python helper: _all_rows (RECOVERABLE_ERRORS path)
# ===========================================================================


class TestAllRows:
    def test_returns_empty_list_on_recoverable_error(self):
        # list_mod_items is imported directly into _mod at module level
        with patch.object(_mod, "list_mod_items", MagicMock(side_effect=OSError("disk error"))):
            result = _mod._all_rows()
        assert result == []

    def test_returns_rows_on_success(self):
        fake_item = MagicMock()
        fake_item.model_dump.return_value = {"id": "mod-a", "name": "Mod A"}
        with patch.object(_mod, "list_mod_items", MagicMock(return_value=[fake_item])):
            result = _mod._all_rows()
        assert len(result) == 1
        assert result[0]["id"] == "mod-a"


# ===========================================================================
# 4. Pure-Python helper: _installed_by_id
# ===========================================================================


class TestInstalledById:
    def test_filters_to_installed_only(self):
        rows = [
            {"id": "a", "is_installed": True},
            {"id": "b", "is_installed": False},
            {"id": "c", "is_installed": True},
        ]
        with patch.object(_mod, "_all_rows", return_value=rows):
            result = _mod._installed_by_id()
        assert set(result.keys()) == {"a", "c"}
        assert "b" not in result


# ===========================================================================
# 5. _remote_to_mod_info
# ===========================================================================


class TestRemoteToModInfo:
    def _call(self, d, installed_ids=None):
        return _mod._remote_to_mod_info(d, installed_ids or set())

    def test_no_commerce_dict_gets_empty(self):
        info = self._call({"id": "m1", "commerce": "not-a-dict"})
        assert info["commerce"] == {}

    def test_commerce_dict_passed_through(self):
        info = self._call({"id": "m1", "commerce": {"seller": "Bob", "collection": "premium"}})
        assert info["commerce"]["seller"] == "Bob"

    def test_store_collection_from_commerce(self):
        old = sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value=""
        )
        try:
            info = self._call({"id": "m1", "commerce": {"collection": "premium"}})
        finally:
            sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = old
        assert info["store_collection"] == "premium"

    def test_store_collection_from_top_level(self):
        old = sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value=""
        )
        try:
            info = self._call({"id": "m1", "store_collection": "basic"})
        finally:
            sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = old
        assert info["store_collection"] == "basic"

    def test_dependencies_dict_passed_through(self):
        info = self._call({"id": "m1", "dependencies": {"dep-a": "1.0"}})
        assert info["dependencies"] == {"dep-a": "1.0"}

    def test_dependencies_non_dict_becomes_empty(self):
        info = self._call({"id": "m1", "dependencies": ["dep-a"]})
        assert info["dependencies"] == {}

    def test_is_installed_true_when_in_installed_ids(self):
        info = self._call({"id": "m1"}, installed_ids={"m1"})
        assert info["is_installed"] is True

    def test_is_installed_false_when_not_in_installed_ids(self):
        info = self._call({"id": "m1"}, installed_ids=set())
        assert info["is_installed"] is False

    def test_store_collection_falls_back_to_catalog_store_collection(self):
        """Branch where store_collection empty → calls catalog_store_collection."""
        old = sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value="inferred"
        )
        try:
            info = self._call({"id": "m1"})
        finally:
            sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = old
        assert info["store_collection"] == "inferred"


# ===========================================================================
# 6. _filter_rows
# ===========================================================================


class TestFilterRows:
    _ROWS = [
        {
            "id": "a",
            "name": "Alpha",
            "description": "First",
            "author": "Alice",
            "is_installed": True,
        },
        {
            "id": "b",
            "name": "Beta",
            "description": "Second",
            "author": "Bob",
            "is_installed": False,
        },
        {
            "id": "c",
            "name": "Gamma",
            "description": "Third",
            "author": "Alice",
            "is_installed": True,
        },
    ]

    def test_no_filters_returns_all(self):
        out = _mod._filter_rows(self._ROWS)
        assert len(out) == 3

    def test_q_filter_by_name(self):
        out = _mod._filter_rows(self._ROWS, q="alpha")
        assert len(out) == 1 and out[0]["id"] == "a"

    def test_q_filter_by_id(self):
        out = _mod._filter_rows(self._ROWS, q="b")
        assert any(r["id"] == "b" for r in out)

    def test_q_filter_by_description(self):
        out = _mod._filter_rows(self._ROWS, q="third")
        assert len(out) == 1 and out[0]["id"] == "c"

    def test_author_filter(self):
        out = _mod._filter_rows(self._ROWS, author="Alice")
        assert all(r["author"] == "Alice" for r in out)
        assert len(out) == 2

    def test_installed_true(self):
        out = _mod._filter_rows(self._ROWS, installed=True)
        assert all(r["is_installed"] for r in out)
        assert len(out) == 2

    def test_installed_false(self):
        out = _mod._filter_rows(self._ROWS, installed=False)
        assert all(not r["is_installed"] for r in out)
        assert len(out) == 1

    def test_q_empty_string_ignored(self):
        out = _mod._filter_rows(self._ROWS, q="  ")
        assert len(out) == 3

    def test_author_empty_string_ignored(self):
        out = _mod._filter_rows(self._ROWS, author="  ")
        assert len(out) == 3


# ===========================================================================
# 7. _safe_text
# ===========================================================================


class TestSafeText:
    def test_none_returns_empty(self):
        assert _mod._safe_text(None) == ""

    def test_empty_string_returns_empty(self):
        assert _mod._safe_text("") == ""

    def test_actual_string(self):
        assert _mod._safe_text("  hello  ") == "hello"

    def test_number(self):
        assert _mod._safe_text(42) == "42"


# ===========================================================================
# 8. _split_package_file
# ===========================================================================


class TestSplitPackageFile:
    def test_with_colon(self):
        mid, ver = _mod._split_package_file("my-mod:1.2.3")
        assert mid == "my-mod"
        assert ver == "1.2.3"

    def test_without_colon(self):
        mid, ver = _mod._split_package_file("my-mod")
        assert mid == "my-mod"
        assert ver == ""

    def test_empty(self):
        mid, ver = _mod._split_package_file("")
        assert mid == ""
        assert ver == ""


# ===========================================================================
# 9. _body_value (ASYNC)
# ===========================================================================


class TestBodyValue:
    def _sync(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_json_body_returns_key(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value={"mod_id": " abc "})
        result = self._sync(_mod._body_value(req, "mod_id"))
        assert result == "abc"

    def test_json_body_non_dict_returns_default(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value="not a dict")
        result = self._sync(_mod._body_value(req, "mod_id"))
        assert result == ""

    def test_form_body_returns_key(self):
        req = MagicMock()
        req.headers = {"content-type": "application/x-www-form-urlencoded"}
        req.form = AsyncMock(return_value={"mod_id": "xyz"})
        result = self._sync(_mod._body_value(req, "mod_id"))
        assert result == "xyz"

    def test_recoverable_exception_returns_default(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(side_effect=ValueError("bad json"))
        result = self._sync(_mod._body_value(req, "mod_id", default="fallback"))
        assert result == "fallback"


# ===========================================================================
# 10. _request_payload (ASYNC)
# ===========================================================================


class TestRequestPayload:
    def _sync(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_json_dict_body(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value={"key": "value"})
        result = self._sync(_mod._request_payload(req))
        assert result == {"key": "value"}

    def test_json_non_dict_body_returns_empty(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value=["list"])
        result = self._sync(_mod._request_payload(req))
        assert result == {}

    def test_form_body(self):
        req = MagicMock()
        req.headers = {"content-type": "application/x-www-form-urlencoded"}
        req.form = AsyncMock(return_value={"a": "1", "b": "2"})
        result = self._sync(_mod._request_payload(req))
        assert result["a"] == "1"
        assert result["b"] == "2"

    def test_exception_returns_empty(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(side_effect=ValueError("oops"))
        result = self._sync(_mod._request_payload(req))
        assert result == {}


# ===========================================================================
# 11. _map_market_catalog_page (ASYNC)
# ===========================================================================


class TestMapMarketCatalogPage:
    def _sync(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _setup(self, *, public=True, row_out=None):
        sys.modules["app.application.mod_store_catalog_app"].is_public_catalog_row = MagicMock(
            return_value=public
        )
        sys.modules["app.application.mod_store_catalog_app"].market_item_to_package_row = MagicMock(
            return_value=row_out or {"id": "p1", "commerce": {"collection": "coll"}}
        )
        sys.modules["app.mod_sdk.host_foundation"].catalog_store_collection = MagicMock(
            return_value=""
        )

    def test_non_list_items_returns_empty(self):
        self._setup()
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(
                _mod._map_market_catalog_page({"items": "not-a-list", "total": 0})
            )
        assert items == []

    def test_non_dict_row_skipped(self):
        self._setup()
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(
                _mod._map_market_catalog_page({"items": ["string-item"], "total": 1})
            )
        assert items == []

    def test_total_as_int(self):
        self._setup()
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(_mod._map_market_catalog_page({"items": [], "total": 42}))
        assert total == 42

    def test_total_bad_type_falls_back_to_len(self):
        self._setup()
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(_mod._map_market_catalog_page({"items": [], "total": "bad"}))
        assert total == 0

    def test_is_public_catalog_row_false_branch(self):
        """Branch: row returned by market_item_to_package_row but is_public_catalog_row=False."""
        self._setup(public=False)
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(
                _mod._map_market_catalog_page({"items": [{"id": "p1"}], "total": 1})
            )
        assert items == []

    def test_collection_hint_overrides_commerce(self):
        self._setup(row_out={"id": "p1", "commerce": {"collection": "from_commerce"}})
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(
                _mod._map_market_catalog_page(
                    {"items": [{"id": "p1"}], "total": 1},
                    collection_hint="forced_hint",
                )
            )
        assert len(items) == 1
        assert items[0]["store_collection"] == "forced_hint"

    def test_hint_from_commerce_when_no_collection_hint(self):
        self._setup(row_out={"id": "p1", "commerce": {"collection": "from_commerce"}})
        with patch.object(_mod, "_installed_by_id", return_value={}):
            items, total = self._sync(
                _mod._map_market_catalog_page(
                    {"items": [{"id": "p1"}], "total": 1},
                    collection_hint="",
                )
            )
        assert len(items) == 1
        assert items[0]["store_collection"] == "from_commerce"


# ===========================================================================
# 12. _inject_host_foundation_row
# ===========================================================================


class TestInjectHostFoundationRow:
    _HF_ID = "xcagi-host-foundation-employee"

    def _call(self, available, installed_ids=None):
        _mod._inject_host_foundation_row(available, installed_ids or set())

    def test_already_present_early_return(self):
        """Branch: HF row already in available → early return, no insert."""
        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(return_value=False)
        try:
            available = [{"id": self._HF_ID, "name": "Host Foundation"}]
            original_len = len(available)
            self._call(available)
            assert len(available) == original_len
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden

    def test_not_present_inserts_at_front(self):
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
            available = [{"id": "other-mod"}]
            self._call(available)
            assert available[0]["id"] == self._HF_ID
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed

    def test_infrastructure_mod_hidden_without_public_listing_popped(self):
        """Branch: hidden infra mod without public_listing gets removed."""

        def _is_hidden(mid):
            return mid == "infra-hidden"

        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        old_installed = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(side_effect=_is_hidden)
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed = MagicMock(
            return_value=False
        )
        try:
            available = [{"id": "infra-hidden", "public_listing": False}]
            self._call(available)
            ids = [r["id"] for r in available]
            assert "infra-hidden" not in ids
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed

    def test_infrastructure_mod_with_public_listing_stays(self):
        """Branch: hidden infra mod WITH public_listing stays."""

        def _is_hidden(mid):
            return mid == "infra-listed"

        old_hidden = sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store
        old_installed = sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed
        sys.modules[
            "app.mod_sdk.host_foundation"
        ].is_infrastructure_mod_hidden_from_store = MagicMock(side_effect=_is_hidden)
        sys.modules["app.mod_sdk.host_foundation"].is_host_foundation_pack_installed = MagicMock(
            return_value=False
        )
        try:
            available = [{"id": "infra-listed", "public_listing": True}]
            self._call(available)
            ids = [r["id"] for r in available]
            assert "infra-listed" in ids
        finally:
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_infrastructure_mod_hidden_from_store = old_hidden
            sys.modules[
                "app.mod_sdk.host_foundation"
            ].is_host_foundation_pack_installed = old_installed


# ===========================================================================
# Route tests via TestClient
# ===========================================================================


def _patch_combined_rows(available=None, installed=None):
    """Return a context manager patching _mod._combined_rows."""
    available = available or []
    installed = installed or []
    return patch.object(_mod, "_combined_rows", AsyncMock(return_value=(available, installed)))


# ===========================================================================
# 13. GET /catalog
# ===========================================================================


class TestCatalogRoute:
    def test_returns_success_true(self):
        with _patch_combined_rows(available=[{"id": "m1"}]):
            with _make_client() as client:
                resp = client.get("/catalog")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_returns_installed_and_available(self):
        with _patch_combined_rows(
            available=[{"id": "m1"}, {"id": "m2"}],
            installed=[{"id": "m1"}],
        ):
            with _make_client() as client:
                resp = client.get("/catalog")
        data = resp.json()["data"]
        assert data["indexed_count"] == 2
        assert len(data["installed"]) == 1

    def test_empty_catalog(self):
        with _patch_combined_rows():
            with _make_client() as client:
                resp = client.get("/catalog")
        assert resp.json()["data"]["indexed_count"] == 0


# ===========================================================================
# 14. GET /market-catalog
# ===========================================================================


class TestMarketCatalogRoute:
    def test_returns_success(self):
        # fetch_market_catalog_page is imported directly into _mod at module level
        with patch.object(
            _mod, "fetch_market_catalog_page", AsyncMock(return_value={"items": [], "total": 0})
        ):
            with patch.object(_mod, "_map_market_catalog_page", AsyncMock(return_value=([], 0))):
                with _make_client() as client:
                    resp = client.get("/market-catalog")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_query_params_forwarded(self):
        # fetch_market_catalog_page is imported directly into _mod at module level
        fetch_mock = AsyncMock(return_value={"items": [], "total": 0})
        with patch.object(_mod, "fetch_market_catalog_page", fetch_mock):
            with patch.object(_mod, "_map_market_catalog_page", AsyncMock(return_value=([], 0))):
                with _make_client() as client:
                    client.get("/market-catalog?q=hello&collection=premium&limit=10")
        fetch_mock.assert_called_once()
        _, kwargs = fetch_mock.call_args
        assert kwargs.get("q") == "hello"
        assert kwargs.get("collection") == "premium"


# ===========================================================================
# 15. GET /search
# ===========================================================================


class TestSearchRoute:
    def test_no_params_returns_all(self):
        rows = [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/search")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_q_filter(self):
        rows = [
            {"id": "a", "name": "Alpha", "description": "", "author": "x", "is_installed": False},
            {"id": "b", "name": "Beta", "description": "", "author": "y", "is_installed": False},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/search?q=alpha")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == "a"

    def test_installed_filter_true(self):
        rows = [
            {"id": "a", "name": "A", "description": "", "author": "", "is_installed": True},
            {"id": "b", "name": "B", "description": "", "author": "", "is_installed": False},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/search?installed=true")
        data = resp.json()["data"]
        assert all(r["is_installed"] for r in data)

    def test_installed_filter_false(self):
        rows = [
            {"id": "a", "name": "A", "description": "", "author": "", "is_installed": True},
            {"id": "b", "name": "B", "description": "", "author": "", "is_installed": False},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/search?installed=false")
        data = resp.json()["data"]
        assert all(not r["is_installed"] for r in data)

    def test_author_filter(self):
        rows = [
            {"id": "a", "name": "A", "description": "", "author": "Alice", "is_installed": False},
            {"id": "b", "name": "B", "description": "", "author": "Bob", "is_installed": False},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/search?author=alice")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["author"] == "Alice"


# ===========================================================================
# 16. GET /popular  and  GET /recent
# ===========================================================================


class TestPopularAndRecentRoutes:
    def test_popular_returns_sorted_by_downloads(self):
        rows = [
            {"id": "a", "total_downloads": 5, "download_count": 5},
            {"id": "b", "total_downloads": 100, "download_count": 100},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/popular?limit=10")
        data = resp.json()["data"]
        assert data[0]["id"] == "b"

    def test_recent_returns_200(self):
        rows = [
            {"id": "a", "created_at": "2024-01-01"},
            {"id": "b", "created_at": "2025-06-01"},
        ]
        with _patch_combined_rows(available=rows):
            with _make_client() as client:
                resp = client.get("/recent?limit=5")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data[0]["id"] == "b"


# ===========================================================================
# 17. GET /mod/{mod_id}/details
# ===========================================================================


class TestModDetailsRoute:
    # catalog_get_json is imported directly into _mod at module level
    def test_remote_success(self):
        mock = AsyncMock(
            side_effect=[
                {"versions": [{"version": "1.2.0"}]},
                {
                    "id": "my-mod",
                    "name": "My Mod",
                    "version": "1.2.0",
                    "author": "Author",
                    "description": "Desc",
                },
            ]
        )
        with patch.object(_mod, "catalog_get_json", mock):
            with _make_client() as client:
                resp = client.get("/mod/my-mod/details")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "my-mod"

    def test_remote_404_fallback_to_local(self):
        from fastapi import HTTPException as FE

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
        with patch.object(
            _mod, "catalog_get_json", AsyncMock(side_effect=FE(status_code=404, detail="not found"))
        ):
            with _patch_combined_rows(available=rows):
                with _make_client() as client:
                    resp = client.get("/mod/local-mod/details")
        assert resp.status_code == 200
        assert resp.json()["data"]["source"] == "local"

    def test_full_404_when_not_found(self):
        from fastapi import HTTPException as FE

        with patch.object(
            _mod, "catalog_get_json", AsyncMock(side_effect=FE(status_code=404, detail="not found"))
        ):
            with _patch_combined_rows(available=[]):
                with _make_client() as client:
                    resp = client.get("/mod/no-such-mod/details")
        assert resp.status_code == 404

    def test_versions_list_with_string_entries(self):
        """Branch: versions[0] is a plain string, not a dict."""
        mock = AsyncMock(
            side_effect=[
                {"versions": ["1.5.0"]},
                {"id": "m", "name": "M", "version": "1.5.0", "author": "A", "description": "D"},
            ]
        )
        with patch.object(_mod, "catalog_get_json", mock):
            with _make_client() as client:
                resp = client.get("/mod/m/details")
        assert resp.status_code == 200
        assert resp.json()["data"]["version"] == "1.5.0"


# ===========================================================================
# 18. POST /upload
# ===========================================================================


class TestUploadRoute:
    def test_returns_not_implemented(self):
        with _make_client() as client:
            resp = client.post("/upload")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# 19. POST /install
# ===========================================================================


class TestInstallRoute:
    def _patch_install(self):
        return patch.object(
            _mod,
            "_install_from_catalog",
            AsyncMock(return_value=_mod.ModStoreInstallResult(success=True, message="ok")),
        )

    def test_json_body(self):
        with self._patch_install():
            with _make_client() as client:
                resp = client.post("/install", json={"pkg_id": "my-mod", "version": "1.0"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_form_body(self):
        with self._patch_install():
            with _make_client() as client:
                resp = client.post("/install", data={"pkg_id": "my-mod", "version": "1.0"})
        assert resp.status_code == 200

    def test_from_package_file(self):
        with self._patch_install():
            with _make_client() as client:
                resp = client.post("/install", json={"package_file": "my-mod:2.0"})
        assert resp.status_code == 200


# ===========================================================================
# 20. POST /install-industry-seed
# ===========================================================================


class TestInstallIndustrySeedRoute:
    def test_missing_industry_id_returns_400(self):
        with _make_client() as client:
            resp = client.post("/install-industry-seed", json={})
        assert resp.status_code == 400

    def test_success(self):
        old = sys.modules["app.mod_sdk.industry_seed"].install_industry_seed_with_fallback
        sys.modules["app.mod_sdk.industry_seed"].install_industry_seed_with_fallback = AsyncMock(
            return_value={"success": True, "message": "seeded"}
        )
        try:
            with _make_client() as client:
                resp = client.post("/install-industry-seed", json={"industry_id": "retail"})
        finally:
            sys.modules["app.mod_sdk.industry_seed"].install_industry_seed_with_fallback = old
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# 21. POST /install-customer-delivery-seed
# ===========================================================================


class TestInstallCustomerDeliverySeedRoute:
    def test_missing_mod_id_returns_400(self):
        with _make_client() as client:
            resp = client.post("/install-customer-delivery-seed", json={})
        assert resp.status_code == 400

    def _setup_entitlements(self, *, active, entitled_ids=None):
        m = sys.modules["app.enterprise.mod_entitlements"]
        m.enterprise_mod_filter_active = MagicMock(return_value=active)
        m.sync_entitlements_from_request = AsyncMock(return_value=None)
        m.get_cached_entitled_client_mod_ids = MagicMock(return_value=entitled_ids or set())

    def _setup_delivery(self, result=None):
        result = result or {"success": True, "message": "done"}
        sys.modules[
            "app.mod_sdk.customer_delivery_seed"
        ].install_customer_delivery_seed_package = AsyncMock(return_value=result)

    def test_entitlement_filter_active_and_entitled(self):
        self._setup_entitlements(active=True, entitled_ids={"mod-a"})
        self._setup_delivery()
        with _make_client() as client:
            resp = client.post("/install-customer-delivery-seed", json={"mod_id": "mod-a"})
        assert resp.status_code == 200

    def test_entitlement_filter_active_not_entitled_returns_403(self):
        self._setup_entitlements(active=True, entitled_ids=set())
        with _make_client() as client:
            resp = client.post("/install-customer-delivery-seed", json={"mod_id": "not-entitled"})
        assert resp.status_code == 403

    def test_filter_inactive_proceeds_directly(self):
        self._setup_entitlements(active=False)
        self._setup_delivery()
        with _make_client() as client:
            resp = client.post("/install-customer-delivery-seed", json={"mod_id": "mod-x"})
        assert resp.status_code == 200

    def test_recoverable_error_in_entitlement_check_skipped(self):
        """Branch: RECOVERABLE_ERRORS during entitlement check → warning + continue."""
        m = sys.modules["app.enterprise.mod_entitlements"]
        m.enterprise_mod_filter_active = MagicMock(return_value=True)
        m.sync_entitlements_from_request = AsyncMock(side_effect=OSError("network fail"))
        self._setup_delivery()
        with _make_client() as client:
            resp = client.post("/install-customer-delivery-seed", json={"mod_id": "mod-y"})
        assert resp.status_code == 200


# ===========================================================================
# 22. POST /reload-employees
# ===========================================================================


class TestReloadEmployeesRoute:
    def test_returns_success(self):
        old = sys.modules["app.mod_sdk.employee_runtime"].refresh_employee_pack_runtime
        sys.modules["app.mod_sdk.employee_runtime"].refresh_employee_pack_runtime = MagicMock(
            return_value={"refreshed": True}
        )
        try:
            with _make_client() as client:
                resp = client.post("/reload-employees", json={"pack_id": "p1"})
        finally:
            sys.modules["app.mod_sdk.employee_runtime"].refresh_employee_pack_runtime = old
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# 23. POST /uninstall
# ===========================================================================


class TestUninstallRoute:
    def test_missing_mod_id_returns_400(self):
        with _make_client() as client:
            resp = client.post("/uninstall", json={})
        assert resp.status_code == 400

    def test_success_json(self):
        mm = MagicMock()
        mm.uninstall_mod.return_value = (True, "uninstalled")
        old = sys.modules["app.infrastructure.mods.mod_manager"].get_mod_manager
        sys.modules["app.infrastructure.mods.mod_manager"].get_mod_manager = MagicMock(
            return_value=mm
        )
        try:
            with _make_client() as client:
                resp = client.post("/uninstall", json={"mod_id": "m1"})
        finally:
            sys.modules["app.infrastructure.mods.mod_manager"].get_mod_manager = old
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# 24. POST /update
# ===========================================================================


class TestUpdateRoute:
    def test_calls_install_from_catalog(self):
        install_mock = AsyncMock(
            return_value=_mod.ModStoreInstallResult(success=True, message="updated")
        )
        with patch.object(_mod, "_install_from_catalog", install_mock):
            with _make_client() as client:
                resp = client.post("/update", json={"pkg_id": "m1", "version": "2.0"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_from_package_file(self):
        install_mock = AsyncMock(
            return_value=_mod.ModStoreInstallResult(success=True, message="updated")
        )
        with patch.object(_mod, "_install_from_catalog", install_mock):
            with _make_client() as client:
                resp = client.post("/update", json={"package_file": "m1:2.0"})
        assert resp.status_code == 200


# ===========================================================================
# 25. GET /validate, /updates, /dependencies
# ===========================================================================


class TestSimpleGetRoutes:
    def test_validate_returns_not_implemented(self):
        with _make_client() as client:
            resp = client.get("/validate")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_updates_returns_empty_list(self):
        with _make_client() as client:
            resp = client.get("/updates")
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 0

    def test_dependencies_returns_structure(self):
        with _make_client() as client:
            resp = client.get("/dependencies")
        assert resp.status_code == 200
        assert resp.json()["data"]["can_install"] is True


# ===========================================================================
# 26. POST /mod/{mod_id}/rate
# ===========================================================================


class TestRateRoute:
    def test_returns_not_implemented(self):
        with _make_client() as client:
            resp = client.post("/mod/some-mod/rate")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# 27. GET /package/{path}/download  →  404
# ===========================================================================


class TestDownloadRoute:
    def test_returns_404(self):
        with _make_client() as client:
            resp = client.get("/package/some-mod:1.0/download")
        assert resp.status_code == 404

    def test_deep_path_returns_404(self):
        with _make_client() as client:
            resp = client.get("/package/a/b/c/download")
        assert resp.status_code == 404


# ===========================================================================
# 28. DELETE /package/{path}
# ===========================================================================


class TestDeletePackageRoute:
    def test_returns_not_implemented(self):
        with _make_client() as client:
            resp = client.delete("/package/some-mod:1.0")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# 29. POST /index/rebuild
# ===========================================================================


class TestRebuildIndexRoute:
    def test_returns_message(self):
        with _make_client() as client:
            resp = client.post("/index/rebuild")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "无需重建" in resp.json()["message"]


# ===========================================================================
# 30. POST /install-host-foundation
# ===========================================================================


class TestInstallHostFoundationRoute:
    def test_success(self):
        with patch.object(
            _mod,
            "_install_host_foundation_internal",
            AsyncMock(
                return_value=_mod.ModStoreInstallResult(
                    success=True, message="就绪", data={"ready": True}
                )
            ),
        ):
            with _make_client() as client:
                resp = client.post("/install-host-foundation")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_recoverable_error_returns_failure(self):
        with patch.object(
            _mod,
            "_install_host_foundation_internal",
            AsyncMock(side_effect=OSError("disk error")),
        ):
            with _make_client() as client:
                resp = client.post("/install-host-foundation")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "装包失败" in resp.json()["message"]


# ===========================================================================
# 31. POST /bootstrap-edition-pack
# ===========================================================================


class TestBootstrapEditionPackRoute:
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

    def test_invalid_edition_returns_400(self):
        self._set_resolve_edition("generic")
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=INVALID")
        assert resp.status_code == 400

    def test_ready_true(self):
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap({"ready": True, "installed_count": 3, "expected_count": 3})
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "装齐" in resp.json()["message"]

    def test_not_ready_with_failed_catalog_ids(self):
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 1,
                "expected_count": 3,
                "catalog": [
                    {"mod_id": "missing-a", "status": "catalog_failed"},
                    {"mod_id": "missing-b", "status": "missing"},
                    "not-a-dict",  # branch: skip non-dict rows
                ],
                "seed": [
                    {"mod_id": "seed-x", "status": "error"},
                    {"mod_id": "missing-a", "status": "error"},  # dup: not re-added
                ],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "1/3" in body["message"]
        # at least one failed id appears in the message
        assert "missing-a" in body["message"] or "missing-b" in body["message"]

    def test_permission_error_raises_400(self):
        self._set_resolve_edition("generic")
        self._set_assert_allowed(exc=PermissionError("not allowed"))
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 400

    def test_not_ready_no_failed_ids_no_hint(self):
        """Branch: no failed_ids → hint is empty → msg has no trailing colon+hint."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 2,
                "catalog": [],
                "seed": [],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=minimal")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "0/2" in body["message"]

    def test_seed_non_dict_rows_skipped(self):
        """Branch: seed list contains non-dict entries → no AttributeError."""
        self._set_resolve_edition("generic")
        self._set_assert_allowed()
        self._set_bootstrap(
            {
                "ready": False,
                "installed_count": 0,
                "expected_count": 1,
                "catalog": [],
                "seed": ["not-a-dict", None],
            }
        )
        with _make_client() as client:
            resp = client.post("/bootstrap-edition-pack?edition=generic")
        assert resp.status_code == 200


# ===========================================================================
# 32. POST /sync-modstore-library
# ===========================================================================


class TestSyncModstoreLibraryRoute:
    def _patch_sync(self, value):
        """Return a context manager that patches sync_modstore_library_to_local on _mod."""
        return patch.object(_mod, "sync_modstore_library_to_local", value)

    def test_non_json_body_returns_400(self):
        with _make_client() as client:
            resp = client.post(
                "/sync-modstore-library",
                content=b"not json",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 400

    def test_non_dict_json_returns_400(self):
        with _make_client() as client:
            resp = client.post("/sync-modstore-library", json=["list"])
        assert resp.status_code == 400

    def test_missing_token_returns_400(self):
        with _make_client() as client:
            resp = client.post("/sync-modstore-library", json={"base_url": "https://x.com"})
        assert resp.status_code == 400

    def test_no_mod_ids_and_no_all_returns_400(self):
        with _make_client() as client:
            resp = client.post("/sync-modstore-library", json={"token": "tok123"})
        assert resp.status_code == 400

    def test_mod_ids_as_list(self):
        sync_mock = AsyncMock(return_value={"success": True, "message": "ok", "data": {"count": 2}})
        with self._patch_sync(sync_mock):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "mod_ids": ["a", "b"]},
                )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_mod_ids_as_comma_string(self):
        sync_mock = AsyncMock(return_value={"success": True, "message": "ok", "data": {}})
        with self._patch_sync(sync_mock):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "mod_ids": "a, b, c"},
                )
        assert resp.status_code == 200

    def test_all_true(self):
        sync_mock = AsyncMock(return_value={"success": True, "message": "ok", "data": None})
        with self._patch_sync(sync_mock):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "all": True},
                )
        assert resp.status_code == 200

    def test_value_error_from_sync_returns_400(self):
        with self._patch_sync(AsyncMock(side_effect=ValueError("bad value"))):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "all": True},
                )
        assert resp.status_code == 400

    def test_runtime_error_from_sync_returns_502(self):
        with self._patch_sync(AsyncMock(side_effect=RuntimeError("upstream down"))):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "all": True},
                )
        assert resp.status_code == 502

    def test_data_non_dict_becomes_none(self):
        """Branch: raw.get('data') is not dict → response data is None."""
        sync_mock = AsyncMock(return_value={"success": True, "message": "ok", "data": "string"})
        with self._patch_sync(sync_mock):
            with _make_client() as client:
                resp = client.post(
                    "/sync-modstore-library",
                    json={"token": "tok", "all": True},
                )
        assert resp.status_code == 200
        assert resp.json()["data"] is None
