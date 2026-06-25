"""真实行为测试：app/mod_sdk/duty_roster.py 第二波覆盖。

覆盖未命中行：
- _collect_ids_from_blocks 非 dict block 跳过(19) + subzones 递归(25)
- load_duty_roster_document 配置缺失/无 areas&departments → 回退(36)
- all_planned_duty_employee_ids departments 回退分支(46-48)
- primary_department_for_pkg 空 pid / 非 dict dept / 命中 / 未命中(60-76)
- _candidate_duty_registry_paths 环境变量 + 默认根路径(81-94)
- load_duty_employee_records 文件迭代/packages 解析/OSError|JSONDecodeError(104-114)
- _read_json 文件缺失/非 dict/RECOVERABLE_ERRORS(120,123-124)

所有外部依赖(配置目录解析/文件系统/环境变量)均通过 monkeypatch + tmp_path 隔离，
确定性、离线、快速；不依赖任何 ML 重依赖。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mod_sdk import duty_roster as dr


def _clear_roster_cache() -> None:
    """清空 load_duty_roster_document 的 lru_cache（被 monkeypatch 替换时安全跳过）。"""
    fn = dr.load_duty_roster_document
    clear = getattr(fn, "cache_clear", None)
    if callable(clear):
        clear()


@pytest.fixture(autouse=True)
def _clear_doc_cache():
    """load_duty_roster_document 带 lru_cache，每个用例前后清空确保确定性。"""
    _clear_roster_cache()
    yield
    _clear_roster_cache()


# ── _collect_ids_from_blocks ────────────────────────────────────────────────
class TestCollectIdsFromBlocks:
    def test_non_dict_block_is_skipped(self):
        # block 为非 dict(列表/字符串) → continue(line 19)，仅收集合法 dict 的 ids
        blocks = {
            "bad_list": ["e_should_not_appear"],
            "bad_str": "nope",
            "good": {"ids": ["e1", "e2"]},
        }
        assert dr._collect_ids_from_blocks(blocks) == ["e1", "e2"]

    def test_ids_stripped_and_empty_dropped(self):
        blocks = {"z": {"ids": ["  e1  ", "", "   ", "e2"]}}
        assert dr._collect_ids_from_blocks(blocks) == ["e1", "e2"]

    def test_non_list_ids_ignored(self):
        blocks = {"z": {"ids": "notalist"}}
        assert dr._collect_ids_from_blocks(blocks) == []

    def test_subzones_recursion(self):
        # subzones 为 dict → 递归收集(line 25)
        blocks = {
            "dept": {
                "ids": ["top1"],
                "subzones": {
                    "z1": {"ids": ["sub1", "sub2"]},
                    "z2": {"ids": ["sub3"]},
                },
            }
        }
        assert dr._collect_ids_from_blocks(blocks) == ["top1", "sub1", "sub2", "sub3"]

    def test_subzones_non_dict_not_recursed(self):
        blocks = {"dept": {"ids": ["a"], "subzones": ["not", "dict"]}}
        assert dr._collect_ids_from_blocks(blocks) == ["a"]


# ── load_duty_roster_document ───────────────────────────────────────────────
class TestLoadDutyRosterDocument:
    def test_returns_doc_when_areas_present(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config"
        cfg.mkdir()
        doc = {"schema_version": 2, "areas": {"a": {"ids": ["e1"]}}}
        (cfg / "duty_roster.json").write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setattr(dr, "resolve_fhd_config_dir", lambda: cfg)
        dr.load_duty_roster_document.cache_clear()

        out = dr.load_duty_roster_document()
        assert out == doc
        assert out["areas"] == {"a": {"ids": ["e1"]}}

    def test_returns_doc_when_departments_present(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config"
        cfg.mkdir()
        doc = {"schema_version": 1, "departments": {"d": {"five_line_id": "L1"}}}
        (cfg / "duty_roster.json").write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setattr(dr, "resolve_fhd_config_dir", lambda: cfg)
        dr.load_duty_roster_document.cache_clear()

        out = dr.load_duty_roster_document()
        assert out["departments"] == {"d": {"five_line_id": "L1"}}

    def test_fallback_when_config_dir_none(self, monkeypatch):
        # resolve_fhd_config_dir 返回 None → 回退默认文档(line 36)
        monkeypatch.setattr(dr, "resolve_fhd_config_dir", lambda: None)
        dr.load_duty_roster_document.cache_clear()

        out = dr.load_duty_roster_document()
        assert out == {"schema_version": 1, "areas": {}}

    def test_fallback_when_doc_lacks_areas_and_departments(self, monkeypatch, tmp_path):
        # 文件存在但既无 areas 也无 departments dict → 回退(line 34→36)
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "duty_roster.json").write_text(
            json.dumps({"schema_version": 1, "areas": "notadict"}), encoding="utf-8"
        )
        monkeypatch.setattr(dr, "resolve_fhd_config_dir", lambda: cfg)
        dr.load_duty_roster_document.cache_clear()

        out = dr.load_duty_roster_document()
        assert out == {"schema_version": 1, "areas": {}}

    def test_fallback_when_file_missing(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config"
        cfg.mkdir()  # 目录存在但无 duty_roster.json
        monkeypatch.setattr(dr, "resolve_fhd_config_dir", lambda: cfg)
        dr.load_duty_roster_document.cache_clear()

        assert dr.load_duty_roster_document() == {"schema_version": 1, "areas": {}}


# ── all_planned_duty_employee_ids ───────────────────────────────────────────
class TestAllPlannedDutyEmployeeIds:
    def test_collects_from_areas(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_duty_roster_document",
            lambda: {"areas": {"a": {"ids": ["e1", "e2"]}}},
        )
        assert dr.all_planned_duty_employee_ids() == frozenset({"e1", "e2"})

    def test_falls_back_to_departments_when_no_area_ids(self, monkeypatch):
        # areas 为空 → 回退 departments(line 45-48)
        monkeypatch.setattr(
            dr,
            "load_duty_roster_document",
            lambda: {
                "areas": {},
                "departments": {"d": {"ids": ["dx", "dy"]}},
            },
        )
        assert dr.all_planned_duty_employee_ids() == frozenset({"dx", "dy"})

    def test_departments_non_dict_yields_empty(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_duty_roster_document",
            lambda: {"areas": {}, "departments": ["not", "dict"]},
        )
        assert dr.all_planned_duty_employee_ids() == frozenset()

    def test_areas_non_dict_then_departments_used(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_duty_roster_document",
            lambda: {"areas": "bad", "departments": {"d": {"ids": ["z1"]}}},
        )
        assert dr.all_planned_duty_employee_ids() == frozenset({"z1"})

    def test_empty_doc_returns_empty_frozenset(self, monkeypatch):
        monkeypatch.setattr(dr, "load_duty_roster_document", lambda: {})
        assert dr.all_planned_duty_employee_ids() == frozenset()


# ── load_departments ────────────────────────────────────────────────────────
class TestLoadDepartments:
    def test_returns_departments_dict(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_duty_roster_document",
            lambda: {"departments": {"d": {"five_line_id": "L1"}}},
        )
        assert dr.load_departments() == {"d": {"five_line_id": "L1"}}

    def test_non_dict_departments_returns_empty(self, monkeypatch):
        monkeypatch.setattr(dr, "load_duty_roster_document", lambda: {"departments": ["x"]})
        assert dr.load_departments() == {}

    def test_missing_departments_returns_empty(self, monkeypatch):
        monkeypatch.setattr(dr, "load_duty_roster_document", lambda: {})
        assert dr.load_departments() == {}


# ── primary_department_for_pkg ──────────────────────────────────────────────
class TestPrimaryDepartmentForPkg:
    def test_empty_pkg_id_returns_none(self):
        assert dr.primary_department_for_pkg("") is None
        assert dr.primary_department_for_pkg("   ") is None
        assert dr.primary_department_for_pkg(None) is None  # type: ignore[arg-type]

    def test_match_returns_five_line_id(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {
                "dept_a": {
                    "five_line_id": "FIVE_A",
                    "subzones": {"z1": {"ids": ["pkgX", "pkgY"]}},
                }
            },
        )
        assert dr.primary_department_for_pkg("pkgX") == "FIVE_A"

    def test_match_falls_back_to_dept_key_when_no_five_line(self, monkeypatch):
        # five_line_id 缺失 → 用 dept_key(line 66)
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {"dept_key_b": {"subzones": {"z": {"ids": ["pkgZ"]}}}},
        )
        assert dr.primary_department_for_pkg("pkgZ") == "dept_key_b"

    def test_strips_pkg_id_before_match(self, monkeypatch):
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {"d": {"five_line_id": "L", "subzones": {"z": {"ids": ["pkgX"]}}}},
        )
        assert dr.primary_department_for_pkg("  pkgX  ") == "L"

    def test_non_dict_dept_skipped(self, monkeypatch):
        # dept 为非 dict → continue(line 64-65)，命中后续合法 dept
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {
                "bad": ["not", "a", "dict"],
                "good": {"five_line_id": "G", "subzones": {"z": {"ids": ["p1"]}}},
            },
        )
        assert dr.primary_department_for_pkg("p1") == "G"

    def test_non_dict_subzones_skipped(self, monkeypatch):
        # subzones 非 dict → continue(line 68-69) → 未命中返回 None
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {"d": {"five_line_id": "L", "subzones": ["bad"]}},
        )
        assert dr.primary_department_for_pkg("anything") is None

    def test_non_dict_block_skipped(self, monkeypatch):
        # subzones 内 block 非 dict → continue(line 71-72)
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {
                "d": {
                    "five_line_id": "L",
                    "subzones": {"bad_block": ["x"], "ok": {"ids": ["p2"]}},
                }
            },
        )
        assert dr.primary_department_for_pkg("p2") == "L"

    def test_non_list_ids_no_match(self, monkeypatch):
        # block.ids 非 list → 不命中(line 73-74) → None
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {"d": {"five_line_id": "L", "subzones": {"z": {"ids": "p3"}}}},
        )
        assert dr.primary_department_for_pkg("p3") is None

    def test_no_match_returns_none(self, monkeypatch):
        # 遍历完所有部门未命中 → None(line 76)
        monkeypatch.setattr(
            dr,
            "load_departments",
            lambda: {"d": {"five_line_id": "L", "subzones": {"z": {"ids": ["other"]}}}},
        )
        assert dr.primary_department_for_pkg("missing") is None

    def test_empty_departments_returns_none(self, monkeypatch):
        monkeypatch.setattr(dr, "load_departments", lambda: {})
        assert dr.primary_department_for_pkg("anything") is None


# ── _candidate_duty_registry_paths ──────────────────────────────────────────
class TestCandidateDutyRegistryPaths:
    _TAIL = ("modstore_server", "catalog_data", "duty_employee_registry.json")

    def test_env_root_prepended_first(self, monkeypatch, tmp_path):
        # MODSTORE_DEPLOY_ROOT 设置 → 第一条候选路径来自 env(line 84-86)
        env_root = tmp_path / "deploy"
        monkeypatch.setenv("MODSTORE_DEPLOY_ROOT", str(env_root))

        paths = dr._candidate_duty_registry_paths()
        assert paths[0] == env_root.joinpath(*self._TAIL)
        # env 根 + 两条默认根 = 3 条候选
        assert len(paths) == 3

    def test_blank_env_root_skipped(self, monkeypatch):
        # 空/空白 env → 不加入(line 84-85 falsy)，仅两条默认根
        monkeypatch.setenv("MODSTORE_DEPLOY_ROOT", "   ")
        paths = dr._candidate_duty_registry_paths()
        assert len(paths) == 2

    def test_missing_env_root_skipped(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_DEPLOY_ROOT", raising=False)
        paths = dr._candidate_duty_registry_paths()
        assert len(paths) == 2

    def test_all_paths_end_with_registry_tail(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_DEPLOY_ROOT", raising=False)
        paths = dr._candidate_duty_registry_paths()
        for p in paths:
            assert p.name == "duty_employee_registry.json"
            assert p.parts[-3:] == self._TAIL
        # 第二条候选根来自 Path.cwd()
        assert str(Path.cwd()) in str(paths[-1])


# ── load_duty_employee_records ──────────────────────────────────────────────
class TestLoadDutyEmployeeRecords:
    def _write_registry(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_returns_packages_from_first_valid_file(self, monkeypatch, tmp_path):
        target = tmp_path / "reg.json"
        self._write_registry(
            target,
            {"packages": [{"id": "p1"}, {"id": "p2"}, "not_a_dict", 5]},
        )
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [target])

        out = dr.load_duty_employee_records()
        # 仅保留 dict 元素(line 111)
        assert out == [{"id": "p1"}, {"id": "p2"}]

    def test_skips_missing_files_then_loads(self, monkeypatch, tmp_path):
        missing = tmp_path / "nope.json"
        target = tmp_path / "reg.json"
        self._write_registry(target, {"packages": [{"id": "x"}]})
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [missing, target])

        # 第一个不存在 → continue(line 106-107)，第二个命中
        assert dr.load_duty_employee_records() == [{"id": "x"}]

    def test_non_dict_root_yields_empty_packages(self, monkeypatch, tmp_path):
        target = tmp_path / "reg.json"
        self._write_registry(target, ["this", "is", "a", "list"])
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [target])

        # raw 非 dict → packages = [](line 109)，isinstance([], list) → 返回 []
        assert dr.load_duty_employee_records() == []

    def test_packages_not_a_list_skips_to_next(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        good = tmp_path / "good.json"
        self._write_registry(bad, {"packages": {"not": "a list"}})
        self._write_registry(good, {"packages": [{"id": "g"}]})
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [bad, good])

        # bad 的 packages 非 list → 不 return，落到 good
        assert dr.load_duty_employee_records() == [{"id": "g"}]

    def test_malformed_json_is_skipped(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not valid json", encoding="utf-8")
        good = tmp_path / "good.json"
        self._write_registry(good, {"packages": [{"id": "ok"}]})
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [bad, good])

        # JSONDecodeError → except continue(line 112-113)，落到 good
        assert dr.load_duty_employee_records() == [{"id": "ok"}]

    def test_oserror_on_read_is_skipped(self, monkeypatch, tmp_path):
        target = tmp_path / "reg.json"
        self._write_registry(target, {"packages": [{"id": "p"}]})
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [target])

        orig_read = Path.read_text

        def boom(self, *a, **k):
            if self == target:
                raise OSError("disk gone")
            return orig_read(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", boom)
        # OSError → except continue(line 112-113)，无更多候选 → []
        assert dr.load_duty_employee_records() == []

    def test_no_candidates_returns_empty(self, monkeypatch):
        monkeypatch.setattr(dr, "_candidate_duty_registry_paths", lambda: [])
        assert dr.load_duty_employee_records() == []


# ── _read_json ──────────────────────────────────────────────────────────────
class TestReadJson:
    def test_returns_dict_payload(self, tmp_path):
        p = tmp_path / "doc.json"
        p.write_text(json.dumps({"k": "v"}), encoding="utf-8")
        assert dr._read_json(p) == {"k": "v"}

    def test_missing_file_returns_none(self, tmp_path):
        # 文件不存在 → None(line 119-120)
        assert dr._read_json(tmp_path / "nope.json") is None

    def test_non_dict_payload_returns_none(self, tmp_path):
        # JSON 顶层非 dict → None(line 122)
        p = tmp_path / "list.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert dr._read_json(p) is None

    def test_malformed_json_returns_none(self, tmp_path):
        # JSONDecodeError ∈ RECOVERABLE_ERRORS → None(line 123-124)
        p = tmp_path / "broken.json"
        p.write_text("{bad json", encoding="utf-8")
        assert dr._read_json(p) is None

    def test_oserror_returns_none(self, tmp_path, monkeypatch):
        # OSError ∈ RECOVERABLE_ERRORS → None(line 123-124)
        p = tmp_path / "doc.json"
        p.write_text("{}", encoding="utf-8")

        def boom(self, *a, **k):
            raise OSError("io error")

        monkeypatch.setattr(Path, "read_text", boom)
        assert dr._read_json(p) is None
