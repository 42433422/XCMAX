"""Tests for app.infrastructure.mods.artifact_package — extended coverage (ext2).

Focus: peek_manifest_from_zip with root-level manifest, subdirectory manifest,
multiple manifests with id match, multiple manifests fallback, invalid zip,
missing manifest; peek_artifact; validate_bundle_manifest with various shapes;
validate_xcagi_host_profile_extensions; validate_employee_pack_manifest.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.infrastructure.mods.artifact_package import (
    peek_artifact,
    peek_manifest_from_zip,
    validate_bundle_manifest,
    validate_employee_pack_manifest,
    validate_xcagi_host_profile_extensions,
)


def _make_zip(path: Path, files: dict[str, dict | str]) -> str:
    """Create a zip file at path with given files mapping name -> content."""
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            if isinstance(content, (dict, list)):
                content = json.dumps(content)
            zf.writestr(name, content)
    return str(path)


# ---------------------------------------------------------------------------
# peek_manifest_from_zip — root-level manifest
# ---------------------------------------------------------------------------


class TestPeekManifestRootLevel:
    def test_root_manifest_json(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0", "artifact": "mod"}
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_manifest_from_zip(str(zip_path))
        assert result == manifest

    def test_root_manifest_with_extra_files(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0"}
        _make_zip(
            zip_path,
            {"manifest.json": manifest, "code.py": "pass", "README.md": "# Test"},
        )

        result = peek_manifest_from_zip(str(zip_path))
        assert result["id"] == "test-mod"


# ---------------------------------------------------------------------------
# peek_manifest_from_zip — subdirectory manifest
# ---------------------------------------------------------------------------


class TestPeekManifestSubdir:
    def test_single_subdir_manifest(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "sub-mod", "version": "1.0.0"}
        _make_zip(
            zip_path,
            {"sub-mod/manifest.json": manifest, "sub-mod/code.py": "pass"},
        )

        result = peek_manifest_from_zip(str(zip_path))
        assert result["id"] == "sub-mod"

    def test_multiple_subdir_manifests_with_id_match(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest_a = {"id": "mod-a", "version": "1.0.0"}
        manifest_b = {"id": "mod-b", "version": "1.0.0"}
        _make_zip(
            zip_path,
            {
                "mod-a/manifest.json": manifest_a,
                "mod-b/manifest.json": manifest_b,
            },
        )

        result = peek_manifest_from_zip(str(zip_path))
        # Should pick the one whose path matches its id
        assert result["id"] in ("mod-a", "mod-b")

    def test_multiple_subdir_manifests_no_id_match_fallback(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest_a = {"id": "different-id", "version": "1.0.0"}
        manifest_b = {"id": "another-id", "version": "1.0.0"}
        _make_zip(
            zip_path,
            {
                "alpha/manifest.json": manifest_a,
                "beta/manifest.json": manifest_b,
            },
        )

        result = peek_manifest_from_zip(str(zip_path))
        # Falls back to first sorted candidate
        assert result["id"] in ("different-id", "another-id")

    def test_multiple_subdir_manifests_with_invalid_json(self, tmp_path):
        """Invalid JSON in one manifest should be skipped, valid one returned."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest_b = {"id": "mod-b", "version": "1.0.0"}
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mod-a/manifest.json", "{invalid json")
            zf.writestr("mod-b/manifest.json", json.dumps(manifest_b))

        result = peek_manifest_from_zip(str(zip_path))
        assert result["id"] == "mod-b"


# ---------------------------------------------------------------------------
# peek_manifest_from_zip — error cases
# ---------------------------------------------------------------------------


class TestPeekManifestErrors:
    def test_not_a_zip_file(self, tmp_path):
        bad_path = tmp_path / "not-a-zip.txt"
        bad_path.write_text("not a zip", encoding="utf-8")

        with pytest.raises(ValueError, match="不是有效的 zip 文件"):
            peek_manifest_from_zip(str(bad_path))

    def test_zip_without_manifest(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        _make_zip(zip_path, {"code.py": "pass", "README.md": "# Test"})

        with pytest.raises(ValueError, match="zip 内未找到 manifest.json"):
            peek_manifest_from_zip(str(zip_path))

    def test_nonexistent_file(self, tmp_path):
        with pytest.raises((ValueError, FileNotFoundError, OSError)):
            peek_manifest_from_zip(str(tmp_path / "nonexistent.xcmod"))


# ---------------------------------------------------------------------------
# peek_artifact
# ---------------------------------------------------------------------------


class TestPeekArtifact:
    def test_peek_artifact_mod(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0", "artifact": "mod"}
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_artifact(str(zip_path))
        assert result == "mod"

    def test_peek_artifact_employee_pack(self, tmp_path):
        zip_path = tmp_path / "pkg.xcemp"
        manifest = {"id": "test-emp", "version": "1.0.0", "artifact": "employee_pack"}
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_artifact(str(zip_path))
        assert result == "employee_pack"

    def test_peek_artifact_bundle(self, tmp_path):
        zip_path = tmp_path / "pkg.xcbundle"
        manifest = {"id": "test-bundle", "version": "1.0.0", "artifact": "bundle"}
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_artifact(str(zip_path))
        assert result == "bundle"

    def test_peek_artifact_defaults_to_mod(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0"}  # no artifact field
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_artifact(str(zip_path))
        assert result == "mod"

    def test_peek_artifact_with_kind_alias(self, tmp_path):
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0", "kind": "employee_pack"}
        _make_zip(zip_path, {"manifest.json": manifest})

        result = peek_artifact(str(zip_path))
        assert result == "employee_pack"


# ---------------------------------------------------------------------------
# validate_bundle_manifest
# ---------------------------------------------------------------------------


class TestValidateBundleManifest:
    def test_non_bundle_returns_empty(self):
        manifest = {"artifact": "mod"}
        assert validate_bundle_manifest(manifest) == []

    def test_valid_bundle_with_contains(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "contains": [{"ref": "mod-a"}, {"ref": "mod-b"}],
            },
        }
        errs = validate_bundle_manifest(manifest)
        assert errs == []

    def test_valid_bundle_with_embeds(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "embeds": ["path/to/mod-a", "path/to/mod-b"],
            },
        }
        errs = validate_bundle_manifest(manifest)
        assert errs == []

    def test_bundle_without_bundle_field(self):
        manifest = {"artifact": "bundle"}
        errs = validate_bundle_manifest(manifest)
        assert any("bundle 须为对象" in e for e in errs)

    def test_bundle_with_non_dict_bundle(self):
        manifest = {"artifact": "bundle", "bundle": "not-a-dict"}
        errs = validate_bundle_manifest(manifest)
        assert any("bundle 须为对象" in e for e in errs)

    def test_bundle_with_non_list_contains(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": "not-a-list"},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.contains 须为数组" in e for e in errs)

    def test_bundle_with_non_list_embeds(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": "not-a-list"},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.embeds 须为数组" in e for e in errs)

    def test_bundle_without_contains_or_embeds(self):
        manifest = {"artifact": "bundle", "bundle": {}}
        errs = validate_bundle_manifest(manifest)
        assert any("至少需包含 contains 或 embeds" in e for e in errs)

    def test_bundle_contains_item_not_dict(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": ["not-a-dict"]},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.contains[0] 须为对象" in e for e in errs)

    def test_bundle_contains_item_missing_ref(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"name": "no-ref"}]},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.contains[0] 缺少 ref" in e for e in errs)

    def test_bundle_contains_item_empty_ref(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"ref": "  "}]},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.contains[0] 缺少 ref" in e for e in errs)

    def test_bundle_embeds_item_not_string(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": [123]},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.embeds[0] 须为非空相对路径字符串" in e for e in errs)

    def test_bundle_embeds_item_empty_string(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": ["  "]},
        }
        errs = validate_bundle_manifest(manifest)
        assert any("bundle.embeds[0] 须为非空相对路径字符串" in e for e in errs)

    def test_bundle_depth_exceeded(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"ref": "mod-a"}]},
        }
        errs = validate_bundle_manifest(manifest, depth=10)
        assert any("嵌套深度超过上限" in e for e in errs)


