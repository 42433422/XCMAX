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
        # listdir failed -> the root contributes only its abspath, no per-entry parts.
        assert fp == os.path.abspath(str(tmp_path))

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
        # getmtime failed -> entry recorded by bare name (no ":<mtime>" suffix).
        assert fp == f"{os.path.abspath(str(tmp_path))}|demo_mod"

    def test_underscore_entries_excluded_and_mtime_included(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mod_dir = tmp_path / "demo_mod"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text('{"id": "demo_mod"}')
        # _employees and other underscore-prefixed dirs must be ignored by the fingerprint.
        hidden = tmp_path / "_employees"
        hidden.mkdir()
        (hidden / "manifest.json").write_text("{}")

        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp = mm._mods_scan_fingerprint()
        parts = fp.split("|")
        assert parts[0] == os.path.abspath(str(tmp_path))
        # Exactly one entry part, for the real mod, carrying its manifest mtime.
        assert len(parts) == 2
        assert parts[1].startswith("demo_mod:")
        assert "_employees" not in fp


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
        with (
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch("app.infrastructure.mods.mod_manager.parse_manifest") as mock_parse,
        ):
            result = mm._scan_mods_from_build_index("fp1")
        # Rows with a blank/absent mod_path are skipped before any manifest parse,
        # and an index that yields zero mods returns None (caller falls back to full scan).
        assert result is None
        mock_parse.assert_not_called()

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

        calls = []

        def init_fn(app=None):
            calls.append({"app": app})

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        # Legacy signature with only ``app`` -> called exactly once with app injected as None,
        # and mod_id is NOT smuggled in (it is not a declared parameter).
        assert calls == [{"app": None}]

    def test_mod_id_param_passed(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        calls = []

        def init_fn(mod_id=None):
            calls.append({"mod_id": mod_id})

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        # Only ``mod_id`` declared -> bound to the supplied value, called once.
        assert calls == [{"mod_id": "m1"}]

    def test_both_app_and_mod_id_injected(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        calls = []

        def init_fn(app, mod_id):
            calls.append((app, mod_id))

        _invoke_mod_init_hook(init_fn, mod_id="m99")
        # Both known params get injected positionally-by-name: app=None, mod_id="m99".
        assert calls == [(None, "m99")]

    def test_required_unknown_param_skips_call(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        called = []

        def init_fn(unknown_required):
            called.append("called")

        # A required param that the invoker cannot satisfy -> the hook is NOT called at all.
        result = _invoke_mod_init_hook(init_fn, mod_id="m1")
        assert result is None
        assert called == []

    def test_signature_bind_fails_falls_back_to_no_kwargs(self):
        from app.infrastructure.mods.mod_manager import _invoke_mod_init_hook

        calls = []

        def init_fn(**kwargs):
            calls.append(kwargs)

        _invoke_mod_init_hook(init_fn, mod_id="m1")
        # **kwargs-only signature: no positional params to satisfy, so it is called once
        # with an empty kwargs mapping (neither app nor mod_id is force-injected).
        assert calls == [{}]

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
    def test_valid_hook_subscribes_resolved_callable(self, tmp_path):
        """Happy path: the resolved handler is the real on-disk callable, and it is
        subscribed under the exact event name with the ``backend.`` prefix stripped."""
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        (backend_dir / "mymod.py").write_text(
            "def handler(payload=None):\n    return ('handled', payload)\n"
        )

        metadata = MagicMock()
        metadata.hooks = {"order.created": "backend.mymod.handler"}
        metadata.mod_path = str(tmp_path)

        with patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe:
            _register_mod_hooks("m1", metadata)

        mock_subscribe.assert_called_once()
        (event, handler), _ = mock_subscribe.call_args
        assert event == "order.created"
        # The subscribed object is the *real* function loaded from disk, not a sentinel.
        assert callable(handler)
        assert handler.__name__ == "handler"
        assert handler("p1") == ("handled", "p1")

    def test_no_hooks_returns_early(self):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {}
        with patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe:
            result = _register_mod_hooks("m1", metadata)
        # No hooks declared -> early return None, nothing subscribed.
        assert result is None
        mock_subscribe.assert_not_called()

    def test_no_mod_path_logs_error(self):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "backend.handler"}
        metadata.mod_path = ""
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe,
        ):
            _register_mod_hooks("m1", metadata)
        # Missing mod_path -> bails before attempting to import or subscribe anything.
        mock_import.assert_not_called()
        mock_subscribe.assert_not_called()

    def test_invalid_spec_no_module_skipped(self):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        # "no_module_attr".rpartition(".") -> ("", "", "no_module_attr"): no module part.
        metadata.hooks = {"event1": "no_module_attr"}
        metadata.mod_path = "/tmp"
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe,
        ):
            _register_mod_hooks("m1", metadata)
        # Unparseable spec -> never even attempts the import.
        mock_import.assert_not_called()
        mock_subscribe.assert_not_called()

    def test_handler_not_callable_skipped(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "mymod.handler"}
        metadata.mod_path = str(tmp_path)

        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe,
        ):
            mock_module = MagicMock()
            mock_module.handler = "not_callable"  # str, not a function
            mock_import.return_value = mock_module
            _register_mod_hooks("m1", metadata)
        # Import succeeded (attr looked up) but resolved value is not callable -> skip subscribe.
        mock_import.assert_called_once_with(str(tmp_path), "m1", "mymod")
        mock_subscribe.assert_not_called()

    def test_import_error_logged(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_mod_hooks

        metadata = MagicMock()
        metadata.hooks = {"event1": "mymod.handler"}
        metadata.mod_path = str(tmp_path)

        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=ImportError("no module"),
            ) as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_subscribe,
        ):
            # Import failure is a recoverable error -> swallowed (no propagation).
            result = _register_mod_hooks("m1", metadata)
        assert result is None
        mock_import.assert_called_once()
        mock_subscribe.assert_not_called()


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

        # unload_mod must be fault-tolerant: cleanup() and comms unregister both raise,
        # yet the mod is still fully torn down and the call reports success.
        assert result is True
        instance.cleanup.assert_called_once()
        registry.unregister_mod.assert_called_once_with("m1")
        mock_comms_inst.unregister_all.assert_called_once_with("m1")
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
        from app.infrastructure.mods.mod_manager import (
            ModManager,
            _register_single_mod_http_routes,
        )

        # Real ModManager so we can assert the exact failure message that was recorded.
        mm = ModManager(mods_root="/tmp")
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = ""
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg:
            registry = MagicMock()
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            result = _register_single_mod_http_routes(MagicMock(), mm, "m1")
        assert result is False
        failures = mm.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "m1"
        assert failures[0]["message"] == "manifest 缺少 mod_path，无法注册路由"
        assert "m1" not in mm._http_routes_registered

    def test_websocket_register_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import (
            ModManager,
            _register_single_mod_http_routes,
        )

        mm = ModManager(mods_root=str(tmp_path))
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = str(tmp_path)

        mock_module = MagicMock()
        mock_module.register_fastapi_routes = MagicMock()
        mock_module.register_websocket_routes = MagicMock(return_value=False)

        app = MagicMock()
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
            result = _register_single_mod_http_routes(app, mm, "m1")
        # WS registrar returning False is non-fatal: HTTP routes still count as registered.
        assert result is True
        assert "m1" in mm._http_routes_registered
        # HTTP registrar gets (app, mod_id); WS registrar gets only (app,).
        mock_module.register_fastapi_routes.assert_called_once_with(app, "m1")
        mock_module.register_websocket_routes.assert_called_once_with(app)
        # The imported backend module is cached so subsequent loads reuse it.
        assert mm._backend_entry_modules["m1"] is mock_module
        # A successful registration records no blueprint failure.
        assert mm.get_blueprint_failures() == []

    def test_recoverable_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import (
            ModManager,
            _register_single_mod_http_routes,
        )

        mm = ModManager(mods_root=str(tmp_path))
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
        # The raised message is captured verbatim (via _short_exc_message) for diagnostics.
        failures = mm.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "m1"
        assert failures[0]["message"] == "import fail"
        assert "m1" not in mm._http_routes_registered


