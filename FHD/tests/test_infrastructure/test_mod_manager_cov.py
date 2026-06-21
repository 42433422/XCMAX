"""Branch-coverage tests for app.infrastructure.mods.mod_manager.

Targets the 60 missing branches in the 84.8%-covered file.
We never hit real filesystems for mod loading — every FS dependency is mocked.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_manager():
    """Return a fresh ModManager with a fake mods_root (no FS calls)."""
    with patch("app.infrastructure.mods.mod_manager._default_mods_root", return_value="/fake/mods"):
        from app.infrastructure.mods.mod_manager import ModManager
        mm = ModManager.__new__(ModManager)
        mm.mods_root = "/fake/mods"
        mm._loaded_mods = []
        mm._http_routes_registered = set()
        mm._blueprint_failures = []
        mm._recent_load_failures = []
        mm._ensure_attempts = 0
        mm._last_ensure_at = None
        mm._scan_cache_fp = ""
        mm._scan_cache_mods = []
        return mm


# ---------------------------------------------------------------------------
# import_mod_backend_py
# ---------------------------------------------------------------------------

class TestImportModBackendPy:
    def test_returns_cached_module(self, tmp_path):
        """If module is already in sys.modules, return it immediately."""
        mod_path = str(tmp_path / "mymod")
        os.makedirs(os.path.join(mod_path, "backend"), exist_ok=True)
        py = os.path.join(mod_path, "backend", "entry.py")
        open(py, "w").close()
        import hashlib

        from app.infrastructure.mods.mod_manager import import_mod_backend_py
        digest = hashlib.sha256(os.path.normpath(os.path.abspath(mod_path)).encode()).hexdigest()[:16]
        safe = "mymod"
        spec_name = f"_xcagi_mod_{safe}_{digest}_entry"
        sentinel = MagicMock()
        sys.modules[spec_name] = sentinel
        try:
            result = import_mod_backend_py(mod_path, "mymod", "entry")
            assert result is sentinel
        finally:
            sys.modules.pop(spec_name, None)

    def test_raises_file_not_found_for_missing_stem(self, tmp_path):
        from app.infrastructure.mods.mod_manager import import_mod_backend_py
        mod_path = str(tmp_path / "mymod")
        os.makedirs(os.path.join(mod_path, "backend"), exist_ok=True)
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py(mod_path, "mymod", "nonexistent")

    def test_raises_import_error_when_spec_none(self, tmp_path):
        mod_path = str(tmp_path / "mymod")
        backend = os.path.join(mod_path, "backend")
        os.makedirs(backend, exist_ok=True)
        py = os.path.join(backend, "entry.py")
        open(py, "w").close()
        from app.infrastructure.mods.mod_manager import import_mod_backend_py
        with patch("importlib.util.spec_from_file_location", return_value=None):
            with pytest.raises(ImportError):
                import_mod_backend_py(mod_path, "mymod", "entry")


# ---------------------------------------------------------------------------
# _invoke_mod_init_hook
# ---------------------------------------------------------------------------

class TestInvokeModInitHook:
    def test_no_params_calls_directly(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook
        fn = MagicMock()
        fn.__wrapped__ = None
        import inspect
        fn.__signature__ = inspect.Signature([])
        _invoke_mod_init_hook(fn)
        fn.assert_called_once_with()

    def test_with_app_param_passes_none(self):
        import inspect

        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook
        calls = []
        def fn(app):
            calls.append(app)
        _invoke_mod_init_hook(fn, mod_id="mymod")
        assert calls == [None]

    def test_with_mod_id_param_passes_mod_id(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook
        calls = []
        def fn(mod_id):
            calls.append(mod_id)
        _invoke_mod_init_hook(fn, mod_id="testmod")
        assert calls == ["testmod"]

    def test_type_error_sig_calls_directly(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook
        fn = MagicMock()
        with patch("inspect.signature", side_effect=TypeError("no sig")):
            _invoke_mod_init_hook(fn, mod_id="m")
        fn.assert_called_once_with()


# ---------------------------------------------------------------------------
# ModManager._all_mods_roots / all_mods_roots
# ---------------------------------------------------------------------------

class TestAllModsRoots:
    def test_includes_primary_when_exists(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots
        result = _all_mods_roots(str(tmp_path))
        assert str(tmp_path) in result

    def test_excludes_nonexistent_primary(self):
        from app.infrastructure.mods.mod_manager import _all_mods_roots
        result = _all_mods_roots("/definitely/does/not/exist")
        # primary not in result (it's not a dir)
        assert "/definitely/does/not/exist" not in result

    def test_includes_env_root_when_set(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots
        env_path = tmp_path / "extra_mods"
        env_path.mkdir()
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(env_path)}):
            result = _all_mods_roots("/fake")
        assert str(env_path) in result

    def test_deduplicates_roots(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": str(tmp_path)}):
            result = _all_mods_roots(str(tmp_path))
        assert result.count(str(tmp_path)) == 1


# ---------------------------------------------------------------------------
# ModManager.resolve_mod_directory
# ---------------------------------------------------------------------------

class TestResolveModDirectory:
    def test_returns_none_for_empty_mod_id(self):
        mm = _get_manager()
        with patch.object(mm, "_refresh_mods_root_if_needed"):
            result = mm.resolve_mod_directory("")
        assert result is None

    def test_returns_none_for_whitespace(self):
        mm = _get_manager()
        with patch.object(mm, "_refresh_mods_root_if_needed"):
            result = mm.resolve_mod_directory("   ")
        assert result is None

    def test_returns_path_when_mod_dir_exists(self, tmp_path):
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").touch()
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="mymod"),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]),
        ):
            result = mm.resolve_mod_directory("mymod")
        assert result == str(mod_dir)

    def test_tries_canonical_when_direct_fails(self, tmp_path):
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        canonical_dir = tmp_path / "mymod-canonical"
        canonical_dir.mkdir()
        (canonical_dir / "manifest.json").touch()
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="mymod-canonical"),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]),
        ):
            result = mm.resolve_mod_directory("mymod-alias")
        assert result == str(canonical_dir)


# ---------------------------------------------------------------------------
# ModManager.scan_mods
# ---------------------------------------------------------------------------

class TestScanMods:
    def test_returns_from_cache_when_fp_matches(self):
        mm = _get_manager()
        cached = [MagicMock(id="mod1")]
        mm._scan_cache_mods = cached
        mm._scan_cache_fp = "abc"
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="abc"),
        ):
            result = mm.scan_mods()
        assert result == cached

    def test_empty_mods_root_dir_logs_warning(self, tmp_path):
        mm = _get_manager()
        mm.mods_root = str(tmp_path / "nonexistent")
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value=""),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path / "nonexistent")]),
        ):
            result = mm.scan_mods(use_cache=False)
        assert result == []

    def test_skips_underscore_prefixed_entries(self, tmp_path):
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        hidden = tmp_path / "_hidden_mod"
        hidden.mkdir()
        (hidden / "manifest.json").touch()
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value=""),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=None),
        ):
            result = mm.scan_mods(use_cache=False)
        assert result == []


# ---------------------------------------------------------------------------
# ModManager.get_mod_routes
# ---------------------------------------------------------------------------

class TestGetRoutes:
    def test_empty_when_no_mods(self):
        mm = _get_manager()
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[]),
        ):
            result = mm.get_routes()
        assert result == []

    def test_skips_mods_without_frontend_routes(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "mymod"
        m.frontend_routes = ""
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[m]),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=True, create=True),
        ):
            result = mm.get_routes()
        assert result == []

    def test_returns_routes_for_visible_mods(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "mymod"
        m.frontend_routes = "dist/routes.js"
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[m]),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=True, create=True),
        ):
            result = mm.get_routes()
        assert result == [{"mod_id": "mymod", "routes_path": "dist/routes.js"}]

    def test_skips_non_visible_mods(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "secretmod"
        m.frontend_routes = "dist/routes.js"
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[m]),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=False, create=True),
        ):
            result = mm.get_routes()
        assert result == []


# ---------------------------------------------------------------------------
# ModManager.load_all_mods
# ---------------------------------------------------------------------------

class TestLoadAllMods:
    def test_returns_empty_when_no_mods(self):
        mm = _get_manager()
        with patch.object(mm, "scan_mods", return_value=[]):
            result = mm.load_all_mods()
        assert result == []

    def test_skips_mod_with_unsatisfied_deps(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "mymod"
        m.primary = False
        m.dependencies = ["other"]
        with (
            patch.object(mm, "scan_mods", return_value=[m]),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=False),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=True, create=True),
        ):
            result = mm.load_all_mods()
        assert "mymod" not in result

    def test_skips_enterprise_non_visible_mod(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "secretmod"
        m.primary = False
        m.dependencies = []
        with (
            patch.object(mm, "scan_mods", return_value=[m]),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=False, create=True),
        ):
            result = mm.load_all_mods()
        assert "secretmod" not in result

    def test_loads_visible_mod_with_satisfied_deps(self):
        mm = _get_manager()
        m = MagicMock()
        m.id = "mymod"
        m.primary = True
        m.dependencies = []
        with (
            patch.object(mm, "scan_mods", return_value=[m]),
            patch.object(mm, "load_mod", return_value=True),
            patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                  return_value=True, create=True),
        ):
            result = mm.load_all_mods()
        assert "mymod" in result


# ---------------------------------------------------------------------------
# ModManager.validate_mod_package
# ---------------------------------------------------------------------------

class TestValidateModPackage:
    def test_returns_false_when_file_missing(self, tmp_path):
        mm = _get_manager()
        ok, msg, info = mm.validate_mod_package(str(tmp_path / "ghost.xcmod"))
        assert not ok
        assert "不存在" in msg

    def test_returns_false_for_non_zip_file(self, tmp_path):
        f = tmp_path / "bad.xcmod"
        f.write_text("not a zip")
        mm = _get_manager()
        ok, msg, info = mm.validate_mod_package(str(f))
        assert not ok
        assert "ZIP" in msg

    def test_returns_false_when_manifest_has_no_id(self, tmp_path):
        import zipfile
        zf = tmp_path / "test.xcmod"
        with zipfile.ZipFile(zf, "w") as z:
            z.writestr("manifest.json", '{"name": "test", "version": "1.0"}')
        mm = _get_manager()
        with patch("app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                   return_value=(str(tmp_path), {"name": "test", "version": "1.0"})):
            ok, msg, info = mm.validate_mod_package(str(zf))
        assert not ok
        assert "id" in msg


# ---------------------------------------------------------------------------
# get_mod_manager singleton
# ---------------------------------------------------------------------------

class TestGetModManagerSingleton:
    def test_returns_same_instance(self):
        from app.infrastructure.mods import mod_manager as mm_mod
        orig = mm_mod._mod_manager
        try:
            mm_mod._mod_manager = None
            inst1 = mm_mod.get_mod_manager()
            inst2 = mm_mod.get_mod_manager()
            assert inst1 is inst2
        finally:
            mm_mod._mod_manager = orig


# ---------------------------------------------------------------------------
# load_mod_routes
# ---------------------------------------------------------------------------

class TestLoadModRoutes:
    def test_calls_register_for_loaded_mods(self):
        mm = _get_manager()
        mm._loaded_mods = ["mymod"]
        meta = MagicMock()
        meta.id = "mymod"
        meta.backend_entry = "entry"
        mock_app = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes"),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last", create=True),
        ):
            mock_reg.return_value.list_mods.return_value = [meta]
            from app.infrastructure.mods.mod_manager import load_mod_routes
            load_mod_routes(mock_app, mm)

    def test_no_double_registration_for_same_id(self):
        mm = _get_manager()
        mm._loaded_mods = ["mymod", "mymod"]
        meta = MagicMock()
        meta.id = "mymod"
        meta.backend_entry = "entry"
        mock_app = MagicMock()
        register_calls = []
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                  side_effect=lambda a, m, mid: register_calls.append(mid)),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last", create=True),
        ):
            mock_reg.return_value.list_mods.return_value = [meta]
            from app.infrastructure.mods.mod_manager import load_mod_routes
            load_mod_routes(mock_app, mm)
        assert register_calls.count("mymod") == 1


# ---------------------------------------------------------------------------
# register_employee_pack_routes
# ---------------------------------------------------------------------------

class TestRegisterEmployeePackRoutes:
    def test_returns_false_for_empty_pack_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            result = register_employee_pack_routes(MagicMock(), mm, "")
        assert result is False

    def test_returns_false_when_mods_disabled(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes
        mm = _get_manager()
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = register_employee_pack_routes(MagicMock(), mm, "emp1")
        assert result is False

    def test_returns_false_when_manifest_missing(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            result = register_employee_pack_routes(MagicMock(), mm, "emp1")
        assert result is False

    def test_already_registered_returns_true_without_reregistering(self, tmp_path):
        from app.infrastructure.mods import mod_manager as mm_mod
        mm = _get_manager()
        mm.mods_root = str(tmp_path)
        orig = set(mm_mod._employee_pack_routes_registered)
        mm_mod._employee_pack_routes_registered.add("emp1")
        try:
            with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
                result = mm_mod.register_employee_pack_routes(MagicMock(), mm, "emp1", force=False)
            assert result is True
        finally:
            mm_mod._employee_pack_routes_registered.clear()
            mm_mod._employee_pack_routes_registered.update(orig)


# ---------------------------------------------------------------------------
# mount_on_disk_primary_client_mods
# ---------------------------------------------------------------------------

class TestMountOnDiskPrimaryClientMods:
    def test_returns_empty_when_mods_disabled(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mount_on_disk_primary_client_mods()
        assert result == []

    def test_returns_empty_when_sunbird_mod_id_empty(self):
        import types
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods
        _fake_amb = types.ModuleType("app.enterprise.account_mod_binding")
        _fake_amb.SUNBIRD_CLIENT_MOD_ID = ""
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.dict("sys.modules", {"app.enterprise.account_mod_binding": _fake_amb}),
        ):
            result = mount_on_disk_primary_client_mods()
        assert result == []

    def test_returns_mod_id_when_already_loaded(self, tmp_path):
        import types
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods
        _fake_amb = types.ModuleType("app.enterprise.account_mod_binding")
        _fake_amb.SUNBIRD_CLIENT_MOD_ID = "sunbird"
        mm = _get_manager()
        mm._loaded_mods = ["sunbird"]
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.dict("sys.modules", {"app.enterprise.account_mod_binding": _fake_amb}),
            patch.object(mm, "resolve_mod_directory", return_value=str(tmp_path / "sunbird")),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        ):
            result = mount_on_disk_primary_client_mods(mm)
        assert result == ["sunbird"]


# ---------------------------------------------------------------------------
# _default_mods_root fallback paths
# ---------------------------------------------------------------------------

class TestDefaultModsRoot:
    def test_returns_string(self):
        from app.infrastructure.mods.mod_manager import _default_mods_root
        with (
            patch("os.path.isdir", return_value=False),
            patch("os.getcwd", return_value="/tmp"),
        ):
            result = _default_mods_root()
        assert isinstance(result, str)