# ---------------------------------------------------------------------------
# validate_xcagi_host_profile_extensions
# ---------------------------------------------------------------------------


class TestValidateXcagiHostProfileExtensions:
    def test_no_host_profile_returns_empty(self):
        manifest = {"id": "test"}
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_none_returns_empty(self):
        manifest = {"id": "test", "xcagi_host_profile": None}
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_not_dict(self):
        manifest = {"xcagi_host_profile": "not-a-dict"}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert any("xcagi_host_profile 须为对象" in e for e in errs)

    def test_host_profile_invalid_panel_kind(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "invalid_kind"}}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert any("panel_kind 无效" in e for e in errs)

    def test_host_profile_valid_panel_kind_mod_http(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "mod_http"}}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []

    def test_host_profile_valid_panel_kind_builtin_track(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "builtin_track"}}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []

    def test_host_profile_valid_panel_kind_placeholder(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "placeholder"}}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []

    def test_host_profile_invalid_builtin_track_id(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "builtin_track",
                "builtin_track_id": "invalid_track",
            }
        }
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert any("builtin_track_id 不在宿主白名单" in e for e in errs)

    def test_host_profile_valid_builtin_track_id(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "builtin_track",
                "builtin_track_id": "label_print",
            }
        }
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []

    def test_host_profile_builtin_track_id_with_wrong_panel_kind(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "builtin_track_id": "label_print",
            }
        }
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert any("panel_kind 应为 builtin_track" in e for e in errs)

    def test_host_profile_workflow_employee_row_not_dict(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "workflow_employee_row": "not-a-dict",
            }
        }
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert any("workflow_employee_row 须为对象" in e for e in errs)

    def test_host_profile_workflow_employee_row_dict(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "workflow_employee_row": {"key": "value"},
            }
        }
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []

    def test_host_profile_default_panel_kind(self):
        """When panel_kind is missing/empty, defaults to 'mod_http'."""
        manifest = {"xcagi_host_profile": {}}
        errs = validate_xcagi_host_profile_extensions(manifest)
        assert errs == []


