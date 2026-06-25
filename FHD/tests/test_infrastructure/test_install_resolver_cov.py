"""Extended branch coverage tests for app.infrastructure.mods.install_resolver.

Covers missing branches in:
- install_package_dispatch (employee pack error/empty id, regular mod error/no meta)
- _rollback (mod_dir with/without metadata, employee_dir, error suppression, empty stack)
- _install_bundle_zip (depth limit, validation errors, embeds/contains edge cases, signature/package errors)
- get_install_resolver
"""

from __future__ import annotations

import os
import shutil
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.artifact_constants import (
    ARTIFACT_BUNDLE,
    ARTIFACT_EMPLOYEE_PACK,
    BUNDLE_MAX_DEPTH,
)
from app.infrastructure.mods.install_resolver import (
    InstallResolver,
    get_install_resolver,
)
from app.infrastructure.mods.package import ModPackageError, ModSignatureError

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mm():
    mm = MagicMock()
    mm.mods_root = "/tmp/mods"
    return mm


@pytest.fixture
def resolver(mock_mm):
    with patch("app.infrastructure.mods.install_resolver.get_mod_manager", return_value=mock_mm):
        return InstallResolver()


# ---------------------------------------------------------------------------
# install_package_dispatch — employee pack branches
# ---------------------------------------------------------------------------