# ---------------------------------------------------------------------------
# _restore_entitlements_from_session_id
# ---------------------------------------------------------------------------


class TestRestoreEntitlementsFromSessionId:
    def test_empty_session_id_returns(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        with patch(
            "app.enterprise.mod_entitlements.restore_entitlements_from_session_row"
        ) as mock_restore:
            # Empty, None, and whitespace-only all strip to "" and short-circuit.
            assert _restore_entitlements_from_session_id("") is None
            assert _restore_entitlements_from_session_id(None) is None
            assert _restore_entitlements_from_session_id("   ") is None
        # No entitlement restore attempted for any blank session id.
        mock_restore.assert_not_called()

    def test_recoverable_error_swallowed(self):
        from app.infrastructure.mods.mod_manager import (
            _restore_entitlements_from_session_id,
        )

        with (
            patch(
                "app.enterprise.mod_entitlements.restore_entitlements_from_session_row",
                side_effect=RuntimeError("db error"),
            ) as mock_restore,
            patch("app.enterprise.mod_entitlements.set_session_entitlements") as mock_set,
        ):
            # Recoverable error must be swallowed (returns None, no propagation) ...
            result = _restore_entitlements_from_session_id("sid123")
        assert result is None
        # ... the restore was attempted before failing ...
        mock_restore.assert_called_once_with("sid123")
        # ... and the downstream set never runs because the pipeline aborted early.
        mock_set.assert_not_called()

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
    """Post-security-reversal contract: client mods must NOT be auto-mounted just because
    their directory exists on disk; entitlement gates them via ensure_mod_api_ready instead.
    The function is now a no-op stub kept only for legacy call sites."""

    def test_never_loads_even_when_mod_present_on_disk(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = MagicMock()
        # Even with a resolvable, not-yet-loaded mod that would "successfully" load,
        # the stub refuses to touch it: no resolve, no load_mod, empty result.
        mm.resolve_mod_directory.return_value = "/tmp/sunbird"
        mm._loaded_mods = []
        mm.load_mod.return_value = True
        result = mount_on_disk_primary_client_mods(mm)
        assert result == []
        mm.load_mod.assert_not_called()
        mm.resolve_mod_directory.assert_not_called()

    def test_returns_empty_without_a_manager(self):
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        # Tolerates being called with no manager (legacy load_mod_routes call site).
        assert mount_on_disk_primary_client_mods() == []
        assert mount_on_disk_primary_client_mods(None) == []


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

    def test_valid_pack_invokes_registrar_with_resolved_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import (
            _employee_pack_routes_registered,
            register_employee_pack_routes,
        )

        emp_dir = tmp_path / "_employees" / "p1"
        backend_dir = emp_dir / "backend"
        backend_dir.mkdir(parents=True)
        # manifest id ("packX") differs from the directory name ("p1") on purpose.
        (emp_dir / "manifest.json").write_text(
            json.dumps({"id": "packX", "artifact": "employee_pack", "backend": {"entry": "ep"}})
        )
        (backend_dir / "ep.py").write_text(
            "def register_fastapi_routes(app, mod_id):\n"
            "    app.registered_with = mod_id\n"
            "    return True\n"
        )

        mm = MagicMock()
        mm.mods_root = str(tmp_path)

        class FakeApp:
            registered_with = None

        app = FakeApp()
        _employee_pack_routes_registered.discard("packX")
        try:
            result = register_employee_pack_routes(app, mm, "p1")
            assert result is True
            # The real registrar ran and received the manifest-resolved id, not the dir name.
            assert app.registered_with == "packX"
            # Idempotency bookkeeping uses the resolved id too.
            assert "packX" in _employee_pack_routes_registered
            # No blueprint failure recorded on the happy path.
            mm.record_blueprint_failure.assert_not_called()
        finally:
            _employee_pack_routes_registered.discard("packX")


# ---------------------------------------------------------------------------
# load_employee_pack_routes
# ---------------------------------------------------------------------------


class TestLoadEmployeePackRoutes:
    def test_mods_disabled_returns(self):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        mm = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.register_employee_pack_routes"
            ) as mock_register,
        ):
            load_employee_pack_routes(MagicMock(), mm)
        # Disabled -> no employee pack routes registered.
        mock_register.assert_not_called()

    def test_no_employees_dir_returns(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        mm = MagicMock()
        mm.mods_root = str(tmp_path)  # no _employees subdir
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager.register_employee_pack_routes"
            ) as mock_register,
        ):
            load_employee_pack_routes(MagicMock(), mm)
        mock_register.assert_not_called()

    def test_skips_non_employee_pack(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        emp_dir = tmp_path / "_employees" / "p1"
        emp_dir.mkdir(parents=True)
        # artifact is a plain mod, not an employee_pack -> must be skipped.
        (emp_dir / "manifest.json").write_text(json.dumps({"id": "p1", "artifact": "mod"}))

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager.register_employee_pack_routes"
            ) as mock_register,
        ):
            load_employee_pack_routes(MagicMock(), mm)
        mock_register.assert_not_called()

    def test_dispatches_employee_pack_with_manifest_id(self, tmp_path):
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        emp_dir = tmp_path / "_employees" / "p1"
        emp_dir.mkdir(parents=True)
        # Two packs: only the employee_pack should be dispatched, by its manifest id.
        (emp_dir / "manifest.json").write_text(
            json.dumps({"id": "packX", "artifact": "employee_pack", "backend": {"entry": "ep"}})
        )
        other = tmp_path / "_employees" / "p2"
        other.mkdir(parents=True)
        (other / "manifest.json").write_text(json.dumps({"id": "p2", "artifact": "mod"}))

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        app = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager.register_employee_pack_routes"
            ) as mock_register,
        ):
            load_employee_pack_routes(app, mm)
        # Exactly one dispatch, for the employee_pack, keyed by its manifest id ("packX").
        mock_register.assert_called_once_with(app, mm, "packX")