# ---------------------------------------------------------------------------
# validate_employee_pack_manifest
# ---------------------------------------------------------------------------


class TestValidateEmployeePackManifest:
    def test_non_employee_pack_returns_empty(self):
        manifest = {"artifact": "mod"}
        assert validate_employee_pack_manifest(manifest) == []

    def test_valid_employee_pack(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "global",
        }
        errs = validate_employee_pack_manifest(manifest)
        assert errs == []

    def test_employee_pack_without_employee(self):
        manifest = {"artifact": "employee_pack"}
        errs = validate_employee_pack_manifest(manifest)
        assert any("须包含 employee 对象" in e for e in errs)

    def test_employee_pack_with_non_dict_employee(self):
        manifest = {"artifact": "employee_pack", "employee": "not-a-dict"}
        errs = validate_employee_pack_manifest(manifest)
        assert any("须包含 employee 对象" in e for e in errs)

    def test_employee_pack_empty_employee_id(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": ""},
        }
        errs = validate_employee_pack_manifest(manifest)
        assert any("employee.id 不能为空" in e for e in errs)

    def test_employee_pack_missing_employee_id(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {},
        }
        errs = validate_employee_pack_manifest(manifest)
        assert any("employee.id 不能为空" in e for e in errs)

    def test_employee_pack_invalid_scope(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "invalid_scope",
        }
        errs = validate_employee_pack_manifest(manifest)
        assert any("scope 仅支持 global 或 host" in e for e in errs)

    def test_employee_pack_scope_host_without_host_mod(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "host",
        }
        errs = validate_employee_pack_manifest(manifest)
        assert any("scope=host 时需填写 host_mod" in e for e in errs)

    def test_employee_pack_scope_host_with_host_mod(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "host",
            "host_mod": "some-mod",
        }
        errs = validate_employee_pack_manifest(manifest)
        assert errs == []

    def test_employee_pack_default_scope_global(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
        }
        errs = validate_employee_pack_manifest(manifest)
        assert errs == []

    def test_employee_pack_with_host_profile_extensions(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "xcagi_host_profile": {"panel_kind": "mod_http"},
        }
        errs = validate_employee_pack_manifest(manifest)
        assert errs == []

    def test_employee_pack_with_invalid_host_profile(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "xcagi_host_profile": {"panel_kind": "invalid"},
        }
        errs = validate_employee_pack_manifest(manifest)
        assert any("panel_kind 无效" in e for e in errs)
