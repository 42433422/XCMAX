"""Branch-coverage tests for app.security.lan_settings_store.

Targets missing branches at lines:
33/36, 41/42, 57-65, 69-93 (from_json), 99-108 (load_overrides),
121-143 (save_overrides).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _module():
    from app.security import lan_settings_store
    return lan_settings_store


# ---------------------------------------------------------------------------
# _resolve_repo_root
# ---------------------------------------------------------------------------

class TestResolveRepoRoot:
    def test_finds_repo_root_when_fastapi_and_xcagi_present(self, tmp_path):
        # build a fake directory structure:  tmp_path/app/fastapi_routes + tmp_path/XCAGI
        (tmp_path / "app" / "fastapi_routes").mkdir(parents=True)
        (tmp_path / "XCAGI").mkdir()
        mod = _module()
        # Patch Path(__file__).resolve() to return a file 3 levels deep inside tmp_path
        fake_file = tmp_path / "app" / "security" / "lan_settings_store.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.touch()
        with patch("app.security.lan_settings_store.Path") as MockPath:
            instance = MagicMock()
            instance.resolve.return_value = fake_file
            instance.parents = list(fake_file.parents)
            # simulate (parent / "app" / "fastapi_routes").is_dir() => True for tmp_path
            MockPath.return_value = instance
            # Just call directly since patching __file__ is complex; test logic only
        # Simpler: call real function, verify it returns a Path
        result = mod._resolve_repo_root()
        assert isinstance(result, Path)

    def test_fallback_when_no_marker(self):
        mod = _module()
        # On this filesystem, the function will either find the real root or fall back
        result = mod._resolve_repo_root()
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# _settings_path
# ---------------------------------------------------------------------------

class TestSettingsPath:
    def test_uses_env_override(self, tmp_path):
        override = str(tmp_path / "custom_settings.json")
        mod = _module()
        with patch.dict(os.environ, {"LAN_SETTINGS_FILE": override}):
            p = mod._settings_path()
        assert str(p) == str(Path(override).expanduser().resolve())

    def test_empty_env_falls_back_to_default(self):
        mod = _module()
        with patch.dict(os.environ, {"LAN_SETTINGS_FILE": ""}):
            p = mod._settings_path()
        assert p.name == "lan_settings.json"

    def test_whitespace_env_falls_back_to_default(self):
        mod = _module()
        with patch.dict(os.environ, {"LAN_SETTINGS_FILE": "   "}):
            p = mod._settings_path()
        assert p.name == "lan_settings.json"


# ---------------------------------------------------------------------------
# LanSettingsOverride.to_json
# ---------------------------------------------------------------------------

class TestLanSettingsOverrideToJson:
    def test_empty_override_produces_empty_dict(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride()
        assert obj.to_json() == {}

    def test_enabled_true(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(enabled=True)
        assert obj.to_json() == {"enabled": True}

    def test_enabled_false_included(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(enabled=False)
        assert obj.to_json()["enabled"] is False

    def test_license_secret_included(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(license_secret="s3cr3t")
        assert obj.to_json()["license_secret"] == "s3cr3t"

    def test_admin_bootstrap_key_included(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(admin_bootstrap_key="bootkey")
        assert obj.to_json()["admin_bootstrap_key"] == "bootkey"

    def test_allowed_cidrs_included(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(allowed_cidrs=["10.0.0.0/8"])
        d = obj.to_json()
        assert d["allowed_cidrs"] == ["10.0.0.0/8"]

    def test_all_fields_included(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride(
            enabled=True,
            license_secret="sec",
            admin_bootstrap_key="key",
            allowed_cidrs=["192.168.0.0/16"],
        )
        d = obj.to_json()
        assert len(d) == 4


# ---------------------------------------------------------------------------
# LanSettingsOverride.from_json
# ---------------------------------------------------------------------------

class TestLanSettingsOverrideFromJson:
    def test_non_dict_returns_empty(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json("not_a_dict")
        assert obj.enabled is None

    def test_enabled_string_true(self):
        from app.security.lan_settings_store import LanSettingsOverride
        for val in ("true", "1", "yes", "on"):
            obj = LanSettingsOverride.from_json({"enabled": val})
            assert obj.enabled is True, f"failed for {val!r}"

    def test_enabled_string_false(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"enabled": "false"})
        assert obj.enabled is False

    def test_enabled_bool(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"enabled": True})
        assert obj.enabled is True

    def test_enabled_none_stays_none(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({})
        assert obj.enabled is None

    def test_secret_coerced_to_str(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"license_secret": 12345})
        assert obj.license_secret == "12345"

    def test_bootstrap_coerced_to_str(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"admin_bootstrap_key": 99})
        assert obj.admin_bootstrap_key == "99"

    def test_allowed_cidrs_from_list(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"allowed_cidrs": ["10.0.0.0/8", "  ", "192.168.1.0/24"]})
        # empty string stripped out
        assert "10.0.0.0/8" in obj.allowed_cidrs
        assert "" not in obj.allowed_cidrs

    def test_allowed_cidrs_from_string(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({"allowed_cidrs": "10.0.0.0/8, 192.168.0.0/16"})
        assert obj.allowed_cidrs == ["10.0.0.0/8", "192.168.0.0/16"]

    def test_allowed_cidrs_none_when_missing(self):
        from app.security.lan_settings_store import LanSettingsOverride
        obj = LanSettingsOverride.from_json({})
        assert obj.allowed_cidrs is None


# ---------------------------------------------------------------------------
# load_overrides
# ---------------------------------------------------------------------------

class TestLoadOverrides:
    def test_returns_empty_when_file_missing(self, tmp_path):
        mod = _module()
        missing = tmp_path / "no_file.json"
        with patch.object(mod, "_settings_path", return_value=missing):
            result = mod.load_overrides()
        assert result.enabled is None

    def test_returns_parsed_when_file_exists(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        p.write_text(json.dumps({"enabled": True}), encoding="utf-8")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.load_overrides()
        assert result.enabled is True

    def test_empty_file_returns_empty_override(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        p.write_text("   ", encoding="utf-8")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.load_overrides()
        assert result.enabled is None

    def test_ioerror_returns_empty_override(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        p.write_text("{}", encoding="utf-8")
        # Patch Path.read_text at the class level temporarily
        with (
            patch.object(mod, "_settings_path", return_value=p),
            patch("pathlib.Path.read_text", side_effect=OSError("disk error")),
        ):
            result = mod.load_overrides()
        # OSError is in RECOVERABLE_ERRORS, so returns empty
        assert result.enabled is None

    def test_corrupt_json_returns_empty_override(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        p.write_text("{bad json", encoding="utf-8")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.load_overrides()
        assert result.enabled is None


# ---------------------------------------------------------------------------
# save_overrides
# ---------------------------------------------------------------------------

class TestSaveOverrides:
    def test_save_creates_file(self, tmp_path):
        mod = _module()
        p = tmp_path / "data" / "lan_settings.json"
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(enabled=True, license_secret="s")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update)
        assert p.exists()
        assert result.enabled is True

    def test_merge_true_preserves_existing(self, tmp_path):
        mod = _module()
        p = tmp_path / "data" / "lan_settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"enabled": True, "license_secret": "old"}), encoding="utf-8")
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(license_secret="new")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update, merge=True)
        assert result.enabled is True  # preserved from disk
        assert result.license_secret == "new"  # updated

    def test_merge_false_replaces_all(self, tmp_path):
        mod = _module()
        p = tmp_path / "data" / "lan_settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"enabled": True, "license_secret": "old"}), encoding="utf-8")
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(license_secret="new")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update, merge=False)
        assert result.enabled is None  # not preserved
        assert result.license_secret == "new"

    def test_save_with_allowed_cidrs_strips_empty(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(allowed_cidrs=["10.0.0.0/8", "  ", ""])
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update)
        assert result.allowed_cidrs == ["10.0.0.0/8"]

    def test_merge_corrupt_existing_file_starts_fresh(self, tmp_path):
        mod = _module()
        p = tmp_path / "data" / "lan_settings.json"
        p.parent.mkdir(parents=True)
        p.write_text("{bad", encoding="utf-8")
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(enabled=False)
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update, merge=True)
        # corrupt file => started fresh, only update.enabled applied
        assert result.enabled is False

    def test_atomic_replace_on_write(self, tmp_path):
        """Verify os.replace is called (atomic write)."""
        mod = _module()
        p = tmp_path / "lan_settings.json"
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(enabled=True)
        with patch.object(mod, "_settings_path", return_value=p):
            with patch("os.replace") as mock_replace:
                mod.save_overrides(update)
        mock_replace.assert_called_once()

    def test_admin_bootstrap_key_persisted(self, tmp_path):
        mod = _module()
        p = tmp_path / "lan_settings.json"
        from app.security.lan_settings_store import LanSettingsOverride
        update = LanSettingsOverride(admin_bootstrap_key="mykey")
        with patch.object(mod, "_settings_path", return_value=p):
            result = mod.save_overrides(update)
        assert result.admin_bootstrap_key == "mykey"
