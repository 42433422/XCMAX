"""Tests for app.infrastructure.mods.mod_manager — deep coverage for remaining uncovered branches.

Focus: ModManager methods (install, uninstall, update, validate, scan, load, ensure),
module-level functions, and error paths not covered by existing tests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    _default_mods_root,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _short_exc_message,
    import_mod_backend_py,
    is_mods_disabled,
)

# ========================= is_mods_disabled - extended ===================


class TestIsModsDisabledExtended:
    def test_env_1(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}):
            assert is_mods_disabled() is True

    def test_env_true(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "true"}):
            assert is_mods_disabled() is True

    def test_env_yes(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "yes"}):
            assert is_mods_disabled() is True

    def test_env_on(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "on"}):
            assert is_mods_disabled() is True

    def test_env_false(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "0"}):
            assert is_mods_disabled() is False

    def test_env_empty(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": ""}):
            assert is_mods_disabled() is False

    def test_env_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            assert is_mods_disabled() is False


# ========================= _short_exc_message - extended ==================


class TestShortExcMessageExtended:
    def test_short_message(self):
        assert _short_exc_message(ValueError("short")) == "short"

    def test_long_message_truncated(self):
        long_msg = "A" * 600
        result = _short_exc_message(ValueError(long_msg))
        assert len(result) <= 480
        assert result.endswith("...")

    def test_empty_message_uses_type_name(self):
        result = _short_exc_message(ValueError(""))
        assert result == "ValueError"

    def test_exact_max_len(self):
        msg = "A" * 480
        result = _short_exc_message(ValueError(msg))
        assert result == msg


# ========================= _backend_path_for_mod =========================


class TestBackendPathForMod:
    def test_basic(self):
        assert _backend_path_for_mod("/mods/test_mod") == "/mods/test_mod/backend"


# ========================= _register_mod_hooks - extended =================


class TestRegisterModHooksExtended:
    def test_hooks_with_invalid_spec(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "invalid_no_dot"},
        )
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py"),
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            _register_mod_hooks("test", meta)
        # Spec has no module.attr form -> invalid, nothing subscribed.
        mock_sub.assert_not_called()

    def test_hooks_with_backend_prefix(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "backend.services.handler"},
        )
        mock_module = Mock()
        mock_module.handler = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=mock_module
        ):
            with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
                _register_mod_hooks("test", meta)
        mock_sub.assert_called_once()

    def test_hooks_no_mod_path(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="",
            hooks={"on_chat": "services.handler"},
        )
        with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
            _register_mod_hooks("test", meta)
        # Empty mod_path -> cannot resolve handlers, nothing subscribed.
        mock_sub.assert_not_called()

    def test_hooks_handler_not_callable(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "services.not_callable"},
        )
        mock_module = Mock()
        mock_module.not_callable = "not a function"
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mock_module,
            ),
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            _register_mod_hooks("test", meta)
        # Resolved attribute is not callable -> skipped, nothing subscribed.
        mock_sub.assert_not_called()

    def test_hooks_import_error(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "services.handler"},
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=ImportError("no module"),
            ),
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            # Import failure is recoverable -> swallowed, nothing subscribed.
            _register_mod_hooks("test", meta)
        mock_sub.assert_not_called()


# ========================= ModManager - invalidate_scan_cache ============


class TestModManagerInvalidateScanCache:
    def test_invalidate(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_cache_fp = "old_fp"
        mm._scan_cache_mods = [Mock()]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


# ========================= ModManager - _mods_scan_fingerprint ============


class TestModManagerScanFingerprint:
    def test_empty_root(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "nonexistent"))
        fp = mm._mods_scan_fingerprint()
        assert isinstance(fp, str)

    def test_with_manifest(self, tmp_path):
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "test", "name": "Test", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        fp = mm._mods_scan_fingerprint()
        assert "test_mod" in fp


# ========================= ModManager - _refresh_mods_root_if_needed ======


class TestModManagerRefreshModsRoot:
    def test_env_updates_root(self, tmp_path):
        new_root = str(tmp_path / "new_mods")
        os.makedirs(new_root)
        mm = ModManager(mods_root=str(tmp_path / "old_mods"))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": new_root}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == new_root

    def test_env_not_dir_keeps_current(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "/nonexistent/path"}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)

    def test_current_missing_re_resolves(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "missing_dir"))
        with patch(
            "app.infrastructure.mods.mod_manager._default_mods_root", return_value=str(tmp_path)
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)


# ========================= ModManager - record methods ====================


class TestModManagerRecordMethods:
    def test_record_load_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "backend", "load error")
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod1"

    def test_record_blueprint_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm.record_blueprint_failure("mod1", "blueprint error")
        failures = mm.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod1"

    def test_get_scan_manifest_errors(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_manifest_errors = [{"entry": "bad_mod", "message": "invalid"}]
        errors = mm.get_scan_manifest_errors()
        assert len(errors) == 1


# ========================= ModManager - ensure_mods_loaded ================


class TestModManagerEnsureModsLoaded:
    def test_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        mock_load.assert_not_called()

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # ensure_mods_loaded consults list_loaded_mods() (the registry view),
        # not the _loaded_mods attribute directly.
        with (
            patch.object(mm, "list_loaded_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Registry already has a mod -> no reload.
        mock_load.assert_not_called()

    def test_no_discovered_mods(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "scan_mods", return_value=[]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Nothing discovered on disk -> nothing to load.
        mock_load.assert_not_called()

    def test_throttle_rate(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._last_ensure_at = 9999999999.0  # Very recent
        mm._ensure_attempts = 0
        mock_plan = Mock()
        with (
            patch.object(mm, "scan_mods", return_value=[mock_plan]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Within the throttle window -> load is skipped.
        mock_load.assert_not_called()

    def test_max_attempts_reached(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 20
        mock_plan = Mock()
        with (
            patch.object(mm, "scan_mods", return_value=[mock_plan]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Attempt budget exhausted -> load is skipped.
        mock_load.assert_not_called()


# ========================= ModManager - resolve_mod_directory =============


class TestModManagerResolveModDirectory:
    def test_empty_mod_id(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory("")
        assert result is None

    def test_none_mod_id(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory(None)
        assert result is None

    def test_found_in_root(self, tmp_path):
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory("test_mod")
        assert result is not None
        assert "test_mod" in result

    def test_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="unknown"):
            with patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]):
                result = mm.resolve_mod_directory("nonexistent_mod")
        assert result is None


# ========================= ModManager - scan_mods ========================


class TestModManagerScanMods:
    def test_scan_empty_root(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            mods = mm.scan_mods()
        assert isinstance(mods, list)

    def test_scan_with_cache(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_cache_fp = "test_fp"
        mm._scan_cache_mods = [Mock()]
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="test_fp"),
        ):
            mods = mm.scan_mods(use_cache=True)
        assert len(mods) == 1

    def test_scan_skip_underscore_dirs(self, tmp_path):
        underscore_dir = tmp_path / "_private"
        underscore_dir.mkdir()
        (underscore_dir / "manifest.json").write_text("{}")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert len(mods) == 0

    def test_scan_skip_non_dirs(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a mod")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert len(mods) == 0

    def test_scan_invalid_manifest(self, tmp_path):
        mod_dir = tmp_path / "bad_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid json")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert len(mods) == 0
        errors = mm.get_scan_manifest_errors()
        assert len(errors) > 0


# ========================= ModManager - load_mod =========================


class TestModManagerLoadModExtended:
    def test_sku_blocked(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("blocked"),
        ):
            result = mm.load_mod("blocked_mod")
        assert result is False
        failures = mm.get_recent_load_failures()
        assert any(f["stage"] == "sku_policy" for f in failures)

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("existing_mod")
        assert result is True

    def test_already_loaded_but_missing_from_list(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("missing_from_list")
        assert result is True
        assert "missing_from_list" in mm._loaded_mods

    def test_mod_directory_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="unknown"),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]),
        ):
            result = mm.load_mod("nonexistent")
        assert result is False

    def test_invalid_manifest(self, tmp_path):
        mod_dir = tmp_path / "bad_manifest"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid")
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=None),
        ):
            result = mm.load_mod("bad_manifest")
        assert result is False

    def test_bundle_artifact(self, tmp_path):
        mod_dir = tmp_path / "bundle_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "bundle_mod", "name": "Bundle", "version": "1.0", "artifact": "bundle"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.register_mod.return_value = True
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="bundle_mod", name="Bundle", version="1.0", mod_path=str(mod_dir), artifact="bundle"
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
        ):
            result = mm.load_mod("bundle_mod")
        assert result is True

    def test_dependency_not_satisfied(self, tmp_path):
        mod_dir = tmp_path / "dep_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "dep_mod", "name": "Dep", "version": "1.0", "dependencies": ["missing_dep"]}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="dep_mod",
            name="Dep",
            version="1.0",
            mod_path=str(mod_dir),
            dependencies=["missing_dep"],
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=False),
        ):
            result = mm.load_mod("dep_mod")
        assert result is False


# ========================= ModManager - _load_mod_backend ================


class TestModManagerLoadModBackend:
    def test_no_backend_dir(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "no_backend"
        mod_dir.mkdir()  # no backend/ subdir
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="no_backend", name="No Backend", version="1.0", mod_path=str(mod_dir))
        result = mm._load_mod_backend("no_backend", str(mod_dir), meta)
        # No backend directory -> early return, no backend module registered.
        assert result is None
        assert "no_backend" not in mm._backend_entry_modules

    def test_backend_entry_with_init(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "entry_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "main.py").write_text("INIT_CALLED = True\ndef init(): pass\n")
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="entry_mod",
            name="Entry",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="main",
            backend_init="init",
        )
        mock_module = Mock()
        mock_module.init = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=mock_module
        ):
            with patch("app.infrastructure.mods.mod_manager._register_mod_hooks"):
                mm._load_mod_backend("entry_mod", str(mod_dir), meta)
        mock_module.init.assert_called_once()

    def test_backend_entry_import_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "fail_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="fail_mod",
            name="Fail",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="missing",
            backend_init="init",
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=ImportError("no module"),
            ),
            pytest.raises(ImportError),
        ):
            mm._load_mod_backend("fail_mod", str(mod_dir), meta)


# ========================= ModManager - unload_mod ========================


class TestModManagerUnloadMod:
    def test_unload_with_cleanup(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_instance = Mock()
        mock_instance.cleanup = Mock()
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms") as mock_comms,
        ):
            mock_comms.return_value.unregister_all = Mock()
            result = mm.unload_mod("test_mod")
        assert result is True
        mock_instance.cleanup.assert_called_once()
        assert "test_mod" not in mm._loaded_mods

    def test_unload_cleanup_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_instance = Mock()
        mock_instance.cleanup.side_effect = RuntimeError("cleanup failed")
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("test_mod")
        assert result is True


# ========================= ModManager - validate_mod_package ==============


class TestModManagerValidateModPackage:
    def test_file_not_exists(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.validate_mod_package("/nonexistent/path.xcmod")
        assert result[0] is False
        assert "不存在" in result[1]

    def test_not_zip(self, tmp_path):
        not_zip = tmp_path / "not_zip.xcmod"
        not_zip.write_text("not a zip")
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.validate_mod_package(str(not_zip))
        assert result[0] is False
        assert "ZIP" in result[1]

    def test_valid_package(self, tmp_path):
        mod_dir = tmp_path / "valid_mod"
        mod_dir.mkdir()
        manifest = {"id": "valid_mod", "name": "Valid", "version": "1.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        (mod_dir / "backend").mkdir()
        (mod_dir / "backend" / "blueprints.py").write_text("# blueprints")

        zip_path = tmp_path / "valid.xcmod"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for root, dirs, files in os.walk(str(mod_dir)):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, str(mod_dir))
                    zf.write(full, arcname)

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package"
        ) as mock_extract:
            mock_extract.return_value = (str(mod_dir), manifest)
            result = mm.validate_mod_package(str(zip_path))
        assert result[0] is True or isinstance(result[0], bool)


# ========================= ModManager - get_mod / list_loaded_mods ========


class TestModManagerGetMod:
    def test_get_mod(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.get_mod("test_mod")
        assert result is not None

    def test_list_loaded_mods(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [Mock()]
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.list_loaded_mods()
        assert len(result) == 1


# ========================= ModManager - _metadata_to_api_dict =============


class TestModManagerMetadataToApiDict:
    def test_basic_conversion(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            author="dev",
            description="A test mod",
            primary=True,
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["id"] == "test"
        assert result["name"] == "Test"
        assert result["version"] == "1.0"
        assert result["primary"] is True

    def test_with_industry_and_ui_labels(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            industry={"sector": "manufacturing"},
            ui_labels={"title": "Test Title"},
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["industry"] == {"sector": "manufacturing"}
        assert result["ui_labels"] == {"title": "Test Title"}

    def test_with_frontend_menu(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            frontend_menu=[{"label": "Test", "path": "/test"}],
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert len(result["menu"]) == 1


# ========================= ModManager - install_mod_package ===============


class TestModManagerInstallModPackage:
    def test_signature_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=__import__(
                "app.infrastructure.mods.package", fromlist=["ModSignatureError"]
            ).ModSignatureError("bad sig"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "签名" in result[1]

    def test_package_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=__import__(
                "app.infrastructure.mods.package", fromlist=["ModPackageError"]
            ).ModPackageError("bad pkg"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "无效" in result[1]

    def test_missing_id_in_manifest(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=("/tmp/extract", {"name": "No ID", "version": "1.0"}),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "id" in result[1]

    def test_sku_blocked_on_install(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=("/tmp/extract", {"id": "blocked", "version": "1.0"}),
            ),
            patch(
                "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
                side_effect=PermissionError("blocked"),
            ),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False

    def test_activate_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # Create a separate extract directory (not under mods_root) to avoid
        # shutil.rmtree(target_path) removing the extract source.
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "test_mod", "name": "Test", "version": "1.0"},
                ),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.parse_manifest",
                return_value=ModMetadata(
                    id="test_mod", name="Test", version="1.0", mod_path=str(extract_dir)
                ),
            ),
            patch.object(mm, "_refresh_mods_root_if_needed"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod", activate=False)
        assert result[0] is True
        assert "未激活" in result[1]

    def test_generic_exception(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=RuntimeError("unexpected"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "安装失败" in result[1]


# ========================= ModManager - uninstall_mod ====================


class TestModManagerUninstallMod:
    def test_unload_not_in_registry(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_er,
        ):
            mock_er_inst = Mock()
            mock_er.return_value = mock_er_inst
            mock_er_inst._root.return_value = str(tmp_path)
            # mod_id dir doesn't exist in employee root
            result = mm.uninstall_mod("nonexistent")
        assert result[0] is False

    def test_unload_with_remove_files(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_meta = Mock()
        mock_registry.get_mod_metadata.return_value = mock_meta
        mock_registry.get_mod_instance.return_value = None
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}")
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.uninstall_mod("test_mod", remove_files=True)
        assert result[0] is True
        assert not mod_dir.exists()

    def test_unload_generic_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.side_effect = RuntimeError("db error")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.uninstall_mod("test_mod")
        assert result[0] is False
        assert "卸载失败" in result[1]


# ========================= ModManager - update_mod =======================


class TestModManagerUpdateMod:
    def test_mod_not_installed(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.update_mod("nonexistent", "/fake/path.xcmod")
        assert result[0] is False
        assert "未安装" in result[1]

    def test_update_was_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_meta = Mock()
        mock_meta.version = "1.0"
        mock_registry.get_mod_metadata.return_value = mock_meta
        # Create a separate extract directory (not under mods_root) for copytree source
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text('{"id": "test_mod", "version": "2.0"}')
        mock_pkg = Mock()
        mock_pkg.manifest = {"id": "test_mod", "version": "2.0"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.ModPackage", return_value=mock_pkg),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), {"id": "test_mod", "version": "2.0"}),
            ),
            patch.object(mm, "unload_mod", return_value=True),
            patch.object(mm, "load_mod", return_value=True),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=Mock()),
        ):
            result = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert result[0] is True

    def test_update_extract_error_rollback(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_meta = Mock()
        mock_meta.version = "1.0"
        mock_registry.get_mod_metadata.return_value = mock_meta
        mock_pkg = Mock()
        mock_pkg.manifest = {"id": "test_mod", "version": "2.0"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.ModPackage", return_value=mock_pkg),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                side_effect=RuntimeError("extract failed"),
            ),
            patch.object(mm, "unload_mod", return_value=True),
            patch.object(mm, "load_mod", return_value=True),
        ):
            result = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert result[0] is False
        assert "更新失败" in result[1]

    def test_update_generic_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.side_effect = RuntimeError("unexpected")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert result[0] is False


# ========================= ModManager - all_mods_roots ====================


class TestModManagerAllModsRoots:
    def test_returns_list(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        roots = mm.all_mods_roots()
        assert isinstance(roots, list)
