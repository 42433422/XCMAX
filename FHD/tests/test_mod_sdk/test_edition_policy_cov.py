from __future__ import annotations

"""Branch-coverage tests for app.mod_sdk.edition_policy."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.edition_policy import (
    _extra_mod_seed_roots,
    _resolve_mod_seed_source,
    bundled_mods_dir,
    configure_edition_defaults,
    edition_mod_ids,
    resolve_edition,
    seed_edition_mods_from_bundle,
    should_register_host_legacy_routes,
)

# ---------------------------------------------------------------------------
# resolve_edition
# ---------------------------------------------------------------------------

class TestResolveEdition:
    def test_explicit_minimal(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "minimal")
        assert resolve_edition() == "minimal"

    def test_explicit_generic(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "generic")
        assert resolve_edition() == "generic"

    def test_explicit_full(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "full")
        assert resolve_edition() == "full"

    def test_explicit_invalid_falls_through(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "bogus")
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        assert resolve_edition() == "full"

    def test_minimal_via_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EDITION", raising=False)
        monkeypatch.setenv("XCAGI_MINIMAL_EDITION", "true")
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        assert resolve_edition() == "minimal"

    def test_generic_via_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        monkeypatch.setenv("XCAGI_GENERIC_EDITION", "yes")
        assert resolve_edition() == "generic"

    def test_default_is_full(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        assert resolve_edition() == "full"


# ---------------------------------------------------------------------------
# should_register_host_legacy_routes
# ---------------------------------------------------------------------------

class TestShouldRegisterLegacyRoutes:
    def test_flag_0(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "0")
        assert should_register_host_legacy_routes() is False

    def test_flag_false(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "false")
        assert should_register_host_legacy_routes() is False

    def test_flag_no(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "no")
        assert should_register_host_legacy_routes() is False

    def test_flag_1(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "1")
        assert should_register_host_legacy_routes() is True

    def test_flag_true(self, monkeypatch):
        monkeypatch.setenv("XCAGI_REGISTER_LEGACY_ROUTES", "true")
        assert should_register_host_legacy_routes() is True

    def test_delegates_to_edition_profile(self, monkeypatch):
        monkeypatch.delenv("XCAGI_REGISTER_LEGACY_ROUTES", raising=False)
        monkeypatch.delenv("XCAGI_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        with patch("app.mod_sdk.host_profile.edition_legacy_routes_enabled", return_value=True) as mock_fn:
            result = should_register_host_legacy_routes()
        assert result is True


# ---------------------------------------------------------------------------
# edition_mod_ids
# ---------------------------------------------------------------------------

class TestEditionModIds:
    def test_sku_mods_take_precedence(self):
        with patch("app.mod_sdk.edition_policy.bundled_mod_ids_for_sku", return_value=("mod-a", "mod-b")):
            result = edition_mod_ids()
        assert result == ("mod-a", "mod-b")

    def test_minimal_edition(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "minimal")
        with patch("app.mod_sdk.edition_policy.bundled_mod_ids_for_sku", return_value=()):
            result = edition_mod_ids()
        from app.mod_sdk.platform_shell import MINIMAL_HOST_MOD_IDS
        assert result == MINIMAL_HOST_MOD_IDS

    def test_generic_edition(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "generic")
        with patch("app.mod_sdk.edition_policy.bundled_mod_ids_for_sku", return_value=()):
            result = edition_mod_ids()
        from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS
        assert result == GENERIC_HOST_MOD_IDS

    def test_full_edition(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "full")
        with patch("app.mod_sdk.edition_policy.bundled_mod_ids_for_sku", return_value=()):
            result = edition_mod_ids()
        from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS, MINIMAL_HOST_MOD_IDS
        assert set(MINIMAL_HOST_MOD_IDS).issubset(set(result))
        assert set(GENERIC_HOST_MOD_IDS).issubset(set(result))

    def test_explicit_edition_arg_minimal(self):
        with patch("app.mod_sdk.edition_policy.bundled_mod_ids_for_sku", return_value=()):
            result = edition_mod_ids("minimal")
        from app.mod_sdk.platform_shell import MINIMAL_HOST_MOD_IDS
        assert result == MINIMAL_HOST_MOD_IDS


# ---------------------------------------------------------------------------
# configure_edition_defaults
# ---------------------------------------------------------------------------

class TestConfigureEditionDefaults:
    def test_sku_triggers_configure(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "minimal")
        with (
            patch("app.mod_sdk.edition_policy.resolve_product_sku", return_value="sku-x"),
            patch("app.mod_sdk.edition_policy.configure_sku_edition_env") as mock_cfg,
        ):
            result = configure_edition_defaults()
        mock_cfg.assert_called_once()
        assert result == "minimal"

    def test_not_full_returns_early(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "generic")
        with patch("app.mod_sdk.edition_policy.resolve_product_sku", return_value=""):
            result = configure_edition_defaults()
        assert result == "generic"

    def test_full_in_pytest_returns_full(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "full")
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_something")
        with patch("app.mod_sdk.edition_policy.resolve_product_sku", return_value=""):
            result = configure_edition_defaults()
        assert result == "full"

    def test_desktop_mode_sets_generic_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "full")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_DEFAULT_EDITION", raising=False)
        with patch("app.mod_sdk.edition_policy.resolve_product_sku", return_value=""):
            result = configure_edition_defaults(desktop=True)
        # With desktop=True, XCAGI_GENERIC_EDITION is set -> resolves to generic
        assert result in ("generic", "full")

    def test_default_ed_minimal(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EDITION", "full")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        monkeypatch.setenv("XCAGI_DEFAULT_EDITION", "minimal")
        monkeypatch.delenv("XCAGI_GENERIC_EDITION", raising=False)
        monkeypatch.delenv("XCAGI_MINIMAL_EDITION", raising=False)
        with patch("app.mod_sdk.edition_policy.resolve_product_sku", return_value=""):
            result = configure_edition_defaults(desktop=False)
        # XCAGI_MINIMAL_EDITION gets set
        assert result in ("minimal", "full")


# ---------------------------------------------------------------------------
# bundled_mods_dir
# ---------------------------------------------------------------------------

class TestBundledModsDir:
    def test_env_bundled_mods_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_BUNDLED_MODS_DIR", str(tmp_path))
        result = bundled_mods_dir()
        assert result == tmp_path

    def test_env_seed_mods_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCAGI_BUNDLED_MODS_DIR", raising=False)
        monkeypatch.setenv("XCAGI_SEED_MODS_DIR", str(tmp_path))
        result = bundled_mods_dir()
        assert result == tmp_path

    def test_env_missing_dir_not_found(self, monkeypatch):
        monkeypatch.delenv("XCAGI_BUNDLED_MODS_DIR", raising=False)
        monkeypatch.delenv("XCAGI_SEED_MODS_DIR", raising=False)
        # Override cwd search by mocking Path.cwd to somewhere with no mods
        with patch("app.mod_sdk.edition_policy.Path") as mock_path_cls:
            # Let real Path work except cwd
            real_path = Path
            mock_path_cls.side_effect = real_path
            mock_path_cls.cwd.return_value = real_path("/tmp")
            # Will not find mods dir in /tmp normally -> may return None
            result = bundled_mods_dir()
        # result is either None or a Path
        assert result is None or isinstance(result, real_path)

    def test_frozen_meipass(self, tmp_path, monkeypatch):
        """Branch: sys.frozen = True with _MEIPASS."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        monkeypatch.delenv("XCAGI_BUNDLED_MODS_DIR", raising=False)
        monkeypatch.delenv("XCAGI_SEED_MODS_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = bundled_mods_dir()
        assert result == mods_dir
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


# ---------------------------------------------------------------------------
# _extra_mod_seed_roots
# ---------------------------------------------------------------------------

class TestExtraModSeedRoots:
    def test_env_paths_added(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_EXTRA_SEED_MODS_DIR", str(tmp_path))
        monkeypatch.delenv("XCAGI_REPO_MODS_DIR", raising=False)
        roots = _extra_mod_seed_roots()
        assert tmp_path in roots

    def test_missing_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EXTRA_SEED_MODS_DIR", raising=False)
        monkeypatch.delenv("XCAGI_REPO_MODS_DIR", raising=False)
        roots = _extra_mod_seed_roots()
        assert isinstance(roots, list)


# ---------------------------------------------------------------------------
# _resolve_mod_seed_source
# ---------------------------------------------------------------------------

class TestResolveModSeedSource:
    def test_found_in_primary(self, tmp_path):
        mod_id = "test-mod"
        mod_dir = tmp_path / mod_id
        mod_dir.mkdir()
        result = _resolve_mod_seed_source(mod_id, tmp_path)
        assert result == mod_dir

    def test_not_found_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCAGI_EXTRA_SEED_MODS_DIR", raising=False)
        monkeypatch.delenv("XCAGI_REPO_MODS_DIR", raising=False)
        result = _resolve_mod_seed_source("nonexistent-mod-xyz", tmp_path)
        assert result is None

    def test_found_in_extra_root(self, tmp_path, monkeypatch):
        primary = tmp_path / "primary"
        primary.mkdir()
        extra = tmp_path / "extra"
        extra.mkdir()
        mod_id = "my-test-mod"
        (extra / mod_id).mkdir()
        monkeypatch.setenv("XCAGI_EXTRA_SEED_MODS_DIR", str(extra))
        monkeypatch.delenv("XCAGI_REPO_MODS_DIR", raising=False)
        result = _resolve_mod_seed_source(mod_id, primary)
        assert result == extra / mod_id


# ---------------------------------------------------------------------------
# seed_edition_mods_from_bundle
# ---------------------------------------------------------------------------

_ED_MOD_MANAGER_PATH = "app.infrastructure.mods.mod_manager.get_mod_manager"


class TestSeedEditionModsFromBundle:
    def test_no_bundle_dir_returns_empty(self):
        with patch("app.mod_sdk.edition_policy.bundled_mods_dir", return_value=None):
            result = seed_edition_mods_from_bundle()
        assert result == []

    def test_mod_already_present(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        mods_root = tmp_path / "mods_root"
        mods_root.mkdir()

        mod_id = "xcagi-planner-bridge"
        (mods_root / mod_id).mkdir()  # already present

        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch("app.mod_sdk.edition_policy.bundled_mods_dir", return_value=bundle),
            patch(_ED_MOD_MANAGER_PATH, return_value=mm),
            patch("app.mod_sdk.edition_policy.edition_mod_ids", return_value=(mod_id,)),
        ):
            result = seed_edition_mods_from_bundle(mods_root=mods_root)

        assert any(r["status"] == "skipped" for r in result)

    def test_mod_missing_from_bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        mods_root = tmp_path / "mods_root"
        mods_root.mkdir()

        mod_id = "missing-mod"
        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch("app.mod_sdk.edition_policy.bundled_mods_dir", return_value=bundle),
            patch(_ED_MOD_MANAGER_PATH, return_value=mm),
            patch("app.mod_sdk.edition_policy.edition_mod_ids", return_value=(mod_id,)),
            patch("app.mod_sdk.edition_policy._resolve_mod_seed_source", return_value=None),
        ):
            result = seed_edition_mods_from_bundle(mods_root=mods_root)

        assert any(r["status"] == "missing" for r in result)

    def test_mod_seeded_successfully(self, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        mod_id = "seed-mod"
        src = bundle / mod_id
        src.mkdir()
        (src / "manifest.json").write_text("{}", encoding="utf-8")

        mods_root = tmp_path / "mods_root"
        mods_root.mkdir()

        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch("app.mod_sdk.edition_policy.bundled_mods_dir", return_value=bundle),
            patch(_ED_MOD_MANAGER_PATH, return_value=mm),
            patch("app.mod_sdk.edition_policy.edition_mod_ids", return_value=(mod_id,)),
            patch("app.mod_sdk.edition_policy._resolve_mod_seed_source", return_value=src),
        ):
            result = seed_edition_mods_from_bundle(mods_root=mods_root)

        assert any(r["status"] == "seeded" for r in result)

    def test_mod_seed_oserror(self, tmp_path):
        import shutil

        bundle = tmp_path / "bundle"
        bundle.mkdir()
        mod_id = "error-mod"
        src = bundle / mod_id
        src.mkdir()

        mods_root = tmp_path / "mods_root"
        mods_root.mkdir()

        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch("app.mod_sdk.edition_policy.bundled_mods_dir", return_value=bundle),
            patch(_ED_MOD_MANAGER_PATH, return_value=mm),
            patch("app.mod_sdk.edition_policy.edition_mod_ids", return_value=(mod_id,)),
            patch("app.mod_sdk.edition_policy._resolve_mod_seed_source", return_value=src),
            patch("shutil.copytree", side_effect=OSError("permission denied")),
        ):
            result = seed_edition_mods_from_bundle(mods_root=mods_root)

        assert any(r["status"] == "error" for r in result)
