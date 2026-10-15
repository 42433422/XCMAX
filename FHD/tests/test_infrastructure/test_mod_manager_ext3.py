"""Mod manager discovery, mounting, and import regressions."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.infrastructure.mods import mod_manager
from app.infrastructure.mods.manifest import ModMetadata


class TestModManagerListMods:
    def test_list_mods_returns_api_dicts(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            result = mm.list_mods()
        assert len(result) >= 1
        assert any(r["id"] == "test" for r in result)

    @pytest.mark.parametrize("failure", [False, True])
    def test_list_all_mods_includes_unloaded(self, tmp_path, failure):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.filter_mod_rows_for_enterprise",
                side_effect=RuntimeError("unavailable") if failure else lambda rows: rows,
            ),
        ):
            result = mm.list_all_mods()
        assert (result == []) if failure else len(result) >= 1


class TestModManagerGetRoutes:
    @pytest.mark.parametrize("failure", [False, True])
    def test_returns_routes(self, tmp_path, failure):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="test", name="Test", version="1.0", frontend_routes="frontend/routes.js"
        )
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
                side_effect=RuntimeError("unavailable") if failure else None,
            ),
        ):
            result = mm.get_routes()
        assert (result == []) if failure else len(result) == 1


class TestModManagerLoadAllMods:
    @pytest.mark.parametrize("failure", [False, True])
    def test_load_all_with_dependencies(self, tmp_path, failure):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        # dependencies is dict[str, str], not list
        meta_a = ModMetadata(id="mod_a", name="A", version="1.0", mod_path="/tmp/a", primary=True)
        meta_b = ModMetadata(
            id="mod_b", name="B", version="1.0", mod_path="/tmp/b", dependencies={"mod_a": ">=1.0"}
        )
        with (
            patch.object(mm, "scan_mods", return_value=[meta_a, meta_b]),
            patch.object(mm, "load_mod", return_value=True) as load,
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
                side_effect=RuntimeError("unavailable") if failure else None,
            ),
        ):
            result = mm.load_all_mods()
        assert isinstance(result, list)
        if failure:
            load.assert_not_called()
            assert result == []

    def test_load_all_empty(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "scan_mods", return_value=[]):
            result = mm.load_all_mods()
        assert result == []


class TestGetModManagerSingleton:
    def test_returns_same_instance(self):
        # The singleton variable is _mod_manager
        import app.infrastructure.mods.mod_manager as mm_mod

        old = mm_mod._mod_manager
        try:
            mm_mod._mod_manager = None
            mm1 = mod_manager.get_mod_manager()
            mm2 = mod_manager.get_mod_manager()
            assert mm1 is mm2
        finally:
            mm_mod._mod_manager = old


class TestImportModBackendPyEdgeCases:
    def test_import_with_hash_naming(self, tmp_path):
        backend_dir = tmp_path / "test_mod" / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "__init__.py").write_text("")
        (backend_dir / "services.py").write_text("HANDLER = True\n")

        result = mod_manager.import_mod_backend_py(
            str(tmp_path / "test_mod"), "test_mod", "services"
        )
        assert result is not None
        assert hasattr(result, "HANDLER")

    @pytest.mark.parametrize("missing", [True, False], ids=["missing-module", "syntax-error"])
    def test_invalid_import(self, tmp_path, missing):
        backend = tmp_path / "backend"
        backend.mkdir()
        if not missing:
            (backend / "entry.py").write_text("def broken(\n")
        with pytest.raises(FileNotFoundError if missing else SyntaxError):
            mod_manager.import_mod_backend_py(str(tmp_path), "bad_mod", "entry")


class TestAllModsRoots:
    def test_returns_list_of_strings(self):
        result = mod_manager._all_mods_roots("/tmp/mods")
        assert isinstance(result, list)
        for root in result:
            assert isinstance(root, str)

    def test_includes_primary_root(self, tmp_path):
        custom_root = str(tmp_path / "custom_mods")
        os.makedirs(custom_root)
        result = mod_manager._all_mods_roots(custom_root)
        assert custom_root in result


class TestRepoLayoutModsCandidates:
    @pytest.mark.parametrize("present", [True, False])
    def test_existing_and_missing_candidates(self, tmp_path, present):
        if present:
            (tmp_path / "mods").mkdir()
        root = tmp_path if present else tmp_path / "nonexistent"
        with patch("app.infrastructure.mods.mod_manager.os.path.dirname", return_value=str(root)):
            result = mod_manager._repo_layout_mods_candidates()
        assert isinstance(result, list)


class TestDefaultModsRootExtended:
    def test_env_var_overrides(self, tmp_path):
        custom_root = str(tmp_path / "custom_mods")
        os.makedirs(custom_root)
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": custom_root}):
            result = mod_manager._default_mods_root()
        assert result == custom_root

    def test_no_env_var(self):
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False):
            result = mod_manager._default_mods_root()
        assert isinstance(result, str)


class TestRegisterSingleModHttpRoutes:
    def test_empty_mod_id(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        mock_app = Mock()
        result = mod_manager._register_single_mod_http_routes(mock_app, mm, "")
        assert result is False

    def test_already_registered(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        mm._http_routes_registered.add("test_mod")
        mock_app = Mock()
        result = mod_manager._register_single_mod_http_routes(mock_app, mm, "test_mod")
        assert result is True

    def test_no_backend_entry(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        meta = ModMetadata(id="test_mod", name="Test", version="1.0", mod_path=str(tmp_path))
        mock_registry.get_mod_metadata.return_value = meta
        mock_app = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mod_manager._register_single_mod_http_routes(mock_app, mm, "test_mod")
        assert result is False


class TestRestoreEntitlementsFromSessionId:
    @pytest.mark.parametrize("sid", ["", "sid1"])
    def test_existing_session_restore(self, sid):
        assert mod_manager._restore_entitlements_from_session_id(sid) is None


class TestModAllowedForApiLoad:
    def test_empty_mod_id(self):
        result = mod_manager._mod_allowed_for_api_load("")
        assert result is False

    def test_import_error_defaults_not_allowed(self):
        # When enterprise modules can't be imported, returns False
        with patch.dict(
            "sys.modules",
            {
                "app.enterprise.account_mod_binding": None,
                "app.enterprise.mod_entitlements": None,
                "app.mod_sdk.industry_mod_aliases": None,
            },
        ):
            result = mod_manager._mod_allowed_for_api_load("test_mod")
        assert result is False


class TestEnsureModApiReady:
    def test_empty_mod_id(self, tmp_path):
        result = mod_manager.ensure_mod_api_ready("")
        assert result is False

    def test_mods_disabled(self, tmp_path):
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mod_manager.ensure_mod_api_ready("test_mod")
        assert result is False


class TestMountOnDiskPrimaryClientMods:
    def test_with_mods_root(self, tmp_path):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "scan_mods", return_value=[]):
            result = mod_manager.mount_on_disk_primary_client_mods(mm)
        assert isinstance(result, list)

    def test_no_mods_root(self, tmp_path):
        result = mod_manager.mount_on_disk_primary_client_mods(None)
        assert isinstance(result, list)


class TestLoadModRoutes:
    @pytest.mark.parametrize("loaded", [True, False])
    def test_loaded_routes_and_missing_app(self, tmp_path, loaded):
        mm = mod_manager.ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"] if loaded else []
        meta = ModMetadata(
            id="test_mod",
            name="Test",
            version="1.0",
            mod_path=str(tmp_path),
            backend_entry="backend.main",
        )
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [meta] if loaded else []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes"
            ) as register,
            patch(
                "app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods",
                return_value=[],
            ),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mod_manager.load_mod_routes(Mock() if loaded else None, mm)
        assert register.call_count == int(loaded)


class TestLoadEmployeePackRoutes:
    def test_with_mods_disabled(self, tmp_path):
        mock_app = Mock()
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            mod_manager.load_employee_pack_routes(mock_app)


class TestRegisterEmployeePackRoutes:
    def test_with_empty_pack_id(self, tmp_path):
        mock_app = Mock()
        result = mod_manager.register_employee_pack_routes(mock_app, None, "")
        assert result is False
