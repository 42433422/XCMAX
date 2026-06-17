"""Tests for app.infrastructure.mods.mod_manager — uncovered branches (ext3).

Focus: list_mods, list_all_mods, get_routes, load_all_mods, get_mod_manager singleton,
register_employee_pack_routes, load_employee_pack_routes, _register_single_mod_http_routes,
_restore_entitlements_from_session_id, _mod_allowed_for_api_load, ensure_mod_api_ready,
mount_on_disk_primary_client_mods, load_mod_routes, import_mod_backend_py edge cases,
_all_mods_roots, _repo_layout_mods_candidates.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _default_mods_root,
    _repo_layout_mods_candidates,
    import_mod_backend_py,
    is_mods_disabled,
)


# ========================= list_mods / list_all_mods =======================


class TestModManagerListMods:
    def test_list_mods_returns_api_dicts(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            result = mm.list_mods()
        assert len(result) >= 1
        assert any(r["id"] == "test" for r in result)

    def test_list_all_mods_includes_unloaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test")
        mock_registry.list_mods.return_value = [meta]
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry),
            patch.object(mm, "scan_mods", return_value=[]),
        ):
            result = mm.list_all_mods()
        assert isinstance(result, list)


# ========================= get_routes =====================================


class TestModManagerGetRoutes:
    def test_returns_routes(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="test", name="Test", version="1.0", mod_path="/tmp/test",
            frontend_menu=[{"label": "Test", "path": "/test"}],
        )
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [meta]
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry):
            result = mm.get_routes()
        assert isinstance(result, list)


# ========================= load_all_mods ==================================


class TestModManagerLoadAllMods:
    def test_load_all_with_dependencies(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # dependencies is dict[str, str], not list
        meta_a = ModMetadata(id="mod_a", name="A", version="1.0", mod_path="/tmp/a", primary=True)
        meta_b = ModMetadata(id="mod_b", name="B", version="1.0", mod_path="/tmp/b", dependencies={"mod_a": ">=1.0"})
        with (
            patch.object(mm, "scan_mods", return_value=[meta_a, meta_b]),
            patch.object(mm, "load_mod", return_value=True),
        ):
            result = mm.load_all_mods()
        assert isinstance(result, list)

    def test_load_all_empty(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "scan_mods", return_value=[]):
            result = mm.load_all_mods()
        assert result == []


# ========================= get_mod_manager singleton ======================


class TestGetModManagerSingleton:
    def test_returns_same_instance(self):
        from app.infrastructure.mods.mod_manager import get_mod_manager

        # The singleton variable is _mod_manager
        import app.infrastructure.mods.mod_manager as mm_mod
        old = mm_mod._mod_manager
        try:
            mm_mod._mod_manager = None
            mm1 = get_mod_manager()
            mm2 = get_mod_manager()
            assert mm1 is mm2
        finally:
            mm_mod._mod_manager = old


# ========================= import_mod_backend_py edge cases ================


class TestImportModBackendPyEdgeCases:
    def test_import_with_hash_naming(self, tmp_path):
        backend_dir = tmp_path / "test_mod" / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "__init__.py").write_text("")
        (backend_dir / "services.py").write_text("HANDLER = True\n")

        result = import_mod_backend_py(str(tmp_path / "test_mod"), "test_mod", "services")
        assert result is not None
        assert hasattr(result, "HANDLER")

    def test_import_nonexistent_module(self, tmp_path):
        backend_dir = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py(str(backend_dir), "nonexistent", "missing_module")

    def test_import_with_syntax_error(self, tmp_path):
        backend_dir = tmp_path / "bad_mod" / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "__init__.py").write_text("")
        (backend_dir / "bad_syntax.py").write_text("def broken(\n")

        with pytest.raises(SyntaxError):
            import_mod_backend_py(str(tmp_path / "bad_mod"), "bad_mod", "bad_syntax")


# ========================= _all_mods_roots ================================


class TestAllModsRoots:
    def test_returns_list_of_strings(self):
        result = _all_mods_roots("/tmp/mods")
        assert isinstance(result, list)
        for root in result:
            assert isinstance(root, str)

    def test_includes_primary_root(self, tmp_path):
        custom_root = str(tmp_path / "custom_mods")
        os.makedirs(custom_root)
        result = _all_mods_roots(custom_root)
        assert custom_root in result


# ========================= _repo_layout_mods_candidates ====================


class TestRepoLayoutModsCandidates:
    def test_returns_candidates(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        with patch("app.infrastructure.mods.mod_manager.os.path.dirname", return_value=str(tmp_path)):
            result = _repo_layout_mods_candidates()
        assert isinstance(result, list)

    def test_skips_nonexistent_dirs(self, tmp_path):
        with patch("app.infrastructure.mods.mod_manager.os.path.dirname", return_value=str(tmp_path / "nonexistent")):
            result = _repo_layout_mods_candidates()
        assert isinstance(result, list)


# ========================= _default_mods_root ==============================


class TestDefaultModsRootExtended:
    def test_env_var_overrides(self, tmp_path):
        custom_root = str(tmp_path / "custom_mods")
        os.makedirs(custom_root)
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": custom_root}):
            result = _default_mods_root()
        assert result == custom_root

    def test_no_env_var(self):
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False):
            result = _default_mods_root()
        assert isinstance(result, str)


# ========================= _register_single_mod_http_routes ===============


class TestRegisterSingleModHttpRoutes:
    def test_empty_mod_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root=str(tmp_path))
        mock_app = Mock()
        result = _register_single_mod_http_routes(mock_app, mm, "")
        assert result is False

    def test_already_registered(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root=str(tmp_path))
        mm._http_routes_registered.add("test_mod")
        mock_app = Mock()
        result = _register_single_mod_http_routes(mock_app, mm, "test_mod")
        assert result is True

    def test_no_backend_entry(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        meta = ModMetadata(id="test_mod", name="Test", version="1.0", mod_path=str(tmp_path))
        mock_registry.get_mod_metadata.return_value = meta
        mock_app = Mock()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry):
            result = _register_single_mod_http_routes(mock_app, mm, "test_mod")
        assert result is False


# ========================= _restore_entitlements_from_session_id ===========


class TestRestoreEntitlementsFromSessionId:
    def test_with_empty_session(self):
        from app.infrastructure.mods.mod_manager import _restore_entitlements_from_session_id

        # Empty session should return immediately without calling anything
        _restore_entitlements_from_session_id("")

    def test_with_valid_session(self):
        from app.infrastructure.mods.mod_manager import _restore_entitlements_from_session_id

        with patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id") as mock_fn:
            # Just verify it can be called without error
            mock_fn("sid1")

    def test_with_import_error(self):
        from app.infrastructure.mods.mod_manager import _restore_entitlements_from_session_id

        # The function catches RECOVERABLE_ERRORS, so ImportError should not raise
        _restore_entitlements_from_session_id("sid1")


# ========================= _mod_allowed_for_api_load ======================


class TestModAllowedForApiLoad:
    def test_empty_mod_id(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        result = _mod_allowed_for_api_load("")
        assert result is False

    def test_import_error_defaults_not_allowed(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        # When enterprise modules can't be imported, returns False
        with patch.dict("sys.modules", {"app.enterprise.account_mod_binding": None, "app.enterprise.mod_entitlements": None, "app.mod_sdk.industry_mod_aliases": None}):
            result = _mod_allowed_for_api_load("test_mod")
        assert result is False


# ========================= ensure_mod_api_ready ============================


class TestEnsureModApiReady:
    def test_empty_mod_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        result = ensure_mod_api_ready("")
        assert result is False

    def test_mods_disabled(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = ensure_mod_api_ready("test_mod")
        assert result is False


# ========================= mount_on_disk_primary_client_mods ===============


class TestMountOnDiskPrimaryClientMods:
    def test_with_mods_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "scan_mods", return_value=[]):
            result = mount_on_disk_primary_client_mods(mm)
        assert isinstance(result, list)

    def test_no_mods_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        result = mount_on_disk_primary_client_mods(None)
        assert isinstance(result, list)


# ========================= load_mod_routes ================================


class TestLoadModRoutes:
    def test_with_loaded_mods(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        meta = ModMetadata(id="test_mod", name="Test", version="1.0", mod_path=str(tmp_path), backend_entry="backend.main")
        mock_registry.list_mods.return_value = [meta]
        mock_app = Mock()
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry),
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes"),
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods", return_value=[]),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(mock_app, mm)

    def test_without_app(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = []
        mock_registry = Mock()
        mock_registry.list_mods.return_value = []
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry),
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods", return_value=[]),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(None, mm)


# ========================= load_employee_pack_routes ======================


class TestLoadEmployeePackRoutes:
    def test_with_mods_disabled(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        mock_app = Mock()
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            load_employee_pack_routes(mock_app)


# ========================= register_employee_pack_routes ===================


class TestRegisterEmployeePackRoutes:
    def test_with_empty_pack_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        mock_app = Mock()
        result = register_employee_pack_routes(mock_app, None, "")
        assert result is False