# ---------------------------------------------------------------------------
# load_mod_blueprints (no-op)
# ---------------------------------------------------------------------------


class TestLoadModBlueprints:
    def test_no_op_does_not_raise(self):
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        # Documented compatibility shim: it is a no-op that returns None and
        # must NOT mount routes (routes go through load_mod_routes instead).
        app = MagicMock()
        result = load_mod_blueprints(app, None)
        assert result is None
        app.include_router.assert_not_called()
        app.add_api_route.assert_not_called()


# ---------------------------------------------------------------------------
# load_mod_routes
# ---------------------------------------------------------------------------


class TestLoadModRoutes:
    def test_load_mod_routes_with_empty_registry(self):
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = MagicMock()
        mm._loaded_mods = []
        mm._blueprint_failures = ["stale"]  # should be reset by load_mod_routes
        app = MagicMock()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"
            ) as mock_mount,
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes") as mock_emp,
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last") as mock_spa,
        ):
            registry = MagicMock()
            registry.list_mods.return_value = []
            mock_reg.return_value = registry
            load_mod_routes(app, mm)
        # The unconditional on-disk client mount still runs ...
        mock_mount.assert_called_once_with(mm)
        # ... blueprint failures are reset ...
        assert mm._blueprint_failures == []
        # ... employee-pack routes and the SPA fallback are always wired up ...
        mock_emp.assert_called_once_with(app, mm)
        mock_spa.assert_called_once_with(app)
        # ... and with an empty registry no per-mod HTTP routers are mounted.
        app.include_router.assert_not_called()

    def test_routable_mod_is_registered_and_ordered(self):
        from app.infrastructure.mods.mod_manager import ModManager, load_mod_routes

        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods = ["m1"]
        app = MagicMock()

        meta = MagicMock()
        meta.id = "m1"
        meta.backend_entry = "entry"
        meta.mod_path = "/tmp/m1"

        # A mod with a registrar but no backend_entry must be filtered out of routing.
        meta_skip = MagicMock()
        meta_skip.id = "no_entry"
        meta_skip.backend_entry = ""

        mod_module = MagicMock()
        mod_module.register_fastapi_routes = MagicMock()
        del mod_module.register_websocket_routes

        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as mock_reg,
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mod_module,
            ),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            registry = MagicMock()
            registry.list_mods.return_value = [meta, meta_skip]
            registry.get_mod_metadata.return_value = meta
            mock_reg.return_value = registry
            load_mod_routes(app, mm)

        # Only the mod with a backend_entry got its FastAPI routes mounted, keyed by id.
        mod_module.register_fastapi_routes.assert_called_once_with(app, "m1")
        assert "m1" in mm._http_routes_registered
        assert "no_entry" not in mm._http_routes_registered


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
    def test_only_existing_absolute_dirs_no_dupes(self):
        from app.infrastructure.mods.mod_manager import _repo_layout_mods_candidates

        result = _repo_layout_mods_candidates()
        # Every candidate is an absolute path that actually exists as a directory ...
        assert all(os.path.isabs(p) for p in result)
        assert all(os.path.isdir(p) for p in result)
        # ... and the function de-dups so each root appears at most once.
        assert len(result) == len(set(result))
        # Each candidate is named "mods" (possibly under XCAGI/ or mods-admin-runtime).
        assert all(os.path.basename(p) in {"mods", "mods-admin-runtime"} for p in result)


