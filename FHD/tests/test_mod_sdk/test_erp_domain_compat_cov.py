from __future__ import annotations

"""Branch-coverage tests for app.mod_sdk.erp_domain_compat."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.erp_domain_compat import (
    DOMAIN_SPECS,
    ERP_DOMAIN_BRIDGE_MOD_ID,
    _mod_handler_domains,
    _read_manifest,
    _resolve_mod_dir,
    _truthy_env,
    is_erp_domain_mod_installed,
    is_erp_domain_via_mod_enabled,
    list_erp_domains_registry,
    load_erp_domains_config,
    resolve_host_api_path,
)

# ---------------------------------------------------------------------------
# _truthy_env
# ---------------------------------------------------------------------------


class TestTruthyEnv:
    def test_value_1(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "1")
        assert _truthy_env("_TEST_FLAG") is True

    def test_value_true(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "true")
        assert _truthy_env("_TEST_FLAG") is True

    def test_value_yes(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "yes")
        assert _truthy_env("_TEST_FLAG") is True

    def test_value_on(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "on")
        assert _truthy_env("_TEST_FLAG") is True

    def test_value_0(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "0")
        assert _truthy_env("_TEST_FLAG") is False

    def test_value_false(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLAG", "false")
        assert _truthy_env("_TEST_FLAG") is False

    def test_missing(self, monkeypatch):
        monkeypatch.delenv("_TEST_FLAG", raising=False)
        assert _truthy_env("_TEST_FLAG") is False


# ---------------------------------------------------------------------------
# _resolve_mod_dir
# ---------------------------------------------------------------------------

_MOD_MANAGER_PATH = "app.infrastructure.mods.mod_manager.get_mod_manager"
_IS_MODS_DISABLED_PATH = "app.infrastructure.mods.mod_manager.is_mods_disabled"


class TestResolveModDir:
    def test_falls_through_to_repo_path(self, monkeypatch):
        """Most installs won't have the mod dir -> returns None."""
        monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        with patch(_MOD_MANAGER_PATH, side_effect=RuntimeError("no mm")):
            result = _resolve_mod_dir()
        assert result is None or isinstance(result, Path)

    def test_env_mods_root_with_manifest(self, tmp_path, monkeypatch):
        """Branch: XCAGI_MODS_ROOT set and manifest exists."""
        mod_dir = tmp_path / ERP_DOMAIN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        with patch(_MOD_MANAGER_PATH, side_effect=RuntimeError("no mm")):
            result = _resolve_mod_dir()
        assert result == mod_dir

    def test_env_mods_dir_with_manifest(self, tmp_path, monkeypatch):
        """Branch: XCAGI_MODS_DIR set and manifest exists."""
        mod_dir = tmp_path / ERP_DOMAIN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")
        monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
        monkeypatch.setenv("XCAGI_MODS_DIR", str(tmp_path))
        with patch(_MOD_MANAGER_PATH, side_effect=RuntimeError("no mm")):
            result = _resolve_mod_dir()
        assert result == mod_dir

    def test_mod_manager_meta_with_path(self, tmp_path, monkeypatch):
        """Branch: get_mod_manager().get_mod() returns meta with mod_path."""
        mod_dir = tmp_path / ERP_DOMAIN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")

        meta = MagicMock()
        meta.mod_path = str(mod_dir)
        mm = MagicMock()
        mm.get_mod.return_value = meta
        mm.resolve_mod_directory.return_value = None

        with patch(_MOD_MANAGER_PATH, return_value=mm):
            result = _resolve_mod_dir()
        assert result == mod_dir

    def test_mod_manager_resolve_disk(self, tmp_path, monkeypatch):
        """Branch: get_mod() returns meta without path, resolve_mod_directory succeeds."""
        mod_dir = tmp_path / ERP_DOMAIN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")

        meta = MagicMock()
        meta.mod_path = None
        mm = MagicMock()
        mm.get_mod.return_value = meta
        mm.resolve_mod_directory.return_value = str(mod_dir)

        with patch(_MOD_MANAGER_PATH, return_value=mm):
            result = _resolve_mod_dir()
        assert result == mod_dir


# ---------------------------------------------------------------------------
# _read_manifest
# ---------------------------------------------------------------------------


class TestReadManifest:
    def test_no_mod_dir(self):
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=None):
            assert _read_manifest() == {}

    def test_valid_manifest(self, tmp_path):
        manifest_data = {"id": ERP_DOMAIN_BRIDGE_MOD_ID, "config": {"erp_domain_facade": True}}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=tmp_path):
            result = _read_manifest()
        assert result["id"] == ERP_DOMAIN_BRIDGE_MOD_ID

    def test_bad_manifest_returns_empty(self, tmp_path):
        (tmp_path / "manifest.json").write_text("[not a dict]", encoding="utf-8")
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=tmp_path):
            assert _read_manifest() == {}


# ---------------------------------------------------------------------------
# is_erp_domain_mod_installed
# ---------------------------------------------------------------------------


class TestIsErpDomainModInstalled:
    def test_mods_disabled(self):
        with (
            patch(_IS_MODS_DISABLED_PATH, return_value=True),
            patch(_MOD_MANAGER_PATH, MagicMock()),
        ):
            assert is_erp_domain_mod_installed() is False

    def test_mod_in_list(self):
        mm = MagicMock()
        mm.list_all_mods.return_value = [{"id": ERP_DOMAIN_BRIDGE_MOD_ID}]
        with (
            patch(_IS_MODS_DISABLED_PATH, return_value=False),
            patch(_MOD_MANAGER_PATH, return_value=mm),
        ):
            assert is_erp_domain_mod_installed() is True

    def test_mod_not_in_list_falls_back_to_dir(self, tmp_path):
        mm = MagicMock()
        mm.list_all_mods.return_value = [{"id": "other-mod"}]
        mod_dir = tmp_path / ERP_DOMAIN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")
        with (
            patch(_IS_MODS_DISABLED_PATH, return_value=False),
            patch(_MOD_MANAGER_PATH, return_value=mm),
            patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=mod_dir),
        ):
            assert is_erp_domain_mod_installed() is True

    def test_exception_falls_back_to_dir(self, tmp_path):
        with (
            patch(_MOD_MANAGER_PATH, side_effect=RuntimeError("fail")),
            patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=None),
        ):
            assert is_erp_domain_mod_installed() is False


