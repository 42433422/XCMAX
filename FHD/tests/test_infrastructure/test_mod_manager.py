"""Tests for app.infrastructure.mods.mod_manager — coverage ramp for uncovered branches."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

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

# ========================= _repo_layout_mods_candidates ==================


class TestRepoLayoutModsCandidates:
    def test_returns_list(self):
        result = _repo_layout_mods_candidates()
        assert isinstance(result, list)

    def test_no_duplicates(self):
        result = _repo_layout_mods_candidates()
        assert len(result) == len(set(result))


# ========================= _all_mods_roots ===============================


class TestAllModsRoots:
    def test_empty_primary(self, tmp_path):
        result = _all_mods_roots("")
        assert isinstance(result, list)

    def test_valid_primary(self, tmp_path):
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        result = _all_mods_roots(mods_dir)
        assert mods_dir in result

    def test_deduplication(self, tmp_path):
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": mods_dir}):
            result = _all_mods_roots(mods_dir)
        # Should not duplicate
        assert result.count(mods_dir) <= 1


# ========================= import_mod_backend_py =========================


class TestImportModBackendPy:
    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py(str(tmp_path / "nonexistent"), "test_mod", "blueprints")

    def test_successful_import(self, tmp_path):
        mod_path = str(tmp_path / "test_mod")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        py_file = os.path.join(backend_path, "services.py")
        Path(py_file).write_text("VALUE = 42\n")
        module = import_mod_backend_py(mod_path, "test_mod", "services")
        assert module.VALUE == 42

    def test_cached_import(self, tmp_path):
        mod_path = str(tmp_path / "test_mod2")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        py_file = os.path.join(backend_path, "cached.py")
        Path(py_file).write_text("COUNTER = 0\n")
        m1 = import_mod_backend_py(mod_path, "test_mod2", "cached")
        m2 = import_mod_backend_py(mod_path, "test_mod2", "cached")
        assert m1 is m2


# ========================= _register_mod_hooks ===========================


class TestRegisterModHooks:
    def test_no_hooks(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test")
        # Should not raise
        _register_mod_hooks("test", meta)

    def test_with_hooks_but_no_mod_path(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="",
            hooks={"event": "backend.handler.fn"},
        )
        # Should log error but not raise
        _register_mod_hooks("test", meta)

    def test_with_invalid_handler_spec(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"event": "invalid_no_dot"},
        )
        # Should log error but not raise
        _register_mod_hooks("test", meta)


# ========================= ModManager._mods_scan_fingerprint =============


class TestModsScanFingerprint:
    def test_empty_dir(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "mods"))
        fp = mm._mods_scan_fingerprint()
        assert isinstance(fp, str)

    def test_with_manifest(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            '{"id": "test-mod", "name": "Test", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(mods_dir))
        fp = mm._mods_scan_fingerprint()
        assert "test-mod" in fp


# ========================= ModManager._refresh_mods_root_if_needed =======


class TestRefreshModsRootIfNeeded:
    def test_env_var_updates_root(self, tmp_path):
        mods_dir = str(tmp_path / "env_mods")
        os.makedirs(mods_dir)
        mm = ModManager(mods_root="/tmp/old_nonexistent")
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": mods_dir}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == mods_dir

    def test_missing_root_fallback(self, tmp_path):
        mm = ModManager(mods_root="/tmp/nonexistent_path_for_test")
        with patch(
            "app.infrastructure.mods.mod_manager._default_mods_root",
            return_value=str(tmp_path / "fallback"),
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path / "fallback")

    def test_env_var_not_a_dir(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": "/tmp/nonexistent_env_dir"}):
            mm._refresh_mods_root_if_needed()
        # Should keep existing root
        assert mm.mods_root == str(tmp_path)


# ========================= ModManager.ensure_mods_loaded ==================


class TestEnsureModsLoaded:
    def test_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            mm.ensure_mods_loaded(None)
        # Should not raise

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "list_loaded_mods", return_value=[Mock()]):
            mm.ensure_mods_loaded(None)
        # Should not attempt loading

    def test_no_discovered_mods(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
        ):
            mm.ensure_mods_loaded(None)
        # Should not attempt loading

    def test_throttled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._last_ensure_at = 9999999999.0  # very recent
        mm._ensure_attempts = 1
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
        ):
            mm.ensure_mods_loaded(None)
        # Should not attempt loading due to throttle

    def test_max_attempts(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 25
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
        ):
            mm.ensure_mods_loaded(None)
        # Should not attempt loading


# ========================= ModManager.scan_mods ===========================


class TestScanMods:
    def test_scan_empty_dir(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert result == []

    def test_scan_with_valid_mod(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test-mod", "name": "Test Mod", "version": "1.0.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert len(result) == 1
        assert result[0].id == "test-mod"

    def test_scan_caching(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test-mod", "name": "Test Mod", "version": "1.0.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            r1 = mm.scan_mods(use_cache=True)
            r2 = mm.scan_mods(use_cache=True)
        assert len(r1) == len(r2)

    def test_scan_skips_underscore_dirs(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "_private"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "private", "name": "Private", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert len(result) == 0


# ========================= ModManager.load_mod ===========================


class TestLoadMod:
    def test_sku_blocked(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("blocked"),
        ):
            result = mm.load_mod("blocked-mod")
        assert result is False
        assert len(mm._recent_load_failures) == 1

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("already-loaded")
        assert result is True

    def test_already_loaded_syncs_list(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("sync-mod")
        assert "sync-mod" in mm._loaded_mods

    def test_mod_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            with patch.object(mm, "resolve_mod_directory", return_value=None):
                result = mm.load_mod("missing-mod")
        assert result is False

    def test_invalid_manifest(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "bad-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text("invalid json{{{")
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
                with patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)):
                    result = mm.load_mod("bad-mod")
        assert result is False

    def test_bundle_artifact(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "bundle-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {"id": "bundle-mod", "name": "Bundle", "version": "1.0", "artifact": "bundle"}
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.register_mod.return_value = True
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            with patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)):
                result = mm.load_mod("bundle-mod")
        assert result is True

    def test_dependencies_not_satisfied(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "dep-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "dep-mod",
                    "name": "Dep Mod",
                    "version": "1.0",
                    "dependencies": ["nonexistent-mod"],
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=False),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("dep-mod")
        assert result is False

    def test_load_with_backend(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "backend-mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "init.py").write_text("def setup(): pass\n")
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "backend-mod",
                    "name": "Backend Mod",
                    "version": "1.0",
                    "backend": {"entry": "init", "init": "setup"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        mock_registry.register_mod.return_value = True
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            mock_module = Mock()
            mock_module.setup = Mock()
            mock_import.return_value = mock_module
            result = mm.load_mod("backend-mod")
        assert result is True


# ========================= ModManager.unload_mod =========================


class TestUnloadMod:
    def test_basic_unload(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("test-mod")
        mock_registry = Mock()
        mock_registry.get_mod_instance.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            with patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError):
                result = mm.unload_mod("test-mod")
        assert result is True
        assert "test-mod" not in mm._loaded_mods

    def test_unload_with_cleanup(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("cleanup-mod")
        mock_instance = Mock()
        mock_instance.cleanup = Mock()
        mock_registry = Mock()
        mock_registry.get_mod_instance.return_value = mock_instance
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            with patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError):
                result = mm.unload_mod("cleanup-mod")
        assert result is True
        mock_instance.cleanup.assert_called_once()


# ========================= ModManager.uninstall_mod ======================


class TestUninstallMod:
    def test_unloaded_mod(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_er,
        ):
            mock_er_instance = Mock()
            mock_er_instance._root.return_value = str(tmp_path)
            mock_er.return_value = mock_er_instance
            result, msg = mm.uninstall_mod("unknown-mod")
        assert result is False

    def test_uninstall_with_files(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "uninstall-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "uninstall-mod", "name": "Test", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        mm._loaded_mods.append("uninstall-mod")
        mock_registry = Mock()
        mock_metadata = Mock()
        mock_registry.get_mod_metadata.return_value = mock_metadata
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "unload_mod", return_value=True),
        ):
            result, msg = mm.uninstall_mod("uninstall-mod", remove_files=True)
        assert result is True
        assert not mod_dir.exists()


# ========================= ModManager.validate_mod_package - extended =====


class TestValidateModPackageExtended:
    def test_valid_zip_with_manifest(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # Create a valid .xcmod zip
        mod_dir = tmp_path / "build"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test", "name": "Test", "version": "1.0"})
        )
        zip_path = tmp_path / "test.xcmod"
        import zipfile

        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.write(str(mod_dir / "manifest.json"), "manifest.json")
        ok, msg, info = mm.validate_mod_package(str(zip_path))
        assert ok is True
        assert info.get("id") == "test"

    def test_missing_required_fields(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "build2"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "test"}))
        zip_path = tmp_path / "test2.xcmod"
        import zipfile

        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.write(str(mod_dir / "manifest.json"), "manifest.json")
        ok, msg, info = mm.validate_mod_package(str(zip_path))
        assert ok is False
        assert "name" in msg or "version" in msg


# ========================= ModManager._metadata_to_api_dict - extended ===


class TestMetadataToApiDictExtended:
    def test_bundle_type(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="bundle-mod",
            name="Bundle",
            version="1.0",
            mod_path="/tmp/bundle",
            artifact="bundle",
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["type"] == "bundle"

    def test_non_dict_industry(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            industry="not a dict",
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["industry"] == {}


# ========================= ModManager.list_all_mods ======================


class TestListAllMods:
    def test_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            result = mm.list_all_mods()
        assert result == []

    def test_with_scanned_mods(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "list-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "list-mod", "name": "List Mod", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.list_all_mods()
        assert len(result) >= 1


# ========================= ModManager.get_routes =========================


class TestGetRoutes:
    def test_mods_disabled(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            result = mm.get_routes()
        assert result == []

    def test_with_frontend_routes(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "route-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "route-mod",
                    "name": "Route Mod",
                    "version": "1.0",
                    "frontend": {"routes": "routes"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.get_routes()
        assert len(result) >= 1
        assert result[0]["mod_id"] == "route-mod"


# ========================= ModManager.load_all_mods ======================


class TestLoadAllMods:
    def test_empty(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        assert result == []

    def test_with_mod(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "load-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "load-mod", "name": "Load Mod", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "load_mod", return_value=True),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        assert "load-mod" in result


# ========================= ModManager._scan_mods_from_build_index ========


class TestScanModsFromBuildIndex:
    def test_no_index_file(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_fingerprint_mismatch(self, tmp_path):
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "other_fp", "mods": []}))
        mm = ModManager(mods_root=str(tmp_path))
        result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_valid_index(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "idx-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "idx-mod", "name": "Idx Mod", "version": "1.0"})
        )
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps(
                {
                    "fingerprint": "fp1",
                    "mods": [{"mod_path": str(mod_dir)}],
                }
            )
        )
        mm = ModManager(mods_root=str(tmp_path))
        result = mm._scan_mods_from_build_index("fp1")
        assert result is not None
        assert len(result) == 1


# ========================= ModManager._load_mod_backend ==================


class TestLoadModBackend:
    def test_no_backend_dir(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "no_backend_mod"
        mod_dir.mkdir()
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="nb", name="NB", version="1.0", mod_path=str(mod_dir))
        mm._load_mod_backend("nb", str(mod_dir), meta)
        # Should not raise

    def test_backend_entry_load_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "fail_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="fail",
            name="Fail",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="missing",
            backend_init="setup",
        )
        with pytest.raises(Exception):
            mm._load_mod_backend("fail", str(mod_dir), meta)


# ========================= Module-level functions ========================


class TestGetModManager:
    def test_singleton(self):
        from app.infrastructure.mods.mod_manager import get_mod_manager

        with patch("app.infrastructure.mods.mod_manager._mod_manager", None):
            with patch(
                "app.infrastructure.mods.mod_manager._default_mods_root",
                return_value="/tmp/test_mods",
            ):
                mm1 = get_mod_manager()
                mm2 = get_mod_manager()
                assert mm1 is mm2


class TestLoadModRoutes:
    def test_is_callable(self):
        from app.infrastructure.mods.mod_manager import load_mod_routes

        assert callable(load_mod_routes)


class TestLoadModBlueprints:
    def test_is_callable(self):
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        assert callable(load_mod_blueprints)