# ---------------------------------------------------------------------------
# _all_mods_roots
# ---------------------------------------------------------------------------


class TestAllModsRoots:
    def test_primary_not_dir_excluded(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots

        missing = str(tmp_path / "nonexistent")
        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": ""}, clear=False),
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=["/repo/mods"],
            ),
        ):
            result = _all_mods_roots(missing)
        # A non-existent primary is dropped entirely; only the repo candidate survives.
        assert missing not in result
        assert result == ["/repo/mods"]

    def test_primary_dir_listed_first(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots

        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": ""}, clear=False),
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=["/repo/mods"],
            ),
        ):
            result = _all_mods_roots(str(tmp_path))
        # Existing primary is honoured and takes precedence over repo candidates.
        assert result[0] == os.path.abspath(str(tmp_path))
        assert "/repo/mods" in result

    def test_env_path_added_after_primary_no_dupes(self, tmp_path):
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
        # Primary first, then the distinct env-provided root; both present, no repeats.
        assert result == [os.path.abspath(str(tmp_path)), str(env_dir)]

    def test_env_equal_to_primary_not_duplicated(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _all_mods_roots

        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path)}, clear=False),
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
        ):
            result = _all_mods_roots(str(tmp_path))
        # Env duplicates the primary -> de-duplicated to a single entry.
        assert result == [os.path.abspath(str(tmp_path))]


