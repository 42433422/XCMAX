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
        """Root manifest is returned verbatim; sibling files do not leak in."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "test-mod", "version": "1.0.0"}
        _make_zip(
            zip_path,
            {"manifest.json": manifest, "code.py": "pass", "README.md": "# Test"},
        )

        result = peek_manifest_from_zip(str(zip_path))
        # The whole manifest dict is returned, not just a probe of one key, and
        # the extra package files are not folded into the parsed manifest.
        assert result == {"id": "test-mod", "version": "1.0.0"}
        assert "code.py" not in result
        assert "README.md" not in result


# ---------------------------------------------------------------------------
# peek_manifest_from_zip — subdirectory manifest
# ---------------------------------------------------------------------------


class TestPeekManifestSubdir:
    def test_single_subdir_manifest(self, tmp_path):
        """A single ``<dir>/manifest.json`` is parsed and returned in full."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "sub-mod", "version": "1.0.0", "artifact": "mod"}
        _make_zip(
            zip_path,
            {"sub-mod/manifest.json": manifest, "sub-mod/code.py": "pass"},
        )

        result = peek_manifest_from_zip(str(zip_path))
        assert result == {"id": "sub-mod", "version": "1.0.0", "artifact": "mod"}

    def test_nested_manifest_deeper_than_one_level_not_picked(self, tmp_path):
        """Only depth-1 ``<dir>/manifest.json`` qualifies; deeper ones are ignored.

        ``a/b/manifest.json`` has two slashes so it fails the ``count('/') == 1``
        candidate filter, leaving no candidates -> missing-manifest error.
        """
        zip_path = tmp_path / "pkg.xcmod"
        _make_zip(zip_path, {"a/b/manifest.json": {"id": "deep"}})

        with pytest.raises(ValueError, match="zip 内未找到 manifest.json"):
            peek_manifest_from_zip(str(zip_path))

    def test_multiple_subdir_manifests_with_id_match(self, tmp_path):
        """Both paths match their id -> the sorted-first candidate (mod-a) wins."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest_a = {"id": "mod-a", "version": "1.0.0"}
        manifest_b = {"id": "mod-b", "version": "2.0.0"}
        _make_zip(
            zip_path,
            {
                "mod-b/manifest.json": manifest_b,
                "mod-a/manifest.json": manifest_a,
            },
        )

        result = peek_manifest_from_zip(str(zip_path))
        # Deterministic: candidates are sorted, mod-a/ sorts before mod-b/ and its
        # path matches its id, so the mod-a manifest is returned in full.
        assert result == {"id": "mod-a", "version": "1.0.0"}

    def test_multiple_subdir_manifests_picks_path_matching_id(self, tmp_path):
        """When only one manifest's path matches its declared id, that one wins.

        ``alpha/manifest.json`` declares id ``mod-a`` (path mismatch) and
        ``mod-b/manifest.json`` declares id ``mod-b`` (path match). Even though
        ``alpha/`` sorts first, the id-path match for ``mod-b`` is selected.
        """
        zip_path = tmp_path / "pkg.xcmod"
        _make_zip(
            zip_path,
            {
                "alpha/manifest.json": {"id": "mod-a", "version": "1.0.0"},
                "mod-b/manifest.json": {"id": "mod-b", "version": "2.0.0"},
            },
        )

        result = peek_manifest_from_zip(str(zip_path))
        assert result == {"id": "mod-b", "version": "2.0.0"}

    def test_multiple_subdir_manifests_no_id_match_fallback(self, tmp_path):
        """No path matches its id -> fall back to the sorted-first candidate.

        ``alpha/`` sorts before ``beta/``, so the alpha manifest (id
        ``different-id``) is returned even though its path does not match.
        """
        zip_path = tmp_path / "pkg.xcmod"
        _make_zip(
            zip_path,
            {
                "beta/manifest.json": {"id": "another-id", "version": "9.9"},
                "alpha/manifest.json": {"id": "different-id", "version": "1.1"},
            },
        )

        result = peek_manifest_from_zip(str(zip_path))
        assert result == {"id": "different-id", "version": "1.1"}

    def test_multiple_subdir_manifests_with_invalid_json(self, tmp_path):
        """A JSONDecodeError on the sorted-first candidate is swallowed; the
        next valid candidate whose path matches its id is returned."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest_b = {"id": "mod-b", "version": "1.0.0"}
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # mod-a/ sorts first but is unparseable -> the except-continue branch.
            zf.writestr("mod-a/manifest.json", "{invalid json")
            zf.writestr("mod-b/manifest.json", json.dumps(manifest_b))

        result = peek_manifest_from_zip(str(zip_path))
        assert result == {"id": "mod-b", "version": "1.0.0"}

    def test_all_subdir_manifests_invalid_json_raises(self, tmp_path):
        """When every candidate is unparseable, the id-match loop finds nothing
        and the final fallback re-reads the sorted-first candidate, surfacing the
        raw JSONDecodeError (it is not wrapped into a ValueError)."""
        zip_path = tmp_path / "pkg.xcmod"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mod-a/manifest.json", "{not json")
            zf.writestr("mod-b/manifest.json", "still not json")

        with pytest.raises(json.JSONDecodeError):
            peek_manifest_from_zip(str(zip_path))


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

    def test_peek_artifact_artifact_wins_over_kind(self, tmp_path):
        """When both fields exist, ``artifact`` takes precedence over ``kind``."""
        zip_path = tmp_path / "pkg.xcbundle"
        manifest = {"id": "x", "artifact": "bundle", "kind": "mod"}
        _make_zip(zip_path, {"manifest.json": manifest})

        assert peek_artifact(str(zip_path)) == "bundle"

    def test_peek_artifact_unknown_value_falls_back_to_mod(self, tmp_path):
        """An unrecognized artifact string normalizes back to the default 'mod'."""
        zip_path = tmp_path / "pkg.xcmod"
        manifest = {"id": "x", "artifact": "totally-bogus"}
        _make_zip(zip_path, {"manifest.json": manifest})

        assert peek_artifact(str(zip_path)) == "mod"

    def test_peek_artifact_value_is_case_insensitive(self, tmp_path):
        """Mixed-case artifact values are lowercased during normalization."""
        zip_path = tmp_path / "pkg.xcbundle"
        manifest = {"id": "x", "artifact": "Bundle"}
        _make_zip(zip_path, {"manifest.json": manifest})

        assert peek_artifact(str(zip_path)) == "bundle"


# ---------------------------------------------------------------------------
# validate_bundle_manifest
# ---------------------------------------------------------------------------


class TestValidateBundleManifest:
    def test_non_bundle_returns_empty(self):
        """A non-bundle artifact short-circuits before any bundle checks run."""
        # Deliberately give a malformed bundle field: it must be ignored because
        # the artifact is 'mod', proving the early return is what fires.
        manifest = {"artifact": "mod", "bundle": "this-would-error-if-checked"}
        assert validate_bundle_manifest(manifest) == []

    def test_valid_bundle_with_contains(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "contains": [{"ref": "mod-a"}, {"ref": "mod-b"}],
            },
        }
        assert validate_bundle_manifest(manifest) == []

    def test_valid_bundle_with_embeds(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "embeds": ["path/to/mod-a", "path/to/mod-b"],
            },
        }
        assert validate_bundle_manifest(manifest) == []

    def test_valid_bundle_with_both_contains_and_embeds(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "contains": [{"ref": "mod-a"}],
                "embeds": ["path/to/mod-b"],
            },
        }
        assert validate_bundle_manifest(manifest) == []

    def test_bundle_without_bundle_field(self):
        manifest = {"artifact": "bundle"}
        # Missing bundle is an early hard-stop: exactly one error and no later
        # per-item messages.
        assert validate_bundle_manifest(manifest) == ["artifact 为 bundle 时 bundle 须为对象"]

    def test_bundle_with_non_dict_bundle(self):
        manifest = {"artifact": "bundle", "bundle": "not-a-dict"}
        assert validate_bundle_manifest(manifest) == ["artifact 为 bundle 时 bundle 须为对象"]

    def test_bundle_with_non_list_contains(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": "not-a-list"},
        }
        errs = validate_bundle_manifest(manifest)
        # Truthy non-list 'contains' satisfies the "at least one" gate, so the
        # only complaint is the type error.
        assert errs == ["bundle.contains 须为数组"]

    def test_bundle_with_non_list_embeds(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": "not-a-list"},
        }
        assert validate_bundle_manifest(manifest) == ["bundle.embeds 须为数组"]

    def test_bundle_without_contains_or_embeds(self):
        manifest = {"artifact": "bundle", "bundle": {}}
        assert validate_bundle_manifest(manifest) == ["bundle 至少需包含 contains 或 embeds 之一"]

    def test_bundle_empty_contains_and_embeds_lists(self):
        """Empty lists are falsy, so the 'at least one' rule still trips."""
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [], "embeds": []},
        }
        assert validate_bundle_manifest(manifest) == ["bundle 至少需包含 contains 或 embeds 之一"]

    def test_bundle_contains_item_not_dict(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": ["not-a-dict"]},
        }
        assert validate_bundle_manifest(manifest) == ["bundle.contains[0] 须为对象"]

    def test_bundle_contains_item_missing_ref(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"name": "no-ref"}]},
        }
        assert validate_bundle_manifest(manifest) == ["bundle.contains[0] 缺少 ref"]

    def test_bundle_contains_item_empty_ref(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"ref": "  "}]},
        }
        # Whitespace-only ref is stripped to empty -> treated as missing.
        assert validate_bundle_manifest(manifest) == ["bundle.contains[0] 缺少 ref"]

    def test_bundle_embeds_item_not_string(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": [123]},
        }
        assert validate_bundle_manifest(manifest) == ["bundle.embeds[0] 须为非空相对路径字符串"]

    def test_bundle_embeds_item_empty_string(self):
        manifest = {
            "artifact": "bundle",
            "bundle": {"embeds": ["  "]},
        }
        assert validate_bundle_manifest(manifest) == ["bundle.embeds[0] 须为非空相对路径字符串"]

    def test_bundle_errors_accumulate_with_correct_indices(self):
        """Multiple malformed items each produce their own indexed error and the
        whole list is returned (validation does not stop at the first bad item)."""
        manifest = {
            "artifact": "bundle",
            "bundle": {
                "contains": ["bad", {"name": "no-ref"}, {"ref": "ok"}],
                "embeds": [123, "", "fine/path"],
            },
        }
        errs = validate_bundle_manifest(manifest)
        assert errs == [
            "bundle.contains[0] 须为对象",
            "bundle.contains[1] 缺少 ref",
            "bundle.embeds[0] 须为非空相对路径字符串",
            "bundle.embeds[1] 须为非空相对路径字符串",
        ]

    def test_bundle_depth_at_limit_is_allowed(self):
        """depth == BUNDLE_MAX_DEPTH (2) is the boundary and must NOT error."""
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"ref": "mod-a"}]},
        }
        assert validate_bundle_manifest(manifest, depth=2) == []

    def test_bundle_depth_exceeded(self):
        """depth > BUNDLE_MAX_DEPTH short-circuits with only the depth error."""
        manifest = {
            "artifact": "bundle",
            "bundle": {"contains": [{"ref": "mod-a"}]},
        }
        assert validate_bundle_manifest(manifest, depth=3) == ["bundle 嵌套深度超过上限 2"]


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
        # Non-dict short-circuits: exactly the type error, nothing else.
        assert validate_xcagi_host_profile_extensions(manifest) == ["xcagi_host_profile 须为对象"]

    def test_host_profile_invalid_panel_kind_echoes_value(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "invalid_kind"}}
        # The error message embeds the offending value via repr().
        assert validate_xcagi_host_profile_extensions(manifest) == [
            "xcagi_host_profile.panel_kind 无效: 'invalid_kind'"
        ]

    def test_host_profile_valid_panel_kind_mod_http(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "mod_http"}}
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_valid_panel_kind_builtin_track(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "builtin_track"}}
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_valid_panel_kind_placeholder(self):
        manifest = {"xcagi_host_profile": {"panel_kind": "placeholder"}}
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_invalid_builtin_track_id(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "builtin_track",
                "builtin_track_id": "invalid_track",
            }
        }
        # panel_kind is valid here, so the only error is the whitelist miss,
        # with the bad id echoed via repr().
        assert validate_xcagi_host_profile_extensions(manifest) == [
            "xcagi_host_profile.builtin_track_id 不在宿主白名单: 'invalid_track'"
        ]

    def test_host_profile_valid_builtin_track_id(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "builtin_track",
                "builtin_track_id": "label_print",
            }
        }
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_all_whitelisted_builtin_track_ids_accepted(self):
        """Every documented builtin track id is accepted under builtin_track."""
        for track_id in (
            "label_print",
            "shipment_mgmt",
            "receipt_confirm",
            "wechat_msg",
            "wechat_phone",
            "real_phone",
        ):
            manifest = {
                "xcagi_host_profile": {
                    "panel_kind": "builtin_track",
                    "builtin_track_id": track_id,
                }
            }
            assert validate_xcagi_host_profile_extensions(manifest) == [], track_id

    def test_host_profile_builtin_track_id_with_wrong_panel_kind(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "builtin_track_id": "label_print",
            }
        }
        # builtin_track_id is whitelisted, but panel_kind mismatches -> exactly
        # the mismatch error (no whitelist error).
        assert validate_xcagi_host_profile_extensions(manifest) == [
            "填写 builtin_track_id 时 panel_kind 应为 builtin_track"
        ]

    def test_host_profile_unwhitelisted_builtin_id_and_wrong_panel_kind(self):
        """An id that is both unknown and under the wrong panel_kind yields BOTH
        errors, in source order (whitelist first, then panel_kind mismatch)."""
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "builtin_track_id": "bogus",
            }
        }
        assert validate_xcagi_host_profile_extensions(manifest) == [
            "xcagi_host_profile.builtin_track_id 不在宿主白名单: 'bogus'",
            "填写 builtin_track_id 时 panel_kind 应为 builtin_track",
        ]

    def test_host_profile_workflow_employee_row_not_dict(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "workflow_employee_row": "not-a-dict",
            }
        }
        assert validate_xcagi_host_profile_extensions(manifest) == [
            "xcagi_host_profile.workflow_employee_row 须为对象"
        ]

    def test_host_profile_workflow_employee_row_dict(self):
        manifest = {
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "workflow_employee_row": {"key": "value"},
            }
        }
        assert validate_xcagi_host_profile_extensions(manifest) == []

    def test_host_profile_default_panel_kind(self):
        """Missing/empty panel_kind defaults to 'mod_http' and validates clean."""
        assert validate_xcagi_host_profile_extensions({"xcagi_host_profile": {}}) == []
        # Explicit empty string also falls back to the default, not an error.
        assert (
            validate_xcagi_host_profile_extensions({"xcagi_host_profile": {"panel_kind": ""}}) == []
        )


