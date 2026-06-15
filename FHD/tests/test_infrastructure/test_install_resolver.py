"""测试 install_resolver 模块的安装调度。"""
import os
import pytest
from unittest.mock import MagicMock, patch

from app.infrastructure.mods.install_resolver import (
    _find_package_in_store,
    InstallResolver,
)


# ---------------------------------------------------------------------------
# _find_package_in_store
# ---------------------------------------------------------------------------

class TestFindPackageInStore:
    def test_empty_dir(self, tmp_path):
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is None

    def test_none_dir(self):
        result = _find_package_in_store(None, "mod1")
        assert result is None

    def test_nonexistent_dir(self):
        result = _find_package_in_store("/nonexistent/path", "mod1")
        assert result is None

    def test_finds_xcmod(self, tmp_path):
        pkg = tmp_path / "mod1-1.0.0.xcmod"
        pkg.write_bytes(b"PK")
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is not None
        assert "mod1-1.0.0.xcmod" in result

    def test_finds_xcemp(self, tmp_path):
        pkg = tmp_path / "emp1-2.0.0.xcemp"
        pkg.write_bytes(b"PK")
        result = _find_package_in_store(str(tmp_path), "emp1")
        assert result is not None
        assert "emp1-2.0.0.xcemp" in result

    def test_underscore_separator(self, tmp_path):
        pkg = tmp_path / "mod1_1.0.0.xcmod"
        pkg.write_bytes(b"PK")
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is not None

    def test_no_match(self, tmp_path):
        pkg = tmp_path / "other-1.0.0.xcmod"
        pkg.write_bytes(b"PK")
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is None

    def test_ignores_non_package_files(self, tmp_path):
        (tmp_path / "mod1.txt").write_text("not a package")
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is None

    def test_strips_ref_id(self, tmp_path):
        pkg = tmp_path / "mod1-1.0.0.xcmod"
        pkg.write_bytes(b"PK")
        result = _find_package_in_store(str(tmp_path), "  mod1  ")
        assert result is not None

    def test_returns_last_match(self, tmp_path):
        # Multiple versions, should return the last found
        (tmp_path / "mod1-1.0.0.xcmod").write_bytes(b"PK1")
        (tmp_path / "mod1-2.0.0.xcmod").write_bytes(b"PK2")
        result = _find_package_in_store(str(tmp_path), "mod1")
        assert result is not None
        assert "mod1" in result


# ---------------------------------------------------------------------------
# InstallResolver
# ---------------------------------------------------------------------------

class TestInstallResolver:
    @pytest.fixture
    def mock_mm(self):
        mm = MagicMock()
        mm.mods_root = "/tmp/mods"
        return mm

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_init_default_root(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()
        assert resolver.mods_root == "/tmp/mods"

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_init_custom_root(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver(mods_root="/custom/path")
        assert resolver.mods_root == os.path.abspath("/custom/path")

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    def test_install_package_dispatch_read_error(self, mock_get_mm, mock_mm):
        mock_get_mm.return_value = mock_mm
        resolver = InstallResolver()

        with patch("app.infrastructure.mods.install_resolver.peek_artifact",
                    side_effect=RuntimeError("bad file")):
            ok, msg, data = resolver.install_package_dispatch("/bad/path", "/store")
            assert ok is False
            assert "无法读取包" in msg

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_install_package_dispatch_employee_pack(self, mock_peek, mock_get_mm, mock_mm):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
        mock_peek.return_value = ARTIFACT_EMPLOYEE_PACK
        mock_get_mm.return_value = mock_mm

        mock_registry = MagicMock()
        mock_registry.install_from_package.return_value = (True, "ok")

        with patch("app.infrastructure.mods.install_resolver.get_employee_registry",
                    return_value=mock_registry), \
             patch("app.infrastructure.mods.artifact_package.peek_manifest_from_zip",
                    return_value={"id": "emp1"}):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch("/path/to/pack.xcemp", "/store")
            assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_install_package_dispatch_bundle(self, mock_peek, mock_get_mm, mock_mm):
        from app.infrastructure.mods.artifact_constants import ARTIFACT_BUNDLE
        mock_peek.return_value = ARTIFACT_BUNDLE
        mock_get_mm.return_value = mock_mm

        mock_pkg = MagicMock()
        mock_pkg.extract_package.return_value = ("/tmp/extract", {"bundle": {"embeds": [], "contains": []}})

        with patch("app.infrastructure.mods.install_resolver.validate_bundle_manifest",
                    return_value=[]), \
             patch("app.infrastructure.mods.install_resolver.ModPackage", mock_pkg):
            resolver = InstallResolver()
            ok, msg, data = resolver.install_package_dispatch("/path/to/bundle.xcmod", "/store")
            assert ok is True

    @patch("app.infrastructure.mods.install_resolver.get_mod_manager")
    @patch("app.infrastructure.mods.install_resolver.peek_artifact")
    def test_install_package_dispatch_regular_mod(self, mock_peek, mock_get_mm, mock_mm):
        mock_peek.return_value = "xcmod"  # Regular mod artifact
        mock_get_mm.return_value = mock_mm

        mock_mm.install_mod_package.return_value = (True, "installed", MagicMock(id="mod1"))

        resolver = InstallResolver()
        ok, msg, data = resolver.install_package_dispatch("/path/to/mod.xcmod", "/store")
        assert ok is True
