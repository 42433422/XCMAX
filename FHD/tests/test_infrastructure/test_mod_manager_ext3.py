"""Behavior tests for app.infrastructure.mods.mod_manager (ext3).

Covers list_mods/list_all_mods, get_routes, load_all_mods, the get_mod_manager
singleton, import_mod_backend_py, the mods-root resolvers (_default_mods_root,
_all_mods_roots, _repo_layout_mods_candidates), HTTP-route registration
(_register_single_mod_http_routes, load_mod_routes), employee-pack routes
(load_employee_pack_routes, register_employee_pack_routes), and the on-demand
API gate (_mod_allowed_for_api_load, ensure_mod_api_ready,
_restore_entitlements_from_session_id, mount_on_disk_primary_client_mods).

Every test asserts a concrete return value / data-structure content / state
change, and exercises both branches where the source has them. Only external
dependencies (the singleton mod registry, enterprise entitlements, the FastAPI
app) are mocked; assertions land on the behavior of the code under test.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock, patch

import pytest

from app.infrastructure.mods import mod_manager as mm_mod
from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _default_mods_root,
    _mod_allowed_for_api_load,
    _register_single_mod_http_routes,
    _repo_layout_mods_candidates,
    _restore_entitlements_from_session_id,
    ensure_mod_api_ready,
    get_mod_manager,
    import_mod_backend_py,
    is_mods_disabled,
    load_employee_pack_routes,
    load_mod_routes,
    mount_on_disk_primary_client_mods,
    register_employee_pack_routes,
)
from app.infrastructure.mods.registry import ModRegistry

MM = "app.infrastructure.mods.mod_manager"


@pytest.fixture(autouse=True)
def fresh_registry():
    """Give every test a pristine ModRegistry singleton (so list_mods /
    get_mod_metadata reflect only what the test registers) and a clean
    employee-pack registration set (a module global)."""
    saved = ModRegistry._instance
    saved_pack_set = set(mm_mod._employee_pack_routes_registered)
    ModRegistry._instance = ModRegistry()
    mm_mod._employee_pack_routes_registered.clear()
    try:
        yield ModRegistry._instance
    finally:
        ModRegistry._instance = saved
        mm_mod._employee_pack_routes_registered.clear()
        mm_mod._employee_pack_routes_registered.update(saved_pack_set)


def _meta(mod_id: str, **kw) -> ModMetadata:
    base = {"id": mod_id, "name": mod_id.title(), "version": "1.0", "mod_path": f"/tmp/{mod_id}"}
    base.update(kw)
    return ModMetadata(**base)


# ========================= list_mods / list_all_mods =======================


class TestModManagerListMods:
    def test_list_all_mods_projects_metadata_to_api_dict(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        meta = _meta(
            "alpha",
            author="ACME",
            description="desc",
            primary=True,
            frontend_menu=[{"label": "A", "path": "/a"}],
        )
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(f"{MM}.is_mods_disabled", return_value=False),
        ):
            rows = mm.list_all_mods()
        row = next(r for r in rows if r["id"] == "alpha")
        assert row["name"] == "Alpha"
        assert row["version"] == "1.0"
        assert row["author"] == "ACME"
        assert row["description"] == "desc"
        assert row["primary"] is True
        assert row["menu"] == [{"label": "A", "path": "/a"}]
        # list_mods is documented to be identical to list_all_mods.
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(f"{MM}.is_mods_disabled", return_value=False),
        ):
            assert mm.list_mods() == rows

    def test_list_all_mods_returns_empty_when_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))

        def _boom():
            raise AssertionError("scan_mods must not run when mods disabled")

        with (
            patch(f"{MM}.is_mods_disabled", return_value=True),
            patch.object(mm, "scan_mods", side_effect=_boom),
        ):
            assert mm.list_all_mods() == []


# ========================= get_routes =====================================


class TestModManagerGetRoutes:
    def test_returns_only_mods_with_frontend_routes(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with_routes = _meta("has_routes", frontend_routes="frontend/routes.js")
        no_routes = _meta("no_routes")  # frontend_routes == "" -> excluded
        with (
            patch.object(mm, "scan_mods", return_value=[with_routes, no_routes]),
            patch(f"{MM}.is_mods_disabled", return_value=False),
        ):
            routes = mm.get_routes()
        assert routes == [{"mod_id": "has_routes", "routes_path": "frontend/routes.js"}]

    def test_returns_empty_when_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(f"{MM}.is_mods_disabled", return_value=True):
            assert mm.get_routes() == []


# ========================= load_all_mods ==================================


class TestModManagerLoadAllMods:
    def test_loads_primary_first_then_dependents(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        meta_a = _meta("mod_a", primary=True)
        meta_b = _meta("mod_b", dependencies={"mod_a": ">=1.0"})
        load_order: list[str] = []

        def _fake_load(mid):
            load_order.append(mid)
            return True

        with (
            patch.object(mm, "scan_mods", return_value=[meta_b, meta_a]),  # unsorted input
            patch.object(mm, "load_mod", side_effect=_fake_load),
        ):
            loaded = mm.load_all_mods()
        # primary sorts ahead of non-primary; mod_a must load before mod_b so the
        # dependency check on mod_b passes.
        assert load_order == ["mod_a", "mod_b"]
        assert loaded == ["mod_a", "mod_b"]
        assert mm.get_recent_load_failures() == []

    def test_skips_dependent_when_dependency_missing(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # mod_b depends on mod_a which is never present -> validate_dependencies fails.
        meta_b = _meta("mod_b", dependencies={"mod_a": ">=1.0"})
        loaded_calls: list[str] = []

        with (
            patch.object(mm, "scan_mods", return_value=[meta_b]),
            patch.object(mm, "load_mod", side_effect=lambda mid: loaded_calls.append(mid) or True),
        ):
            loaded = mm.load_all_mods()
        assert loaded == []
        assert loaded_calls == []  # load_mod never reached
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod_b"
        assert failures[0]["stage"] == "dependencies"

    def test_records_no_load_when_load_mod_fails(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        meta = _meta("flaky")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch.object(mm, "load_mod", return_value=False),
        ):
            loaded = mm.load_all_mods()
        # load_mod returning False keeps the mod out of the result list.
        assert loaded == []

    def test_load_all_empty(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "scan_mods", return_value=[]):
            assert mm.load_all_mods() == []


# ========================= get_mod_manager singleton ======================


class TestGetModManagerSingleton:
    def test_lazily_creates_and_caches_one_instance(self):
        old = mm_mod._mod_manager
        try:
            mm_mod._mod_manager = None
            mm1 = get_mod_manager()
            assert isinstance(mm1, ModManager)
            assert mm_mod._mod_manager is mm1  # cached on module
            mm2 = get_mod_manager()
            assert mm2 is mm1  # second call returns the same object
        finally:
            mm_mod._mod_manager = old


# ========================= import_mod_backend_py edge cases ================


class TestImportModBackendPyEdgeCases:
    def test_loads_module_attributes_and_caches_by_path(self, tmp_path):
        backend_dir = tmp_path / "test_mod" / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "__init__.py").write_text("")
        (backend_dir / "services.py").write_text("HANDLER = True\nVALUE = 42\n")

        module = import_mod_backend_py(str(tmp_path / "test_mod"), "test_mod", "services")
        assert module.HANDLER is True
        assert module.VALUE == 42
        # Same mod_id + path returns the very same cached module object.
        again = import_mod_backend_py(str(tmp_path / "test_mod"), "test_mod", "services")
        assert again is module

    def test_missing_backend_file_raises_with_path_in_message(self, tmp_path):
        backend_dir = tmp_path / "nomod"
        with pytest.raises(FileNotFoundError, match="backend file missing"):
            import_mod_backend_py(str(backend_dir), "nomod", "missing_module")

    def test_syntax_error_propagates(self, tmp_path):
        backend_dir = tmp_path / "bad_mod" / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "__init__.py").write_text("")
        (backend_dir / "bad_syntax.py").write_text("def broken(\n")

        with pytest.raises(SyntaxError):
            import_mod_backend_py(str(tmp_path / "bad_mod"), "bad_mod", "bad_syntax")


# ========================= _all_mods_roots ================================


class TestAllModsRoots:
    def test_primary_root_listed_first(self, tmp_path):
        primary = tmp_path / "primary_mods"
        primary.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False):
            result = _all_mods_roots(str(primary))
        assert result[0] == str(primary)
        # every element is an absolute path string
        assert all(isinstance(p, str) and os.path.isabs(p) for p in result)

    def test_nonexistent_primary_is_dropped(self, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False):
            result = _all_mods_roots(missing)
        assert missing not in result

    def test_env_root_appended_and_deduped(self, tmp_path):
        primary = tmp_path / "p"
        primary.mkdir()
        envroot = tmp_path / "env"
        envroot.mkdir()
        with patch.dict(
            os.environ, {"XCAGI_MODS_ROOT": str(envroot), "XCAGI_MODS_DIR": ""}, clear=False
        ):
            result = _all_mods_roots(str(primary))
        assert str(primary) in result
        assert str(envroot) in result
        # No duplicates in the returned roots.
        assert len(result) == len(set(result))


# ========================= _repo_layout_mods_candidates ====================


class TestRepoLayoutModsCandidates:
    def test_includes_existing_mods_dir_under_repo_root(self, tmp_path):
        # repo_root is __file__ with 4 dirname() applied; build a tree to match
        # and point the module __file__ at it.
        repo_root = tmp_path
        (repo_root / "mods").mkdir()
        fake_file = repo_root / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        with patch.object(mm_mod, "__file__", str(fake_file)):
            result = _repo_layout_mods_candidates()
        assert str(repo_root / "mods") in result
        # mods-admin-runtime and XCAGI/mods do not exist -> not included.
        assert str(repo_root / "mods-admin-runtime") not in result

    def test_skips_nonexistent_dirs(self, tmp_path):
        fake_file = tmp_path / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        # No mods/, mods-admin-runtime/, or XCAGI/mods exist under tmp_path.
        with patch.object(mm_mod, "__file__", str(fake_file)):
            result = _repo_layout_mods_candidates()
        assert result == []


# ========================= _default_mods_root ==============================


class TestDefaultModsRootExtended:
    def test_existing_env_dir_wins(self, tmp_path):
        custom = tmp_path / "custom_mods"
        custom.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(custom)}, clear=False):
            assert _default_mods_root() == str(custom)

    def test_env_dir_missing_falls_through_to_resolution(self, tmp_path):
        # Point env at a non-directory: it is ignored and the package-relative
        # ".../mods" fallback (4 dirs up from __file__, + "mods") is returned.
        bogus = str(tmp_path / "not_a_dir")
        expected_fallback = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(mm_mod.__file__))))
            ),
            "mods",
        )
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": bogus, "XCAGI_MODS_DIR": ""}, clear=False):
            result = _default_mods_root()
        assert result != bogus
        assert result == expected_fallback


# ========================= is_mods_disabled ===============================


class TestIsModsDisabled:
    @pytest.mark.parametrize("val", ["1", "true", "YES", "On", "tRuE"])
    def test_truthy_env_values(self, val):
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": val}, clear=False):
            assert is_mods_disabled() is True

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "maybe"])
    def test_falsey_env_values(self, val):
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": val}, clear=False):
            assert is_mods_disabled() is False


# ========================= _register_single_mod_http_routes ===============


class TestRegisterSingleModHttpRoutes:
    def test_empty_mod_id_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        assert _register_single_mod_http_routes(Mock(), mm, "  ") is False

    def test_already_registered_short_circuits_true(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._http_routes_registered.add("test_mod")
        app = Mock()
        assert _register_single_mod_http_routes(app, mm, "test_mod") is True
        # The fast path must not touch the FastAPI app at all.
        assert app.method_calls == []

    def test_no_backend_entry_returns_false(self, tmp_path, fresh_registry):
        mm = ModManager(mods_root=str(tmp_path))
        fresh_registry.register_mod(_meta("test_mod"))  # backend_entry == ""
        assert _register_single_mod_http_routes(Mock(), mm, "test_mod") is False
        # Without a backend_entry the mod is never marked registered.
        assert "test_mod" not in mm._http_routes_registered

    def test_registers_via_module_register_fn_and_marks_registered(self, tmp_path, fresh_registry):
        mm = ModManager(mods_root=str(tmp_path))
        fresh_registry.register_mod(
            _meta("real_mod", backend_entry="services", mod_path=str(tmp_path))
        )
        # Inject a fake backend module that exposes register_fastapi_routes.
        calls: list[tuple] = []
        fake_mod = type("M", (), {})()
        fake_mod.register_fastapi_routes = lambda app, mid: calls.append((app, mid))
        mm._backend_entry_modules["real_mod"] = fake_mod
        app = Mock()

        assert _register_single_mod_http_routes(app, mm, "real_mod") is True
        assert calls == [(app, "real_mod")]
        assert "real_mod" in mm._http_routes_registered

    def test_module_without_registrar_returns_false(self, tmp_path, fresh_registry):
        mm = ModManager(mods_root=str(tmp_path))
        fresh_registry.register_mod(
            _meta("plain_mod", backend_entry="services", mod_path=str(tmp_path))
        )
        # Backend module exists but exposes no register_* functions.
        mm._backend_entry_modules["plain_mod"] = type("M", (), {})()
        assert _register_single_mod_http_routes(Mock(), mm, "plain_mod") is False
        assert "plain_mod" not in mm._http_routes_registered


# ========================= _restore_entitlements_from_session_id ===========


class TestRestoreEntitlementsFromSessionId:
    def test_empty_session_skips_enterprise_restore(self):
        # Empty/whitespace session must short-circuit *before* touching the
        # enterprise entitlement layer. Spy on the real restore entry point to
        # prove it is never invoked.
        with patch(
            "app.enterprise.mod_entitlements.restore_entitlements_from_session_row"
        ) as restore:
            assert _restore_entitlements_from_session_id("") is None
            assert _restore_entitlements_from_session_id("   ") is None
        restore.assert_not_called()

    def test_valid_session_invokes_enterprise_restore(self):
        # A non-empty session reaches the enterprise layer and forwards the
        # stripped session id to restore_entitlements_from_session_row.
        with (
            patch(
                "app.enterprise.mod_entitlements.restore_entitlements_from_session_row"
            ) as restore,
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="bob",
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_market_identity",
                return_value=(7, "bob"),
            ),
            patch(
                "app.enterprise.mod_entitlements._augment_entitled_for_username",
                return_value=set(),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=set(),
            ),
        ):
            assert _restore_entitlements_from_session_id("  sid-123  ") is None
            restore.assert_called_once_with("sid-123")

    def test_swallows_recoverable_import_error(self):
        # If the enterprise module cannot be imported, the ImportError (a
        # RECOVERABLE_ERROR) is caught and the function returns None.
        with patch.dict(sys.modules, {"app.enterprise.mod_entitlements": None}):
            assert _restore_entitlements_from_session_id("sid-123") is None


# ========================= _mod_allowed_for_api_load ======================


class TestModAllowedForApiLoad:
    def test_empty_mod_id_returns_false(self):
        assert _mod_allowed_for_api_load("  ") is False

    def test_allowed_when_enterprise_filter_inactive(self):
        # Offline test env: SKU is not enterprise so the filter is inactive and any
        # non-empty mod id is permitted.
        with patch(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False
        ):
            assert _mod_allowed_for_api_load("any_mod") is True

    def test_blocked_when_filter_active_and_not_visible(self):
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", return_value=False
            ),
        ):
            assert _mod_allowed_for_api_load("client_only_mod") is False

    def test_allowed_when_filter_active_and_visible(self):
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", return_value=True
            ),
        ):
            assert _mod_allowed_for_api_load("entitled_mod") is True

    def test_import_error_defaults_to_not_allowed(self):
        # When the enterprise module cannot be imported, the except-branch is hit
        # and the conservative default (deny) is returned.
        with patch.dict(sys.modules, {"app.enterprise.mod_entitlements": None}):
            assert _mod_allowed_for_api_load("test_mod") is False


# ========================= ensure_mod_api_ready ============================


class TestEnsureModApiReady:
    def test_empty_mod_id_returns_false(self):
        assert ensure_mod_api_ready("  ") is False

    def test_mods_disabled_returns_false(self):
        with patch(f"{MM}.is_mods_disabled", return_value=True):
            assert ensure_mod_api_ready("test_mod") is False

    def test_returns_false_when_not_allowed(self):
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}._restore_entitlements_from_session_id"),
            patch(f"{MM}._mod_allowed_for_api_load", return_value=False),
        ):
            assert ensure_mod_api_ready("blocked_mod") is False

    def test_already_registered_short_circuits_true(self):
        mm = ModManager(mods_root="/tmp/none")
        mm._loaded_mods = ["ready_mod"]
        mm._http_routes_registered.add("ready_mod")
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}._restore_entitlements_from_session_id"),
            patch(f"{MM}._mod_allowed_for_api_load", return_value=True),
            patch(f"{MM}.get_mod_manager", return_value=mm),
        ):
            assert ensure_mod_api_ready("ready_mod") is True

    def test_loads_mod_when_not_yet_loaded_then_registers(self):
        mm = ModManager(mods_root="/tmp/none")
        mm._loaded_mods = []  # not loaded yet
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}._restore_entitlements_from_session_id"),
            patch(f"{MM}._mod_allowed_for_api_load", return_value=True),
            patch(f"{MM}.get_mod_manager", return_value=mm),
            patch.object(mm, "load_mod", return_value=True) as load_mod,
            patch(f"{MM}._register_single_mod_http_routes", return_value=True) as register,
            patch("app.fastapi_app.get_fastapi_app", return_value=Mock()),
        ):
            assert ensure_mod_api_ready("fresh_mod") is True
        load_mod.assert_called_once_with("fresh_mod")
        assert register.call_count == 1

    def test_returns_false_when_load_mod_fails(self):
        mm = ModManager(mods_root="/tmp/none")
        mm._loaded_mods = []
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}._restore_entitlements_from_session_id"),
            patch(f"{MM}._mod_allowed_for_api_load", return_value=True),
            patch(f"{MM}.get_mod_manager", return_value=mm),
            patch.object(mm, "load_mod", return_value=False),
        ):
            assert ensure_mod_api_ready("broken_mod") is False


# ========================= mount_on_disk_primary_client_mods ===============


class TestMountOnDiskPrimaryClientMods:
    def test_always_returns_empty_list(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # Deliberately removed behavior: never auto-mounts client mods from disk.
        assert mount_on_disk_primary_client_mods(mm) == []
        assert mount_on_disk_primary_client_mods(None) == []


# ========================= load_mod_routes ================================


class TestLoadModRoutes:
    def test_registers_each_routable_mod_in_order(self, tmp_path, fresh_registry):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["mod_b"]  # b is already loaded, a only in registry
        fresh_registry.register_mod(_meta("mod_a", backend_entry="services"))
        fresh_registry.register_mod(_meta("mod_b", backend_entry="services"))
        fresh_registry.register_mod(_meta("mod_no_entry"))  # no backend_entry -> skipped
        app = Mock()
        registered: list[str] = []

        def _reg(_app, _mm, mid, **_kw):
            registered.append(mid)
            return True

        with (
            patch(f"{MM}._register_single_mod_http_routes", side_effect=_reg),
            patch(f"{MM}.mount_on_disk_primary_client_mods", return_value=[]),
            patch(f"{MM}.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(app, mm)
        # _loaded_mods order honored first (mod_b), then registry-only routables
        # (mod_a). The mod without a backend_entry is never registered.
        assert registered == ["mod_b", "mod_a"]

    def test_no_routable_mods_registers_nothing_but_repins_spa(self, tmp_path, fresh_registry):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = []
        # registry is empty -> nothing routable
        registered: list[str] = []
        with (
            patch(
                f"{MM}._register_single_mod_http_routes",
                side_effect=lambda *a, **k: registered.append(a[2]),
            ),
            patch(f"{MM}.mount_on_disk_primary_client_mods", return_value=[]),
            patch(f"{MM}.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last") as spa,
        ):
            load_mod_routes(None, mm)
        assert registered == []
        # SPA fallback is always re-pinned last, even with no mods.
        spa.assert_called_once_with(None)
        # blueprint failures reset at entry.
        assert mm._blueprint_failures == []


# ========================= load_employee_pack_routes ======================


class TestLoadEmployeePackRoutes:
    def test_mods_disabled_returns_without_scanning(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(f"{MM}.is_mods_disabled", return_value=True),
            patch(f"{MM}.register_employee_pack_routes") as reg,
        ):
            assert load_employee_pack_routes(Mock(), mm) is None
        reg.assert_not_called()

    def test_missing_employees_dir_returns_without_registering(self, tmp_path):
        # No mods/_employees directory under tmp_path.
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}.register_employee_pack_routes") as reg,
        ):
            assert load_employee_pack_routes(Mock(), mm) is None
        reg.assert_not_called()

    def test_iterates_employee_packs_and_delegates_registration(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        emp = tmp_path / "_employees" / "pack1"
        emp.mkdir(parents=True)
        (emp / "manifest.json").write_text(
            '{"id": "pack1", "name": "P", "version": "1.0",'
            ' "artifact": "employee_pack", "backend": {"entry": "main"}}'
        )
        with (
            patch(f"{MM}.is_mods_disabled", return_value=False),
            patch(f"{MM}.register_employee_pack_routes", return_value=True) as reg,
        ):
            load_employee_pack_routes(Mock(), mm)
        reg.assert_called_once()
        # the resolved pack id from the manifest is forwarded.
        assert reg.call_args.args[2] == "pack1"


# ========================= register_employee_pack_routes ===================


class TestRegisterEmployeePackRoutes:
    def test_empty_pack_id_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(Mock(), mm, "  ") is False

    def test_disabled_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(f"{MM}.is_mods_disabled", return_value=True):
            assert register_employee_pack_routes(Mock(), mm, "pack1") is False

    def test_missing_manifest_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # _employees/<pack> dir absent -> manifest.json missing -> False.
        with patch(f"{MM}.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(Mock(), mm, "ghost_pack") is False

    def test_registers_routes_from_employee_pack_manifest(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        pack_dir = tmp_path / "_employees" / "pack1"
        backend = pack_dir / "backend"
        backend.mkdir(parents=True)
        (backend / "__init__.py").write_text("")
        # Real employee-pack manifest + a real backend module exporting the registrar.
        (pack_dir / "manifest.json").write_text(
            '{"id": "pack1", "name": "Pack One", "version": "1.0",'
            ' "artifact": "employee_pack", "backend": {"entry": "main"}}'
        )
        (backend / "main.py").write_text(
            "REGISTERED = []\n"
            "def register_fastapi_routes(app, mod_id):\n"
            "    REGISTERED.append((app, mod_id))\n"
        )
        app = object()
        with patch(f"{MM}.is_mods_disabled", return_value=False):
            result = register_employee_pack_routes(app, mm, "pack1")
        assert result is True
        # Idempotent: a second call short-circuits to True without re-registering.
        with patch(f"{MM}.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app, mm, "pack1") is True

    def test_non_employee_pack_artifact_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        pack_dir = tmp_path / "_employees" / "modpack"
        pack_dir.mkdir(parents=True)
        # Wrong artifact type (a plain mod, not employee_pack) -> rejected.
        (pack_dir / "manifest.json").write_text(
            '{"id": "modpack", "name": "M", "version": "1.0",'
            ' "artifact": "mod", "backend": {"entry": "main"}}'
        )
        with patch(f"{MM}.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(Mock(), mm, "modpack") is False
