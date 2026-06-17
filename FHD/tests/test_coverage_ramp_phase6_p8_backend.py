"""COVERAGE_RAMP Phase 6 round 8: backend low-coverage modules.

Targets:
- ``app/mod_sdk/industry_baseline.py`` (72.1% line coverage, ~80 lines uncovered)
- ``app/services/skills/label_template_generator/label_template_generator.py``
  (77.7% line coverage, ~80 lines uncovered)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (filesystem,
mod manager, OCR service, PIL Image). The functions under test are exercised
directly without mocking their internals.

Coverage scenarios (铁律3):
- Happy path (normal input)
- Empty / None inputs
- Boundary values (empty list, empty dict, 0, -1)
- Exception paths (RECOVERABLE_ERRORS, file IO errors, ImportError)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mod_sdk import industry_baseline
from app.mod_sdk.industry_baseline import (
    _custom_employee_extension_ids,
    _custom_line_spec,
    _dedupe,
    _industry_mod_ids_for,
    _industry_package,
    _industry_row,
    _installed_mod_ids,
    _label_for_custom_mod,
    _label_for_mod,
    _load_json,
    _mod_installed,
    _onboarding_package_row,
    _read_mod_manifest_json,
    build_industry_baseline_plan,
    build_onboarding_industry_catalog,
    filter_onboarding_catalog_for_entitlements,
    industry_entitled_for_client_mods,
    load_industry_baseline_document,
)
from app.services.skills.label_template_generator.label_template_generator import (
    LabelTemplateGeneratorSkill,
    _analyze_colors,
    _classify_field,
    _estimate_font_sizes,
    _estimate_sections,
    _extract_fields_by_pattern,
    _identify_fields,
    _pair_fields_by_grid,
    analyze_image,
    extract_text_with_ocr,
    generate_template_code,
    get_label_template_generator_skill,
)

# ---------------------------------------------------------------------------
# Fixtures — clear lru_cache before/after each test to ensure independence
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_industry_baseline_caches() -> None:
    """Clear lru_caches so each test sees its own mocked config dir."""
    load_industry_baseline_document.cache_clear()
    yield
    load_industry_baseline_document.cache_clear()


# ---------------------------------------------------------------------------
# industry_baseline._load_json
# ---------------------------------------------------------------------------


class TestLoadJson:
    """Cover _load_json happy/empty/error paths."""

    def test_load_json_valid_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "a.json"
        p.write_text('{"k": 1}', encoding="utf-8")
        assert _load_json(p) == {"k": 1}

    def test_load_json_missing_file_returns_none(self, tmp_path: Path) -> None:
        # FileNotFoundError is a subclass of OSError → RECOVERABLE_ERRORS
        assert _load_json(tmp_path / "missing.json") is None

    def test_load_json_invalid_json_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json{", encoding="utf-8")
        # json.JSONDecodeError is a subclass of ValueError → RECOVERABLE_ERRORS
        assert _load_json(p) is None

    def test_load_json_read_error_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "perm.json"
        p.write_text("{}", encoding="utf-8")
        # Simulate OSError during read_text
        with patch.object(Path, "read_text", side_effect=OSError("io")):
            assert _load_json(p) is None


# ---------------------------------------------------------------------------
# industry_baseline._dedupe
# ---------------------------------------------------------------------------


class TestDedupe:
    """Cover _dedupe edge cases."""

    def test_empty_list_returns_empty(self) -> None:
        assert _dedupe([]) == []

    def test_strips_whitespace_and_skips_empty(self) -> None:
        assert _dedupe(["  a  ", "", "  ", "b"]) == ["a", "b"]

    def test_preserves_order_first_occurrence(self) -> None:
        assert _dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_handles_non_string_items_via_str_coercion(self) -> None:
        # None is falsy → becomes "" via `raw or ""` → filtered out
        assert _dedupe(["x", None, "x"]) == ["x"]
        # Non-string truthy items are coerced via str()
        assert _dedupe([1, 2, 1]) == ["1", "2"]


# ---------------------------------------------------------------------------
# industry_baseline.load_industry_baseline_document
# ---------------------------------------------------------------------------


class TestLoadIndustryBaselineDocument:
    """Cover fallback path and doc-loading branches."""

    def test_no_config_dir_returns_default(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            doc = load_industry_baseline_document()
        assert doc["schema_version"] == 1
        assert "通用" in doc["industries"]
        assert doc["core_mod_ids"] == ["xcagi-planner-bridge", "xcagi-neuro-bus-bridge"]

    def test_config_dir_with_valid_doc(self, tmp_path: Path) -> None:
        (tmp_path / "industry_baseline.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {"core-1": "Core"},
                    "industries": {"涂料": {"host_mod_ids": ["h1"]}},
                }
            ),
            encoding="utf-8",
        )
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=tmp_path,
        ):
            doc = load_industry_baseline_document()
        assert doc["schema_version"] == 2
        assert "涂料" in doc["industries"]

    def test_config_dir_doc_not_dict_falls_back(self, tmp_path: Path) -> None:
        # industries is a list, not dict → falls back to default
        (tmp_path / "industry_baseline.json").write_text(
            json.dumps({"industries": [1, 2, 3]}),
            encoding="utf-8",
        )
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=tmp_path,
        ):
            doc = load_industry_baseline_document()
        assert "通用" in doc["industries"]


# ---------------------------------------------------------------------------
# industry_baseline._installed_mod_ids
# ---------------------------------------------------------------------------


class TestInstalledModIds:
    """Cover _installed_mod_ids branches."""

    def test_no_mod_manager_returns_empty(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("no mod manager"),
        ):
            assert _installed_mod_ids() == []

    def test_mod_manager_runtime_error_returns_empty(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ):
            assert _installed_mod_ids() == []

    def test_mod_manager_empty_lists_returns_empty(self) -> None:
        mm = MagicMock()
        mm.list_loaded_mods.return_value = []
        mm.scan_mods.return_value = []
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _installed_mod_ids() == []

    def test_mod_manager_with_mods_dedupes(self) -> None:
        mm = MagicMock()
        mm.list_loaded_mods.return_value = [
            SimpleNamespace(id="a"),
            SimpleNamespace(id="b"),
        ]
        mm.scan_mods.return_value = [SimpleNamespace(id="a"), SimpleNamespace(id="c")]
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            result = _installed_mod_ids()
        assert result == ["a", "c", "b"]

    def test_mod_manager_filters_none_ids(self) -> None:
        mm = MagicMock()
        mm.list_loaded_mods.return_value = [
            SimpleNamespace(id=None),
            SimpleNamespace(id="x"),
        ]
        mm.scan_mods.return_value = []
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _installed_mod_ids() == ["x"]


# ---------------------------------------------------------------------------
# industry_baseline._industry_row / _industry_package
# ---------------------------------------------------------------------------


class TestIndustryRowAndPackage:
    """Cover fallbacks for missing industry ids."""

    def test_industry_row_empty_id_returns_default(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            row = _industry_row("")
        assert row == {"host_mod_ids": [], "optional_host_mod_ids": [], "industry_mod_ids": []}

    def test_industry_row_none_id_returns_default(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            row = _industry_row(None)  # type: ignore[arg-type]
        assert isinstance(row, dict)

    def test_industry_row_unknown_id_falls_back_to_default(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            row = _industry_row("不存在的行业")
        assert "host_mod_ids" in row

    def test_industry_package_empty_id_returns_empty_dict(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            assert _industry_package("") == {}

    def test_industry_package_unknown_id_returns_empty_dict(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline.resolve_fhd_config_dir",
            return_value=None,
        ):
            assert _industry_package("unknown") == {}


# ---------------------------------------------------------------------------
# industry_baseline._industry_mod_ids_for
# ---------------------------------------------------------------------------


class TestIndustryModIdsFor:
    """Cover _industry_mod_ids_for branches."""

    def test_with_package_mod_id(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={"industry_packages": {"涂料": {"mod_id": "coating-mod"}}},
            ),
            patch(
                "app.mod_sdk.industry_baseline._industry_package",
                return_value={"mod_id": "coating-mod"},
            ),
        ):
            result = _industry_mod_ids_for("涂料", {"industry_mod_ids": ["x"]})
        assert result == ["coating-mod"]

    def test_without_package_mod_id_uses_row(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={},
        ):
            result = _industry_mod_ids_for("通用", {"industry_mod_ids": ["a", "b", "a"]})
        assert result == ["a", "b"]

    def test_empty_row_returns_empty(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={},
        ):
            assert _industry_mod_ids_for("通用", {}) == []


# ---------------------------------------------------------------------------
# industry_baseline._label_for_mod / _label_for_custom_mod
# ---------------------------------------------------------------------------


class TestLabelForMod:
    """Cover label resolution branches."""

    def test_label_for_mod_with_package_product_name(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={"mod_id": "m1", "product_name": "涂料包"},
        ):
            assert _label_for_mod("m1", "涂料", {}) == "涂料包"

    def test_label_for_mod_with_empty_product_name_falls_back(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={"mod_id": "m1", "product_name": "  "},
        ):
            assert _label_for_mod("m1", "涂料", {"m1": "标签"}) == "标签"

    def test_label_for_mod_no_package_match_uses_labels(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={"mod_id": "other"},
        ):
            assert _label_for_mod("m1", "通用", {"m1": "MyLabel"}) == "MyLabel"

    def test_label_for_mod_no_match_returns_mod_id(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={},
        ):
            assert _label_for_mod("m1", "通用", {}) == "m1"


class TestLabelForCustomMod:
    """Cover _label_for_custom_mod branches."""

    def test_label_resolved_from_labels(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={},
        ):
            assert _label_for_custom_mod("m1", "通用", {"m1": "CustomLabel"}) == "CustomLabel"

    def test_label_falls_back_to_manifest_name(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={"name": "ManifestName"},
        ):
            assert _label_for_custom_mod("m1", "通用", {}) == "ManifestName"

    def test_label_falls_back_to_mod_id_when_no_name(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={"name": ""},
        ):
            assert _label_for_custom_mod("m1", "通用", {}) == "m1"


# ---------------------------------------------------------------------------
# industry_baseline._read_mod_manifest_json
# ---------------------------------------------------------------------------


class TestReadModManifestJson:
    """Cover manifest reading edge cases."""

    def test_mod_manager_import_error_returns_empty(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=ImportError("no"),
        ):
            assert _read_mod_manifest_json("m1") == {}

    def test_mod_manager_runtime_error_returns_empty(self) -> None:
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ):
            assert _read_mod_manifest_json("m1") == {}

    def test_no_mod_path_returns_empty(self) -> None:
        mm = MagicMock()
        mm.resolve_mod_directory.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _read_mod_manifest_json("m1") == {}

    def test_manifest_not_a_file_returns_empty(self, tmp_path: Path) -> None:
        mm = MagicMock()
        mm.resolve_mod_directory.return_value = str(tmp_path)
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _read_mod_manifest_json("m1") == {}

    def test_manifest_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
        mm = MagicMock()
        mm.resolve_mod_directory.return_value = str(tmp_path)
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _read_mod_manifest_json("m1") == {}

    def test_manifest_valid_dict_returns_dict(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text(
            json.dumps({"name": "Test", "version": "1.0"}),
            encoding="utf-8",
        )
        mm = MagicMock()
        mm.resolve_mod_directory.return_value = str(tmp_path)
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            data = _read_mod_manifest_json("m1")
        assert data == {"name": "Test", "version": "1.0"}

    def test_manifest_non_dict_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text(
            json.dumps(["not", "a", "dict"]),
            encoding="utf-8",
        )
        mm = MagicMock()
        mm.resolve_mod_directory.return_value = str(tmp_path)
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mm,
        ):
            assert _read_mod_manifest_json("m1") == {}


# ---------------------------------------------------------------------------
# industry_baseline._custom_line_spec
# ---------------------------------------------------------------------------


class TestCustomLineSpec:
    """Cover _custom_line_spec branches."""

    def test_empty_mod_id_returns_default_hint(self) -> None:
        hint, extra = _custom_line_spec("")
        assert "按行业定制 Mod 加载" in hint
        assert extra == []

    def test_none_mod_id_returns_default_hint(self) -> None:
        hint, extra = _custom_line_spec(None)  # type: ignore[arg-type]
        assert "按行业定制 Mod 加载" in hint
        assert extra == []

    def test_manifest_without_onboarding_uses_default_hint(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={"name": "Test"},
        ):
            hint, extra = _custom_line_spec("m1")
        assert "按行业定制 Mod 加载" in hint
        assert extra == []

    def test_manifest_with_onboarding_hint(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={"onboarding": {"custom_line_hint": "定制提示"}},
        ):
            hint, extra = _custom_line_spec("m1")
        assert hint == "定制提示"
        assert extra == []

    def test_manifest_with_onboarding_hint_field(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={"onboarding": {"hint": "通用 hint"}},
        ):
            hint, _ = _custom_line_spec("m1")
        assert hint == "通用 hint"

    def test_manifest_with_custom_mod_ids(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={
                "onboarding": {"custom_line_hint": "h"},
                "custom_mod_ids": ["a", "b", "m1"],  # m1 is the mod itself, filtered out
            },
        ):
            hint, extra = _custom_line_spec("m1")
        assert extra == ["a", "b"]

    def test_manifest_with_dependencies_excluding_xcagi_and_self(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._read_mod_manifest_json",
            return_value={
                "onboarding": {"custom_line_hint": "h"},
                "dependencies": {"xcagi": "1.0", "m1": "1.0", "dep-a": "2.0"},
            },
        ):
            _, extra = _custom_line_spec("m1")
        assert "dep-a" in extra
        assert "xcagi" not in extra
        assert "m1" not in extra


# ---------------------------------------------------------------------------
# industry_baseline._mod_installed
# ---------------------------------------------------------------------------


class TestModInstalled:
    """Cover _mod_installed branches."""

    def test_empty_mod_id_returns_false(self) -> None:
        assert _mod_installed("", set()) is False

    def test_mod_id_in_installed_returns_true(self) -> None:
        assert _mod_installed("m1", {"m1", "m2"}) is True

    def test_canonical_mod_id_in_installed_returns_true(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                return_value="canonical-m1",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=(),
            ),
        ):
            assert _mod_installed("m1", {"canonical-m1"}) is True

    def test_legacy_mod_id_in_installed_returns_true(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                return_value="canonical-m1",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=("legacy-m1",),
            ),
        ):
            assert _mod_installed("m1", {"legacy-m1"}) is True

    def test_no_match_returns_false(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                return_value="canonical-m1",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=("legacy-m1",),
            ),
        ):
            assert _mod_installed("m1", {"other"}) is False

    def test_alias_import_error_returns_false(self) -> None:
        with patch(
            "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
            side_effect=ImportError("no"),
        ):
            assert _mod_installed("m1", {"other"}) is False


# ---------------------------------------------------------------------------
# industry_baseline._custom_employee_extension_ids
# ---------------------------------------------------------------------------


class TestCustomEmployeeExtensionIds:
    """Cover _custom_employee_extension_ids dedupe + merge."""

    def test_empty_doc_and_row_returns_empty(self) -> None:
        assert _custom_employee_extension_ids("通用", {}, {}) == []

    def test_doc_level_only(self) -> None:
        result = _custom_employee_extension_ids(
            "通用",
            {},
            {"custom_employee_extension_mod_ids": ["a", "b"]},
        )
        assert result == ["a", "b"]

    def test_row_level_only(self) -> None:
        result = _custom_employee_extension_ids(
            "通用",
            {"custom_employee_extension_mod_ids": ["x", "y"]},
            {},
        )
        assert result == ["x", "y"]

    def test_doc_and_row_merged_with_dedupe(self) -> None:
        # doc_level first, then row_level; dedupe preserves first occurrence
        result = _custom_employee_extension_ids(
            "通用",
            {"custom_employee_extension_mod_ids": ["x", "a"]},
            {"custom_employee_extension_mod_ids": ["a", "y"]},
        )
        # doc_level = ["a", "y"], row_level = ["x", "a"] → merged = ["a", "y", "x"]
        assert result == ["a", "y", "x"]


# ---------------------------------------------------------------------------
# industry_baseline._onboarding_package_row
# ---------------------------------------------------------------------------


class TestOnboardingPackageRow:
    """Cover _onboarding_package_row branches."""

    def test_empty_industry_id_uses_id_as_name(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={},
        ):
            row = _onboarding_package_row("", selectable=True, presets={})
        assert row["industry_id"] == ""
        assert row["name"] == ""
        assert row["selectable"] is True
        assert row["product_name"] == "行业包"

    def test_with_preset_name_and_scenario(self) -> None:
        with patch(
            "app.mod_sdk.industry_baseline._industry_package",
            return_value={"product_name": "  涂料包  ", "mod_id": "m1"},
        ):
            row = _onboarding_package_row(
                "涂料",
                selectable=False,
                presets={"涂料": {"name": "涂料场景", "scenario": "test"}},
            )
        assert row["name"] == "涂料场景"
        assert row["scenario"] == "test"
        assert row["product_name"] == "涂料包"
        assert row["mod_id"] == "m1"
        assert row["selectable"] is False


# ---------------------------------------------------------------------------
# industry_baseline.industry_entitled_for_client_mods
# ---------------------------------------------------------------------------


class TestIndustryEntitledForClientMods:
    """Cover industry_entitled_for_client_mods branches."""

    def test_empty_industry_id_returns_false(self) -> None:
        assert industry_entitled_for_client_mods("", {"m1"}) is False

    def test_no_canonical_returns_false(self) -> None:
        with patch(
            "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
            return_value="",
        ):
            assert industry_entitled_for_client_mods("未知", {"m1"}) is False

    def test_canonical_in_entitled_returns_true(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
                return_value="coating-industry",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                side_effect=lambda x: x,
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=(),
            ),
        ):
            assert industry_entitled_for_client_mods("涂料", {"coating-industry"}) is True

    def test_legacy_in_entitled_returns_true(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
                return_value="coating-industry",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                side_effect=lambda x: x,
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=("sz-qsm-pro",),
            ),
        ):
            assert industry_entitled_for_client_mods("涂料", {"sz-qsm-pro"}) is True

    def test_no_match_returns_false(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id_for_industry",
                return_value="coating-industry",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                side_effect=lambda x: x,
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=("sz-qsm-pro",),
            ),
        ):
            assert industry_entitled_for_client_mods("涂料", {"other-mod"}) is False


# ---------------------------------------------------------------------------
# industry_baseline.filter_onboarding_catalog_for_entitlements
# ---------------------------------------------------------------------------


class TestFilterOnboardingCatalogForEntitlements:
    """Cover catalog filtering branches."""

    def test_empty_catalog_returns_empty_lists(self) -> None:
        out = filter_onboarding_catalog_for_entitlements({}, set())
        assert out["open_packages"] == []
        assert out["preview_packages"] == []
        assert out["open_industry_ids"] == []

    def test_entitled_pkg_stays_open(self) -> None:
        catalog = {
            "open_packages": [{"industry_id": "涂料"}],
            "preview_packages": [],
        }
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            return_value=True,
        ):
            out = filter_onboarding_catalog_for_entitlements(catalog, {"m1"})
        assert out["open_packages"][0]["selectable"] is True
        assert out["open_industry_ids"] == ["涂料"]

    def test_non_entitled_pkg_demoted_to_preview(self) -> None:
        catalog = {
            "open_packages": [{"industry_id": "涂料"}],
            "preview_packages": [],
        }
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            return_value=False,
        ):
            out = filter_onboarding_catalog_for_entitlements(catalog, set())
        assert out["open_packages"] == []
        assert out["preview_packages"][0]["selectable"] is False

    def test_demoted_pkg_already_in_preview_not_duplicated(self) -> None:
        catalog = {
            "open_packages": [{"industry_id": "涂料"}],
            "preview_packages": [{"industry_id": "涂料"}],
        }
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            return_value=False,
        ):
            out = filter_onboarding_catalog_for_entitlements(catalog, set())
        # Only one entry in preview
        preview_ids = [p["industry_id"] for p in out["preview_packages"]]
        assert preview_ids.count("涂料") == 1

    def test_non_dict_pkg_skipped(self) -> None:
        catalog = {
            "open_packages": ["not-a-dict", {"industry_id": "涂料"}],
            "preview_packages": [],
        }
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            return_value=True,
        ):
            out = filter_onboarding_catalog_for_entitlements(catalog, {"m1"})
        assert len(out["open_packages"]) == 1


# ---------------------------------------------------------------------------
# industry_baseline.build_onboarding_industry_catalog
# ---------------------------------------------------------------------------


class TestBuildOnboardingIndustryCatalog:
    """Cover catalog building branches."""

    def test_with_default_doc(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "onboarding_open_industry_ids": ["通用"],
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {}},
                },
            ),
            patch(
                "app.mod_sdk.host_profile.load_industry_presets_document",
                return_value={"presets": {}, "preset_ids": ["通用", "涂料"]},
            ),
        ):
            catalog = build_onboarding_industry_catalog()
        assert catalog["schema_version"] == 1
        assert "通用" in catalog["open_industry_ids"]
        # preview should include 涂料 (not in open_ids)
        preview_ids = [p["industry_id"] for p in catalog["preview_packages"]]
        assert "涂料" in preview_ids

    def test_presets_load_error_falls_back_to_empty(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "onboarding_open_industry_ids": [],
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {}},
                },
            ),
            patch(
                "app.mod_sdk.host_profile.load_industry_presets_document",
                side_effect=RuntimeError("presets load failed"),
            ),
        ):
            catalog = build_onboarding_industry_catalog()
        assert catalog["open_packages"] == []
        assert catalog["preview_packages"] == []

    def test_presets_not_dict_uses_empty(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "onboarding_open_industry_ids": [],
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {}},
                },
            ),
            patch(
                "app.mod_sdk.host_profile.load_industry_presets_document",
                return_value={"presets": "not a dict"},
            ),
        ):
            catalog = build_onboarding_industry_catalog()
        assert catalog["open_packages"] == []

    def test_preset_ids_not_list_uses_presets_keys(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "onboarding_open_industry_ids": [],
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {}},
                },
            ),
            patch(
                "app.mod_sdk.host_profile.load_industry_presets_document",
                return_value={"presets": {"通用": {}, "涂料": {}}},
            ),
        ):
            catalog = build_onboarding_industry_catalog()
        preview_ids = {p["industry_id"] for p in catalog["preview_packages"]}
        assert "通用" in preview_ids
        assert "涂料" in preview_ids


# ---------------------------------------------------------------------------
# industry_baseline.build_industry_baseline_plan
# ---------------------------------------------------------------------------


class TestBuildIndustryBaselinePlan:
    """Cover build_industry_baseline_plan branches."""

    def test_plan_with_empty_industry_uses_default(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {"core-1": "Core"},
                    "industries": {"通用": {"host_mod_ids": ["h1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("", installed_mod_ids=["core-1", "h1"])
        assert plan["industry_id"] == "通用"
        assert plan["host_baseline_ready"] is True
        # No industry mod → industry_package group not added
        assert all(g["id"] != "industry_package" for g in plan["groups"])

    def test_plan_with_industry_mod_ids_adds_industry_group(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {},
                    "industries": {"涂料": {"host_mod_ids": [], "industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("涂料", installed_mod_ids=[])
        group_ids = [g["id"] for g in plan["groups"]]
        assert "industry_package" in group_ids

    def test_plan_with_account_custom_ids_adds_account_custom_group(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"涂料": {"industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {},
                    "custom_employee_extension_mod_ids": ["emp-1"],
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=["custom-1"],
            ),
        ):
            plan = build_industry_baseline_plan("涂料", installed_mod_ids=[])
        group_ids = [g["id"] for g in plan["groups"]]
        assert "account_custom" in group_ids
        assert "emp-1" in plan["custom_employee_extension_mod_ids"]

    def test_plan_skip_account_custom_gate(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"涂料": {"industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=["custom-1"],
            ),
        ):
            plan = build_industry_baseline_plan(
                "涂料",
                installed_mod_ids=[],
                skip_account_custom_gate=True,
            )
        # skip_account_custom_gate=True → account_custom_ready=True
        assert plan["account_custom_ready"] is True

    def test_plan_with_industry_package_mod_id(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"涂料": {"industry_mod_ids": []}},
                    "industry_packages": {"涂料": {"mod_id": "pkg-1", "product_name": "涂料包"}},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("涂料", installed_mod_ids=[])
        assert plan["industry_package"] == {"mod_id": "pkg-1", "product_name": "涂料包"}

    def test_plan_optional_ids_filtered_against_required(self) -> None:
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {
                        "通用": {
                            "host_mod_ids": ["req-1"],
                            "optional_host_mod_ids": ["req-1", "opt-1"],
                        }
                    },
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        # req-1 should not appear in optional_mod_ids
        assert "req-1" not in plan["optional_mod_ids"]
        assert "opt-1" in plan["optional_mod_ids"]


# ---------------------------------------------------------------------------
# industry_baseline.build_industry_baseline_plan_for_request (async)
# ---------------------------------------------------------------------------


class TestBuildIndustryBaselinePlanForRequest:
    """Cover async request-aware plan builder."""

    @pytest.mark.asyncio
    async def test_no_enterprise_filter_returns_default_plan(self) -> None:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        request = MagicMock()
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=False,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_industry_baseline_plan",
                return_value={"industry_id": "通用"},
            ) as mock_plan,
        ):
            result = await build_industry_baseline_plan_for_request(request, "通用")
        assert result == {"industry_id": "通用"}
        mock_plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_enterprise_filter_no_session_id(self) -> None:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        request = MagicMock()
        request.cookies = {}
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_industry_baseline_plan",
                return_value={"industry_id": "通用"},
            ) as mock_plan,
        ):
            result = await build_industry_baseline_plan_for_request(request, "通用")
        # No sid → no sync, default plan
        assert result == {"industry_id": "通用"}
        # entitled_mod_ids should be None
        _, kwargs = mock_plan.call_args
        assert kwargs.get("entitled_mod_ids") is None

    @pytest.mark.asyncio
    async def test_enterprise_filter_admin_session_skips_gate(self) -> None:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        request = MagicMock()
        request.cookies = {"session_id": "sid-1"}
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={"m1"},
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_industry_baseline_plan",
                return_value={"industry_id": "通用"},
            ) as mock_plan,
        ):
            await build_industry_baseline_plan_for_request(request, "通用")
        _, kwargs = mock_plan.call_args
        assert kwargs.get("skip_account_custom_gate") is True
        assert kwargs.get("entitled_mod_ids") == {"m1"}


# ---------------------------------------------------------------------------
# industry_baseline.build_onboarding_industry_catalog_for_request (async)
# ---------------------------------------------------------------------------


class TestBuildOnboardingIndustryCatalogForRequest:
    """Cover async catalog builder."""

    @pytest.mark.asyncio
    async def test_no_user_returns_catalog_with_meta(self) -> None:
        from app.mod_sdk.industry_baseline import (
            build_onboarding_industry_catalog_for_request,
        )

        request = MagicMock()
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=False,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog",
                return_value={"open_industry_ids": ["通用"]},
            ),
        ):
            result = await build_onboarding_industry_catalog_for_request(request)
        assert result["enterprise_filter_applied"] is False
        assert result["owner_id"] is None
        assert result["selected_industry_id"] is None

    @pytest.mark.asyncio
    async def test_user_with_owner_id_and_selected_industry(self) -> None:
        from app.mod_sdk.industry_baseline import (
            build_onboarding_industry_catalog_for_request,
        )

        request = MagicMock()
        user = SimpleNamespace(id=1)
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=user,
            ),
            patch(
                "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
                return_value=42,
            ),
            patch(
                "app.application.tenant_workspace_prefs.get_workspace_prefs",
                return_value={"selected_industry_id": "涂料"},
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=False,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog",
                return_value={"open_industry_ids": []},
            ),
        ):
            result = await build_onboarding_industry_catalog_for_request(request)
        assert result["owner_id"] == 42
        assert result["selected_industry_id"] == "涂料"

    @pytest.mark.asyncio
    async def test_enterprise_filter_no_session_id(self) -> None:
        from app.mod_sdk.industry_baseline import (
            build_onboarding_industry_catalog_for_request,
        )

        request = MagicMock()
        request.cookies = {}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog",
                return_value={"open_industry_ids": []},
            ),
        ):
            result = await build_onboarding_industry_catalog_for_request(request)
        # No sid → no filter applied
        assert result["enterprise_filter_applied"] is False

    @pytest.mark.asyncio
    async def test_enterprise_filter_admin_session_no_filter(self) -> None:
        from app.mod_sdk.industry_baseline import (
            build_onboarding_industry_catalog_for_request,
        )

        request = MagicMock()
        request.cookies = {"session_id": "sid-1"}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog",
                return_value={"open_industry_ids": []},
            ),
        ):
            result = await build_onboarding_industry_catalog_for_request(request)
        assert result["enterprise_filter_applied"] is True

    @pytest.mark.asyncio
    async def test_enterprise_filter_applies_entitlements(self) -> None:
        from app.mod_sdk.industry_baseline import (
            build_onboarding_industry_catalog_for_request,
        )

        request = MagicMock()
        request.cookies = {"session_id": "sid-1"}
        with (
            patch(
                "app.infrastructure.auth.dependencies.resolve_session_user",
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
            patch(
                "app.enterprise.mod_entitlements.is_admin_account_session",
                return_value=False,
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={"m1"},
            ),
            patch(
                "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog",
                return_value={"open_packages": [], "preview_packages": []},
            ),
            patch(
                "app.mod_sdk.industry_baseline.filter_onboarding_catalog_for_entitlements",
                return_value={"open_packages": [{"industry_id": "x"}], "preview_packages": []},
            ) as mock_filter,
        ):
            result = await build_onboarding_industry_catalog_for_request(request)
        assert result["enterprise_filter_applied"] is True
        mock_filter.assert_called_once()


# ---------------------------------------------------------------------------
# label_template_generator.analyze_image
# ---------------------------------------------------------------------------


class TestAnalyzeImage:
    """Cover analyze_image happy/error paths."""

    def test_file_not_found_returns_failure(self) -> None:
        result = analyze_image("/nonexistent/path/img.png")
        assert result["success"] is False
        assert "文件不存在" in result["message"]

    def test_valid_image_returns_success(self, tmp_path: Path) -> None:
        # Create a small test image
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        result = analyze_image(str(img_path))
        assert result["success"] is True
        assert result["size"]["width"] == 100
        assert result["size"]["height"] == 50

    def test_verbose_mode_adds_additional_info(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        result = analyze_image(str(img_path), verbose=True)
        assert result["success"] is True
        assert "additional_info" in result
        assert "estimated_font_sizes" in result["additional_info"]

    def test_recoverable_error_returns_failure(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        # Force a ValueError (RECOVERABLE_ERRORS) during processing
        with patch("PIL.Image.open", side_effect=ValueError("bad image")):
            result = analyze_image(str(img_path))
        assert result["success"] is False
        assert "分析失败" in result["message"]


# ---------------------------------------------------------------------------
# label_template_generator._analyze_colors
# ---------------------------------------------------------------------------


class TestAnalyzeColors:
    """Cover _analyze_colors branches."""

    def test_consistent_background(self) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 100), color=(255, 255, 255))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is True
        assert result["background"] == "#ffffff"

    def test_inconsistent_background(self) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 100), color=(255, 255, 255))
        # Draw different colors in corners
        img.putpixel((10, 10), (255, 0, 0))
        result = _analyze_colors(img)
        assert result["is_consistent_background"] is False

    def test_convert_failure_returns_default(self) -> None:
        img = MagicMock()
        img.convert.side_effect = RuntimeError("convert failed")
        result = _analyze_colors(img)
        assert result["background"] == "#FFFFFF"
        assert result["is_consistent_background"] is True


# ---------------------------------------------------------------------------
# label_template_generator._estimate_sections
# ---------------------------------------------------------------------------


class TestEstimateSections:
    """Cover _estimate_sections size branches."""

    def test_large_dimensions_returns_5_sections(self) -> None:
        sections = _estimate_sections(800, 500)
        assert len(sections) == 5
        assert sections[0]["name"] == "product_number"

    def test_medium_dimensions_returns_3_sections(self) -> None:
        sections = _estimate_sections(400, 300)
        assert len(sections) == 3
        assert sections[0]["name"] == "header"

    def test_small_dimensions_returns_1_section(self) -> None:
        sections = _estimate_sections(100, 100)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"

    def test_zero_dimensions_returns_main(self) -> None:
        sections = _estimate_sections(0, 0)
        assert len(sections) == 1
        assert sections[0]["name"] == "main"


# ---------------------------------------------------------------------------
# label_template_generator._estimate_font_sizes
# ---------------------------------------------------------------------------


class TestEstimateFontSizes:
    """Cover _estimate_font_sizes branches."""

    def test_large_width(self) -> None:
        result = _estimate_font_sizes(800, 500)
        assert result["title"] == 70
        assert result["label"] == 40

    def test_medium_width(self) -> None:
        result = _estimate_font_sizes(400, 300)
        assert result["title"] == 40
        assert result["label"] == 24

    def test_small_width(self) -> None:
        result = _estimate_font_sizes(100, 100)
        assert result["title"] == 24
        assert result["label"] == 14


# ---------------------------------------------------------------------------
# label_template_generator._classify_field
# ---------------------------------------------------------------------------


class TestClassifyField:
    """Cover _classify_field branches."""

    def test_known_label_returns_fixed_label(self) -> None:
        ftype, key = _classify_field("品名")
        assert ftype == "fixed_label"
        assert key == "product_name"

    def test_label_ending_with_jia_returns_price(self) -> None:
        ftype, key = _classify_field("会员价")
        assert ftype == "fixed_label"
        assert key == "price"

    def test_unknown_label_returns_dynamic(self) -> None:
        ftype, key = _classify_field("自定义字段")
        assert ftype == "dynamic"
        assert key == "自定义字段"


# ---------------------------------------------------------------------------
# label_template_generator._extract_fields_by_pattern
# ---------------------------------------------------------------------------


class TestExtractFieldsByPattern:
    """Cover fallback field extraction."""

    def test_returns_seven_default_fields(self) -> None:
        fields = _extract_fields_by_pattern("/some/path.png")
        assert len(fields) == 7
        labels = [f["label"] for f in fields]
        assert "品名" in labels
        assert "颜色" in labels
        assert all(f["type"] == "fixed_label" for f in fields)


# ---------------------------------------------------------------------------
# label_template_generator._identify_fields
# ---------------------------------------------------------------------------


class TestIdentifyFields:
    """Cover _identify_fields branches."""

    def test_empty_blocks_returns_empty(self) -> None:
        assert _identify_fields([]) == []

    def test_block_with_colon_known_label(self) -> None:
        blocks = [
            {
                "text": "品名：测试产品",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "品名"
        assert fields[0]["value"] == "测试产品"
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "product_name"

    def test_block_with_colon_unknown_label(self) -> None:
        blocks = [
            {
                "text": "自定义：值",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "dynamic"
        assert fields[0]["field_key"] == "自定义"

    def test_block_with_colon_label_ending_jia(self) -> None:
        blocks = [
            {
                "text": "会员价：99",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["type"] == "fixed_label"
        assert fields[0]["field_key"] == "price"

    def test_block_without_colon_known_label_with_value(self) -> None:
        blocks = [
            {
                "text": "产品编号 6808AA",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert len(fields) == 1
        assert fields[0]["label"] == "产品编号"
        assert fields[0]["value"] == "6808AA"

    def test_block_without_colon_known_label_no_value(self) -> None:
        blocks = [
            {
                "text": "产品编号",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        # No value part → no field added
        assert fields == []

    def test_block_without_colon_unknown_label(self) -> None:
        blocks = [
            {
                "text": "完全未知的内容",
                "left": 10,
                "top": 20,
                "width": 100,
                "height": 30,
                "conf": 0.9,
            }
        ]
        fields = _identify_fields(blocks)
        assert fields == []


# ---------------------------------------------------------------------------
# label_template_generator._pair_fields_by_grid
# ---------------------------------------------------------------------------


class TestPairFieldsByGrid:
    """Cover _pair_fields_by_grid branches."""

    def test_empty_blocks_returns_empty(self) -> None:
        assert _pair_fields_by_grid([], [], []) == []

    def test_blocks_with_no_grid_lines(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "left": 10,
                "top": 40,
                "width": 80,
                "height": 20,
                "conf": 0.9,
                "y_center": 50,
            }
        ]
        # No grid lines → all blocks go to row 0, col 0
        result = _pair_fields_by_grid(blocks, [], [])
        assert len(result) == 1
        assert result[0]["label"] == "品名"

    def test_pair_label_with_value(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "left": 10,
                "top": 40,
                "width": 80,
                "height": 20,
                "conf": 0.9,
                "y_center": 50,
            },
            {
                "text": "测试产品",
                "center": (150, 50),
                "left": 110,
                "top": 40,
                "width": 80,
                "height": 20,
                "conf": 0.85,
                "y_center": 50,
            },
        ]
        # With grid lines that put them in adjacent columns
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100, 200])
        assert len(result) == 1
        assert result[0]["label"] == "品名"
        assert result[0]["value"] == "测试产品"

    def test_single_block_in_row_no_pair(self) -> None:
        blocks = [
            {
                "text": "品名",
                "center": (50, 50),
                "left": 10,
                "top": 40,
                "width": 80,
                "height": 20,
                "conf": 0.9,
                "y_center": 50,
            }
        ]
        result = _pair_fields_by_grid(blocks, [0, 100], [0, 100])
        assert len(result) == 1
        assert result[0]["value"] == ""


# ---------------------------------------------------------------------------
# label_template_generator.extract_text_with_ocr
# ---------------------------------------------------------------------------


class TestExtractTextWithOcr:
    """Cover extract_text_with_ocr error branches."""

    def test_import_error_returns_fallback(self) -> None:
        # Force ImportError on cv2/numpy import
        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            result = extract_text_with_ocr("/some/img.png")
        assert result["success"] is False
        assert "fallback_fields" in result

    def test_recoverable_error_returns_fallback(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        # Force a ValueError after the imports succeed
        with patch("PIL.Image.open", side_effect=ValueError("bad")):
            result = extract_text_with_ocr(str(img_path))
        assert result["success"] is False
        assert "fallback_fields" in result


# ---------------------------------------------------------------------------
# label_template_generator.generate_template_code
# ---------------------------------------------------------------------------


class TestGenerateTemplateCode:
    """Cover generate_template_code branches."""

    def test_invalid_image_returns_error_comment(self) -> None:
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            return_value={"success": False, "error": "bad"},
        ):
            code = generate_template_code("/nonexistent.png")
        assert code.startswith("# Error")

    def test_without_ocr_generates_basic_code(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        code = generate_template_code(str(img_path), ocr_result=None)
        assert "class LabelTemplateGenerator" in code

    def test_with_failed_ocr_generates_basic_code(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        code = generate_template_code(
            str(img_path),
            ocr_result={"success": False},
        )
        assert "class LabelTemplateGenerator" in code

    def test_with_successful_ocr_generates_field_code(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        ocr_result = {
            "success": True,
            "fields": [
                {
                    "label": "品名",
                    "value": "测试",
                    "field_key": "product_name",
                    "type": "fixed_label",
                }
            ],
        }
        code = generate_template_code(str(img_path), ocr_result=ocr_result)
        assert "class LabelTemplateGenerator" in code
        assert "product_name" in code


# ---------------------------------------------------------------------------
# label_template_generator.LabelTemplateGeneratorSkill
# ---------------------------------------------------------------------------


class TestLabelTemplateGeneratorSkill:
    """Cover skill execute / info / singleton."""

    def test_get_skill_info_returns_parameters(self) -> None:
        skill = LabelTemplateGeneratorSkill()
        info = skill.get_skill_info()
        assert info["name"] == "label_template_generator"
        assert "image_path" in info["parameters"]
        assert info["parameters"]["image_path"]["required"] is True

    def test_execute_invalid_image_returns_analysis(self) -> None:
        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            return_value={"success": False, "message": "bad image"},
        ):
            result = skill.execute("/nonexistent.png")
        assert result["success"] is False

    def test_execute_valid_image_no_ocr(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(str(img_path), enable_ocr=False)
        assert result["success"] is True
        assert "code" in result
        assert result["ocr_result"] is None

    def test_execute_with_output_file(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)
        out_file = tmp_path / "out.py"

        skill = LabelTemplateGeneratorSkill()
        result = skill.execute(
            str(img_path),
            enable_ocr=False,
            output_file=str(out_file),
        )
        assert result["success"] is True
        assert result["output_file"] == str(out_file)
        assert out_file.exists()

    def test_execute_output_file_write_error(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        # Patch the open call only inside the skill module's namespace
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.open",
            side_effect=OSError("write fail"),
            create=True,
        ):
            result = skill.execute(
                str(img_path),
                enable_ocr=False,
                output_file="/bad/path/out.py",
            )
        assert result["success"] is True
        assert "output_error" in result

    def test_execute_recoverable_error_returns_failure(self, tmp_path: Path) -> None:
        from PIL import Image as PILImage

        img = PILImage.new("RGB", (100, 50), color=(255, 255, 255))
        img_path = tmp_path / "test.png"
        img.save(img_path)

        skill = LabelTemplateGeneratorSkill()
        with patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            side_effect=RuntimeError("unexpected"),
        ):
            result = skill.execute(str(img_path))
        assert result["success"] is False
        assert "unexpected" in result["message"]

    def test_get_label_template_generator_skill_singleton(self) -> None:
        # Reset singleton
        import app.services.skills.label_template_generator.label_template_generator as mod

        mod._skill_instance = None
        s1 = get_label_template_generator_skill()
        s2 = get_label_template_generator_skill()
        assert s1 is s2
        # Cleanup
        mod._skill_instance = None
