"""Tests for app.infrastructure.mods.manifest — coverage ramp C3.3-b.

Covers:
* ``ModMetadata.from_dict`` happy path with all sections.
* ``ModMetadata.from_dict`` menu_overrides supports both ``list`` and ``dict``
  shapes (key-as-string).
* ``ModMetadata.from_dict`` rejects non-dict ``industry`` blocks with a warning.
* ``ModMetadata.from_dict`` filters ``comms.exports`` to non-empty strings.
* ``parse_manifest`` returns ``None`` when manifest file is missing.
* ``parse_manifest`` returns ``None`` when JSON is malformed.
* ``parse_manifest`` returns ``None`` when ``id`` field is missing.
* ``validate_dependencies`` rejects missing required mods.
* ``_check_xcagi_version`` accepts >=N.N.N, rejects below required.
* ``_compare_versions`` orders correctly.
* ``normalize_artifact`` handles unknown values, ``kind`` alias, and dict-shaped
  fields.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import patch

from app.infrastructure.mods.manifest import (
    ModMetadata,
    _check_xcagi_version,
    _compare_versions,
    normalize_artifact,
    parse_manifest,
    validate_dependencies,
)

# ---------------------------------------------------------------------------
# normalize_artifact (re-exported; also re-tested for direct coverage)
# ---------------------------------------------------------------------------


class TestNormalizeArtifact:
    def test_default_when_empty(self) -> None:
        assert normalize_artifact(None) == "mod"
        assert normalize_artifact({}) == "mod"

    def test_explicit_mod(self) -> None:
        assert normalize_artifact({"artifact": "mod"}) == "mod"

    def test_employee_pack(self) -> None:
        assert normalize_artifact({"artifact": "employee_pack"}) == "employee_pack"

    def test_bundle(self) -> None:
        assert normalize_artifact({"artifact": "bundle"}) == "bundle"

    def test_kind_alias(self) -> None:
        assert normalize_artifact({"kind": "bundle"}) == "bundle"

    def test_unknown_value_falls_back_to_mod(self) -> None:
        assert normalize_artifact({"artifact": "weird"}) == "mod"

    def test_non_string_value_falls_back(self) -> None:
        assert normalize_artifact({"artifact": 123}) == "mod"

    def test_strips_and_lowercases(self) -> None:
        assert normalize_artifact({"artifact": "  BUNDLE  "}) == "bundle"


# ---------------------------------------------------------------------------
# ModMetadata.from_dict
# ---------------------------------------------------------------------------


class TestFromDictHappyPath:
    def test_minimal(self) -> None:
        m = ModMetadata.from_dict({"id": "m1", "name": "M1", "version": "1.0.0"})
        assert m.id == "m1"
        assert m.name == "M1"
        assert m.version == "1.0.0"
        assert m.artifact == "mod"
        assert m.bundle == {}
        assert m.dependencies == {}
        assert m.backend_entry == ""
        assert m.frontend_routes == ""
        assert m.industry == {}
        assert m.ui_labels == {}
        assert m.workflow_employees == []

    def test_full_sections(self) -> None:
        data: dict[str, Any] = {
            "id": "m2",
            "name": "M2",
            "version": "2.3.4",
            "author": "alice",
            "description": "测试",
            "primary": True,
            "backend": {"entry": "mod2:main", "init": "mod2:init"},
            "frontend": {
                "routes": "/m2/routes",
                "pro_entry_path": "/m2/ProEntry.tsx",
                "menu": [{"key": "a", "label": "A"}],
                "menu_overrides": [{"key": "x", "label": "X"}],
            },
            "config": {"industry_overrides": "m2.yaml"},
            "hooks": {"on_load": "m2.on_load"},
            "comms": {"exports": ["alpha", "", "beta"]},
            "dependencies": {"xcagi": ">=10.0.0", "other_mod": "^1.0"},
            "bundle": {"foo": "bar"},
            "industry": {
                "id": "feed",
                "name": "饲料",
                "description": "饲料行业",
            },
            "ui_labels": {"entity": "客户"},
            "ui_starter_pack": [{"id": "p1"}],
            "workflow_employees": [{"id": "e1", "name": "E1"}],
        }
        m = ModMetadata.from_dict(data, mod_path="/tmp/m2")
        assert m.author == "alice"
        assert m.primary is True
        assert m.backend_entry == "mod2:main"
        assert m.backend_init == "mod2:init"
        assert m.frontend_routes == "/m2/routes"
        assert m.frontend_pro_entry_path == "/m2/ProEntry.tsx"
        assert m.frontend_menu == [{"key": "a", "label": "A"}]
        assert m.frontend_menu_overrides == [{"key": "x", "label": "X"}]
        assert m.config_overrides == "m2.yaml"
        assert m.hooks == {"on_load": "m2.on_load"}
        assert m.comms_exports == ["alpha", "beta"]  # empty stripped
        assert m.dependencies == {"xcagi": ">=10.0.0", "other_mod": "^1.0"}
        assert m.bundle == {"foo": "bar"}
        assert m.industry["id"] == "feed"
        assert m.ui_labels == {"entity": "客户"}
        assert m.ui_starter_pack == [{"id": "p1"}]
        assert m.workflow_employees == [{"id": "e1", "name": "E1"}]
        assert m.mod_path == "/tmp/m2"


class TestFromDictEdgeCases:
    def test_menu_overrides_as_dict(self) -> None:
        data: dict[str, Any] = {
            "id": "m3",
            "name": "M3",
            "frontend": {
                "menu_overrides": {
                    "alpha": {"label": "Alpha"},
                    "beta": "B",  # scalar -> {"label": "B"}
                    "": {"label": "ignored"},
                }
            },
        }
        m = ModMetadata.from_dict(data)
        keys = [row.get("key") for row in m.frontend_menu_overrides]
        assert "alpha" in keys
        assert "beta" in keys
        assert "" not in keys

    def test_comms_exports_not_list(self) -> None:
        data: dict[str, Any] = {
            "id": "m4",
            "name": "M4",
            "comms": {"exports": "alpha"},  # not a list
        }
        m = ModMetadata.from_dict(data)
        assert m.comms_exports == []

    def test_industry_missing_id_warns(self, caplog) -> None:
        data: dict[str, Any] = {
            "id": "m5",
            "name": "M5",
            "industry": {"name": "NoId"},  # dict but no id
        }
        with caplog.at_level(logging.WARNING, logger="app.infrastructure.mods.manifest"):
            m = ModMetadata.from_dict(data)
        assert m.industry == {}
        assert "industry field ignored" in caplog.text

    def test_industry_non_dict_warns(self, caplog) -> None:
        data: dict[str, Any] = {
            "id": "m6",
            "name": "M6",
            "industry": "feed",  # string, not dict
        }
        with caplog.at_level(logging.WARNING, logger="app.infrastructure.mods.manifest"):
            m = ModMetadata.from_dict(data)
        assert m.industry == {}
        assert "industry field ignored" in caplog.text

    def test_bundle_non_dict_ignored(self) -> None:
        data: dict[str, Any] = {
            "id": "m7",
            "name": "M7",
            "bundle": "not-a-dict",
        }
        m = ModMetadata.from_dict(data)
        assert m.bundle == {}

    def test_ui_starter_pack_filters_non_dict(self) -> None:
        data: dict[str, Any] = {
            "id": "m8",
            "name": "M8",
            "ui_starter_pack": [{"id": "p1"}, "bad", None, {"id": "p2"}],
        }
        m = ModMetadata.from_dict(data)
        assert m.ui_starter_pack == [{"id": "p1"}, {"id": "p2"}]

    def test_frontend_pro_entry_path_stripped(self) -> None:
        data: dict[str, Any] = {
            "id": "m9",
            "name": "M9",
            "frontend": {"pro_entry_path": "  /m9/Pro.tsx  "},
        }
        m = ModMetadata.from_dict(data)
        assert m.frontend_pro_entry_path == "/m9/Pro.tsx"

    def test_frontend_pro_entry_path_empty(self) -> None:
        data: dict[str, Any] = {
            "id": "m10",
            "name": "M10",
            "frontend": {"pro_entry_path": None},
        }
        m = ModMetadata.from_dict(data)
        assert m.frontend_pro_entry_path == ""


# ---------------------------------------------------------------------------
# parse_manifest (file I/O)
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_missing_file_returns_none(self, tmp_path, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="app.infrastructure.mods.manifest"):
            out = parse_manifest(str(tmp_path))
        assert out is None
        assert "Mod manifest not found" in caplog.text

    def test_malformed_json_returns_none(self, tmp_path, caplog) -> None:
        (tmp_path / "manifest.json").write_text("{ not valid json")
        with caplog.at_level(logging.ERROR, logger="app.infrastructure.mods.manifest"):
            out = parse_manifest(str(tmp_path))
        assert out is None
        assert "Failed to parse manifest JSON" in caplog.text

    def test_missing_id_returns_none(self, tmp_path, caplog) -> None:
        (tmp_path / "manifest.json").write_text(json.dumps({"name": "M11"}))
        with caplog.at_level(logging.ERROR, logger="app.infrastructure.mods.manifest"):
            out = parse_manifest(str(tmp_path))
        assert out is None
        assert "missing 'id' field" in caplog.text

    def test_oserror_on_read_returns_none(self, tmp_path, caplog) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"id": "m1", "name": "M"}))
        with caplog.at_level(logging.ERROR, logger="app.infrastructure.mods.manifest"):
            with patch("builtins.open", side_effect=OSError("perm denied")):
                out = parse_manifest(str(tmp_path))
        assert out is None
        assert "Failed to read manifest" in caplog.text

    def test_happy_path(self, tmp_path) -> None:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"id": "m1", "name": "M1", "version": "1.2.3"}))
        out = parse_manifest(str(tmp_path))
        assert isinstance(out, ModMetadata)
        assert out.id == "m1"
        assert out.name == "M1"
        assert out.version == "1.2.3"
        assert out.mod_path == str(tmp_path)


# ---------------------------------------------------------------------------
# validate_dependencies
# ---------------------------------------------------------------------------


class TestValidateDependencies:
    def _m(self, deps: dict[str, str]) -> ModMetadata:
        return ModMetadata(id="m", name="M", version="1.0.0", dependencies=deps)

    def test_no_dependencies(self) -> None:
        assert validate_dependencies(self._m({}), []) is True

    def test_satisfied(self) -> None:
        m = self._m({"other": "^1.0"})
        assert validate_dependencies(m, ["other"]) is True

    def test_missing_dep(self, caplog) -> None:
        m = self._m({"other": "^1.0"})
        with caplog.at_level(logging.WARNING, logger="app.infrastructure.mods.manifest"):
            ok = validate_dependencies(m, [])
        assert ok is False
        assert "depends on other which is not loaded" in caplog.text

    def test_xcagi_version_satisfied(self) -> None:
        m = self._m({"xcagi": ">=10.0.0"})
        assert validate_dependencies(m, []) is True

    def test_xcagi_version_unsatisfied(self, caplog) -> None:
        # current_version constant in module is "10.0.0"
        m = self._m({"xcagi": ">=99.0.0"})
        with caplog.at_level(logging.WARNING, logger="app.infrastructure.mods.manifest"):
            ok = validate_dependencies(m, [])
        assert ok is False
        assert ">=99.0.0" in caplog.text


class TestCheckXcagiVersion:
    def test_version_geq_required(self) -> None:
        assert _check_xcagi_version(">=1.0.0") is True

    def test_version_lt_required(self) -> None:
        assert _check_xcagi_version(">=99.0.0") is False

    def test_no_prefix_returns_true(self) -> None:
        # Anything not matching >=N.N.N is treated as "no constraint" → True
        assert _check_xcagi_version("^1.0") is True
        assert _check_xcagi_version("") is True


class TestCompareVersions:
    def test_equal(self) -> None:
        assert _compare_versions("1.0.0", "1.0.0") == 0

    def test_greater(self) -> None:
        assert _compare_versions("2.0.0", "1.9.9") == 1

    def test_less(self) -> None:
        assert _compare_versions("1.0.0", "1.0.1") == -1

    def test_prefix_strict(self) -> None:
        assert _compare_versions("10.0.0", "9.9.9") == 1
        assert _compare_versions("9.9.9", "10.0.0") == -1
