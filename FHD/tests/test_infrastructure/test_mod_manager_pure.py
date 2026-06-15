"""Tests for app.infrastructure.mods.mod_manager — coverage ramp for pure functions."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestIsModsDisabled:
    def test_default_not_disabled(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_DISABLE_MODS", None)
            assert is_mods_disabled() is False

    def test_disabled_with_1(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            assert is_mods_disabled() is True

    def test_disabled_with_true(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "true"}):
            assert is_mods_disabled() is True

    def test_disabled_with_yes(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "yes"}):
            assert is_mods_disabled() is True

    def test_not_disabled_with_other(self):
        from app.infrastructure.mods.mod_manager import is_mods_disabled

        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "no"}):
            assert is_mods_disabled() is False


class TestShortExcMessage:
    def test_short_message(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        assert _short_exc_message(ValueError("test")) == "test"

    def test_long_message_truncated(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        long_msg = "x" * 600
        result = _short_exc_message(ValueError(long_msg))
        assert len(result) <= 480
        assert result.endswith("...")

    def test_empty_exception(self):
        from app.infrastructure.mods.mod_manager import _short_exc_message

        result = _short_exc_message(ValueError())
        assert result == "ValueError"


class TestBackendPathForMod:
    def test_returns_backend_path(self):
        from app.infrastructure.mods.mod_manager import _backend_path_for_mod

        assert _backend_path_for_mod("/mods/test-mod") == "/mods/test-mod/backend"


class TestDefaultModsRoot:
    def test_env_var_set_and_dir_exists(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _default_mods_root

        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": mods_dir}):
            result = _default_mods_root()
            assert result == mods_dir

    def test_env_var_set_but_dir_missing(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _default_mods_root

        fake_path = str(tmp_path / "nonexistent_mods")
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": fake_path}):
            result = _default_mods_root()
            # Should fall back to package-relative path
            assert isinstance(result, str)


class TestModManagerInit:
    def test_default_init(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/nonexistent_mods_for_test")
        assert mm.mods_root == "/tmp/nonexistent_mods_for_test"
        assert mm._loaded_mods == []
        assert mm._recent_load_failures == []

    def test_invalidate_scan_cache(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        mm._scan_cache_fp = "old_fp"
        mm._scan_cache_mods = ["old"]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


class TestModManagerRecordFailures:
    def test_record_load_failure(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        mm._record_load_failure("test_mod", "backend", "something went wrong")
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["mod_id"] == "test_mod"

    def test_record_blueprint_failure(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        mm.record_blueprint_failure("test_mod", "blueprint error")
        assert len(mm._blueprint_failures) == 1

    def test_get_recent_load_failures(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        mm._record_load_failure("mod1", "stage1", "err1")
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        # Should be a copy
        failures.append({"mod_id": "extra"})
        assert len(mm._recent_load_failures) == 1

    def test_get_blueprint_failures(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        mm.record_blueprint_failure("mod1", "err")
        assert len(mm.get_blueprint_failures()) == 1

    def test_get_scan_manifest_errors(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        errors = mm.get_scan_manifest_errors()
        assert isinstance(errors, list)


class TestModManagerMetadataToApiDict:
    def test_basic_conversion(self):
        from app.infrastructure.mods.mod_manager import ModManager
        from app.infrastructure.mods.manifest import ModMetadata

        mm = ModManager(mods_root="/tmp/test_mods")
        meta = ModMetadata(
            id="test-mod",
            name="Test Mod",
            version="1.0.0",
            mod_path="/mods/test-mod",
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["id"] == "test-mod"
        assert result["name"] == "Test Mod"
        assert result["version"] == "1.0.0"
        assert result["primary"] is False


class TestModManagerResolveModDirectory:
    def test_empty_mod_id(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        assert mm.resolve_mod_directory("") is None

    def test_none_mod_id(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        assert mm.resolve_mod_directory(None) is None


class TestModManagerValidateModPackage:
    def test_file_not_found(self):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        ok, msg, info = mm.validate_mod_package("/nonexistent/file.xcmod")
        assert ok is False
        assert "不存在" in msg

    def test_not_zip_file(self, tmp_path):
        from app.infrastructure.mods.mod_manager import ModManager

        mm = ModManager(mods_root="/tmp/test_mods")
        fake_file = tmp_path / "fake.xcmod"
        fake_file.write_text("not a zip")
        ok, msg, info = mm.validate_mod_package(str(fake_file))
        assert ok is False
        assert "ZIP" in msg


class TestLoadModBlueprints:
    def test_is_noop(self):
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        # Should not raise
        load_mod_blueprints(None)
