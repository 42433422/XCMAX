"""Tests for app.infrastructure.mods.mod_manager — deep coverage (ext4).

Focus: ModManager.__init__, invalidate_scan_cache, _mods_scan_fingerprint,
_refresh_mods_root_if_needed, _record_load_failure, ensure_mods_loaded,
all_mods_roots, resolve_mod_directory, scan_mods, load_mod, unload_mod,
install_mod_package, uninstall_mod, update_mod, validate_mod_package,
get_mod, list_loaded_mods, list_mods, list_all_mods, get_routes,
load_all_mods, get_mod_manager singleton, is_mods_disabled,
_default_mods_root, import_mod_backend_py, _register_mod_hooks.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# is_mods_disabled
# ---------------------------------------------------------------------------


class TestIsModsDisabled:
    def test_default_not_disabled(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": ""}, clear=False):
            result = is_mods_disabled()
            assert result is False

    def test_disabled_via_env(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}):
            result = is_mods_disabled()
            assert result is True

    def test_disabled_via_true(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "true"}):
            result = is_mods_disabled()
            assert result is True


# ---------------------------------------------------------------------------
# _default_mods_root
# ---------------------------------------------------------------------------


class TestDefaultModsRoot:
    def test_returns_string(self):
        from app.infrastructure.mods.mod_manager import _default_mods_root

        result = _default_mods_root()
        assert isinstance(result, str)

    def test_env_override(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _default_mods_root

        custom = tmp_path / "custom_mods"
        custom.mkdir()
        with patch.dict(
            "os.environ",
            {"XCAGI_MODS_ROOT": str(custom), "XCAGI_MODS_DIR": ""},
            clear=False,
        ):
            result = _default_mods_root()
            assert result == str(custom)


# ---------------------------------------------------------------------------
# ModManager.__init__
# ---------------------------------------------------------------------------


class TestModManagerInit:
    def test_init_with_explicit_mods_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mods_root = str(tmp_path / "mods")
        mgr = ModManager(mods_root=mods_root)
        assert mgr.mods_root == mods_root
        assert mgr._loaded_mods == []

    def test_init_with_none_uses_default(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=None)
        assert isinstance(mgr.mods_root, str)
        assert mgr._loaded_mods == []

    def test_init_default_attributes(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        assert mgr._recent_load_failures == []
        assert mgr._blueprint_failures == []
        assert mgr._scan_manifest_errors == []
        assert mgr._ensure_attempts == 0
        assert mgr._http_routes_registered == set()
        assert mgr._scan_cache_fp == ""
        assert mgr._scan_cache_mods == []


# ---------------------------------------------------------------------------
# ModManager.invalidate_scan_cache
# ---------------------------------------------------------------------------


class TestInvalidateScanCache:
    def test_clears_cache(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._scan_cache_fp = "old_fp"
        mgr._scan_cache_mods = [MagicMock()]
        mgr.invalidate_scan_cache()
        assert mgr._scan_cache_fp == ""
        assert mgr._scan_cache_mods == []


# ---------------------------------------------------------------------------
# ModManager._mods_scan_fingerprint
# ---------------------------------------------------------------------------


class TestModsScanFingerprint:
    def test_empty_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path / "nonexistent"))
        fp = mgr._mods_scan_fingerprint()
        assert isinstance(fp, str)

    def test_with_manifest(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text(json.dumps({"id": "test", "name": "Test", "version": "1.0"}))
        mgr = ModManager(mods_root=str(tmp_path))
        fp = mgr._mods_scan_fingerprint()
        assert "test_mod" in fp


# ---------------------------------------------------------------------------
# ModManager._refresh_mods_root_if_needed
# ---------------------------------------------------------------------------


class TestRefreshModsRootIfNeeded:
    def test_env_override_updates_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        new_root = tmp_path / "new_mods"
        new_root.mkdir()
        mgr = ModManager(mods_root=str(tmp_path / "old"))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(new_root)}):
            mgr._refresh_mods_root_if_needed()
            assert mgr.mods_root == str(new_root)

    def test_missing_root_fallback(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        bad_root = str(tmp_path / "nonexistent_dir_xyz")
        mgr = ModManager(mods_root=bad_root)
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False):
            mgr._refresh_mods_root_if_needed()
            # Should have re-resolved to default
            assert mgr.mods_root != bad_root or os.path.isdir(mgr.mods_root)


# ---------------------------------------------------------------------------
# ModManager._record_load_failure
# ---------------------------------------------------------------------------


class TestRecordLoadFailure:
    def test_records_failure(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._record_load_failure("test_mod", "backend", "import failed")
        assert len(mgr._recent_load_failures) == 1
        assert mgr._recent_load_failures[0]["mod_id"] == "test_mod"
        assert mgr._recent_load_failures[0]["stage"] == "backend"

    def test_truncates_long_message(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        long_msg = "x" * 1000
        mgr._record_load_failure("mod", "stage", long_msg)
        assert len(mgr._recent_load_failures[0]["message"]) <= 500


# ---------------------------------------------------------------------------
# ModManager.record_blueprint_failure / get_blueprint_failures
# ---------------------------------------------------------------------------


class TestBlueprintFailures:
    def test_record_and_retrieve(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr.record_blueprint_failure("mod1", "blueprint error")
        failures = mgr.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod1"

    def test_get_scan_manifest_errors(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        errors = mgr.get_scan_manifest_errors()
        assert isinstance(errors, list)


# ---------------------------------------------------------------------------
# ModManager.get_recent_load_failures
# ---------------------------------------------------------------------------


class TestGetRecentLoadFailures:
    def test_returns_copy(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._record_load_failure("mod1", "fs", "not found")
        failures = mgr.get_recent_load_failures()
        assert len(failures) == 1
        # Modifying returned list shouldn't affect internal state
        failures.clear()
        assert len(mgr.get_recent_load_failures()) == 1


# ---------------------------------------------------------------------------
# ModManager.all_mods_roots
# ---------------------------------------------------------------------------


class TestAllModsRoots:
    def test_returns_list(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        roots = mgr.all_mods_roots()
        assert isinstance(roots, list)
        assert str(tmp_path) in roots


# ---------------------------------------------------------------------------
# ModManager.resolve_mod_directory
# ---------------------------------------------------------------------------


class TestResolveModDirectory:
    def test_empty_mod_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        result = mgr.resolve_mod_directory("")
        assert result is None

    def test_none_mod_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        result = mgr.resolve_mod_directory(None)
        assert result is None

    def test_nonexistent_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        result = mgr.resolve_mod_directory("nonexistent_mod")
        assert result is None

    def test_existing_mod_with_manifest(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "my_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "my_mod", "name": "My Mod", "version": "1.0"})
        )
        mgr = ModManager(mods_root=str(tmp_path))
        result = mgr.resolve_mod_directory("my_mod")
        assert result is not None
        assert "my_mod" in result


# ---------------------------------------------------------------------------
# ModManager.scan_mods
# ---------------------------------------------------------------------------


class TestScanMods:
    def test_empty_directory(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
        ):
            result = mgr.scan_mods(use_cache=False)
            assert isinstance(result, list)
            assert len(result) == 0

    def test_with_valid_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test_mod", "name": "Test Mod", "version": "1.0"})
        )
        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
        ):
            result = mgr.scan_mods(use_cache=False)
            assert len(result) == 1
            assert result[0].id == "test_mod"

    def test_skips_underscore_prefix(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "_internal"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "_internal", "name": "Internal", "version": "1.0"})
        )
        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
        ):
            result = mgr.scan_mods(use_cache=False)
            assert len(result) == 0

    def test_uses_cache(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
        ):
            # First scan populates cache
            result1 = mgr.scan_mods()
            # Second scan should use cache
            result2 = mgr.scan_mods(use_cache=True)
            assert result1 == result2

    def test_cache_invalidation(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
        ):
            mgr.scan_mods()
            assert mgr._scan_cache_fp != "" or len(mgr._scan_cache_mods) == 0
            mgr.invalidate_scan_cache()
            assert mgr._scan_cache_fp == ""
            assert mgr._scan_cache_mods == []


# ---------------------------------------------------------------------------
# ModManager.load_mod
# ---------------------------------------------------------------------------


class TestLoadMod:
    def test_load_nonexistent_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = None
            result = mgr.load_mod("nonexistent_mod")
            assert result is False

    def test_load_already_loaded_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_meta = MagicMock()
        mock_meta.id = "already_loaded"
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = mock_meta
            mgr._loaded_mods.append("already_loaded")
            result = mgr.load_mod("already_loaded")
            assert result is True

    def test_load_mod_sku_blocked(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("blocked"),
        ):
            result = mgr.load_mod("blocked_mod")
            assert result is False
            assert any(f["mod_id"] == "blocked_mod" for f in mgr._recent_load_failures)


# ---------------------------------------------------------------------------
# ModManager.unload_mod
# ---------------------------------------------------------------------------


class TestUnloadMod:
    def test_unload_removes_from_loaded(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._loaded_mods.append("test_mod")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_instance.return_value = None
            mock_reg.return_value.unregister_mod.return_value = None
            with patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError):
                result = mgr.unload_mod("test_mod")
                assert result is True
                assert "test_mod" not in mgr._loaded_mods

    def test_unload_with_cleanup(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._loaded_mods.append("cleanup_mod")
        mock_instance = MagicMock()
        mock_instance.cleanup = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_instance.return_value = mock_instance
            mock_reg.return_value.unregister_mod.return_value = None
            with patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError):
                result = mgr.unload_mod("cleanup_mod")
                assert result is True
                mock_instance.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# ModManager.validate_mod_package
# ---------------------------------------------------------------------------


class TestValidateModPackage:
    def test_nonexistent_file(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mgr.validate_mod_package("/nonexistent/file.xcmod")
        assert ok is False
        assert "不存在" in msg

    def test_not_a_zip(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        bad_file = tmp_path / "bad.xcmod"
        bad_file.write_text("not a zip file")
        mgr = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mgr.validate_mod_package(str(bad_file))
        assert ok is False
        assert "ZIP" in msg


# ---------------------------------------------------------------------------
# ModManager.get_mod
# ---------------------------------------------------------------------------


class TestGetMod:
    def test_get_mod_delegates_to_registry(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_meta = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = mock_meta
            result = mgr.get_mod("some_mod")
            assert result is mock_meta

    def test_get_mod_not_found(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = None
            result = mgr.get_mod("nonexistent")
            assert result is None


# ---------------------------------------------------------------------------
# ModManager.list_loaded_mods
# ---------------------------------------------------------------------------


class TestListLoadedMods:
    def test_delegates_to_registry(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_list = [MagicMock()]
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.list_mods.return_value = mock_list
            result = mgr.list_loaded_mods()
            assert result == mock_list


# ---------------------------------------------------------------------------
# ModManager.list_all_mods
# ---------------------------------------------------------------------------


class TestListAllMods:
    def test_disabled_returns_empty(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mgr.list_all_mods()
            assert result == []

    def test_returns_api_dicts(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "api_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "api_mod", "name": "API Mod", "version": "1.0"})
        )
        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            result = mgr.list_all_mods()
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ModManager.get_routes
# ---------------------------------------------------------------------------


class TestGetRoutes:
    def test_disabled_returns_empty(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mgr.get_routes()
            assert result == []

    def test_returns_routes_for_mods_with_frontend(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "route_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "route_mod",
                    "name": "Route Mod",
                    "version": "1.0",
                    "frontend": {"routes": "routes"},
                }
            )
        )
        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            result = mgr.get_routes()
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ModManager._metadata_to_api_dict
# ---------------------------------------------------------------------------


class TestMetadataToApiDict:
    def test_converts_metadata(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_meta = MagicMock()
        mock_meta.id = "test"
        mock_meta.name = "Test"
        mock_meta.version = "1.0"
        mock_meta.author = "author"
        mock_meta.description = "desc"
        mock_meta.primary = False
        mock_meta.artifact = None
        mock_meta.industry = {}
        mock_meta.ui_labels = {}
        mock_meta.ui_starter_pack = []
        mock_meta.frontend_menu = []
        mock_meta.frontend_pro_entry_path = ""
        mock_meta.frontend_menu_overrides = []
        mock_meta.workflow_employees = []
        mock_meta.comms_exports = []
        result = ModManager._metadata_to_api_dict(mock_meta)
        assert result["id"] == "test"
        assert result["name"] == "Test"
        assert result["version"] == "1.0"


# ---------------------------------------------------------------------------
# ModManager.ensure_mods_loaded
# ---------------------------------------------------------------------------


class TestEnsureModsLoaded:
    def test_disabled_skips(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_app = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            mgr.ensure_mods_loaded(mock_app)
            # Should not attempt to load

    def test_already_loaded_skips(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._loaded_mods = ["already_there"]
        mock_app = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            mgr.ensure_mods_loaded(mock_app)

    def test_throttle_after_attempts(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mgr._ensure_attempts = 20  # Already at max
        mock_app = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
        ):
            mock_reg.return_value.list_mods.return_value = []
            mgr.ensure_mods_loaded(mock_app)
            # Should not attempt further


# ---------------------------------------------------------------------------
# get_mod_manager singleton
# ---------------------------------------------------------------------------


class TestGetModManager:
    def test_returns_mod_manager(self):
        from app.infrastructure.mods.mod_manager import ModManager, get_mod_manager

        mgr = get_mod_manager()
        assert isinstance(mgr, ModManager)

    def test_singleton_identity(self):
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr1 = get_mod_manager()
        mgr2 = get_mod_manager()
        assert mgr1 is mgr2


# ---------------------------------------------------------------------------
# import_mod_backend_py
# ---------------------------------------------------------------------------


class TestImportModBackendPy:
    def test_nonexistent_path(self, tmp_path):
        from app.infrastructure.mods.mod_manager import import_mod_backend_py

        # import_mod_backend_py raises FileNotFoundError when the backend file is missing.
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py(str(tmp_path / "nope"), "mod_id", "entry")


# ---------------------------------------------------------------------------
# _short_exc_message
# ---------------------------------------------------------------------------


class TestShortExcMessage:
    def test_truncates_long_message(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        exc = RuntimeError("x" * 1000)
        msg = _short_exc_message(exc, max_len=100)
        assert len(msg) <= 100

    def test_short_message_unchanged(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        exc = ValueError("short error")
        msg = _short_exc_message(exc)
        assert "short error" in msg


# ---------------------------------------------------------------------------
# ModManager.load_all_mods
# ---------------------------------------------------------------------------


class TestLoadAllMods:
    def test_empty_directory(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
        ):
            result = mgr.load_all_mods()
            assert isinstance(result, list)
            assert len(result) == 0

    def test_with_mods(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "loadable_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "loadable_mod", "name": "Loadable", "version": "1.0"})
        )
        mgr = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
            patch.dict(
                "os.environ",
                {"XCAGI_MODS_ROOT": str(tmp_path), "XCAGI_MODS_DIR": ""},
                clear=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
        ):
            result = mgr.load_all_mods()
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ModManager.install_mod_package
# ---------------------------------------------------------------------------


class TestInstallModPackage:
    def test_nonexistent_package(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        ok, msg, meta = mgr.install_mod_package("/nonexistent/path.xcmod")
        assert ok is False


# ---------------------------------------------------------------------------
# ModManager.uninstall_mod
# ---------------------------------------------------------------------------


class TestUninstallMod:
    def test_unloaded_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = None
            with patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
                side_effect=ImportError,
            ):
                ok, msg = mgr.uninstall_mod("nonexistent_mod")
                assert ok is False

    def test_loaded_mod_uninstall(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mgr = ModManager(mods_root=str(tmp_path))
        mock_meta = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            mock_reg.return_value.get_mod_metadata.return_value = mock_meta
            with patch.object(mgr, "unload_mod", return_value=True):
                ok, msg = mgr.uninstall_mod("test_mod", remove_files=False)
                assert ok is True