# ---------------------------------------------------------------------------
# validate_employee_pack_manifest
# ---------------------------------------------------------------------------


class TestValidateEmployeePackManifest:
    def test_non_employee_pack_returns_empty(self):
        """Non-employee_pack short-circuits: a missing employee object that would
        otherwise error is ignored because the artifact is 'mod'."""
        assert validate_employee_pack_manifest({"artifact": "mod"}) == []

    def test_valid_employee_pack(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "global",
        }
        assert validate_employee_pack_manifest(manifest) == []

    def test_employee_pack_without_employee(self):
        manifest = {"artifact": "employee_pack"}
        # Missing employee is an early hard-stop: scope checks never run.
        assert validate_employee_pack_manifest(manifest) == ["employee_pack 须包含 employee 对象"]

    def test_employee_pack_with_non_dict_employee(self):
        manifest = {"artifact": "employee_pack", "employee": "not-a-dict"}
        assert validate_employee_pack_manifest(manifest) == ["employee_pack 须包含 employee 对象"]

    def test_employee_pack_empty_employee_id(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": ""},
        }
        assert validate_employee_pack_manifest(manifest) == ["employee.id 不能为空"]

    def test_employee_pack_whitespace_employee_id(self):
        """Whitespace-only id strips to empty and is rejected."""
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "   "},
        }
        assert validate_employee_pack_manifest(manifest) == ["employee.id 不能为空"]

    def test_employee_pack_missing_employee_id(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {},
        }
        assert validate_employee_pack_manifest(manifest) == ["employee.id 不能为空"]

    def test_employee_pack_invalid_scope(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "invalid_scope",
        }
        assert validate_employee_pack_manifest(manifest) == [
            "scope 仅支持 global 或 host（预留 host_mod 二期）"
        ]

    def test_employee_pack_scope_is_case_insensitive(self):
        """scope is normalized to lowercase, so 'GLOBAL' validates clean while
        'HOST' still triggers the host_mod requirement."""
        ok = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "GLOBAL",
        }
        assert validate_employee_pack_manifest(ok) == []

        host_caps = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "HOST",
        }
        assert validate_employee_pack_manifest(host_caps) == [
            "scope=host 时需填写 host_mod（二期启用）"
        ]

    def test_employee_pack_scope_host_without_host_mod(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "host",
        }
        assert validate_employee_pack_manifest(manifest) == [
            "scope=host 时需填写 host_mod（二期启用）"
        ]

    def test_employee_pack_scope_host_with_host_mod(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "scope": "host",
            "host_mod": "some-mod",
        }
        assert validate_employee_pack_manifest(manifest) == []

    def test_employee_pack_default_scope_global(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
        }
        assert validate_employee_pack_manifest(manifest) == []

    def test_employee_pack_with_host_profile_extensions(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "xcagi_host_profile": {"panel_kind": "mod_http"},
        }
        assert validate_employee_pack_manifest(manifest) == []

    def test_employee_pack_with_invalid_host_profile(self):
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": "emp-001"},
            "xcagi_host_profile": {"panel_kind": "invalid"},
        }
        # The host-profile sub-validator's error is appended to the pack errors.
        assert validate_employee_pack_manifest(manifest) == [
            "xcagi_host_profile.panel_kind 无效: 'invalid'"
        ]

    def test_employee_pack_combines_id_and_host_profile_errors(self):
        """A missing id AND a bad host profile both surface, with the host-profile
        error appended after the core pack errors."""
        manifest = {
            "artifact": "employee_pack",
            "employee": {"id": ""},
            "xcagi_host_profile": {"panel_kind": "nope"},
        }
        assert validate_employee_pack_manifest(manifest) == [
            "employee.id 不能为空",
            "xcagi_host_profile.panel_kind 无效: 'nope'",
        ]
