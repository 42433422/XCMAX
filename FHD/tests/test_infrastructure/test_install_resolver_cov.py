"""Branch-coverage tests for app.infrastructure.mods.install_resolver.

Targets missing branches at lines 36, 81-131, 143-206.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# _find_package_in_store
# ---------------------------------------------------------------------------

class TestFindPackageInStore:
    def test_returns_none_when_store_dir_empty_string(self):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        assert _find_package_in_store("", "some-mod") is None

    def test_returns_none_when_store_dir_not_a_dir(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        assert _find_package_in_store(str(tmp_path / "nonexistent"), "some-mod") is None

    def test_returns_none_when_no_matching_files(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        (tmp_path / "other-mod-1.0.xcmod").touch()
        result = _find_package_in_store(str(tmp_path), "mymod")
        assert result is None

    def test_returns_path_for_dash_prefixed_xcmod(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        f = tmp_path / "mymod-1.0.xcmod"
        f.touch()
        result = _find_package_in_store(str(tmp_path), "mymod")
        assert result == str(f)

    def test_returns_path_for_underscore_prefixed_xcmod(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        f = tmp_path / "mymod_v2.xcmod"
        f.touch()
        result = _find_package_in_store(str(tmp_path), "mymod")
        assert result == str(f)

    def test_returns_path_for_xcemp_extension(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        f = tmp_path / "mypack-1.0.xcemp"
        f.touch()
        result = _find_package_in_store(str(tmp_path), "mypack")
        assert result == str(f)

    def test_ignores_directories(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        d = tmp_path / "mymod-fake.xcmod"
        d.mkdir()
        result = _find_package_in_store(str(tmp_path), "mymod")
        assert result is None

    def test_strips_whitespace_from_ref_id(self, tmp_path):
        from app.infrastructure.mods.install_resolver import _find_package_in_store
        f = tmp_path / "mymod-1.0.xcmod"
        f.touch()
        result = _find_package_in_store(str(tmp_path), "  mymod  ")
        assert result == str(f)


# ---------------------------------------------------------------------------
# InstallResolver helpers & dispatch
# ---------------------------------------------------------------------------

def _make_resolver(mods_root: str) -> Any:
    with patch("app.infrastructure.mods.install_resolver.get_mod_manager") as mock_mm:
        mock_mm.return_value = MagicMock(mods_root=mods_root)
        from app.infrastructure.mods.install_resolver import InstallResolver
        return InstallResolver(mods_root=mods_root)


class TestInstallPackageDispatch:
    def test_unreadable_package_returns_false(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        with patch("app.infrastructure.mods.install_resolver.peek_artifact", side_effect=OSError("bad")):
            ok, msg, meta = resolver.install_package_dispatch("bad.xcmod", str(tmp_path))
        assert not ok
        assert "无法读取包" in msg

    def test_employee_pack_success(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        with (
            patch("app.infrastructure.mods.install_resolver.peek_artifact", return_value=ARTIFACT_EMPLOYEE_PACK),
            patch("app.infrastructure.mods.install_resolver.get_employee_registry") as mock_reg,
            patch("app.infrastructure.mods.install_resolver.InstallResolver._rollback"),
        ):
            reg_instance = MagicMock()
            reg_instance.install_from_package.return_value = (True, "ok")
            mock_reg.return_value = reg_instance
            # peek_manifest_from_zip returns id
            with patch("app.infrastructure.mods.artifact_package.peek_manifest_from_zip", return_value={"id": "emp1"}):
                ok, msg, meta = resolver.install_package_dispatch("emp.xcemp", str(tmp_path))
        assert ok

    def test_employee_pack_failure_triggers_rollback(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        with (
            patch("app.infrastructure.mods.install_resolver.peek_artifact", return_value=ARTIFACT_EMPLOYEE_PACK),
            patch("app.infrastructure.mods.install_resolver.get_employee_registry") as mock_reg,
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            reg_instance = MagicMock()
            reg_instance.install_from_package.return_value = (False, "fail")
            mock_reg.return_value = reg_instance
            ok, msg, meta = resolver.install_package_dispatch("emp.xcemp", str(tmp_path))
        assert not ok
        mock_rb.assert_called_once()

    def test_bundle_delegates_to_install_bundle_zip(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        with (
            patch("app.infrastructure.mods.install_resolver.peek_artifact", return_value=ARTIFACT_BUNDLE),
            patch.object(resolver, "_install_bundle_zip", return_value=(True, "ok", None)) as mock_bz,
        ):
            ok, msg, meta = resolver.install_package_dispatch("bundle.xcmod", str(tmp_path))
        assert ok
        mock_bz.assert_called_once()

    def test_regular_mod_success_appends_to_rollback(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        with (
            patch("app.infrastructure.mods.install_resolver.peek_artifact", return_value="mod"),
        ):
            meta_mock = MagicMock()
            meta_mock.id = "mymod"
            resolver.mm.install_mod_package.return_value = (True, "installed", meta_mock)
            rb: list = []
            ok, msg, meta = resolver.install_package_dispatch("mod.xcmod", str(tmp_path), rollback_stack=rb)
        assert ok
        assert any(k == "mod_dir" for k, _ in rb)

    def test_regular_mod_failure_triggers_rollback(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        with (
            patch("app.infrastructure.mods.install_resolver.peek_artifact", return_value="mod"),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            resolver.mm.install_mod_package.return_value = (False, "fail", None)
            ok, msg, meta = resolver.install_package_dispatch("mod.xcmod", str(tmp_path))
        assert not ok
        mock_rb.assert_called_once()


# ---------------------------------------------------------------------------
# _rollback
# ---------------------------------------------------------------------------

class TestRollback:
    def _patch_registry(self, ret=None):
        """Patch get_mod_registry inside install_resolver._rollback's local import."""
        from app.infrastructure.mods import registry as reg_mod
        mock_reg = MagicMock()
        mock_reg.get_mod_metadata.return_value = ret
        return patch.object(reg_mod, "get_mod_registry", return_value=mock_reg)

    def test_rollback_clears_list(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        rb = [("mod_dir", str(mod_dir))]
        with self._patch_registry(None):
            resolver._rollback(rb)
        assert rb == []

    def test_rollback_calls_unload_if_mod_registered(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        rb = [("mod_dir", str(mod_dir))]
        with self._patch_registry(MagicMock()):
            resolver._rollback(rb)
        resolver.mm.unload_mod.assert_called_once_with("mymod")

    def test_rollback_removes_employee_dir(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        emp_dir = tmp_path / "_employees" / "emp1"
        emp_dir.mkdir(parents=True)
        rb = [("employee_dir", str(emp_dir))]
        with self._patch_registry(None):
            resolver._rollback(rb)
        assert not emp_dir.exists()

    def test_rollback_handles_recoverable_error(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        rb = [("mod_dir", str(tmp_path / "ghost"))]
        from app.infrastructure.mods import registry as reg_mod
        mock_reg = MagicMock()
        mock_reg.get_mod_metadata.side_effect = OSError("bad")
        with patch.object(reg_mod, "get_mod_registry", return_value=mock_reg):
            resolver._rollback(rb)
        assert rb == []


# ---------------------------------------------------------------------------
# _install_bundle_zip
# ---------------------------------------------------------------------------

class TestInstallBundleZip:
    def test_depth_exceeded_returns_false(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        from app.infrastructure.mods.artifact_constants import BUNDLE_MAX_DEPTH
        rb: list = []
        with patch.object(resolver, "_rollback") as mock_rb:
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False,
                activate=True,
                depth=BUNDLE_MAX_DEPTH + 1,
                rollback_stack=rb,
            )
        assert not ok
        assert "嵌套" in msg
        mock_rb.assert_called_once()

    def test_bundle_invalid_manifest_returns_false(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        from app.infrastructure.mods.package import ModPackage
        with (
            patch.object(ModPackage, "extract_package", return_value=(str(tmp_path), {})),
            patch("app.infrastructure.mods.install_resolver.validate_bundle_manifest", return_value=["error 1"]),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False, activate=True, depth=0, rollback_stack=rb,
            )
        assert not ok
        mock_rb.assert_called_once()

    def test_bundle_missing_embedded_file_returns_false(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        manifest = {"bundle": {"embeds": ["sub.xcmod"], "contains": []}}
        from app.infrastructure.mods.package import ModPackage
        with (
            patch.object(ModPackage, "extract_package", return_value=(str(tmp_path), manifest)),
            patch("app.infrastructure.mods.install_resolver.validate_bundle_manifest", return_value=[]),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False, activate=True, depth=0, rollback_stack=rb,
            )
        assert not ok
        assert "缺少嵌入文件" in msg
        mock_rb.assert_called_once()

    def test_bundle_contains_missing_ref_returns_false(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        manifest = {"bundle": {"embeds": [], "contains": [{"ref": "missing-ref"}]}}
        from app.infrastructure.mods.package import ModPackage
        with (
            patch.object(ModPackage, "extract_package", return_value=(str(tmp_path), manifest)),
            patch("app.infrastructure.mods.install_resolver.validate_bundle_manifest", return_value=[]),
            patch("app.infrastructure.mods.install_resolver._find_package_in_store", return_value=None),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False, activate=True, depth=0, rollback_stack=rb,
            )
        assert not ok
        assert "未找到" in msg

    def test_bundle_contains_non_dict_item_skipped(self, tmp_path):
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        manifest = {"bundle": {"embeds": [], "contains": ["not-a-dict"]}}
        from app.infrastructure.mods.package import ModPackage
        with (
            patch.object(ModPackage, "extract_package", return_value=(str(tmp_path), manifest)),
            patch("app.infrastructure.mods.install_resolver.validate_bundle_manifest", return_value=[]),
            patch.object(resolver, "_rollback"),
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False, activate=True, depth=0, rollback_stack=rb,
            )
        assert ok  # no refs to process = success

    def test_bundle_signature_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.package import ModPackage, ModSignatureError
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        with (
            patch.object(ModPackage, "extract_package", side_effect=ModSignatureError("bad sig")),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=True, activate=True, depth=0, rollback_stack=rb,
            )
        assert not ok
        assert "签名" in msg
        mock_rb.assert_called_once()

    def test_bundle_package_error_returns_false(self, tmp_path):
        from app.infrastructure.mods.package import ModPackage, ModPackageError
        resolver = _make_resolver(str(tmp_path))
        rb: list = []
        with (
            patch.object(ModPackage, "extract_package", side_effect=ModPackageError("bad pkg")),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, meta = resolver._install_bundle_zip(
                "bundle.xcmod", str(tmp_path),
                verify_signature=False, activate=True, depth=0, rollback_stack=rb,
            )
        assert not ok
        mock_rb.assert_called_once()
