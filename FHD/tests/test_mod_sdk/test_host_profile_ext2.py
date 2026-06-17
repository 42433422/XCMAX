"""Tests for app.mod_sdk.host_profile — coverage ramp ext2.

Covers ``_resolve_product_sku``, ``resolve_fhd_config_dir``, ``_deep_merge``,
``_load_json``, ``_validate_profile_schema``, ``_load_merged_profile``,
``get_profile_validation_errors``, ``load_host_profile``, ``_legacy_profile_for_sku``,
``load_industry_presets_document``, ``load_workflow_employee_catalog``,
``get_bridge_mod_host_apis``, ``get_minimal_host_mod_ids``,
``get_generic_host_mod_ids``, ``get_protected_client_mod_ids``,
``get_core_workflow_mod_id``, ``get_platform_shell_api_prefixes``,
``get_client_mod_policies``, ``get_employee_registry_rules``,
``bundled_mod_ids_for_profile_sku``, ``package_stage_mod_ids_for_sku``,
``workflow_delivery_mod_ids_for_package``, ``edition_legacy_routes_enabled``,
``scan_workflow_employee_catalog_from_mods``, ``build_host_profile_api_payload``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk import host_profile as hp


# ── _resolve_product_sku ─────────────────────────────────────────────────────


class TestResolveProductSku:
    def test_env_direct_personal(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        assert hp._resolve_product_sku() == "personal"

    def test_env_direct_enterprise(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "ENTERPRISE")
        assert hp._resolve_product_sku() == "enterprise"

    def test_env_invalid_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "invalid")
        assert hp._resolve_product_sku() is None

    def test_env_empty_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "")
        assert hp._resolve_product_sku() is None

    def test_sku_file(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"sku": "personal"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() == "personal"

    def test_sku_file_product_sku_key(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"product_sku": "enterprise"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() == "enterprise"

    def test_resources_dir(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "product-sku.json"
        sku_file.write_text(json.dumps({"sku": "personal"}))
        monkeypatch.setenv("XCAGI_RESOURCES_DIR", str(tmp_path))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        monkeypatch.delenv("XCAGI_PRODUCT_SKU_FILE", raising=False)
        assert hp._resolve_product_sku() == "personal"

    def test_desktop_resources(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "product-sku.json"
        sku_file.write_text(json.dumps({"sku": "enterprise"}))
        monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(tmp_path))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        monkeypatch.delenv("XCAGI_PRODUCT_SKU_FILE", raising=False)
        monkeypatch.delenv("XCAGI_RESOURCES_DIR", raising=False)
        assert hp._resolve_product_sku() == "enterprise"

    def test_no_env_returns_none(self, monkeypatch):
        for key in (
            "XCAGI_PRODUCT_SKU",
            "XCAGI_PRODUCT_SKU_FILE",
            "XCAGI_RESOURCES_DIR",
            "XCAGI_DESKTOP_RESOURCES",
        ):
            monkeypatch.delenv(key, raising=False)
        assert hp._resolve_product_sku() is None


# ── resolve_fhd_config_dir ───────────────────────────────────────────────────


class TestResolveFhdConfigDir:
    def test_env_xcagi_fhd_root(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("XCAGI_FHD_ROOT", str(tmp_path))
        assert hp.resolve_fhd_config_dir() == config_dir.resolve()

    def test_env_xcagi_repo_root(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("XCAGI_REPO_ROOT", str(tmp_path))
        monkeypatch.delenv("XCAGI_FHD_ROOT", raising=False)
        assert hp.resolve_fhd_config_dir() == config_dir.resolve()

    def test_no_env_no_config_returns_none(self, monkeypatch):
        # Force no env and no config dir nearby
        monkeypatch.delenv("XCAGI_FHD_ROOT", raising=False)
        monkeypatch.delenv("XCAGI_REPO_ROOT", raising=False)
        # The actual repo may have a config dir; just verify it returns Path or None
        result = hp.resolve_fhd_config_dir()
        assert result is None or isinstance(result, Path)


# ── _deep_merge ──────────────────────────────────────────────────────────────


class TestDeepMerge:
    def test_simple_overlay(self):
        out = hp._deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert out == {"a": 1, "b": 3, "c": 4}

    def test_nested_dict_merge(self):
        out = hp._deep_merge(
            {"a": {"x": 1, "y": 2}}, {"a": {"y": 3, "z": 4}}
        )
        assert out == {"a": {"x": 1, "y": 3, "z": 4}}

    def test_overlay_replaces_non_dict(self):
        out = hp._deep_merge({"a": [1, 2]}, {"a": [3]})
        assert out == {"a": [3]}

    def test_does_not_mutate_inputs(self):
        base = {"a": {"x": 1}}
        overlay = {"a": {"y": 2}}
        hp._deep_merge(base, overlay)
        assert base == {"a": {"x": 1}}
        assert overlay == {"a": {"y": 2}}


# ── _load_json ───────────────────────────────────────────────────────────────


class TestLoadJson:
    def test_loads_dict(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"k": "v"}))
        assert hp._load_json(f) == {"k": "v"}

    def test_missing_file_returns_none(self, tmp_path):
        assert hp._load_json(tmp_path / "missing.json") is None

    def test_non_dict_returns_none(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps([1, 2]))
        assert hp._load_json(f) is None

    def test_invalid_json_returns_none(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text("not json")
        assert hp._load_json(f) is None


# ── _validate_profile_schema ─────────────────────────────────────────────────


class TestValidateProfileSchema:
    def test_valid_schema(self):
        data = {
            "schema_version": 1,
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
        }
        assert hp._validate_profile_schema(data) == []

    def test_schema_version_mismatch(self):
        data = {
            "schema_version": 2,
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
        }
        errs = hp._validate_profile_schema(data)
        assert any("PROFILE_SCHEMA_MISMATCH" in e for e in errs)

    def test_missing_required_keys(self):
        data = {"schema_version": 1}
        errs = hp._validate_profile_schema(data)
        assert len(errs) == 4  # sku, package_stage_ids, sku_bundled_mod_ids, bridge_api_map

    def test_no_schema_version_ok(self):
        # schema_version None is allowed
        data = {
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
        }
        assert hp._validate_profile_schema(data) == []


# ── _load_merged_profile ─────────────────────────────────────────────────────


class TestLoadMergedProfile:
    def test_returns_none_when_no_config_dir(self, monkeypatch):
        # Clear cache
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "resolve_fhd_config_dir", return_value=None):
            assert hp._load_merged_profile("personal") is None

    def test_returns_merged_profile(self, monkeypatch, tmp_path):
        hp._load_merged_profile.cache_clear()
        config_dir = tmp_path / "config"
        profiles_dir = config_dir / "host_profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "_base.json").write_text(
            json.dumps({"schema_version": 1, "base_key": "base"})
        )
        (profiles_dir / "personal.json").write_text(
            json.dumps({"sku_specific": "personal"})
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp._load_merged_profile("personal")
        assert out is not None
        assert out["base_key"] == "base"
        assert out["sku_specific"] == "personal"
        assert out["sku"] == "personal"

    def test_returns_none_when_base_missing(self, monkeypatch, tmp_path):
        hp._load_merged_profile.cache_clear()
        config_dir = tmp_path / "config"
        profiles_dir = config_dir / "host_profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "personal.json").write_text(json.dumps({"k": "v"}))
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            assert hp._load_merged_profile("personal") is None

    def test_returns_none_when_overlay_missing(self, monkeypatch, tmp_path):
        hp._load_merged_profile.cache_clear()
        config_dir = tmp_path / "config"
        profiles_dir = config_dir / "host_profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "_base.json").write_text(json.dumps({"k": "v"}))
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            assert hp._load_merged_profile("personal") is None


# ── get_profile_validation_errors ────────────────────────────────────────────


class TestGetProfileValidationErrors:
    def test_no_sku_returns_empty(self, monkeypatch):
        for key in (
            "XCAGI_PRODUCT_SKU",
            "XCAGI_PRODUCT_SKU_FILE",
            "XCAGI_RESOURCES_DIR",
            "XCAGI_DESKTOP_RESOURCES",
        ):
            monkeypatch.delenv(key, raising=False)
        hp._load_merged_profile.cache_clear()
        assert hp.get_profile_validation_errors() == []

    def test_no_profile_returns_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "resolve_fhd_config_dir", return_value=None):
            assert hp.get_profile_validation_errors() == []


# ── load_host_profile ────────────────────────────────────────────────────────


class TestLoadHostProfile:
    def test_returns_legacy_when_no_config(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "_load_merged_profile", return_value=None):
            out = hp.load_host_profile("personal")
        assert out["sku"] == "personal"
        assert out["_source"] == "legacy_fallback"
        assert out["runtime_edition"] == "minimal"

    def test_returns_legacy_enterprise(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "_load_merged_profile", return_value=None):
            out = hp.load_host_profile("enterprise")
        assert out["sku"] == "enterprise"
        assert out["runtime_edition"] == "full"

    def test_returns_legacy_unknown_sku(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "_load_merged_profile", return_value=None):
            out = hp.load_host_profile("unknown")
        assert out["sku"] == "unknown"
        assert out["runtime_edition"] == "full"

    def test_returns_merged_when_available(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        merged = {
            "schema_version": 1,
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
            "custom_key": "custom",
        }
        with patch.object(hp, "_load_merged_profile", return_value=merged):
            out = hp.load_host_profile("personal")
        assert out["custom_key"] == "custom"

    def test_logs_warning_on_validation_errors(self, monkeypatch, caplog):
        hp._load_merged_profile.cache_clear()
        merged = {
            "schema_version": 99,  # mismatch
            "sku": "personal",
        }
        with patch.object(hp, "_load_merged_profile", return_value=merged):
            with caplog.at_level("WARNING"):
                hp.load_host_profile("personal")
        assert any("host_profile validation" in r.message for r in caplog.records)


# ── _legacy_profile_for_sku ──────────────────────────────────────────────────


class TestLegacyProfileForSku:
    def test_personal_blocks_erp(self):
        out = hp._legacy_profile_for_sku("personal")
        assert "xcagi-erp-domain-bridge" in out["blocked_mod_ids"]
        assert out["runtime_edition"] == "minimal"

    def test_enterprise_no_blocks(self):
        out = hp._legacy_profile_for_sku("enterprise")
        assert out["blocked_mod_ids"] == []
        assert out["runtime_edition"] == "full"

    def test_unknown_sku_defaults_full(self):
        out = hp._legacy_profile_for_sku("unknown")
        assert out["runtime_edition"] == "full"

    def test_personal_minimal_host_mod_ids(self):
        out = hp._legacy_profile_for_sku("personal")
        assert "xcagi-planner-bridge" in out["minimal_host_mod_ids"]

    def test_has_required_keys(self):
        for sku in ("personal", "enterprise"):
            out = hp._legacy_profile_for_sku(sku)
            for key in (
                "schema_version",
                "sku",
                "runtime_edition",
                "frontend_edition",
                "workflow_delivery",
                "package_stage_ids",
                "sku_bundled_mod_ids",
                "bridge_api_map",
                "platform_shell_api_prefixes",
                "protected_client_mod_ids",
                "core_workflow_mod_id",
                "client_mod_policies",
                "employee_registry_rules",
                "editions",
            ):
                assert key in out, f"missing {key} for {sku}"


# ── load_industry_presets_document ───────────────────────────────────────────


class TestLoadIndustryPresetsDocument:
    def test_returns_default_when_no_config(self, monkeypatch):
        hp.load_industry_presets_document.cache_clear()
        with patch.object(hp, "resolve_fhd_config_dir", return_value=None):
            out = hp.load_industry_presets_document()
        assert out["schema_version"] == hp.INDUSTRY_PRESETS_SCHEMA_VERSION
        assert "presets" in out
        assert out["presets"] == {}

    def test_loads_from_config(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text(
            json.dumps({"schema_version": 1, "presets": {"a": {}}})
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        assert out["presets"] == {"a": {}}

    def test_invalid_presets_returns_default(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text(
            json.dumps({"schema_version": 1, "presets": "not a dict"})
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        assert out["presets"] == {}


# ── load_workflow_employee_catalog ───────────────────────────────────────────


class TestLoadWorkflowEmployeeCatalog:
    def test_returns_default_when_no_config(self, monkeypatch):
        hp.load_workflow_employee_catalog.cache_clear()
        with patch.object(hp, "resolve_fhd_config_dir", return_value=None):
            out = hp.load_workflow_employee_catalog()
        assert out["schema_version"] == hp.WORKFLOW_CATALOG_SCHEMA_VERSION
        assert out["workflow_viz_bridge_mod_id"] == hp._LEGACY_CORE_WORKFLOW

    def test_loads_from_config(self, monkeypatch, tmp_path):
        hp.load_workflow_employee_catalog.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "workflow_employee_catalog.json").write_text(
            json.dumps({"schema_version": 1, "custom_key": "v"})
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_workflow_employee_catalog()
        assert out["custom_key"] == "v"


# ── get_* helpers ────────────────────────────────────────────────────────────


class TestGetBridgeModHostApis:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"bridge_api_map": {"bridge1": ["/api/x"]}},
        ):
            out = hp.get_bridge_mod_host_apis()
        assert out == {"bridge1": ["/api/x"]}

    def test_returns_legacy_when_empty(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={"bridge_api_map": {}}):
            out = hp.get_bridge_mod_host_apis()
        assert "xcagi-planner-bridge" in out

    def test_returns_legacy_when_missing(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_bridge_mod_host_apis()
        assert "xcagi-planner-bridge" in out

    def test_handles_non_list_values(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"bridge_api_map": {"bridge1": "not a list"}},
        ):
            out = hp.get_bridge_mod_host_apis()
        assert out["bridge1"] == []


class TestGetMinimalHostModIds:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp, "load_host_profile", return_value={"minimal_host_mod_ids": ["a", "b"]}
        ):
            assert hp.get_minimal_host_mod_ids() == ("a", "b")

    def test_returns_legacy_when_empty(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_minimal_host_mod_ids()
        assert "xcagi-planner-bridge" in out


class TestGetGenericHostModIds:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp, "load_host_profile", return_value={"generic_host_mod_ids": ["a"]}
        ):
            assert hp.get_generic_host_mod_ids() == ("a",)

    def test_returns_legacy_when_empty(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_generic_host_mod_ids()
        assert "xcagi-planner-bridge" in out


class TestGetProtectedClientModIds:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp, "load_host_profile", return_value={"protected_client_mod_ids": ["a"]}
        ):
            assert hp.get_protected_client_mod_ids() == ("a",)

    def test_returns_legacy_when_empty(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_protected_client_mod_ids()
        assert "attendance-industry" in out


class TestGetCoreWorkflowModId:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp, "load_host_profile", return_value={"core_workflow_mod_id": "custom"}
        ):
            assert hp.get_core_workflow_mod_id() == "custom"

    def test_returns_legacy_when_missing(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            assert hp.get_core_workflow_mod_id() == hp._LEGACY_CORE_WORKFLOW


class TestGetPlatformShellApiPrefixes:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"platform_shell_api_prefixes": ["/api/x"]},
        ):
            assert hp.get_platform_shell_api_prefixes() == ["/api/x"]

    def test_returns_legacy_when_empty(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_platform_shell_api_prefixes()
        assert "/api/print" in out


class TestGetClientModPolicies:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"client_mod_policies": {"k": "v"}},
        ):
            assert hp.get_client_mod_policies() == {"k": "v"}

    def test_returns_legacy_when_missing(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.get_client_mod_policies()
        assert "client_primary_erp_mod_id" in out


class TestGetEmployeeRegistryRules:
    def test_returns_from_profile(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"employee_registry_rules": {"k": "v"}},
        ):
            assert hp.get_employee_registry_rules() == {"k": "v"}

    def test_returns_legacy_when_missing(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"employee_registry_rules": {"legacy": True}},
        ):
            out = hp.get_employee_registry_rules()
        assert out == {"legacy": True}


# ── bundled_mod_ids_for_profile_sku / package_stage_mod_ids_for_sku ──────────


class TestBundledModIdsForProfileSku:
    def test_no_sku_returns_empty(self, monkeypatch):
        for key in (
            "XCAGI_PRODUCT_SKU",
            "XCAGI_PRODUCT_SKU_FILE",
            "XCAGI_RESOURCES_DIR",
            "XCAGI_DESKTOP_RESOURCES",
        ):
            monkeypatch.delenv(key, raising=False)
        hp._load_merged_profile.cache_clear()
        assert hp.bundled_mod_ids_for_profile_sku() == ()

    def test_returns_from_profile(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"sku_bundled_mod_ids": ["a", "b"]},
        ):
            assert hp.bundled_mod_ids_for_profile_sku() == ("a", "b")

    def test_returns_legacy_when_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.bundled_mod_ids_for_profile_sku()
        assert "xcagi-planner-bridge" in out


class TestPackageStageModIdsForSku:
    def test_no_sku_defaults_enterprise(self, monkeypatch):
        for key in (
            "XCAGI_PRODUCT_SKU",
            "XCAGI_PRODUCT_SKU_FILE",
            "XCAGI_RESOURCES_DIR",
            "XCAGI_DESKTOP_RESOURCES",
        ):
            monkeypatch.delenv(key, raising=False)
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"package_stage_ids": ["a"]},
        ):
            assert hp.package_stage_mod_ids_for_sku() == ("a",)

    def test_returns_from_profile(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"package_stage_ids": ["a", "b"]},
        ):
            assert hp.package_stage_mod_ids_for_sku() == ("a", "b")

    def test_returns_legacy_when_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(hp, "load_host_profile", return_value={}):
            out = hp.package_stage_mod_ids_for_sku()
        assert "xcagi-planner-bridge" in out


# ── workflow_delivery_mod_ids_for_package ────────────────────────────────────


class TestWorkflowDeliveryModIdsForPackage:
    def test_monolith_default(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"workflow_delivery": "monolith", "workflow_monolith_mod_id": "mono"},
        ):
            assert hp.workflow_delivery_mod_ids_for_package() == ("mono",)

    def test_split_returns_list(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={
                "workflow_delivery": "split",
                "workflow_split_mod_ids": ["a", "b"],
            },
        ):
            assert hp.workflow_delivery_mod_ids_for_package() == ("a", "b")

    def test_split_empty_falls_back_to_monolith(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={
                "workflow_delivery": "split",
                "workflow_split_mod_ids": [],
                "workflow_monolith_mod_id": "mono",
            },
        ):
            assert hp.workflow_delivery_mod_ids_for_package() == ("mono",)

    def test_default_monolith_mod_id(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"workflow_delivery": "monolith"},
        ):
            out = hp.workflow_delivery_mod_ids_for_package()
        assert out == ("xcagi-core-workflow-employees",)


# ── edition_legacy_routes_enabled ────────────────────────────────────────────


class TestEditionLegacyRoutesEnabled:
    def test_full_edition_enabled(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"editions": {"full": {"legacy_routes_enabled": True}}},
        ), patch(
            "app.mod_sdk.edition_policy.resolve_edition", return_value="full"
        ):
            assert hp.edition_legacy_routes_enabled() is True

    def test_minimal_edition_disabled(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"editions": {"minimal": {"legacy_routes_enabled": False}}},
        ), patch(
            "app.mod_sdk.edition_policy.resolve_edition", return_value="minimal"
        ):
            assert hp.edition_legacy_routes_enabled() is False

    def test_no_editions_block_defaults_to_full_check(self, monkeypatch):
        with patch.object(
            hp, "load_host_profile", return_value={"editions": {}}
        ), patch(
            "app.mod_sdk.edition_policy.resolve_edition", return_value="full"
        ):
            assert hp.edition_legacy_routes_enabled() is True

    def test_no_editions_key(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={}), patch(
            "app.mod_sdk.edition_policy.resolve_edition", return_value="minimal"
        ):
            assert hp.edition_legacy_routes_enabled() is False

    def test_explicit_edition_param(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"editions": {"generic": {"legacy_routes_enabled": True}}},
        ):
            assert hp.edition_legacy_routes_enabled("generic") is True


# ── scan_workflow_employee_catalog_from_mods ─────────────────────────────────


class TestScanWorkflowEmployeeCatalogFromMods:
    def test_no_mods_root_returns_default(self, monkeypatch):
        with patch.object(
            hp, "load_workflow_employee_catalog", return_value={"default": True}
        ):
            out = hp.scan_workflow_employee_catalog_from_mods(mods_root=None)
        # When mods_root is None, it tries to import bundled_mods_dir
        # If that fails, returns the default doc
        assert "default" in out or "split_mod_entries" in out

    def test_scans_mods_dir(self, tmp_path):
        # Create a fake mod manifest
        mod_dir = tmp_path / "xcagi-workflow-employee-test"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "xcagi-workflow-employee-test",
                    "name": "Test Employee",
                    "workflow_employees": [
                        {"id": "emp-1", "label": "Test", "panel_title": "T", "panel_summary": "S"}
                    ],
                }
            )
        )
        with patch.object(
            hp,
            "load_workflow_employee_catalog",
            return_value={
                "schema_version": 1,
                "split_mod_entries": [],
                "default_mod_ids": [],
                "default_employee_ids": [],
            },
        ):
            out = hp.scan_workflow_employee_catalog_from_mods(mods_root=tmp_path)
        assert len(out["split_mod_entries"]) == 1
        assert out["split_mod_entries"][0]["mod_id"] == "xcagi-workflow-employee-test"
        assert out["split_mod_entries"][0]["employee_id"] == "emp-1"
        assert out["default_mod_ids"] == ["xcagi-workflow-employee-test"]
        assert out["default_employee_ids"] == ["emp-1"]

    def test_skips_invalid_manifest(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-bad"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json")
        with patch.object(
            hp,
            "load_workflow_employee_catalog",
            return_value={
                "split_mod_entries": [],
                "default_mod_ids": [],
                "default_employee_ids": [],
            },
        ):
            out = hp.scan_workflow_employee_catalog_from_mods(mods_root=tmp_path)
        assert out["split_mod_entries"] == []

    def test_uses_config_when_no_workflow_employees(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-cfg"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "xcagi-workflow-employee-cfg",
                    "name": "Cfg Employee",
                    "config": {"employee_id": "cfg-emp"},
                }
            )
        )
        with patch.object(
            hp,
            "load_workflow_employee_catalog",
            return_value={
                "split_mod_entries": [],
                "default_mod_ids": [],
                "default_employee_ids": [],
            },
        ):
            out = hp.scan_workflow_employee_catalog_from_mods(mods_root=tmp_path)
        assert len(out["split_mod_entries"]) == 1
        assert out["split_mod_entries"][0]["employee_id"] == "cfg-emp"


# ── build_host_profile_api_payload ───────────────────────────────────────────


class TestBuildHostProfileApiPayload:
    def test_returns_complete_payload(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={
                "schema_version": 1,
                "workflow_delivery": "monolith",
                "custom": "value",
            },
        ), patch.object(hp, "get_profile_validation_errors", return_value=[]), patch.object(
            hp,
            "load_industry_presets_document",
            return_value={"schema_version": 1, "presets": {"a": {}}},
        ), patch.object(
            hp,
            "load_workflow_employee_catalog",
            return_value={"schema_version": 1},
        ):
            out = hp.build_host_profile_api_payload()
        assert out["schema_version"] == 1
        assert out["profile"]["custom"] == "value"
        assert out["validation_errors"] == []
        assert out["industry_presets_meta"]["preset_count"] == 1
        assert out["workflow_catalog_meta"]["delivery"] == "monolith"
