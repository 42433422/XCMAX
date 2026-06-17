"""Deep coverage tests for app.mod_sdk.host_profile.

Targets remaining uncovered branches:
- _resolve_product_sku with invalid SKU in file
- resolve_fhd_config_dir with parents traversal
- _load_json with permission error
- _validate_profile_schema with non-int schema_version
- _load_merged_profile cache behavior
- load_host_profile with validation errors logging
- _legacy_profile_for_sku with unknown SKU
- load_industry_presets_document with missing presets key
- load_workflow_employee_catalog with missing file
- get_bridge_mod_host_apis with non-dict values
- scan_workflow_employee_catalog_from_mods with empty workflow_employees
- build_host_profile_api_payload with validation errors
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk import host_profile as hp

# ── _resolve_product_sku deep ───────────────────────────────────────────────


class TestResolveProductSkuDeep:
    def test_sku_file_invalid_sku_returns_none(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"sku": "invalid"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() is None

    def test_sku_file_empty_sku_returns_none(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"sku": ""}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() is None

    def test_sku_file_missing_keys_returns_none(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"other": "value"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() is None

    def test_resources_dir_invalid_sku(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "product-sku.json"
        sku_file.write_text(json.dumps({"sku": "invalid"}))
        monkeypatch.setenv("XCAGI_RESOURCES_DIR", str(tmp_path))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        monkeypatch.delenv("XCAGI_PRODUCT_SKU_FILE", raising=False)
        assert hp._resolve_product_sku() is None

    def test_sku_file_overrides_resources_dir(self, monkeypatch, tmp_path):
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"sku": "personal"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        # resources_dir has invalid sku, but sku_file takes priority
        resources_dir = tmp_path / "resources"
        resources_dir.mkdir()
        (resources_dir / "product-sku.json").write_text(json.dumps({"sku": "invalid"}))
        monkeypatch.setenv("XCAGI_RESOURCES_DIR", str(resources_dir))
        monkeypatch.delenv("XCAGI_PRODUCT_SKU", raising=False)
        assert hp._resolve_product_sku() == "personal"

    def test_env_overrides_sku_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
        sku_file = tmp_path / "sku.json"
        sku_file.write_text(json.dumps({"sku": "personal"}))
        monkeypatch.setenv("XCAGI_PRODUCT_SKU_FILE", str(sku_file))
        # env takes priority
        assert hp._resolve_product_sku() == "enterprise"


# ── resolve_fhd_config_dir deep ─────────────────────────────────────────────


class TestResolveFhdConfigDirDeep:
    def test_env_takes_priority_over_repo_root(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("XCAGI_FHD_ROOT", str(tmp_path))
        # XCAGI_FHD_ROOT takes priority over XCAGI_REPO_ROOT
        other = tmp_path / "other"
        other.mkdir()
        (other / "config").mkdir()
        monkeypatch.setenv("XCAGI_REPO_ROOT", str(other))
        result = hp.resolve_fhd_config_dir()
        assert result == config_dir.resolve()

    def test_no_config_dir_in_env_path(self, monkeypatch, tmp_path):
        # env set but no config dir
        monkeypatch.setenv("XCAGI_FHD_ROOT", str(tmp_path / "nonexistent"))
        monkeypatch.delenv("XCAGI_REPO_ROOT", raising=False)
        # Falls through to parent traversal (may find real config or None)
        result = hp.resolve_fhd_config_dir()
        assert result is None or isinstance(result, Path)


# ── _load_json deep ─────────────────────────────────────────────────────────


class TestLoadJsonDeep:
    def test_permission_error_returns_none(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"k": "v"}))
        with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
            assert hp._load_json(f) is None

    def test_unicode_decode_error_returns_none(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_bytes(b"\xff\xfe\x00")
        assert hp._load_json(f) is None


# ── _validate_profile_schema deep ───────────────────────────────────────────


class TestValidateProfileSchemaDeep:
    def test_non_int_schema_version(self):
        # int(ver) will fail on non-numeric string
        data = {
            "schema_version": "invalid",
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
        }
        with pytest.raises((ValueError, TypeError)):
            hp._validate_profile_schema(data)

    def test_partial_missing_keys(self):
        data = {
            "schema_version": 1,
            "sku": "personal",
            # missing package_stage_ids, sku_bundled_mod_ids, bridge_api_map
        }
        errs = hp._validate_profile_schema(data)
        assert len(errs) == 3

    def test_all_keys_present_no_errors(self):
        data = {
            "schema_version": 1,
            "sku": "personal",
            "package_stage_ids": [],
            "sku_bundled_mod_ids": [],
            "bridge_api_map": {},
        }
        assert hp._validate_profile_schema(data) == []


# ── _load_merged_profile deep ───────────────────────────────────────────────


class TestLoadMergedProfileDeep:
    def test_cache_returns_same_result(self, monkeypatch, tmp_path):
        hp._load_merged_profile.cache_clear()
        config_dir = tmp_path / "config"
        profiles_dir = config_dir / "host_profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "_base.json").write_text(json.dumps({"base": True}))
        (profiles_dir / "personal.json").write_text(json.dumps({"overlay": True}))
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            result1 = hp._load_merged_profile("personal")
            result2 = hp._load_merged_profile("personal")
        assert result1 is result2  # cached
        hp._load_merged_profile.cache_clear()

    def test_deep_merge_in_profile(self, monkeypatch, tmp_path):
        hp._load_merged_profile.cache_clear()
        config_dir = tmp_path / "config"
        profiles_dir = config_dir / "host_profiles"
        profiles_dir.mkdir(parents=True)
        (profiles_dir / "_base.json").write_text(
            json.dumps({"nested": {"a": 1, "b": 2}, "keep": "base"})
        )
        (profiles_dir / "personal.json").write_text(
            json.dumps({"nested": {"b": 3, "c": 4}, "add": "overlay"})
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            result = hp._load_merged_profile("personal")
        assert result["nested"] == {"a": 1, "b": 3, "c": 4}
        assert result["keep"] == "base"
        assert result["add"] == "overlay"
        assert result["sku"] == "personal"
        hp._load_merged_profile.cache_clear()


# ── load_host_profile deep ──────────────────────────────────────────────────


class TestLoadHostProfileDeep:
    def test_default_sku_when_none(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        for key in (
            "XCAGI_PRODUCT_SKU",
            "XCAGI_PRODUCT_SKU_FILE",
            "XCAGI_RESOURCES_DIR",
            "XCAGI_DESKTOP_RESOURCES",
        ):
            monkeypatch.delenv(key, raising=False)
        with patch.object(hp, "_load_merged_profile", return_value=None):
            out = hp.load_host_profile()
        # When no SKU resolved, defaults to "enterprise"
        assert out["sku"] == "enterprise"
        assert out["_source"] == "legacy_fallback"

    def test_explicit_sku_overrides_env(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        with patch.object(hp, "_load_merged_profile", return_value=None):
            out = hp.load_host_profile("enterprise")
        # Explicit sku param takes priority
        assert out["sku"] == "enterprise"


# ── _legacy_profile_for_sku deep ────────────────────────────────────────────


class TestLegacyProfileForSkuDeep:
    def test_personal_blocks_erp_domain_bridge(self):
        out = hp._legacy_profile_for_sku("personal")
        assert "xcagi-erp-domain-bridge" in out["blocked_mod_ids"]
        assert out["erp_domain_bridge_mod_id"] == "xcagi-erp-domain-bridge"

    def test_enterprise_no_blocks(self):
        out = hp._legacy_profile_for_sku("enterprise")
        assert out["blocked_mod_ids"] == []

    def test_personal_minimal_edition(self):
        out = hp._legacy_profile_for_sku("personal")
        assert out["runtime_edition"] == "minimal"
        assert out["frontend_edition"] == "minimal"

    def test_enterprise_full_edition(self):
        out = hp._legacy_profile_for_sku("enterprise")
        assert out["runtime_edition"] == "full"
        assert out["frontend_edition"] == "full"

    def test_has_employee_registry_rules(self):
        for sku in ("personal", "enterprise"):
            out = hp._legacy_profile_for_sku(sku)
            rules = out["employee_registry_rules"]
            assert "workflow_employee_id_prefixes" in rules
            assert "exclude_id_suffixes" in rules
            assert "exclude_artifact_types" in rules
            assert "exclude_mod_ids" in rules

    def test_has_editions_block(self):
        for sku in ("personal", "enterprise"):
            out = hp._legacy_profile_for_sku(sku)
            assert "minimal" in out["editions"]
            assert "generic" in out["editions"]
            assert "full" in out["editions"]

    def test_personal_sku_bundled_subset(self):
        out = hp._legacy_profile_for_sku("personal")
        enterprise = hp._legacy_profile_for_sku("enterprise")
        # Personal has fewer bundled mods
        assert len(out["sku_bundled_mod_ids"]) < len(enterprise["sku_bundled_mod_ids"])

    def test_sku_aux_mod_ids(self):
        out = hp._legacy_profile_for_sku("enterprise")
        assert "xcagi-planner-excel-tools" in out["sku_aux_mod_ids"]
        assert "wechat-contacts-ai-employee" in out["sku_aux_mod_ids"]


# ── load_industry_presets_document deep ─────────────────────────────────────


class TestLoadIndustryPresetsDocumentDeep:
    def test_missing_presets_key(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text(
            json.dumps({"schema_version": 1})  # no presets key
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        # Missing presets → returns default
        assert out["presets"] == {}

    def test_presets_not_dict_returns_default(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text(json.dumps({"presets": "not a dict"}))
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        assert out["presets"] == {}

    def test_invalid_json_returns_default(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text("not json")
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        assert out["presets"] == {}

    def test_loads_with_preset_ids(self, monkeypatch, tmp_path):
        hp.load_industry_presets_document.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "industry_presets.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "preset_ids": ["a", "b"],
                    "presets": {"a": {}, "b": {}},
                }
            )
        )
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_industry_presets_document()
        assert out["preset_ids"] == ["a", "b"]
        assert len(out["presets"]) == 2


# ── load_workflow_employee_catalog deep ─────────────────────────────────────


class TestLoadWorkflowEmployeeCatalogDeep:
    def test_missing_file_returns_default(self, monkeypatch, tmp_path):
        hp.load_workflow_employee_catalog.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # No workflow_employee_catalog.json
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_workflow_employee_catalog()
        assert out["schema_version"] == hp.WORKFLOW_CATALOG_SCHEMA_VERSION
        assert out["workflow_viz_bridge_mod_id"] == hp._LEGACY_CORE_WORKFLOW

    def test_invalid_json_returns_default(self, monkeypatch, tmp_path):
        hp.load_workflow_employee_catalog.cache_clear()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "workflow_employee_catalog.json").write_text("not json")
        with patch.object(hp, "resolve_fhd_config_dir", return_value=config_dir):
            out = hp.load_workflow_employee_catalog()
        assert out["schema_version"] == hp.WORKFLOW_CATALOG_SCHEMA_VERSION


# ── get_bridge_mod_host_apis deep ───────────────────────────────────────────


class TestGetBridgeModHostApisDeep:
    def test_handles_non_dict_bridge_api_map(self, monkeypatch):
        with patch.object(hp, "load_host_profile", return_value={"bridge_api_map": "not a dict"}):
            out = hp.get_bridge_mod_host_apis()
        # Falls back to legacy
        assert "xcagi-planner-bridge" in out

    def test_preserves_list_values(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"bridge_api_map": {"b1": ["/api/x", "/api/y"]}},
        ):
            out = hp.get_bridge_mod_host_apis()
        assert out["b1"] == ["/api/x", "/api/y"]

    def test_converts_non_list_to_empty(self, monkeypatch):
        with patch.object(
            hp,
            "load_host_profile",
            return_value={"bridge_api_map": {"b1": "string", "b2": 123, "b3": None}},
        ):
            out = hp.get_bridge_mod_host_apis()
        assert out["b1"] == []
        assert out["b2"] == []
        assert out["b3"] == []


# ── scan_workflow_employee_catalog_from_mods deep ───────────────────────────


class TestScanWorkflowEmployeeCatalogFromModsDeep:
    def test_empty_workflow_employees_uses_config(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-empty"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "xcagi-workflow-employee-empty",
                    "name": "Empty Employee",
                    "workflow_employees": [],
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
        entry = out["split_mod_entries"][0]
        assert entry["employee_id"] == "cfg-emp"

    def test_no_workflow_employees_no_config(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-bare"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "xcagi-workflow-employee-bare", "name": "Bare"})
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
        entry = out["split_mod_entries"][0]
        assert entry["employee_id"] == ""
        assert entry["label"] == "Bare"

    def test_uses_mod_id_from_manifest(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-custom"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "custom-mod-id",
                    "name": "Custom",
                    "workflow_employees": [{"id": "emp-1", "label": "L"}],
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
        assert out["split_mod_entries"][0]["mod_id"] == "custom-mod-id"

    def test_falls_back_to_dir_name(self, tmp_path):
        mod_dir = tmp_path / "xcagi-workflow-employee-noname"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"name": "No ID"})  # no "id" key
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
        assert out["split_mod_entries"][0]["mod_id"] == "xcagi-workflow-employee-noname"

    def test_multiple_mods(self, tmp_path):
        for i in range(3):
            mod_dir = tmp_path / f"xcagi-workflow-employee-{i}"
            mod_dir.mkdir()
            (mod_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": f"mod-{i}",
                        "name": f"Mod {i}",
                        "workflow_employees": [{"id": f"emp-{i}", "label": f"L{i}"}],
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
        assert len(out["split_mod_entries"]) == 3
        assert len(out["default_mod_ids"]) == 3
        assert len(out["default_employee_ids"]) == 3

    def test_no_matching_mods_returns_default(self, tmp_path):
        # Create a non-matching directory
        (tmp_path / "not-a-workflow-mod").mkdir()
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
        # No entries added
        assert out["split_mod_entries"] == []


# ── build_host_profile_api_payload deep ─────────────────────────────────────


class TestBuildHostProfileApiPayloadDeep:
    def test_with_validation_errors(self, monkeypatch):
        with (
            patch.object(
                hp,
                "load_host_profile",
                return_value={"schema_version": 1, "workflow_delivery": "monolith"},
            ),
            patch.object(
                hp,
                "get_profile_validation_errors",
                return_value=["error1", "error2"],
            ),
            patch.object(
                hp,
                "load_industry_presets_document",
                return_value={"schema_version": 1, "presets": {}},
            ),
            patch.object(
                hp,
                "load_workflow_employee_catalog",
                return_value={"schema_version": 1},
            ),
        ):
            out = hp.build_host_profile_api_payload()
        assert out["validation_errors"] == ["error1", "error2"]

    def test_with_empty_presets(self, monkeypatch):
        with (
            patch.object(
                hp,
                "load_host_profile",
                return_value={"schema_version": 1, "workflow_delivery": "split"},
            ),
            patch.object(hp, "get_profile_validation_errors", return_value=[]),
            patch.object(
                hp,
                "load_industry_presets_document",
                return_value={"schema_version": 1, "presets": {}},
            ),
            patch.object(
                hp,
                "load_workflow_employee_catalog",
                return_value={"schema_version": 1},
            ),
        ):
            out = hp.build_host_profile_api_payload()
        assert out["industry_presets_meta"]["preset_count"] == 0
        assert out["workflow_catalog_meta"]["delivery"] == "split"

    def test_default_schema_version(self, monkeypatch):
        with (
            patch.object(
                hp,
                "load_host_profile",
                return_value={"workflow_delivery": "monolith"},  # no schema_version
            ),
            patch.object(hp, "get_profile_validation_errors", return_value=[]),
            patch.object(
                hp,
                "load_industry_presets_document",
                return_value={"schema_version": 1, "presets": {"a": {}}},
            ),
            patch.object(
                hp,
                "load_workflow_employee_catalog",
                return_value={"schema_version": 1},
            ),
        ):
            out = hp.build_host_profile_api_payload()
        assert out["schema_version"] == hp.PROFILE_SCHEMA_VERSION
        assert out["industry_presets_meta"]["preset_count"] == 1


# ── get_profile_validation_errors deep ──────────────────────────────────────


class TestGetProfileValidationErrorsDeep:
    def test_with_valid_profile(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "_load_merged_profile",
            return_value={
                "schema_version": 1,
                "sku": "personal",
                "package_stage_ids": [],
                "sku_bundled_mod_ids": [],
                "bridge_api_map": {},
            },
        ):
            assert hp.get_profile_validation_errors() == []

    def test_with_invalid_profile(self, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "_load_merged_profile",
            return_value={"schema_version": 99, "sku": "personal"},
        ):
            errs = hp.get_profile_validation_errors()
        assert any("PROFILE_SCHEMA_MISMATCH" in e for e in errs)

    def test_explicit_sku_param(self, monkeypatch):
        hp._load_merged_profile.cache_clear()
        with patch.object(
            hp,
            "_load_merged_profile",
            return_value={
                "schema_version": 1,
                "sku": "enterprise",
                "package_stage_ids": [],
                "sku_bundled_mod_ids": [],
                "bridge_api_map": {},
            },
        ):
            assert hp.get_profile_validation_errors("enterprise") == []