# ---------------------------------------------------------------------------
# ModManager._load_mod_backend — no backend dir
# ---------------------------------------------------------------------------


class TestLoadModBackendNoDir:
    def test_no_backend_dir_returns(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root=str(tmp_path))
        mod_path = str(tmp_path / "m1")
        os.makedirs(mod_path)  # no backend/ subdir
        backend_path = os.path.join(mod_path, "backend")
        meta = MagicMock()
        meta.backend_entry = ""
        meta.hooks = {}
        sys_path_before = list(sys.path)
        result = mm._load_mod_backend("m1", mod_path, meta)
        # No backend directory -> early return before touching sys.path or the module cache.
        assert result is None
        assert "m1" not in mm._backend_entry_modules
        assert backend_path not in sys.path
        assert sys.path == sys_path_before


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
    def test_happy_path_loads_and_mounts_routes(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        app = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as mock_load,
            patch("app.infrastructure.mods.mod_manager.load_mod_routes") as mock_routes,
        ):
            mm.ensure_mods_loaded(app)
        # Empty registry + manifests on disk -> load_all_mods then route mount, attempt counted.
        mock_load.assert_called_once_with()
        mock_routes.assert_called_once_with(app, mm)
        assert mm._ensure_attempts == 1
        assert mm._last_ensure_at > 0

    def test_mods_disabled_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(MagicMock())
        # Disabled -> no loading work and the retry counter stays untouched.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_already_loaded_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[MagicMock()]),
            patch.object(mm, "scan_mods") as mock_scan,
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(MagicMock())
        # Registry already populated -> short-circuit before even scanning the disk.
        mock_scan.assert_not_called()
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_no_discovered_returns(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(MagicMock())
        # No manifests on disk -> nothing to load and no attempt consumed.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_throttled_returns(self):
        import time

        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        sentinel = time.monotonic()
        mm._last_ensure_at = sentinel
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(MagicMock())
        # Within the 1.5s throttle window -> load skipped, no new attempt, timestamp unchanged.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0
        assert mm._last_ensure_at == sentinel

    def test_max_attempts_reached(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        mm._ensure_attempts = 20
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(MagicMock())
        # Attempt budget exhausted -> load skipped and counter not pushed past the cap.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 20

    def test_recoverable_error_swallowed(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp")
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                side_effect=RuntimeError("err"),
            ),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            # Recoverable error is swallowed (returns None, does not propagate) and no load runs.
            result = mm.ensure_mods_loaded(MagicMock())
        assert result is None
        mock_load.assert_not_called()


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
    def _meta(self, **overrides):
        m = MagicMock()
        defaults = {
            "id": "m1",
            "name": "Mod",
            "version": "1.0",
            "author": "alice",
            "description": "desc",
            "primary": True,
            "industry": {"k": "v"},
            "ui_labels": {"a": "b"},
            "ui_starter_pack": ["s1"],
            "frontend_menu": ["menu1"],
            "frontend_menu_overrides": ["ov"],
            "workflow_employees": ["e1"],
            "comms_exports": ["c1"],
            "frontend_pro_entry_path": "/pro",
        }
        defaults.update(overrides)
        for key, value in defaults.items():
            setattr(m, key, value)
        return m

    def test_bundle_artifact_adds_type(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        from app.infrastructure.mods.mod_manager import ModManager

        m = self._meta(artifact=ARTIFACT_BUNDLE)
        result = ModManager._metadata_to_api_dict(m)
        # Bundles carry the extra "type" discriminator the frontend keys on.
        assert result["type"] == "bundle"
        assert result["artifact"] == "bundle"

    def test_full_field_mapping_for_plain_mod(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_MOD
        from app.infrastructure.mods.mod_manager import ModManager

        m = self._meta(artifact=ARTIFACT_MOD)
        result = ModManager._metadata_to_api_dict(m)
        # Every scalar/collection field is projected through verbatim ...
        assert result == {
            "id": "m1",
            "name": "Mod",
            "version": "1.0",
            "author": "alice",
            "description": "desc",
            "primary": True,
            "artifact": "mod",
            "industry": {"k": "v"},
            "ui_labels": {"a": "b"},
            "ui_starter_pack": ["s1"],
            "menu": ["menu1"],
            "frontend": {"pro_entry_path": "/pro"},
            "menu_overrides": ["ov"],
            "workflow_employees": ["e1"],
            "comms_exports": ["c1"],
        }
        # ... and a non-bundle artifact must NOT add the "type" discriminator.
        assert "type" not in result

    def test_malformed_collections_coerced_to_empty(self):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_MOD
        from app.infrastructure.mods.mod_manager import ModManager

        # industry/ui_labels not dicts, ui_starter_pack not a list, falsy menus.
        m = self._meta(
            artifact=ARTIFACT_MOD,
            author=None,
            description=None,
            primary=0,
            industry="not-a-dict",
            ui_labels=None,
            ui_starter_pack="nope",
            frontend_menu=[],
            frontend_menu_overrides=None,
            workflow_employees=None,
            comms_exports=None,
            frontend_pro_entry_path="  /trim  ",
        )
        result = ModManager._metadata_to_api_dict(m)
        assert result["author"] == ""
        assert result["description"] == ""
        assert result["primary"] is False
        assert result["industry"] == {}
        assert result["ui_labels"] == {}
        assert result["ui_starter_pack"] == []
        assert result["menu"] == []
        assert result["menu_overrides"] == []
        assert result["workflow_employees"] == []
        assert result["comms_exports"] == []
        # pro_entry_path is stripped of surrounding whitespace.
        assert result["frontend"]["pro_entry_path"] == "/trim"
