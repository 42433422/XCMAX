"""测试 app.mod_sdk.duty_roster 的分支覆盖。

覆盖目标：
- _collect_ids_from_blocks（非 dict 跳过 / ids 非 list / subzones 递归）
- load_duty_roster_document（cfg None / doc 无 areas+departments / 正常）
- all_planned_duty_employee_ids（areas 有 ids / areas 空 fallback departments）
- load_departments（无 departments / 非 dict / 正常）
- primary_department_for_pkg（空 pid / dept 非 dict / subzones 非 dict / block 非 dict / 命中）
- _candidate_duty_registry_paths（env_root / 多 root）
- load_duty_employee_records（文件不存在 / JSON 错误 / 非 dict / packages 非 list / 正常）
- _read_json（不存在 / 非 dict / 异常）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk import duty_roster


@pytest.fixture(autouse=True)
def _reset_lru_cache() -> None:
    duty_roster.load_duty_roster_document.cache_clear()
    yield
    duty_roster.load_duty_roster_document.cache_clear()


class TestCollectIdsFromBlocks:
    """_collect_ids_from_blocks 分支覆盖。"""

    def test_collects_ids_from_list(self) -> None:
        blocks = {"a": {"ids": ["1", "2", " 3 "]}}
        assert duty_roster._collect_ids_from_blocks(blocks) == ["1", "2", "3"]

    def test_skips_non_dict_block(self) -> None:
        blocks = {"a": "not a dict", "b": {"ids": ["1"]}}
        assert duty_roster._collect_ids_from_blocks(blocks) == ["1"]

    def test_skips_when_ids_not_list(self) -> None:
        blocks = {"a": {"ids": "not a list"}}
        assert duty_roster._collect_ids_from_blocks(blocks) == []

    def test_skips_empty_ids_strings(self) -> None:
        blocks = {"a": {"ids": ["", "  ", "1"]}}
        assert duty_roster._collect_ids_from_blocks(blocks) == ["1"]

    def test_recurses_into_subzones(self) -> None:
        blocks = {
            "a": {
                "ids": ["1"],
                "subzones": {
                    "sub1": {"ids": ["2"]},
                    "sub2": {"ids": ["3"]},
                },
            }
        }
        result = duty_roster._collect_ids_from_blocks(blocks)
        assert sorted(result) == ["1", "2", "3"]

    def test_subzones_not_dict_skipped(self) -> None:
        blocks = {"a": {"ids": ["1"], "subzones": "not a dict"}}
        assert duty_roster._collect_ids_from_blocks(blocks) == ["1"]

    def test_empty_blocks(self) -> None:
        assert duty_roster._collect_ids_from_blocks({}) == []


class TestLoadDutyRosterDocument:
    """load_duty_roster_document 分支覆盖。"""

    def test_returns_default_when_cfg_none(self) -> None:
        with patch("app.mod_sdk.duty_roster.resolve_fhd_config_dir", return_value=None):
            doc = duty_roster.load_duty_roster_document()
            assert doc == {"schema_version": 1, "areas": {}}

    def test_returns_default_when_doc_empty(self) -> None:
        with (
            patch("app.mod_sdk.duty_roster.resolve_fhd_config_dir", return_value=Path("/x")),
            patch("app.mod_sdk.duty_roster._read_json", return_value=None),
        ):
            doc = duty_roster.load_duty_roster_document()
            assert doc == {"schema_version": 1, "areas": {}}

    def test_returns_default_when_doc_no_areas_no_departments(self) -> None:
        with (
            patch("app.mod_sdk.duty_roster.resolve_fhd_config_dir", return_value=Path("/x")),
            patch("app.mod_sdk.duty_roster._read_json", return_value={"schema_version": 2}),
        ):
            doc = duty_roster.load_duty_roster_document()
            assert doc == {"schema_version": 1, "areas": {}}

    def test_returns_doc_when_areas_present(self) -> None:
        fake_doc = {"areas": {"a": {"ids": ["1"]}}, "departments": {}}
        with (
            patch("app.mod_sdk.duty_roster.resolve_fhd_config_dir", return_value=Path("/x")),
            patch("app.mod_sdk.duty_roster._read_json", return_value=fake_doc),
        ):
            doc = duty_roster.load_duty_roster_document()
            assert doc == fake_doc

    def test_returns_doc_when_departments_present(self) -> None:
        fake_doc = {"departments": {"d": {"ids": ["1"]}}}
        with (
            patch("app.mod_sdk.duty_roster.resolve_fhd_config_dir", return_value=Path("/x")),
            patch("app.mod_sdk.duty_roster._read_json", return_value=fake_doc),
        ):
            doc = duty_roster.load_duty_roster_document()
            assert doc == fake_doc


class TestAllPlannedDutyEmployeeIds:
    """all_planned_duty_employee_ids 分支覆盖。"""

    def test_collects_from_areas(self) -> None:
        fake_doc = {"areas": {"a": {"ids": ["1", "2"]}}, "departments": {}}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            ids = duty_roster.all_planned_duty_employee_ids()
            assert ids == frozenset({"1", "2"})

    def test_falls_back_to_departments_when_areas_empty(self) -> None:
        fake_doc = {"areas": {}, "departments": {"d": {"ids": ["3", "4"]}}}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            ids = duty_roster.all_planned_duty_employee_ids()
            assert ids == frozenset({"3", "4"})

    def test_returns_empty_when_no_areas_no_departments(self) -> None:
        fake_doc = {"areas": {}, "departments": {}}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            assert duty_roster.all_planned_duty_employee_ids() == frozenset()

    def test_areas_not_dict_returns_empty(self) -> None:
        fake_doc = {"areas": "not a dict", "departments": "not a dict"}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            assert duty_roster.all_planned_duty_employee_ids() == frozenset()

    def test_departments_not_dict_skipped(self) -> None:
        fake_doc = {"areas": {}, "departments": "not a dict"}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            assert duty_roster.all_planned_duty_employee_ids() == frozenset()


class TestLoadDepartments:
    """load_departments 分支覆盖。"""

    def test_returns_departments_when_dict(self) -> None:
        fake_doc = {"departments": {"d": {"ids": ["1"]}}}
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value=fake_doc):
            assert duty_roster.load_departments() == {"d": {"ids": ["1"]}}

    def test_returns_empty_when_no_departments(self) -> None:
        with patch("app.mod_sdk.duty_roster.load_duty_roster_document", return_value={}):
            assert duty_roster.load_departments() == {}

    def test_returns_empty_when_departments_not_dict(self) -> None:
        with patch(
            "app.mod_sdk.duty_roster.load_duty_roster_document",
            return_value={"departments": "not a dict"},
        ):
            assert duty_roster.load_departments() == {}


class TestPrimaryDepartmentForPkg:
    """primary_department_for_pkg 分支覆盖。"""

    def test_empty_pid_returns_none(self) -> None:
        assert duty_roster.primary_department_for_pkg("") is None
        assert duty_roster.primary_department_for_pkg(None) is None
        assert duty_roster.primary_department_for_pkg("  ") is None

    def test_dept_not_dict_skipped(self) -> None:
        fake_depts = {"d1": "not a dict", "d2": {"five_line_id": "L2", "subzones": {}}}
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") is None

    def test_subzones_not_dict_skipped(self) -> None:
        fake_depts = {"d1": {"five_line_id": "L1", "subzones": "not a dict"}}
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") is None

    def test_block_not_dict_skipped(self) -> None:
        fake_depts = {
            "d1": {
                "five_line_id": "L1",
                "subzones": {"b1": "not a dict", "b2": {"ids": ["p1"]}},
            }
        }
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") == "L1"

    def test_ids_not_list_skipped(self) -> None:
        fake_depts = {"d1": {"five_line_id": "L1", "subzones": {"b1": {"ids": "p1"}}}}
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") is None

    def test_returns_five_line_id_when_found(self) -> None:
        fake_depts = {
            "d1": {
                "five_line_id": "LINE_A",
                "subzones": {"b1": {"ids": ["p1", "p2"]}},
            }
        }
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") == "LINE_A"

    def test_falls_back_to_dept_key_when_no_five_line_id(self) -> None:
        fake_depts = {"d_key": {"subzones": {"b1": {"ids": ["p1"]}}}}
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") == "d_key"

    def test_returns_none_when_pid_not_found(self) -> None:
        fake_depts = {"d1": {"five_line_id": "L1", "subzones": {"b1": {"ids": ["p2"]}}}}
        with patch("app.mod_sdk.duty_roster.load_departments", return_value=fake_depts):
            assert duty_roster.primary_department_for_pkg("p1") is None


class TestCandidateDutyRegistryPaths:
    """_candidate_duty_registry_paths 分支覆盖。"""

    def test_includes_env_root_when_set(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"MODSTORE_DEPLOY_ROOT": str(tmp_path)}):
            paths = duty_roster._candidate_duty_registry_paths()
            assert any(str(tmp_path) in str(p) for p in paths)

    def test_excludes_env_root_when_empty(self) -> None:
        with patch.dict("os.environ", {"MODSTORE_DEPLOY_ROOT": ""}, clear=False):
            paths = duty_roster._candidate_duty_registry_paths()
            assert len(paths) >= 2

    def test_returns_multiple_paths(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            paths = duty_roster._candidate_duty_registry_paths()
            assert len(paths) >= 2
            for p in paths:
                assert p.name == "duty_employee_registry.json"


class TestLoadDutyEmployeeRecords:
    """load_duty_employee_records 分支覆盖。"""

    def test_returns_empty_when_no_files_exist(self) -> None:
        with patch(
            "app.mod_sdk.duty_roster._candidate_duty_registry_paths",
            return_value=[Path("/nonexistent/path1.json"), Path("/nonexistent/path2.json")],
        ):
            assert duty_roster.load_duty_employee_records() == []

    def test_returns_empty_when_json_invalid(self, tmp_path: Path) -> None:
        bad = tmp_path / "registry.json"
        bad.write_text("not json {")
        with patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[bad]):
            assert duty_roster.load_duty_employee_records() == []

    def test_returns_empty_when_raw_not_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "registry.json"
        f.write_text(json.dumps(["not a dict"]))
        with patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[f]):
            assert duty_roster.load_duty_employee_records() == []

    def test_returns_empty_when_packages_not_list(self, tmp_path: Path) -> None:
        f = tmp_path / "registry.json"
        f.write_text(json.dumps({"packages": "not a list"}))
        with patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[f]):
            assert duty_roster.load_duty_employee_records() == []

    def test_filters_non_dict_packages(self, tmp_path: Path) -> None:
        f = tmp_path / "registry.json"
        f.write_text(json.dumps({"packages": [{"id": 1}, "skip me", {"id": 2}]}))
        with patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[f]):
            records = duty_roster.load_duty_employee_records()
            assert len(records) == 2
            assert records[0] == {"id": 1}

    def test_skips_first_file_falls_to_second(self, tmp_path: Path) -> None:
        f1 = tmp_path / "r1.json"
        f2 = tmp_path / "r2.json"
        f1.write_text("invalid json")
        f2.write_text(json.dumps({"packages": [{"id": 99}]}))
        with patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[f1, f2]):
            records = duty_roster.load_duty_employee_records()
            assert records == [{"id": 99}]

    def test_handles_os_error(self, tmp_path: Path) -> None:
        f = tmp_path / "registry.json"
        f.write_text(json.dumps({"packages": []}))
        with (
            patch("app.mod_sdk.duty_roster._candidate_duty_registry_paths", return_value=[f]),
            patch("pathlib.Path.is_file", side_effect=OSError("boom")),
        ):
            assert duty_roster.load_duty_employee_records() == []


class TestReadJson:
    """_read_json 分支覆盖。"""

    def test_returns_none_when_not_file(self, tmp_path: Path) -> None:
        result = duty_roster._read_json(tmp_path / "missing.json")
        assert result is None

    def test_returns_none_when_not_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "x.json"
        f.write_text(json.dumps(["list"]))
        assert duty_roster._read_json(f) is None

    def test_returns_dict_when_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"a": 1}))
        assert duty_roster._read_json(f) == {"a": 1}

    def test_returns_none_on_recoverable_error(self, tmp_path: Path) -> None:
        f = tmp_path / "x.json"
        f.write_text("invalid")
        with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
            assert duty_roster._read_json(f) is None