# ---------------------------------------------------------------------------
# is_erp_domain_via_mod_enabled
# ---------------------------------------------------------------------------


class TestIsErpDomainViaModEnabled:
    def test_disabled_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", "1")
        assert is_erp_domain_via_mod_enabled() is False

    def test_forced_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.setenv("XCAGI_ERP_DOMAIN_VIA_MOD", "1")
        assert is_erp_domain_via_mod_enabled() is True

    def test_mod_not_installed(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_ERP_DOMAIN_VIA_MOD", raising=False)
        with patch("app.mod_sdk.erp_domain_compat.is_erp_domain_mod_installed", return_value=False):
            assert is_erp_domain_via_mod_enabled() is False

    def test_mod_installed_facade_true(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_ERP_DOMAIN_VIA_MOD", raising=False)
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_mod_installed", return_value=True),
            patch(
                "app.mod_sdk.erp_domain_compat._read_manifest",
                return_value={"config": {"erp_domain_facade": True}},
            ),
        ):
            assert is_erp_domain_via_mod_enabled() is True

    def test_mod_installed_facade_via_erp_domains(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_ERP_DOMAIN_VIA_MOD", raising=False)
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_mod_installed", return_value=True),
            patch(
                "app.mod_sdk.erp_domain_compat._read_manifest",
                return_value={"config": {"erp_domains": {"facade_enabled": True}}},
            ),
        ):
            assert is_erp_domain_via_mod_enabled() is True

    def test_mod_installed_no_facade_key(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_ERP_DOMAIN_VIA_MOD", raising=False)
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_mod_installed", return_value=True),
            patch("app.mod_sdk.erp_domain_compat._read_manifest", return_value={"config": {}}),
        ):
            assert is_erp_domain_via_mod_enabled() is False

    def test_cfg_not_dict(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_DOMAIN_MOD", raising=False)
        monkeypatch.delenv("XCAGI_ERP_DOMAIN_VIA_MOD", raising=False)
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_mod_installed", return_value=True),
            patch("app.mod_sdk.erp_domain_compat._read_manifest", return_value={"config": "bad"}),
        ):
            assert is_erp_domain_via_mod_enabled() is False


# ---------------------------------------------------------------------------
# load_erp_domains_config
# ---------------------------------------------------------------------------


class TestLoadErpDomainsConfig:
    def test_no_mod_dir(self):
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=None):
            assert load_erp_domains_config() == {}

    def test_no_config_file(self, tmp_path):
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=tmp_path):
            assert load_erp_domains_config() == {}

    def test_valid_config_file(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "erp_domains.json").write_text(
            json.dumps({"domains_enabled": True}), encoding="utf-8"
        )
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=tmp_path):
            result = load_erp_domains_config()
        assert result["domains_enabled"] is True

    def test_bad_json_returns_empty(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "erp_domains.json").write_text("[invalid", encoding="utf-8")
        with patch("app.mod_sdk.erp_domain_compat._resolve_mod_dir", return_value=tmp_path):
            assert load_erp_domains_config() == {}


# ---------------------------------------------------------------------------
# list_erp_domains_registry
# ---------------------------------------------------------------------------


class TestListErpDomainsRegistry:
    def test_host_api_path_no_mod(self):
        with (
            patch(
                "app.mod_sdk.erp_domain_compat.is_erp_domain_via_mod_enabled", return_value=False
            ),
            patch("app.mod_sdk.erp_domain_compat._mod_handler_domains", return_value=set()),
        ):
            result = list_erp_domains_registry()
        assert result["success"] is True
        assert result["execution_path"] == "host.api"
        assert len(result["domains"]) == len(DOMAIN_SPECS)

    def test_with_mod_facade(self):
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_via_mod_enabled", return_value=True),
            patch("app.mod_sdk.erp_domain_compat._mod_handler_domains", return_value=set()),
        ):
            result = list_erp_domains_registry()
        assert result["execution_via_mod_facade"] is True
        assert result["execution_path"] == "mod_facade"

    def test_with_handler_domains(self):
        with (
            patch("app.mod_sdk.erp_domain_compat.is_erp_domain_via_mod_enabled", return_value=True),
            patch("app.mod_sdk.erp_domain_compat._mod_handler_domains", return_value={"products"}),
        ):
            result = list_erp_domains_registry()
        assert result["execution_path"] == "mod_domain_handler"
        # products domain should have mod_domain_handler=True
        products_domain = next(d for d in result["domains"] if d["domain_id"] == "products")
        assert products_domain["mod_domain_handler"] is True


# ---------------------------------------------------------------------------
# resolve_host_api_path
# ---------------------------------------------------------------------------


class TestResolveHostApiPath:
    def test_facade_path_mapped(self):
        facade = f"/api/mod/{ERP_DOMAIN_BRIDGE_MOD_ID}/products/list"
        result = resolve_host_api_path(facade)
        assert result == "/api/products/list"

    def test_non_facade_path_unchanged(self):
        path = "/api/orders/123"
        assert resolve_host_api_path(path) == path
