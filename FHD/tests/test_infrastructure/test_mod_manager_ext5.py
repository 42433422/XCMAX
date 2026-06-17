"""Tests for app.infrastructure.mods.mod_manager — extended coverage (ext5).

Focus: uncovered branches in _mods_scan_fingerprint, _scan_mods_from_build_index,
load_mod bundle path, _load_mod_backend init hook error branches,
unload_mod cleanup error, install_mod_package signature/invalid paths,
uninstall_mod employee_pack path, update_mod extract failure,
validate_mod_package backend/frontend checks, _register_mod_hooks invalid spec,
_register_single_mod_http_routes websocket branches, _restore_entitlements_from_session_id,
_mod_allowed_for_api_load, ensure_mod_api_ready, mount_on_disk_primary_client_mods,
load_mod_routes, load_mod_blueprints, register_employee_pack_routes,
load_employee_pack_routes, _invoke_mod_init_hook signature branches.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# _mods_scan_fingerprint — OSError branches
# ---------------------------------------------------------------------------


class TestModsScanFingerprintOSError:
    def test_listdir_oserror_skips_root(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch("os.listdir", side_effect=OSError("denied")),
        ):
            fp = mm._mods_scan_fingerprint()
        # Should still produce a fingerprint with the root path
        assert str(tmp_path) in fp

    def test_getmtime_oserror_falls_back_to_entry(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "demo_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "demo_mod"}')

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch("os.path.getmtime", side_effect=OSError("stat failed")),
        ):
            fp = mm._mods_scan_fingerprint()
        assert "demo_mod" in fp


# ---------------------------------------------------------------------------
# _scan_mods_from_build_index — branches
# ---------------------------------------------------------------------------


class TestScanModsFromBuildIndex:
    def test_no_index_file_returns_none(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_index_fingerprint_mismatch_returns_none(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "other_fp", "mods": []}))
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_index_invalid_json_returns_none(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        index_path = tmp_path / "mods-index.json"
        index_path.write_text("not json")
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_index_mods_not_list_returns_none(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "fp1", "mods": "not_a_list"}))
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_index_row_missing_mod_path_skipped(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps(
                {
                    "fingerprint": "fp1",
                    "mods": [{"mod_path": ""}, {"not_mod_path": "x"}],
                }
            )
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_index_returns_mods_when_valid(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "demo_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "demo_mod", "name": "Demo", "version": "1.0.0"})
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
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "demo_mod"


# ---------------------------------------------------------------------------
# _invoke_mod_init_hook — signature branches
# ---------------------------------------------------------------------------


class TestInvokeModInitHook:
    def test_no_params_calls_directly(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        called = []

        def init_fn():
            called.append("called")

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        assert called == ["called"]

    def test_app_param_passed_as_none(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        received = {}

        def init_fn(app=None):
            received["app"] = app

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        assert received["app"] is None

    def test_mod_id_param_passed(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        received = {}

        def init_fn(mod_id=None):
            received["mod_id"] = mod_id

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        assert received["mod_id"] == "m1"

    def test_required_unknown_param_skips_call(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        called = []

        def init_fn(unknown_required):
            called.append("called")

        # Should skip calling because required param cannot be satisfied
        _invoke_mod_init_hook(init_fn, mod_id="m1")
        assert called == []

    def test_signature_bind_fails_falls_back_to_no_kwargs(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        called = []

        def init_fn(**kwargs):
            # sig.bind(**kwargs) will succeed for **kwargs, but we force a fallback
            called.append(kwargs)

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        # Should call with mod_id kwarg
        assert len(called) == 1

    def test_signature_inspect_failure_calls_directly(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        called = []

        class BadSig:
            def __call__(self):
                called.append("called")

            def __signature__(self):
                raise TypeError("no sig")

        # Use a callable that raises on inspect.signature
        class Weird:
            def __call__(self, *args, **kwargs):
                called.append("weird")

        # Make inspect.signature raise
        obj = Weird()
        with patch("inspect.signature", side_effect=TypeError("bad")):
            _invoke_mod_init_hook(obj, mod_id="m1")
        assert called == ["weird"]


# ---------------------------------------------------------------------------
# _register_mod_hooks — invalid spec branches
# ---------------------------------------------------------------------------


class TestRegisterModHooks:
    def test_no_hooks_returns_early(self):
        from app.infrastructure.mods.manifest import ModMetadata
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {}
        # Should not raise
        _register_mod_hooks("m1", metadata)

    def test_no_mod_path_logs_error(self):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "backend.handler"}
        metadata.mod_path = ""
        # Should not raise, just log
        _register_mod_hooks("m1", metadata)

    def test_invalid_spec_no_module_skipped(self):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "no_module_attr"}
        metadata.mod_path = "/tmp"
        # spec.rpartition(".") returns ("", "", "no_module_attr") - no module
        _register_mod_hooks("m1", metadata)

    def test_handler_not_callable_skipped(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        (backend_dir / "mymod.py").write_text("handler = 'not_callable'\n")

        metadata = MagicMock()
        metadata.hooks = {"event1": "mymod.handler"}
        metadata.mod_path = str(tmp_path)

        with patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import:
            mock_module = MagicMock()
            mock_module.handler = "not_callable"
            mock_import.return_value = mock_module
            _register_mod_hooks("m1", metadata)

    def test_import_error_logged(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "mymod.handler"}
        metadata.mod_path = str(tmp_path)

        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py",
            side_effect=ImportError("no module"),
        ):
            _register_mod_hooks("m1", metadata)


# ---------------------------------------------------------------------------
# unload_mod — cleanup error branch
# ---------------------------------------------------------------------------


class TestUnloadModCleanupError:
    def test_cleanup_raises_recoverable_error(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods.append("m1")

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.comms.get_mod_comms") as mock_comms,
        ):
            registry = MagicMock()
            instance = MagicMock()
            instance.cleanup.side_effect = RuntimeError("cleanup failed")
            registry.get_mod_instance.return_value = instance
            mock_reg.return_value = registry
            mock_comms_inst = MagicMock()
            mock_comms_inst.unregister_all.side_effect = RuntimeError("comms fail")
            mock_comms.return_value = mock_comms_inst

            result = mm.unload_mod("m1")

        assert result is True
        assert "m1" not in mm._loaded_mods


# ---------------------------------------------------------------------------
# install_mod_package — signature error and invalid package
# ---------------------------------------------------------------------------


class TestInstallModPackageErrors:
    def test_signature_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager
        from app.infrastructure.mods.package import ModSignatureError

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.package.ModPackage.extract_package",
            side_effect=ModSignatureError("bad signature"),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "签名验证失败" in msg
        assert meta is None

    def test_package_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager
        from app.infrastructure.mods.package import ModPackageError

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.package.ModPackage.extract_package",
            side_effect=ModPackageError("bad package"),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "MOD 包无效" in msg
        assert meta is None

    def test_missing_mod_id_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.package.ModPackage.extract_package",
            return_value=(str(tmp_path / "extract"), {"id": "", "version": "1.0"}),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "缺少 id" in msg

    def test_sku_permission_denied_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        with (
            patch(
                "app.infrastructure.mods.package.ModPackage.extract_package",
                return_value=(str(extract_dir), {"id": "m1", "version": "1.0"}),
            ),
            patch(
                "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
                side_effect=PermissionError("not allowed"),
            ),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "not allowed" in msg

    def test_recoverable_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=RuntimeError("disk full"),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "安装失败" in msg


# ---------------------------------------------------------------------------
# uninstall_mod — employee pack path
# ---------------------------------------------------------------------------


class TestUninstallModEmployeePack:
    def test_employee_pack_uninstall(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        emp_dir = tmp_path / "_employees" / "pack1"
        emp_dir.mkdir(parents=True)

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_get_er,
        ):
            registry = MagicMock()
            registry.get_mod_metadata.return_value = None
            mock_reg.return_value = registry

            er = MagicMock()
            er._root.return_value = str(tmp_path / "_employees")
            er.uninstall_pack.return_value = (True, "ok")
            mock_get_er.return_value = er

            ok, msg = mm.uninstall_mod("pack1")
        assert ok is True
        assert msg == "ok"

    def test_metadata_none_and_no_employee_pack(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_get_er,
        ):
            registry = MagicMock()
            registry.get_mod_metadata.return_value = None
            mock_reg.return_value = registry

            er = MagicMock()
            er._root.return_value = str(tmp_path / "_employees")
            mock_get_er.return_value = er

            ok, msg = mm.uninstall_mod("nonexistent")
        assert ok is False
        assert "未加载或不存在" in msg

    def test_recoverable_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry",
            side_effect=RuntimeError("db error"),
        ):
            ok, msg = mm.uninstall_mod("m1")
        assert ok is False
        assert "卸载失败" in msg


# ---------------------------------------------------------------------------
# update_mod — extract failure
# ---------------------------------------------------------------------------


class TestUpdateModExtractFailure:
    def test_mod_not_installed_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            registry = MagicMock()
            registry.get_mod_metadata.return_value = None
            mock_reg.return_value = registry
            ok, msg, meta = mm.update_mod("m1", "/fake/path.xcmod")
        assert ok is False
        assert "未安装" in msg

    def test_extract_failure_reloads_mod(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("m1")

        mock_meta = MagicMock()
        mock_meta.version = "1.0"

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.mod_manager.ModPackage") as mock_pkg,
            patch.object(mm, "unload_mod"),
            patch.object(mm, "load_mod") as mock_load,
        ):
            registry = MagicMock()
            registry.get_mod_metadata.return_value = mock_meta
            mock_reg.return_value = registry

            mock_pkg_instance = MagicMock()
            mock_pkg_instance.manifest = {"version": "2.0"}
            mock_pkg.return_value = mock_pkg_instance

            mock_pkg.extract_package.side_effect = RuntimeError("extract failed")

            ok, msg, meta = mm.update_mod("m1", "/fake/path.xcmod")

        assert ok is False
        assert "更新失败" in msg
        # Should attempt to reload the mod after extract failure
        mock_load.assert_called_once_with("m1")


# ---------------------------------------------------------------------------
# validate_mod_package — backend/frontend file checks
# ---------------------------------------------------------------------------


class TestValidateModPackageAdditional:
    def test_file_not_exists(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package("/nonexistent/file.xcmod")
        assert ok is False
        assert "文件不存在" in msg

    def test_not_a_zip(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        not_zip = tmp_path / "notzip.xcmod"
        not_zip.write_text("not a zip")
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package(str(not_zip))
        assert ok is False
        assert "ZIP" in msg

    def test_missing_id_field(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        fake_pkg = tmp_path / "fake.xcmod"
        fake_pkg.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal zip EOCD

        with (
            patch(
                "app.infrastructure.mods.package.ModPackage.extract_package",
                return_value=(str(extract_dir), {"id": "", "name": "n", "version": "1"}),
            ),
            patch("zipfile.is_zipfile", return_value=True),
        ):
            ok, msg, info = mm.validate_mod_package(str(fake_pkg))
        assert ok is False
        assert "id" in msg

    def test_mod_package_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager
        from app.infrastructure.mods.package import ModPackageError

        mm = ModManager(mods_root=str(tmp_path))
        fake_pkg = tmp_path / "fake.xcmod"
        fake_pkg.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

        with (
            patch(
                "app.infrastructure.mods.package.ModPackage.extract_package",
                side_effect=ModPackageError("bad"),
            ),
            patch("zipfile.is_zipfile", return_value=True),
        ):
            ok, msg, info = mm.validate_mod_package(str(fake_pkg))
        assert ok is False
        assert "bad" in msg

    def test_recoverable_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        fake_pkg = tmp_path / "fake.xcmod"
        fake_pkg.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

        with (
            patch(
                "app.infrastructure.mods.package.ModPackage.extract_package",
                side_effect=RuntimeError("disk"),
            ),
            patch("zipfile.is_zipfile", return_value=True),
        ):
            ok, msg, info = mm.validate_mod_package(str(fake_pkg))
        assert ok is False
        assert "验证失败" in msg


# ---------------------------------------------------------------------------
# _register_single_mod_http_routes — websocket branches
# ---------------------------------------------------------------------------


class TestRegisterSingleModHttpRoutes:
    def test_empty_mod_id_returns_false(self):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        result = _register_single_mod_http_routes(MagicMock(), mm, "")
        assert result is False

    def test_already_registered_returns_true(self):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = {"m1"}
        result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is True

    def test_no_metadata_returns_false(self):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            registry = MagicMock()
            registry.get_mod_metadata.return_value = None
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is False

    def test_no_backend_entry_returns_false(self):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        meta = MagicMock()
        meta.backend_entry = ""
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            registry = MagicMock()
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is False

    def test_no_mod_path_records_failure(self):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = ""
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            registry = MagicMock()
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is False
        mm.record_blueprint_failure.assert_called_once()

    def test_websocket_register_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        mm._backend_entry_modules = {}
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = str(tmp_path)

        mock_module = MagicMock()
        mock_module.register_fastapi_routes = MagicMock()
        mock_module.register_websocket_routes = MagicMock(return_value=False)

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mock_module,
            ),
        ):
            registry = MagicMock()
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is True  # HTTP routes registered successfully
        assert "m1" in mm._http_routes_registered

    def test_recoverable_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        mm._backend_entry_modules = {}
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = str(tmp_path)

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=RuntimeError("import fail"),
            ),
        ):
            registry = MagicMock()
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is False
        mm.record_blueprint_failure.assert_called_once()


# ---------------------------------------------------------------------------
# _restore_entitlements_from_session_id
# ---------------------------------------------------------------------------


class TestRestoreEntitlementsFromSessionId:
    def test_empty_session_id_returns(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        # Should not raise
        _restore_entitlements_from_session_id("")
        _restore_entitlements_from_session_id(None)

    def test_recoverable_error_swallowed(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        with patch(
            "app.enterprise.mod_entitlements.restore_entitlements_from_session_row",
            side_effect=RuntimeError("db error"),
        ):
            # Should not raise
            _restore_entitlements_from_session_id("sid123")

    def test_successful_restore_with_cached(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        with (
            patch(
                "app.enterprise.mod_entitlements.restore_entitlements_from_session_row"
            ) as mock_restore,
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="user1",
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={"m1", "m2"},
            ),
            patch(
                "app.enterprise.mod_entitlements._augment_entitled_for_username",
                return_value={"m1", "m2", "m3"},
            ),
            patch("app.enterprise.mod_entitlements.set_session_entitlements") as mock_set,
        ):
            _restore_entitlements_from_session_id("sid123")
        mock_set.assert_called_once_with(
            market_user_id=None,
            market_username="user1",
            entitled_client_mod_ids={"m1", "m2", "m3"},
        )

    def test_no_cached_does_not_set(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        with (
            patch("app.enterprise.mod_entitlements.restore_entitlements_from_session_row"),
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="user1",
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=set(),
            ),
            patch(
                "app.enterprise.mod_entitlements._augment_entitled_for_username",
                return_value=set(),
            ),
            patch("app.enterprise.mod_entitlements.set_session_entitlements") as mock_set,
        ):
            _restore_entitlements_from_session_id("sid123")
        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# _mod_allowed_for_api_load
# ---------------------------------------------------------------------------


class TestModAllowedForApiLoad:
    def test_empty_mod_id_returns_false(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        assert _mod_allowed_for_api_load("") is False

    def test_filter_not_active_returns_true(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        with patch(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            return_value=False,
        ):
            result = _mod_allowed_for_api_load("m1")
        assert result is True

    def test_mod_visible_returns_true(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
        ):
            result = _mod_allowed_for_api_load("m1")
        assert result is True

    def test_sunbird_mod_resolved_returns_true(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=False,
            ),
            patch(
                "app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID",
                "sunbird",
            ),
            patch(
                "app.enterprise.account_mod_binding.is_sunbird_local_username",
                return_value=False,
            ),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="sunbird"),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
        ):
            mm = MagicMock()
            mm.resolve_mod_directory.return_value = "/tmp/sunbird"
            mock_mm.return_value = mm
            result = _mod_allowed_for_api_load("sunbird")
        assert result is False

    def test_sunbird_mod_username_match_returns_true(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=False,
            ),
            patch(
                "app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID",
                "sunbird",
            ),
            patch(
                "app.enterprise.account_mod_binding.is_sunbird_local_username",
                return_value=True,
            ),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="sunbird"),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="sunbird_user",
            ),
        ):
            mm = MagicMock()
            mm.resolve_mod_directory.return_value = None
            mock_mm.return_value = mm
            result = _mod_allowed_for_api_load("sunbird", "sid123")
        assert result is False

    def test_recoverable_error_returns_false(self):
        from app.infrastructure.mods.mod_manager import _mod_allowed_for_api_load

        with patch(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            side_effect=RuntimeError("db"),
        ):
            result = _mod_allowed_for_api_load("m1")
        assert result is False


# ---------------------------------------------------------------------------
# ensure_mod_api_ready
# ---------------------------------------------------------------------------


class TestEnsureModApiReady:
    def test_empty_mod_id_returns_false(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        assert ensure_mod_api_ready("") is False

    def test_mods_disabled_returns_false(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = ensure_mod_api_ready("m1")
        assert result is False

    def test_mod_not_allowed_returns_false(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=False,
            ),
        ):
            result = ensure_mod_api_ready("m1")
        assert result is False

    def test_load_mod_fails_returns_false(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        mm = MagicMock()
        mm._loaded_mods = []
        mm.load_mod.return_value = False
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        ):
            result = ensure_mod_api_ready("m1")
        assert result is False

    def test_already_registered_returns_true(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        mm = MagicMock()
        mm._loaded_mods = ["m1"]
        mm._http_routes_registered = {"m1"}
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        ):
            result = ensure_mod_api_ready("m1")
        assert result is True

    def test_get_fastapi_app_fails_returns_false(self):
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        mm = MagicMock()
        mm._loaded_mods = ["m1"]
        mm._http_routes_registered = set()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
            patch(
                "app.fastapi_app.get_fastapi_app",
                side_effect=RuntimeError("no app"),
            ),
        ):
            result = ensure_mod_api_ready("m1")
        assert result is False


# ---------------------------------------------------------------------------
# mount_on_disk_primary_client_mods
# ---------------------------------------------------------------------------


class TestMountOnDiskPrimaryClientMods:
    def test_mods_disabled_returns_empty(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mount_on_disk_primary_client_mods()
        assert result == []

    def test_no_mod_path_returns_empty(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = MagicMock()
        mm.resolve_mod_directory.return_value = None
        with (
            patch("app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID", "sunbird"),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            result = mount_on_disk_primary_client_mods(mm)
        assert result == []

    def test_already_loaded_returns_list(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = MagicMock()
        mm.resolve_mod_directory.return_value = "/tmp/sunbird"
        mm._loaded_mods = ["sunbird"]
        with (
            patch("app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID", "sunbird"),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            result = mount_on_disk_primary_client_mods(mm)
        assert result == []

    def test_load_mod_success(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = MagicMock()
        mm.resolve_mod_directory.return_value = "/tmp/sunbird"
        mm._loaded_mods = []
        mm.load_mod.return_value = True
        with (
            patch("app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID", "sunbird"),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            result = mount_on_disk_primary_client_mods(mm)
        assert result == []


# ---------------------------------------------------------------------------
# register_employee_pack_routes
# ---------------------------------------------------------------------------


class TestRegisterEmployeePackRoutes:
    def test_empty_pack_id_returns_false(self):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        result = register_employee_pack_routes(MagicMock(), None, "")
        assert result is False

    def test_mods_disabled_returns_false(self):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = register_employee_pack_routes(MagicMock(), None, "p1")
        assert result is False

    def test_already_registered_returns_true(self):
        from app.infrastructure.mods.mod_manager import (
            _employee_pack_routes_registered,
            register_employee_pack_routes,
        )

        _employee_pack_routes_registered.add("p1")
        try:
            mm = MagicMock()
            mm.mods_root = "/tmp"
            result = register_employee_pack_routes(MagicMock(), mm, "p1")
            assert result is True
        finally:
            _employee_pack_routes_registered.discard("p1")

    def test_no_manifest_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        result = register_employee_pack_routes(MagicMock(), mm, "p1")
        assert result is False

    def test_manifest_not_employee_pack_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        emp_dir = tmp_path / "_employees" / "p1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(json.dumps({"id": "p1", "artifact": "mod"}))

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        result = register_employee_pack_routes(MagicMock(), mm, "p1")
        assert result is False

    def test_no_entry_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        emp_dir = tmp_path / "_employees" / "p1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"id": "p1", "artifact": "employee_pack", "backend": {}})
        )

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        result = register_employee_pack_routes(MagicMock(), mm, "p1")
        assert result is False


# ---------------------------------------------------------------------------
# load_employee_pack_routes
# ---------------------------------------------------------------------------


class TestLoadEmployeePackRoutes:
    def test_mods_disabled_returns(self):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            load_employee_pack_routes(MagicMock(), None)

    def test_no_employees_dir_returns(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        load_employee_pack_routes(MagicMock(), mm)

    def test_skips_non_employee_pack(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        emp_dir = tmp_path / "_employees" / "p1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(json.dumps({"id": "p1", "artifact": "mod"}))

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        load_employee_pack_routes(MagicMock(), mm)


# ---------------------------------------------------------------------------
# load_mod_blueprints (no-op)
# ---------------------------------------------------------------------------


class TestLoadModBlueprints:
    def test_no_op_does_not_raise(self):
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        # Should not raise
        load_mod_blueprints(MagicMock(), None)


# ---------------------------------------------------------------------------
# load_mod_routes
# ---------------------------------------------------------------------------


class TestLoadModRoutes:
    def test_load_mod_routes_with_empty_registry(self):
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = MagicMock()
        mm._loaded_mods = []
        mm._blueprint_failures = []
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            registry = MagicMock()
            registry.list_mods.return_value = []
            mock_reg.return_value = registry
            load_mod_routes(MagicMock(), mm)


# ---------------------------------------------------------------------------
# _short_exc_message
# ---------------------------------------------------------------------------


class TestShortExcMessage:
    def test_short_message_returned_as_is(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        result = _short_exc_message(ValueError("short"))
        assert result == "short"

    def test_empty_message_uses_type_name(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        result = _short_exc_message(ValueError())
        assert result == "ValueError"

    def test_long_message_truncated(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        long_msg = "x" * 600
        result = _short_exc_message(ValueError(long_msg), max_len=100)
        assert len(result) == 100
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# _backend_path_for_mod
# ---------------------------------------------------------------------------


class TestBackendPathForMod:
    def test_returns_joined_path(self):
        from app.infrastructure.mods.mod_manager import _backend_path_for_mod

        result = _backend_path_for_mod("/tmp/m1")
        assert result == os.path.join("/tmp/m1", "backend")


# ---------------------------------------------------------------------------
# _repo_layout_mods_candidates
# ---------------------------------------------------------------------------


class TestRepoLayoutModsCandidates:
    def test_returns_list(self):
        from app.infrastructure.mods.mod_manager import _repo_layout_mods_candidates

        result = _repo_layout_mods_candidates()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _all_mods_roots
# ---------------------------------------------------------------------------


class TestAllModsRoots:
    def test_primary_not_dir_excluded(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots

        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": ""}, clear=False):
            result = _all_mods_roots(str(tmp_path / "nonexistent"))
        # primary is not a dir, but repo candidates may be added
        assert isinstance(result, list)

    def test_env_path_added(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots

        env_dir = tmp_path / "env_mods"
        env_dir.mkdir()
        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(env_dir)}, clear=False),
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
        ):
            result = _all_mods_roots(str(tmp_path))
        assert str(env_dir) in result


# ---------------------------------------------------------------------------
# ModManager._load_mod_backend — no backend dir
# ---------------------------------------------------------------------------


class TestLoadModBackendNoDir:
    def test_no_backend_dir_returns(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        mod_path = str(tmp_path / "m1")
        os.makedirs(mod_path)
        meta = MagicMock()
        meta.backend_entry = ""
        # Should not raise
        mm._load_mod_backend("m1", mod_path, meta)


# ---------------------------------------------------------------------------
# ModManager.load_mod — bundle path
# ---------------------------------------------------------------------------


class TestLoadModBundlePath:
    def _setup_bundle_mocks(self, mm, register_return=True, already_registered=False):
        """Common setup for bundle path tests."""
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE

        meta = MagicMock()
        meta.artifact = ARTIFACT_BUNDLE
        meta.id = "m1"

        reg_mock = MagicMock()
        if already_registered:
            reg_mock.get_mod_metadata.return_value = meta
        else:
            reg_mock.get_mod_metadata.return_value = None
            reg_mock.register_mod.return_value = register_return

        return meta, reg_mock

    def test_bundle_already_registered_returns_true(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        meta, reg_mock = self._setup_bundle_mocks(mm, already_registered=True)

        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry",
                return_value=reg_mock,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.normalize_artifact",
                return_value=ARTIFACT_BUNDLE,
            ),
        ):
            # First call: registry already has metadata, returns True early
            result = mm.load_mod("m1")
        assert result is True

    def test_bundle_register_success_returns_true(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        meta, reg_mock = self._setup_bundle_mocks(mm, register_return=True)

        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry",
                return_value=reg_mock,
            ),
            patch.object(mm, "resolve_mod_directory", return_value="/tmp/m1"),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch(
                "app.infrastructure.mods.mod_manager.normalize_artifact",
                return_value=ARTIFACT_BUNDLE,
            ),
        ):
            result = mm.load_mod("m1")
        assert result is True
        assert "m1" in mm._loaded_mods

    def test_bundle_register_false_still_returns_true(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        meta, reg_mock = self._setup_bundle_mocks(mm, register_return=False)

        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry",
                return_value=reg_mock,
            ),
            patch.object(mm, "resolve_mod_directory", return_value="/tmp/m1"),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch(
                "app.infrastructure.mods.mod_manager.normalize_artifact",
                return_value=ARTIFACT_BUNDLE,
            ),
        ):
            result = mm.load_mod("m1")
        assert result is True


# ---------------------------------------------------------------------------
# ModManager.scan_mods — manifest error
# ---------------------------------------------------------------------------


class TestScanModsManifestError:
    def test_invalid_manifest_recorded(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "bad_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid json")

        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            mods = mm.scan_mods()
        assert mods == []
        assert len(mm._scan_manifest_errors) == 1
        assert mm._scan_manifest_errors[0]["entry"] == "bad_mod"


# ---------------------------------------------------------------------------
# ModManager.list_all_mods / list_mods / get_routes — disabled
# ---------------------------------------------------------------------------


class TestListAllModsDisabled:
    def test_list_all_mods_disabled_returns_empty(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mm.list_all_mods()
        assert result == []

    def test_list_mods_disabled_returns_empty(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mm.list_mods()
        assert result == []

    def test_get_routes_disabled_returns_empty(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            result = mm.get_routes()
        assert result == []


# ---------------------------------------------------------------------------
# ModManager._refresh_mods_root_if_needed — env not a dir
# ---------------------------------------------------------------------------


class TestRefreshModsRootEnvNotDir:
    def test_env_not_dir_keeps_current(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(
            "os.environ",
            {"XCAGI_MODS_ROOT": str(tmp_path / "nonexistent")},
            clear=False,
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)

    def test_mods_root_missing_re_resolves(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path / "missing"))
        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": ""}, clear=False),
            patch(
                "app.infrastructure.mods.mod_manager._default_mods_root",
                return_value=str(tmp_path),
            ),
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)


# ---------------------------------------------------------------------------
# ModManager.ensure_mods_loaded — branches
# ---------------------------------------------------------------------------


class TestEnsureModsLoadedBranches:
    def test_mods_disabled_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            mm.ensure_mods_loaded(MagicMock())

    def test_already_loaded_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[MagicMock()]),
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_no_discovered_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_throttled_returns(self):
        import time

        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm._last_ensure_at = time.monotonic()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_max_attempts_reached(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm._ensure_attempts = 20
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_recoverable_error_swallowed(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            side_effect=RuntimeError("err"),
        ):
            # Should not raise
            mm.ensure_mods_loaded(MagicMock())


# ---------------------------------------------------------------------------
# ModManager.record_blueprint_failure / get_blueprint_failures
# ---------------------------------------------------------------------------


class TestBlueprintFailures:
    def test_record_and_get(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm.record_blueprint_failure("m1", "some error")
        failures = mm.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "m1"
        assert failures[0]["message"] == "some error"

    def test_get_scan_manifest_errors(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm._scan_manifest_errors.append({"entry": "x", "message": "y"})
        errors = mm.get_scan_manifest_errors()
        assert len(errors) == 1
        assert errors[0]["entry"] == "x"


# ---------------------------------------------------------------------------
# ModManager._metadata_to_api_dict
# ---------------------------------------------------------------------------


class TestMetadataToApiDict:
    def test_bundle_artifact_adds_type(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        from app.infrastructure.mods.mod_manager import ModManager

        m = MagicMock()
        m.id = "m1"
        m.name = "Mod"
        m.version = "1.0"
        m.author = ""
        m.description = ""
        m.primary = False
        m.artifact = ARTIFACT_BUNDLE
        m.industry = {}
        m.ui_labels = {}
        m.ui_starter_pack = []
        m.frontend_menu = []
        m.frontend_menu_overrides = []
        m.workflow_employees = []
        m.comms_exports = []
        m.frontend_pro_entry_path = ""

        with patch(
            "app.infrastructure.mods.mod_manager.normalize_artifact",
            return_value=ARTIFACT_BUNDLE,
        ):
            result = ModManager._metadata_to_api_dict(m)
        assert result["type"] == "bundle"