class TestEmployeePackBranches:
    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_employee_pack_install_fails_triggers_rollback(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (False, "install failed")

        with (
            patch(
                "app.infrastructure.mods.install_resolver.get_employee_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                return_value={"id": "emp1"},
            ),
        ):
            resolver = InstallResolver()
            with patch.object(resolver, "_rollback") as mock_rb:
                ok, msg, data = resolver.install_package_dispatch("/path/to/pack.xcemp", "/store")
                mock_rb.assert_called_once()

        assert ok is False
        assert msg == "install failed"

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_employee_pack_peek_manifest_error_suppressed(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (True, "ok")

        with (
            patch(
                "app.infrastructure.mods.install_resolver.get_employee_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                side_effect=RuntimeError("zip error"),
            ),
        ):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch("/path/to/pack.xcemp", "/store")

        # Should still succeed; pack_id is empty so nothing added to rollback stack
        assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_employee_pack_empty_id_not_added_to_rollback(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (True, "ok")

        rb: list = []

        with (
            patch(
                "app.infrastructure.mods.install_resolver.get_employee_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                return_value={"id": ""},  # empty id
            ),
        ):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch(
                "/path/to/pack.xcemp", "/store", rollback_stack=rb
            )

        assert ok is True
        # pack_id is empty, so nothing should be appended to rb
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_employee_pack_none_id_not_added_to_rollback(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (True, "ok")

        rb: list = []

        with (
            patch(
                "app.infrastructure.mods.install_resolver.get_employee_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                return_value={},  # no id key
            ),
        ):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch(
                "/path/to/pack.xcemp", "/store", rollback_stack=rb
            )

        assert ok is True
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_employee_pack_success_adds_to_rollback(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (True, "ok")

        rb: list = []

        with (
            patch(
                "app.infrastructure.mods.install_resolver.get_employee_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                return_value={"id": "emp-123"},
            ),
        ):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch(
                "/path/to/pack.xcemp", "/store", rollback_stack=rb
            )

        assert ok is True
        assert len(rb) == 1
        assert rb[0][0] == "employee_dir"
        assert "emp-123" in rb[0][1]


# ---------------------------------------------------------------------------
# install_package_dispatch — regular mod branches
# ---------------------------------------------------------------------------


class TestRegularModBranches:
    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_mod_install_fails_triggers_rollback(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = "xcmod"
        mock_get_mm.return_value = mock_mm
        mock_mm.install_mod_package.return_value = (False, "install error", None)

        resolver = InstallResolver()
        with patch.object(resolver, "_rollback") as mock_rb:
            ok, msg, data = resolver.install_package_dispatch("/path/to/mod.xcmod", "/store")
            mock_rb.assert_called_once()

        assert ok is False
        assert msg == "install error"

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_mod_install_success_no_meta_not_added_to_rollback(
        self, mock_peek, mock_get_mm, mock_mm
    ):
        mock_peek.return_value = "xcmod"
        mock_get_mm.return_value = mock_mm
        mock_mm.install_mod_package.return_value = (True, "ok", None)

        rb: list = []

        resolver = InstallResolver()
        ok, msg, data = resolver.install_package_dispatch(
            "/path/to/mod.xcmod", "/store", rollback_stack=rb
        )

        assert ok is True
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_mod_install_success_meta_no_id_not_added_to_rollback(
        self, mock_peek, mock_get_mm, mock_mm
    ):
        mock_peek.return_value = "xcmod"
        mock_get_mm.return_value = mock_mm
        mock_meta = MagicMock()
        mock_meta.id = None
        mock_mm.install_mod_package.return_value = (True, "ok", mock_meta)

        rb: list = []

        resolver = InstallResolver()
        ok, msg, data = resolver.install_package_dispatch(
            "/path/to/mod.xcmod", "/store", rollback_stack=rb
        )

        assert ok is True
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_mod_install_success_meta_has_id_added_to_rollback(
        self, mock_peek, mock_get_mm, mock_mm
    ):
        mock_peek.return_value = "xcmod"
        mock_get_mm.return_value = mock_mm
        mock_meta = MagicMock()
        mock_meta.id = "mod-abc"
        mock_mm.install_mod_package.return_value = (True, "ok", mock_meta)

        rb: list = []

        resolver = InstallResolver()
        ok, msg, data = resolver.install_package_dispatch(
            "/path/to/mod.xcmod", "/store", rollback_stack=rb
        )

        assert ok is True
        assert len(rb) == 1
        assert rb[0][0] == "mod_dir"
        assert "mod-abc" in rb[0][1]


# ---------------------------------------------------------------------------
# _rollback
# ---------------------------------------------------------------------------


class TestRollback:
    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_empty_rollback_stack(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        rb: list = []
        # Should not raise
        resolver._rollback(rb)
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_mod_dir_with_metadata(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        # Create a directory to be removed
        mod_dir = tmp_path / "mod-1"
        mod_dir.mkdir()
        mod_dir_path = str(mod_dir)

        mock_registry = MagicMock()
        mock_registry.get_mod_metadata.return_value = {"name": "mod-1"}

        resolver = InstallResolver()
        with patch("app.infrastructure.mods.registry.get_mod_registry", return_value=mock_registry):
            rb = [("mod_dir", mod_dir_path)]
            resolver._rollback(rb)

        assert len(rb) == 0  # rb.clear() called
        mock_mm.unload_mod.assert_called_once_with("mod-1")
        assert not mod_dir.exists()

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_mod_dir_without_metadata(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        mod_dir = tmp_path / "mod-2"
        mod_dir.mkdir()
        mod_dir_path = str(mod_dir)

        mock_registry = MagicMock()
        mock_registry.get_mod_metadata.return_value = None  # no metadata

        resolver = InstallResolver()
        with patch("app.infrastructure.mods.registry.get_mod_registry", return_value=mock_registry):
            rb = [("mod_dir", mod_dir_path)]
            resolver._rollback(rb)

        assert len(rb) == 0
        mock_mm.unload_mod.assert_not_called()  # no unload since no metadata
        assert not mod_dir.exists()

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_mod_dir_path_not_exists(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_registry = MagicMock()
        mock_registry.get_mod_metadata.return_value = None

        resolver = InstallResolver()
        with patch("app.infrastructure.mods.registry.get_mod_registry", return_value=mock_registry):
            rb = [("mod_dir", "/nonexistent/path/mod-3")]
            resolver._rollback(rb)

        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_employee_dir(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        emp_dir_path = str(emp_dir)

        resolver = InstallResolver()
        rb = [("employee_dir", emp_dir_path)]
        resolver._rollback(rb)

        assert len(rb) == 0
        assert not emp_dir.exists()

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_employee_dir_not_exists(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        rb = [("employee_dir", "/nonexistent/emp")]
        resolver._rollback(rb)
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_employee_dir_is_file(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        emp_file = tmp_path / "emp-file"
        emp_file.write_text("test")
        emp_file_path = str(emp_file)

        resolver = InstallResolver()
        rb = [("employee_dir", emp_file_path)]
        resolver._rollback(rb)

        assert len(rb) == 0
        # shutil.rmtree(path, ignore_errors=True) on a file does NOT remove it
        # (rmtree raises NotADirectoryError which is suppressed by ignore_errors)
        assert emp_file.exists()

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_empty_path_skipped(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        rb = [("mod_dir", ""), ("employee_dir", "")]
        resolver._rollback(rb)
        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_recoverable_error_suppressed(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        mod_dir = tmp_path / "mod-err"
        mod_dir.mkdir()

        mock_registry = MagicMock()
        mock_registry.get_mod_metadata.side_effect = RuntimeError("registry error")

        resolver = InstallResolver()
        with patch("app.infrastructure.mods.registry.get_mod_registry", return_value=mock_registry):
            rb = [("mod_dir", str(mod_dir))]
            # Should not raise despite the error
            resolver._rollback(rb)

        assert len(rb) == 0

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_multiple_items_reversed_order(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        resolver = InstallResolver()
        rb = [("employee_dir", str(dir1)), ("employee_dir", str(dir2))]
        resolver._rollback(rb)

        assert len(rb) == 0
        assert not dir1.exists()
        assert not dir2.exists()

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_rollback_unknown_kind_skipped(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        rb = [("unknown_kind", "/some/path")]
        resolver._rollback(rb)
        assert len(rb) == 0


# ---------------------------------------------------------------------------
# _install_bundle_zip — edge cases
# ---------------------------------------------------------------------------


class TestInstallBundleZipEdgeCases:
    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_depth_exceeds_max(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        rb: list = []
        with patch.object(resolver, "_rollback") as mock_rb:
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=BUNDLE_MAX_DEPTH + 1,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert f"bundle 嵌套超过 {BUNDLE_MAX_DEPTH} 层" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_validation_errors_trigger_rollback(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            "/tmp/extract",
            {"bundle": {}},
        )

        resolver = InstallResolver()
        rb: list = []
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=["error1", "error2"],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "error1" in msg
        assert "error2" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_embeds_not_list_treated_as_empty(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            "/tmp/extract",
            {"bundle": {"embeds": "not a list", "contains": []}},
        )

        resolver = InstallResolver()
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=[],
            )

        assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_contains_not_list_treated_as_empty(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            "/tmp/extract",
            {"bundle": {"embeds": [], "contains": "not a list"}},
        )

        resolver = InstallResolver()
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=[],
            )

        assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_embed_file_not_found(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            str(tmp_path),
            {"bundle": {"embeds": ["missing.xcmod"], "contains": []}},
        )

        resolver = InstallResolver()
        rb: list = []
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "缺少嵌入文件" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_embed_install_fails(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        # Create the embed file
        embed_file = tmp_path / "inner.xcmod"
        embed_file.write_bytes(b"PK")

        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            str(tmp_path),
            {"bundle": {"embeds": ["inner.xcmod"], "contains": []}},
        )

        resolver = InstallResolver()
        rb: list = []
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
            patch.object(
                resolver,
                "install_package_dispatch",
                return_value=(False, "inner install failed", None),
            ),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "安装嵌入失败" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_contains_item_not_dict_skipped(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            "/tmp/extract",
            {"bundle": {"embeds": [], "contains": ["not a dict", 123, None]}},
        )

        resolver = InstallResolver()
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=[],
            )

        assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_contains_item_empty_ref_skipped(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            "/tmp/extract",
            {"bundle": {"embeds": [], "contains": [{"ref": ""}, {"ref": "   "}]}},
        )

        resolver = InstallResolver()
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=[],
            )

        assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_contains_ref_not_found_in_store(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            str(tmp_path),
            {"bundle": {"embeds": [], "contains": [{"ref": "nonexistent"}]}},
        )

        resolver = InstallResolver()
        rb: list = []
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                str(tmp_path),  # store_dir
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "未找到 ref=nonexistent" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_contains_install_fails(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        # Create a package in the store
        pkg = tmp_path / "ref-pkg-1.0.0.xcmod"
        pkg.write_bytes(b"PK")

        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            str(tmp_path),
            {"bundle": {"embeds": [], "contains": [{"ref": "ref-pkg"}]}},
        )

        resolver = InstallResolver()
        rb: list = []
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
            patch.object(
                resolver,
                "install_package_dispatch",
                return_value=(False, "member install failed", None),
            ),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                str(tmp_path),
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "安装成员失败" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_signature_error(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.side_effect = ModSignatureError("bad signature")

        resolver = InstallResolver()
        rb: list = []
        with (
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "签名验证失败" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_package_error(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.side_effect = ModPackageError("bad package")

        resolver = InstallResolver()
        rb: list = []
        with (
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "bad package" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_recoverable_error(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        mock_pkg = MagicMock()
        mock_pkg.extract_package.side_effect = RuntimeError("unexpected error")

        resolver = InstallResolver()
        rb: list = []
        with (
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(resolver, "_rollback") as mock_rb,
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                "/store",
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=rb,
            )
            mock_rb.assert_called_once_with(rb)

        assert ok is False
        assert "unexpected error" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_successful_bundle_with_embeds_and_contains(self, mock_get_mm, mock_mm, tmp_path):
        mock_get_mm.return_value = mock_mm
        # Create embed file
        embed_file = tmp_path / "inner.xcmod"
        embed_file.write_bytes(b"PK")
        # Create contains package in store
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        contains_pkg = store_dir / "ref-pkg-1.0.0.xcmod"
        contains_pkg.write_bytes(b"PK")

        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = (
            str(tmp_path),
            {
                "bundle": {
                    "embeds": ["inner.xcmod"],
                    "contains": [{"ref": "ref-pkg"}],
                }
            },
        )

        resolver = InstallResolver()
        with (
            patch(
                "app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                return_value=[],
            ),
            patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg),
            patch.object(
                resolver,
                "install_package_dispatch",
                return_value=(True, "ok", None),
            ),
        ):
            ok, msg, data = resolver._install_bundle_zip(
                "/path/to/bundle.xcmod",
                str(store_dir),
                verify_signature=True,
                activate=True,
                depth=0,
                rollback_stack=[],
            )

        assert ok is True
        assert "bundle 安装完成" in msg


# ---------------------------------------------------------------------------
# get_install_resolver
# ---------------------------------------------------------------------------


class TestGetInstallResolver:
    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_returns_resolver_instance(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = get_install_resolver()
        assert isinstance(resolver, InstallResolver)
        assert resolver.mods_root == "/tmp/mods"
