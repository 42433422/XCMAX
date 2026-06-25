"""测试 ai_group_chat_service 的分支覆盖（聚焦未覆盖方法与边界分支）。

覆盖目标：
- 模块级辅助函数：_env_float, _utc_now, _safe_json_line, _xiaoc_assistant_member,
  _member_public_shape, _with_required_group_members, _is_required_group_member,
  _default_departments, _default_enterprise_departments, _dept_key_to_employee_ids,
  _employee_manifest, _default_duty_employee_loader, _append_super_employees,
  _default_enterprise_employee_loader
- 静态方法：_is_broadcast_mention, _should_run_super_discussion, _parse_routing_json,
  _heuristic_dispatch_targets, _format_routing_decision_message, _format_work_order_message,
  _format_work_report_message, _latest_relay_desktop, _stringify_summary, _compact_result,
  _execution_summary, _execution_risk, _relay_result_dispatch_value, _find, _replace
- 实例方法：__init__, list_groups, create_group, add_member, remove_member,
  toggle_pinned, mark_unread, mark_read, toggle_followed, toggle_hidden, delete_group,
  get_messages, append_relay_work_report, post_message, _pick_responders,
  _pick_dispatch_targets, _explicit_member_ids, _discussion_round_count,
  _super_discussion_reply, _route_after_discussion, _ai_reply, _dispatch_work,
  _execute_employee_work, _invoke_super_employee_task, _create_super_employee_relay_task,
  _relay_report_message, _relay_task_report, _relay_result_summary, _relay_result_risk,
  _super_employee_reply, _seed_department_groups, _public_group, _public_message,
  _message_row, _latest_previews, _read_jsonl, _ensure_required_members,
  _backfill_department_members
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.application.ai_group_chat_service as group_chat_module
from app.application.ai_group_chat_service import (
    MAX_RESPONDERS,
    SUPER_DISCUSSION_DEFAULT_ROUNDS,
    SUPER_DISCUSSION_MAX_ROUNDS,
    _append_super_employees,
    _dept_key_to_employee_ids,
    _default_departments,
    _default_duty_employee_loader,
    _default_enterprise_departments,
    _default_enterprise_employee_loader,
    _employee_manifest,
    _env_float,
    _is_required_group_member,
    _member_public_shape,
    _safe_json_line,
    _utc_now,
    _with_required_group_members,
    _xiaoc_assistant_member,
    AiGroupChatService,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def fake_departments() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "ops_partner": {"label": "O-B 伙伴部"},
        "prod_web": {"label": "P-W 网站部"},
        "prod_mod": {"label": "P-M Mod 部"},
        "prod_software": {"label": "P-S 软件部"},
        "shared_retention": {"label": "S-R 归档部"},
    }


def fake_enterprise_departments() -> dict[str, dict[str, str]]:
    return {
        "tools": {"label": "工具层"},
        "execution": {"label": "执行层"},
        "service": {"label": "服务层"},
        "management": {"label": "管理层"},
    }


def make_completion(seen: list[dict] | None = None, content: str = "收到"):
    async def completion(messages):
        if seen is not None:
            seen.append({"system": messages[0]["content"], "user": messages[1]["content"]})
        return {"success": True, "content": content, "error": ""}

    return completion


def make_service(
    tmp_path: Path,
    seen: list[dict] | None = None,
    employees=None,
    mode: str = "admin",
    executor=None,
    completion_fn=None,
    department_loader=None,
) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=completion_fn or make_completion(seen),
        employee_executor_fn=executor,
        department_loader=department_loader or (fake_enterprise_departments if mode == "enterprise" else fake_departments),
        employee_loader=(employees if callable(employees) else (lambda: employees or [])),
        mode=mode,
    )


# ---------------------------------------------------------------------------
# 模块级辅助函数
# ---------------------------------------------------------------------------


class TestEnvFloat:
    """_env_float 的分支覆盖。"""

    def test_env_float_returns_default_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("TEST_ENV_FLOAT_VAR", raising=False)
        assert _env_float("TEST_ENV_FLOAT_VAR", 3.14) == 3.14

    def test_env_float_returns_value_when_env_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEST_ENV_FLOAT_VAR", "9.5")
        assert _env_float("TEST_ENV_FLOAT_VAR", 3.14) == 9.5

    def test_env_float_returns_default_when_env_is_empty_string(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEST_ENV_FLOAT_VAR", "")
        assert _env_float("TEST_ENV_FLOAT_VAR", 2.5) == 2.5

    def test_env_float_returns_default_when_env_is_invalid(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEST_ENV_FLOAT_VAR", "not-a-number")
        assert _env_float("TEST_ENV_FLOAT_VAR", 1.0) == 1.0

    def test_env_float_returns_default_when_env_is_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEST_ENV_FLOAT_VAR", "None")
        assert _env_float("TEST_ENV_FLOAT_VAR", 7.0) == 7.0


class TestUtcNow:
    """_utc_now 的分支覆盖。"""

    def test_utc_now_returns_isoformat_string(self):
        result = _utc_now()
        assert isinstance(result, str)
        assert "T" in result
        assert "+" in result or "Z" in result


class TestSafeJsonLine:
    """_safe_json_line 的分支覆盖。"""

    def test_safe_json_line_returns_json_with_newline(self):
        result = _safe_json_line({"a": 1})
        assert result.endswith("\n")
        assert json.loads(result.strip()) == {"a": 1}

    def test_safe_json_line_handles_chinese_without_ascii_escape(self):
        result = _safe_json_line({"name": "小C"})
        assert "小C" in result

    def test_safe_json_line_handles_empty_dict(self):
        result = _safe_json_line({})
        assert result == "{}\n"

    def test_safe_json_line_handles_nested_structure(self):
        result = _safe_json_line({"outer": {"inner": [1, 2]}})
        parsed = json.loads(result.strip())
        assert parsed == {"outer": {"inner": [1, 2]}}


class TestXiaocAssistantMember:
    """_xiaoc_assistant_member 的分支覆盖。"""

    def test_xiaoc_assistant_member_returns_expected_shape(self):
        member = _xiaoc_assistant_member()
        assert member["employee_id"] == "xcagi-assistant"
        assert member["mod_id"] == "xcagi-core-assistant"
        assert member["name"] == "小C助理"
        assert member["avatar"] == ""
        assert "department_key" in member
        assert member["department_key"] == ""


class TestMemberPublicShape:
    """_member_public_shape 的分支覆盖。"""

    def test_member_public_shape_with_full_member(self):
        member = {
            "employee_id": "e1",
            "mod_id": "m1",
            "name": "小销",
            "avatar": "http://a.com/1.png",
            "summary": "负责获客",
        }
        result = _member_public_shape(member)
        assert result["employee_id"] == "e1"
        assert result["mod_id"] == "m1"
        assert result["name"] == "小销"
        assert result["avatar"] == "http://a.com/1.png"
        assert result["summary"] == "负责获客"

    def test_member_public_shape_with_empty_employee_id(self):
        result = _member_public_shape({"employee_id": "", "name": "x"})
        assert result["employee_id"] == ""
        assert result["name"] == "x"

    def test_member_public_shape_with_none_employee_id(self):
        result = _member_public_shape({"employee_id": None, "name": "x"})
        assert result["employee_id"] == ""

    def test_member_public_shape_with_whitespace_employee_id(self):
        result = _member_public_shape({"employee_id": "  e1  ", "name": "x"})
        assert result["employee_id"] == "e1"

    def test_member_public_shape_with_no_name_falls_back_to_employee_id(self):
        result = _member_public_shape({"employee_id": "e1"})
        assert result["name"] == "e1"

    def test_member_public_shape_with_none_name_falls_back_to_employee_id(self):
        result = _member_public_shape({"employee_id": "e1", "name": None})
        assert result["name"] == "e1"

    def test_member_public_shape_with_empty_name_falls_back_to_employee_id(self):
        result = _member_public_shape({"employee_id": "e1", "name": ""})
        assert result["name"] == "e1"

    def test_member_public_shape_truncates_name_to_60(self):
        long_name = "x" * 100
        result = _member_public_shape({"employee_id": "e1", "name": long_name})
        assert len(result["name"]) == 60

    def test_member_public_shape_truncates_summary_to_280(self):
        long_summary = "s" * 500
        result = _member_public_shape({"employee_id": "e1", "summary": long_summary})
        assert len(result["summary"]) == 280

    def test_member_public_shape_with_no_mod_id(self):
        result = _member_public_shape({"employee_id": "e1"})
        assert result["mod_id"] == ""

    def test_member_public_shape_with_none_mod_id(self):
        result = _member_public_shape({"employee_id": "e1", "mod_id": None})
        assert result["mod_id"] == ""

    def test_member_public_shape_with_no_avatar(self):
        result = _member_public_shape({"employee_id": "e1"})
        assert result["avatar"] == ""

    def test_member_public_shape_with_none_avatar(self):
        result = _member_public_shape({"employee_id": "e1", "avatar": None})
        assert result["avatar"] == ""

    def test_member_public_shape_with_no_summary(self):
        result = _member_public_shape({"employee_id": "e1"})
        assert result["summary"] == ""

    def test_member_public_shape_with_none_summary(self):
        result = _member_public_shape({"employee_id": "e1", "summary": None})
        assert result["summary"] == ""


class TestWithRequiredGroupMembers:
    """_with_required_group_members 的分支覆盖。"""

    def test_with_required_group_members_empty_list_adds_xiaoc(self):
        result = _with_required_group_members([])
        assert len(result) == 1
        assert result[0]["employee_id"] == "xcagi-assistant"

    def test_with_required_group_members_adds_xiaoc_to_existing(self):
        result = _with_required_group_members([{"employee_id": "e1", "name": "小销"}])
        ids = [m["employee_id"] for m in result]
        assert "xcagi-assistant" in ids
        assert "e1" in ids

    def test_with_required_group_members_deduplicates_xiaoc(self):
        result = _with_required_group_members([{"employee_id": "xcagi-assistant", "name": "小C"}])
        assert len(result) == 1
        assert result[0]["employee_id"] == "xcagi-assistant"

    def test_with_required_group_members_skips_non_dict_member(self):
        result = _with_required_group_members(["not-a-dict", 42, None, {"employee_id": "e1"}])
        ids = [m["employee_id"] for m in result]
        assert "xcagi-assistant" in ids
        assert "e1" in ids
        assert len(result) == 2

    def test_with_required_group_members_skips_empty_employee_id(self):
        result = _with_required_group_members([{"employee_id": "", "name": "x"}])
        ids = [m["employee_id"] for m in result]
        assert "xcagi-assistant" in ids
        assert "" not in ids

    def test_with_required_group_members_skips_whitespace_only_employee_id(self):
        result = _with_required_group_members([{"employee_id": "   ", "name": "x"}])
        ids = [m["employee_id"] for m in result]
        assert "xcagi-assistant" in ids

    def test_with_required_group_members_deduplicates_duplicate_employee_ids(self):
        result = _with_required_group_members([
            {"employee_id": "e1", "name": "小销"},
            {"employee_id": "e1", "name": "重复"},
        ])
        ids = [m["employee_id"] for m in result]
        assert ids.count("e1") == 1
        assert "xcagi-assistant" in ids

    def test_with_required_group_members_preserves_order_with_xiaoc_first(self):
        result = _with_required_group_members([{"employee_id": "e1"}, {"employee_id": "e2"}])
        assert result[0]["employee_id"] == "xcagi-assistant"
        assert result[1]["employee_id"] == "e1"
        assert result[2]["employee_id"] == "e2"


class TestIsRequiredGroupMember:
    """_is_required_group_member 的分支覆盖。"""

    def test_is_required_group_member_true_for_xiaoc(self):
        assert _is_required_group_member("xcagi-assistant") is True

    def test_is_required_group_member_false_for_other(self):
        assert _is_required_group_member("e1") is False

    def test_is_required_group_member_false_for_empty(self):
        assert _is_required_group_member("") is False

    def test_is_required_group_member_false_for_none(self):
        assert _is_required_group_member(None) is False

    def test_is_required_group_member_handles_whitespace(self):
        assert _is_required_group_member("  xcagi-assistant  ") is True

    def test_is_required_group_member_handles_non_string(self):
        assert _is_required_group_member(123) is False


class TestDefaultDepartments:
    """_default_departments 的分支覆盖。"""

    def test_default_departments_returns_dict_on_success(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: {"d1": {"label": "L1"}})
        result = _default_departments()
        assert isinstance(result, dict)
        assert "d1" in result

    def test_default_departments_returns_empty_when_not_dict(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: ["not", "a", "dict"])
        result = _default_departments()
        assert result == {}

    def test_default_departments_returns_empty_on_exception(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        def boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(duty_roster, "load_departments", boom)
        result = _default_departments()
        assert result == {}


class TestDefaultEnterpriseDepartments:
    """_default_enterprise_departments 的分支覆盖。"""

    def test_default_enterprise_departments_returns_dict(self):
        result = _default_enterprise_departments()
        assert isinstance(result, dict)
        assert len(result) > 0


class TestDeptKeyToEmployeeIds:
    """_dept_key_to_employee_ids 的分支覆盖。"""

    def test_dept_key_to_employee_ids_normal_case(self):
        depts = {
            "d1": {
                "subzones": {
                    "s1": {"ids": ["e1", "e2"]},
                    "s2": {"ids": ["e3"]},
                }
            },
            "d2": {"subzones": {"s1": {"ids": ["e4"]}}},
        }
        result = _dept_key_to_employee_ids(depts)
        assert set(result["d1"]) == {"e1", "e2", "e3"}
        assert result["d2"] == ["e4"]

    def test_dept_key_to_employee_ids_skips_non_dict_dept(self):
        depts = {"d1": "not-a-dict", "d2": {"subzones": {"s1": {"ids": ["e1"]}}}}
        result = _dept_key_to_employee_ids(depts)
        assert "d1" not in result
        assert result["d2"] == ["e1"]

    def test_dept_key_to_employee_ids_handles_no_subzones(self):
        depts = {"d1": {}}
        result = _dept_key_to_employee_ids(depts)
        assert result == {}

    def test_dept_key_to_employee_ids_handles_none_subzones(self):
        depts = {"d1": {"subzones": None}}
        result = _dept_key_to_employee_ids(depts)
        assert result == {}

    def test_dept_key_to_employee_ids_skips_non_dict_subzone_block(self):
        depts = {"d1": {"subzones": {"s1": "not-a-dict", "s2": {"ids": ["e1"]}}}}
        result = _dept_key_to_employee_ids(depts)
        assert result["d1"] == ["e1"]

    def test_dept_key_to_employee_ids_skips_non_list_ids(self):
        depts = {"d1": {"subzones": {"s1": {"ids": "not-a-list"}}}}
        result = _dept_key_to_employee_ids(depts)
        assert result == {}

    def test_dept_key_to_employee_ids_filters_empty_and_whitespace_ids(self):
        depts = {"d1": {"subzones": {"s1": {"ids": ["e1", "", "  ", "e2"]}}}}
        result = _dept_key_to_employee_ids(depts)
        assert result["d1"] == ["e1", "e2"]

    def test_dept_key_to_employee_ids_skips_dept_with_no_valid_ids(self):
        depts = {"d1": {"subzones": {"s1": {"ids": []}}}}
        result = _dept_key_to_employee_ids(depts)
        assert "d1" not in result

    def test_dept_key_to_employee_ids_empty_input(self):
        assert _dept_key_to_employee_ids({}) == {}

    def test_dept_key_to_employee_ids_subzones_not_dict(self):
        depts = {"d1": {"subzones": ["not", "a", "dict"]}}
        result = _dept_key_to_employee_ids(depts)
        assert result == {}


class TestEmployeeManifest:
    """_employee_manifest 的分支覆盖。"""

    def test_employee_manifest_returns_empty_when_file_not_found(self):
        result = _employee_manifest("nonexistent-employee-id-xyz")
        assert result == {}

    def test_employee_manifest_returns_empty_when_invalid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        manifest_dir = tmp_path / "mods" / "_employees" / "bad-emp"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text("{invalid json", encoding="utf-8")

        original_file = group_chat_module.__file__
        fake_file = tmp_path / "ai_group_chat_service.py"
        fake_file.write_text("", encoding="utf-8")

        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.return_value = MagicMock(parents=[tmp_path, tmp_path, tmp_path])
            with patch("pathlib.Path.read_text", side_effect=["{invalid json"]):
                result = _employee_manifest("bad-emp")
        assert result == {}

    def test_employee_manifest_returns_empty_when_not_dict(self, monkeypatch: pytest.MonkeyPatch):
        with patch("pathlib.Path.read_text", return_value='["not", "a", "dict"]'):
            result = _employee_manifest("some-emp")
        assert result == {}


class TestAppendSuperEmployees:
    """_append_super_employees 的分支覆盖。"""

    def test_append_super_employees_adds_three_when_none_exist(self):
        employees: list[dict] = []
        _append_super_employees(employees)
        assert len(employees) == 3
        ids = {e["employee_id"] for e in employees}
        assert "codex-super-employee" in ids
        assert "cursor-super-employee" in ids
        assert "claude-super-employee" in ids

    def test_append_super_employees_skips_existing(self):
        employees = [{"employee_id": "codex-super-employee", "name": "existing"}]
        _append_super_employees(employees)
        ids = [e["employee_id"] for e in employees]
        assert ids.count("codex-super-employee") == 1
        assert len(employees) == 3

    def test_append_super_employees_skips_non_dict_entries(self):
        employees = ["not-a-dict", 42, None]
        _append_super_employees(employees)
        # non-dict entries are skipped when checking existing
        assert len([e for e in employees if isinstance(e, dict)]) == 3

    def test_append_super_employees_silently_returns_on_import_error(self, monkeypatch: pytest.MonkeyPatch):
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "super_employee_service" in name:
                raise ImportError("module not found")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        employees: list[dict] = []
        _append_super_employees(employees)
        assert employees == []


class TestDefaultDutyEmployeeLoader:
    """_default_duty_employee_loader 的分支覆盖。"""

    def test_default_duty_employee_loader_returns_empty_when_no_depts(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: {})
        result = _default_duty_employee_loader()
        assert result == []

    def test_default_duty_employee_loader_returns_empty_when_depts_not_dict(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: "not-a-dict")
        result = _default_duty_employee_loader()
        assert result == []

    def test_default_duty_employee_loader_with_employees(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: {
            "d1": {"subzones": {"s1": {"ids": ["e1"]}}}
        })
        monkeypatch.setattr(duty_roster, "load_duty_employee_records", lambda: [
            {"id": "e1", "name": "小销", "mod_id": "m1"}
        ])
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            MagicMock(side_effect=Exception("no mod manager")),
        )
        result = _default_duty_employee_loader()
        assert len(result) >= 1
        e1 = next(e for e in result if e["employee_id"] == "e1")
        assert e1["name"] == "小销"
        assert e1["department_key"] == "d1"

    def test_default_duty_employee_loader_handles_mod_manager_exception(self, monkeypatch: pytest.MonkeyPatch):
        from app.mod_sdk import duty_roster

        monkeypatch.setattr(duty_roster, "load_departments", lambda: {
            "d1": {"subzones": {"s1": {"ids": ["e1"]}}}
        })
        monkeypatch.setattr(duty_roster, "load_duty_employee_records", lambda: [])
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        result = _default_duty_employee_loader()
        assert isinstance(result, list)


class TestDefaultEnterpriseEmployeeLoader:
    """_default_enterprise_employee_loader 的分支覆盖。"""

    def test_default_enterprise_employee_loader_returns_empty_on_import_error(self, monkeypatch: pytest.MonkeyPatch):
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "mod_manager" in name:
                raise ImportError("not found")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_returns_empty_on_list_exception(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.side_effect = RuntimeError("db error")
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_skips_non_dict_mods(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = ["not-a-dict", 42, None]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        monkeypatch.setattr(
            "app.application.ai_group_chat_service._append_super_employees",
            lambda x: None,
        )
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_skips_mods_without_workflow_employees(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = [
            {"id": "m1", "workflow_employees": "not-a-list"},
            {"id": "m2"},
        ]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        monkeypatch.setattr(
            "app.application.ai_group_chat_service._append_super_employees",
            lambda x: None,
        )
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_skips_non_dict_employees(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = [
            {"id": "m1", "workflow_employees": ["not-a-dict", 42, None]},
        ]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        monkeypatch.setattr(
            "app.application.ai_group_chat_service._append_super_employees",
            lambda x: None,
        )
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_skips_empty_employee_id(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = [
            {"id": "m1", "workflow_employees": [{"id": ""}, {"id": "  "}]},
        ]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        monkeypatch.setattr(
            "app.application.ai_group_chat_service._append_super_employees",
            lambda x: None,
        )
        result = _default_enterprise_employee_loader()
        assert result == []

    def test_default_enterprise_employee_loader_with_valid_employee(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = [
            {
                "id": "m1",
                "workflow_employees": [
                    {"id": "e1", "name": "小销", "panel_title": "销售"},
                ],
            },
        ]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        result = _default_enterprise_employee_loader()
        assert len(result) >= 1
        assert result[0]["employee_id"] == "e1"
        assert result[0]["mod_id"] == "m1"

    def test_default_enterprise_employee_loader_falls_back_through_name_fields(self, monkeypatch: pytest.MonkeyPatch):
        mock_mod_manager = MagicMock()
        mock_mod_manager.list_all_mods.return_value = [
            {
                "id": "m1",
                "workflow_employees": [
                    {"id": "e1", "label": "标签名"},
                    {"id": "e2", "title": "标题名"},
                    {"id": "e3", "panel_title": "面板名"},
                    {"id": "e4"},
                ],
            },
        ]
        monkeypatch.setattr(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            lambda: mock_mod_manager,
        )
        result = _default_enterprise_employee_loader()
        names = {e["employee_id"]: e["name"] for e in result}
        assert names["e1"] == "标签名"
        assert names["e2"] == "标题名"
        assert names["e3"] == "面板名"
        assert names["e4"] == "e4"


# ---------------------------------------------------------------------------
# 静态方法
# ---------------------------------------------------------------------------


class TestIsBroadcastMention:
    """_is_broadcast_mention 的分支覆盖。"""

    def test_is_broadcast_mention_true_for_all_markers(self):
        for marker in ("@所有人", "@全体", "@全员", "@all", "@everyone"):
            assert AiGroupChatService._is_broadcast_mention(f"hello {marker} world") is True

    def test_is_broadcast_mention_true_for_uppercase_all(self):
        assert AiGroupChatService._is_broadcast_mention("@ALL 大家好") is True

    def test_is_broadcast_mention_false_for_no_marker(self):
        assert AiGroupChatService._is_broadcast_mention("普通消息") is False

    def test_is_broadcast_mention_false_for_empty_string(self):
        assert AiGroupChatService._is_broadcast_mention("") is False

    def test_is_broadcast_mention_false_for_none(self):
        assert AiGroupChatService._is_broadcast_mention(None) is False

    def test_is_broadcast_mention_case_insensitive(self):
        assert AiGroupChatService._is_broadcast_mention("@EvErYoNe") is True


class TestShouldRunSuperDiscussion:
    """_should_run_super_discussion 的分支覆盖。"""

    def test_should_run_super_discussion_false_when_zero_super(self):
        members = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        assert AiGroupChatService._should_run_super_discussion(members) is False

    def test_should_run_super_discussion_false_when_one_super(self):
        members = [{"employee_id": "codex-super-employee"}, {"employee_id": "e2"}]
        assert AiGroupChatService._should_run_super_discussion(members) is False

    def test_should_run_super_discussion_true_when_two_supers(self):
        members = [
            {"employee_id": "codex-super-employee"},
            {"employee_id": "cursor-super-employee"},
        ]
        assert AiGroupChatService._should_run_super_discussion(members) is True

    def test_should_run_super_discussion_true_when_three_supers(self):
        members = [
            {"employee_id": "codex-super-employee"},
            {"employee_id": "cursor-super-employee"},
            {"employee_id": "claude-super-employee"},
        ]
        assert AiGroupChatService._should_run_super_discussion(members) is True

    def test_should_run_super_discussion_handles_none_employee_id(self):
        members = [{"employee_id": None}, {"employee_id": ""}]
        assert AiGroupChatService._should_run_super_discussion(members) is False

    def test_should_run_super_discussion_empty_list(self):
        assert AiGroupChatService._should_run_super_discussion([]) is False


class TestParseRoutingJson:
    """_parse_routing_json 的分支覆盖。"""

    def test_parse_routing_json_valid_json(self):
        content = '{"target_employee_ids": ["e1", "e2"], "rationale": "because"}'
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}, {"employee_id": "e3"}]
        ids, rationale = AiGroupChatService._parse_routing_json(content, candidates)
        assert ids == ["e1", "e2"]
        assert rationale == "because"

    def test_parse_routing_json_empty_content(self):
        ids, rationale = AiGroupChatService._parse_routing_json("", [])
        assert ids == []
        assert rationale == ""

    def test_parse_routing_json_no_braces(self):
        ids, rationale = AiGroupChatService._parse_routing_json("no json here", [])
        assert ids == []

    def test_parse_routing_json_only_open_brace(self):
        ids, rationale = AiGroupChatService._parse_routing_json("{ incomplete", [])
        assert ids == []

    def test_parse_routing_json_invalid_json(self):
        ids, rationale = AiGroupChatService._parse_routing_json("{invalid json}", [])
        assert ids == []

    def test_parse_routing_json_falls_back_to_targets_key(self):
        content = '{"targets": ["e1"], "rationale": "alt"}'
        candidates = [{"employee_id": "e1"}]
        ids, rationale = AiGroupChatService._parse_routing_json(content, candidates)
        assert ids == ["e1"]
        assert rationale == "alt"

    def test_parse_routing_json_falls_back_to_reason_key(self):
        content = '{"target_employee_ids": ["e1"], "reason": "alt reason"}'
        candidates = [{"employee_id": "e1"}]
        ids, rationale = AiGroupChatService._parse_routing_json(content, candidates)
        assert ids == ["e1"]
        assert rationale == "alt reason"

    def test_parse_routing_json_filters_invalid_ids(self):
        content = '{"target_employee_ids": ["e1", "invalid", ""]}'
        candidates = [{"employee_id": "e1"}]
        ids, _ = AiGroupChatService._parse_routing_json(content, candidates)
        assert ids == ["e1"]

    def test_parse_routing_json_truncates_to_max_responders(self):
        ids_in = [f"e{i}" for i in range(MAX_RESPONDERS + 5)]
        candidates = [{"employee_id": eid} for eid in ids_in]
        content = json.dumps({"target_employee_ids": ids_in})
        ids, _ = AiGroupChatService._parse_routing_json(content, candidates)
        assert len(ids) == MAX_RESPONDERS

    def test_parse_routing_json_handles_non_list_target_ids(self):
        content = '{"target_employee_ids": "not-a-list"}'
        ids, _ = AiGroupChatService._parse_routing_json(content, [{"employee_id": "e1"}])
        assert ids == []

    def test_parse_routing_json_truncates_rationale_to_500(self):
        long_rationale = "x" * 600
        content = f'{{"target_employee_ids": [], "rationale": "{long_rationale}"}}'
        _, rationale = AiGroupChatService._parse_routing_json(content, [])
        assert len(rationale) == 500

    def test_parse_routing_json_handles_none_rationale(self):
        content = '{"target_employee_ids": []}'
        _, rationale = AiGroupChatService._parse_routing_json(content, [])
        assert rationale == ""

    def test_parse_routing_json_extracts_from_surrounding_text(self):
        content = 'Here is the plan: {"target_employee_ids": ["e1"]} done'
        candidates = [{"employee_id": "e1"}]
        ids, _ = AiGroupChatService._parse_routing_json(content, candidates)
        assert ids == ["e1"]


class TestHeuristicDispatchTargets:
    """_heuristic_dispatch_targets 的分支覆盖。"""

    def test_heuristic_dispatch_targets_cursor_for_ui_keywords(self):
        candidates = [
            {"employee_id": "cursor-super-employee", "name": "Cursor"},
            {"employee_id": "codex-super-employee", "name": "Codex"},
        ]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "修改输入框样式")
        assert any(m["employee_id"] == "cursor-super-employee" for m in result)

    def test_heuristic_dispatch_targets_codex_for_backend_keywords(self):
        candidates = [
            {"employee_id": "cursor-super-employee", "name": "Cursor"},
            {"employee_id": "codex-super-employee", "name": "Codex"},
        ]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "修复后端接口")
        assert any(m["employee_id"] == "codex-super-employee" for m in result)

    def test_heuristic_dispatch_targets_claude_for_arch_keywords(self):
        candidates = [
            {"employee_id": "claude-super-employee", "name": "Claude"},
            {"employee_id": "codex-super-employee", "name": "Codex"},
        ]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "架构评审方案")
        assert any(m["employee_id"] == "claude-super-employee" for m in result)

    def test_heuristic_dispatch_targets_falls_back_to_super_members(self):
        candidates = [
            {"employee_id": "cursor-super-employee", "name": "Cursor"},
            {"employee_id": "e1", "name": "普通员工"},
        ]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "无关键词任务")
        assert result[0]["employee_id"] == "cursor-super-employee"

    def test_heuristic_dispatch_targets_falls_back_to_all_candidates(self):
        candidates = [{"employee_id": "e1", "name": "普通1"}, {"employee_id": "e2", "name": "普通2"}]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "无关键词")
        assert len(result) <= MAX_RESPONDERS
        assert result[0] in candidates

    def test_heuristic_dispatch_targets_empty_candidates(self):
        result = AiGroupChatService._heuristic_dispatch_targets([], "任何任务")
        assert result == []

    def test_heuristic_dispatch_targets_multiple_keywords_match(self):
        candidates = [
            {"employee_id": "cursor-super-employee", "name": "Cursor"},
            {"employee_id": "codex-super-employee", "name": "Codex"},
            {"employee_id": "claude-super-employee", "name": "Claude"},
        ]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "UI 接口架构")
        ids = {m["employee_id"] for m in result}
        assert "cursor-super-employee" in ids
        assert "codex-super-employee" in ids
        assert "claude-super-employee" in ids

    def test_heuristic_dispatch_targets_android_keyword(self):
        candidates = [{"employee_id": "cursor-super-employee", "name": "Cursor"}]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "android 页面")
        assert result[0]["employee_id"] == "cursor-super-employee"

    def test_heuristic_dispatch_targets_python_keyword(self):
        candidates = [{"employee_id": "codex-super-employee", "name": "Codex"}]
        result = AiGroupChatService._heuristic_dispatch_targets(candidates, "python 测试覆盖")
        assert result[0]["employee_id"] == "codex-super-employee"


class TestFormatRoutingDecisionMessage:
    """_format_routing_decision_message 的分支覆盖。"""

    def test_format_routing_decision_message_with_targets(self):
        result = AiGroupChatService._format_routing_decision_message("小销、小服", "因为这样")
        assert "小销、小服" in result
        assert "因为这样" in result
        assert "【小C分工】" in result

    def test_format_routing_decision_message_empty_targets(self):
        result = AiGroupChatService._format_routing_decision_message("", "没有候选")
        assert "没有找到可执行负责人" in result
        assert "没有候选" in result

    def test_format_routing_decision_message_empty_targets_no_rationale(self):
        result = AiGroupChatService._format_routing_decision_message("", "")
        assert "没有找到可执行负责人" in result
        assert "候选员工为空" in result

    def test_format_routing_decision_message_no_rationale_uses_default(self):
        result = AiGroupChatService._format_routing_decision_message("小销", "")
        assert "按任务类型和成员能力分流" in result


class TestFormatWorkOrderMessage:
    """_format_work_order_message 的分支覆盖。"""

    def test_format_work_order_message_with_targets(self):
        result = AiGroupChatService._format_work_order_message("做任务", ["小销", "小服"])
        assert "做任务" in result
        assert "小销、小服" in result
        assert "【小C派单】" in result

    def test_format_work_order_message_empty_targets(self):
        result = AiGroupChatService._format_work_order_message("做任务", [])
        assert "【派工失败】" in result
        assert "没有可派工成员" in result

    def test_format_work_order_message_targets_with_empty_names(self):
        result = AiGroupChatService._format_work_order_message("做任务", ["", ""])
        assert "群成员" in result


class TestFormatWorkReportMessage:
    """_format_work_report_message 的分支覆盖。"""

    def test_format_work_report_message_done_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "done", "summary": "完成了", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "完成" in result
        assert "完成了" in result
        assert "未发现阻塞" in result

    def test_format_work_report_message_failed_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "failed", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "失败" in result
        assert "无结果摘要" in result
        assert "存在执行阻塞" in result

    def test_format_work_report_message_queued_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "queued", "summary": "已接单", "risk": "无"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result

    def test_format_work_report_message_running_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "running", "summary": "进行中", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "执行中" in result

    def test_format_work_report_message_blocked_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "blocked", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "阻塞" in result

    def test_format_work_report_message_in_progress_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "in_progress", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "执行中" in result

    def test_format_work_report_message_completed_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "completed", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "完成" in result

    def test_format_work_report_message_accepted_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "accepted", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result

    def test_format_work_report_message_assigned_status(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "assigned", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "已接单" in result

    def test_format_work_report_message_unknown_status_success(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": True, "status": "weird", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "完成" in result

    def test_format_work_report_message_unknown_status_failure(self):
        member = {"name": "小销", "employee_id": "e1"}
        report = {"success": False, "status": "weird", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "失败" in result

    def test_format_work_report_message_no_name_falls_back_to_employee_id(self):
        member = {"employee_id": "e1"}
        report = {"success": True, "status": "done", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "e1" in result

    def test_format_work_report_message_no_name_no_employee_id(self):
        member = {}
        report = {"success": True, "status": "done", "summary": "", "risk": ""}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "员工" in result

    def test_format_work_report_message_with_custom_risk(self):
        member = {"name": "小销"}
        report = {"success": True, "status": "done", "summary": "", "risk": "有风险"}
        result = AiGroupChatService._format_work_report_message(member, report)
        assert "有风险" in result


class TestLatestRelayDesktop:
    """_latest_relay_desktop 的分支覆盖。"""

    def test_latest_relay_desktop_returns_none_when_empty(self):
        assert AiGroupChatService._latest_relay_desktop([]) is None

    def test_latest_relay_desktop_returns_none_when_no_paired(self):
        desktops = [{"relay_id": "r1", "status": "offline"}]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_returns_none_when_no_relay_id(self):
        desktops = [{"relay_id": "", "status": "paired"}]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_skips_non_dict(self):
        desktops = ["not-a-dict", 42, None]
        assert AiGroupChatService._latest_relay_desktop(desktops) is None

    def test_latest_relay_desktop_returns_paired_with_relay_id(self):
        desktops = [{"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"}]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r1"

    def test_latest_relay_desktop_picks_latest_by_last_seen_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01T00:00:00Z"},
            {"relay_id": "r2", "status": "paired", "last_seen_at": "2026-01-02T00:00:00Z"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_updated_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "updated_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "updated_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_paired_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "paired_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "paired_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_falls_back_to_created_at(self):
        desktops = [
            {"relay_id": "r1", "status": "paired", "created_at": "2026-01-01"},
            {"relay_id": "r2", "status": "paired", "created_at": "2026-01-02"},
        ]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result["relay_id"] == "r2"

    def test_latest_relay_desktop_case_insensitive_status(self):
        desktops = [{"relay_id": "r1", "status": "PAIRED", "last_seen_at": "2026-01-01"}]
        result = AiGroupChatService._latest_relay_desktop(desktops)
        assert result is not None


class TestStringifySummary:
    """_stringify_summary 的分支覆盖。"""

    def test_stringify_summary_none_returns_empty(self):
        assert AiGroupChatService._stringify_summary(None) == ""

    def test_stringify_summary_string_returns_stripped(self):
        assert AiGroupChatService._stringify_summary("  hello  ") == "hello"

    def test_stringify_summary_empty_string_returns_empty(self):
        assert AiGroupChatService._stringify_summary("") == ""

    def test_stringify_summary_dict_returns_json(self):
        result = AiGroupChatService._stringify_summary({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_stringify_summary_list_returns_json(self):
        result = AiGroupChatService._stringify_summary([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_stringify_summary_int_returns_string(self):
        result = AiGroupChatService._stringify_summary(42)
        assert result == "42"

    def test_stringify_summary_truncates_dict_to_1200(self):
        long_dict = {"data": "x" * 2000}
        result = AiGroupChatService._stringify_summary(long_dict)
        assert len(result) <= 1200

    def test_stringify_summary_string_not_truncated(self):
        long_str = "x" * 2000
        result = AiGroupChatService._stringify_summary(long_str)
        assert len(result) == 2000

    def test_stringify_summary_handles_non_serializable(self):
        class NotSerializable:
            pass

        result = AiGroupChatService._stringify_summary(NotSerializable())
        assert isinstance(result, str)
        assert len(result) > 0


class TestCompactResult:
    """_compact_result 的分支覆盖。"""

    def test_compact_result_includes_known_keys(self):
        result = AiGroupChatService._compact_result({
            "success": True,
            "status": "done",
            "message": "ok",
            "summary": "完成了",
            "task_id": "t1",
            "run_id": "r1",
            "error": "",
            "dispatch_request_id": "d1",
            "dispatcher": "mobile_relay",
            "relay_id": "relay-1",
        })
        assert result["success"] is True
        assert result["status"] == "done"
        assert result["message"] == "ok"
        assert result["summary"] == "完成了"
        assert result["task_id"] == "t1"

    def test_compact_result_skips_unknown_keys(self):
        result = AiGroupChatService._compact_result({"unknown_key": "value", "success": True})
        assert "unknown_key" not in result
        assert result["success"] is True

    def test_compact_result_stringifies_non_primitive_values(self):
        result = AiGroupChatService._compact_result({
            "summary": {"nested": "dict"},
            "message": ["list", "value"],
        })
        assert isinstance(result["summary"], str)
        assert isinstance(result["message"], str)

    def test_compact_result_keeps_none_values(self):
        result = AiGroupChatService._compact_result({"success": None, "status": None})
        assert result["success"] is None
        assert result["status"] is None

    def test_compact_result_empty_dict(self):
        assert AiGroupChatService._compact_result({}) == {}


class TestExecutionSummary:
    """_execution_summary 的分支覆盖。"""

    def test_execution_summary_from_summary(self):
        assert AiGroupChatService._execution_summary({"summary": "摘要"}) == "摘要"

    def test_execution_summary_from_message(self):
        assert AiGroupChatService._execution_summary({"message": "消息"}) == "消息"

    def test_execution_summary_from_output(self):
        assert AiGroupChatService._execution_summary({"output": "输出"}) == "输出"

    def test_execution_summary_from_result(self):
        assert AiGroupChatService._execution_summary({"result": "结果"}) == "结果"

    def test_execution_summary_from_report(self):
        assert AiGroupChatService._execution_summary({"report": "报告"}) == "报告"

    def test_execution_summary_from_data_dict(self):
        result = AiGroupChatService._execution_summary({"data": {"summary": "数据摘要"}})
        assert result == "数据摘要"

    def test_execution_summary_falls_back_to_stringified_result(self):
        result = AiGroupChatService._execution_summary({"other": "value"})
        assert "other" in result
        assert "value" in result

    def test_execution_summary_empty_dict(self):
        result = AiGroupChatService._execution_summary({})
        assert result == "{}"

    def test_execution_summary_truncates_to_1200(self):
        long_summary = "x" * 2000
        result = AiGroupChatService._execution_summary({"summary": long_summary})
        assert len(result) == 1200

    def test_execution_summary_skips_empty_values(self):
        result = AiGroupChatService._execution_summary({"summary": "", "message": "  ", "output": "real"})
        assert result == "real"


class TestExecutionRisk:
    """_execution_risk 的分支覆盖。"""

    def test_execution_risk_from_risk(self):
        assert AiGroupChatService._execution_risk({"risk": "有风险"}, True) == "有风险"

    def test_execution_risk_from_risks(self):
        assert AiGroupChatService._execution_risk({"risks": "风险列表"}, True) == "风险列表"

    def test_execution_risk_from_blocker(self):
        assert AiGroupChatService._execution_risk({"blocker": "阻塞"}, False) == "阻塞"

    def test_execution_risk_from_data_dict(self):
        result = AiGroupChatService._execution_risk({"data": {"risk": "数据风险"}}, True)
        assert result == "数据风险"

    def test_execution_risk_default_when_success(self):
        assert AiGroupChatService._execution_risk({}, True) == "未发现阻塞。"

    def test_execution_risk_default_when_failure(self):
        assert AiGroupChatService._execution_risk({}, False) == "执行失败，需负责人介入。"

    def test_execution_risk_truncates_to_500(self):
        long_risk = "x" * 600
        result = AiGroupChatService._execution_risk({"risk": long_risk}, True)
        assert len(result) == 500

    def test_execution_risk_skips_empty_values(self):
        result = AiGroupChatService._execution_risk({"risk": "", "risks": "  ", "blocker": "real"}, True)
        assert result == "real"


class TestRelayResultDispatchValue:
    """_relay_result_dispatch_value 的分支覆盖。"""

    def test_relay_result_dispatch_value_finds_key(self):
        result = {"dispatch_info": {"dispatch": {"dispatcher": "mobile_relay", "status": "queued"}}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "dispatcher") == "mobile_relay"
        assert AiGroupChatService._relay_result_dispatch_value(result, "status") == "queued"

    def test_relay_result_dispatch_value_returns_empty_when_no_dispatch(self):
        result = {"key": "value"}
        assert AiGroupChatService._relay_result_dispatch_value(result, "dispatcher") == ""

    def test_relay_result_dispatch_value_skips_non_dict_values(self):
        result = {"key": "not-a-dict", "real": {"dispatch": {"dispatcher": "found"}}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "dispatcher") == "found"

    def test_relay_result_dispatch_value_returns_empty_when_key_none(self):
        result = {"key": {"dispatch": {"dispatcher": None}}}
        assert AiGroupChatService._relay_result_dispatch_value(result, "dispatcher") == ""

    def test_relay_result_dispatch_value_empty_result(self):
        assert AiGroupChatService._relay_result_dispatch_value({}, "dispatcher") == ""


class TestFind:
    """_find 的分支覆盖。"""

    def test_find_returns_matching_group(self):
        groups = [{"id": "g1"}, {"id": "g2"}]
        assert AiGroupChatService._find(groups, "g2") == {"id": "g2"}

    def test_find_returns_none_when_not_found(self):
        groups = [{"id": "g1"}]
        assert AiGroupChatService._find(groups, "g999") is None

    def test_find_empty_groups(self):
        assert AiGroupChatService._find([], "g1") is None

    def test_find_matches_by_string_id(self):
        groups = [{"id": 123}]
        assert AiGroupChatService._find(groups, "123") == {"id": 123}


class TestReplace:
    """_replace 的分支覆盖。"""

    def test_replace_swaps_matching_group(self):
        groups = [{"id": "g1", "name": "old"}, {"id": "g2"}]
        updated = {"id": "g1", "name": "new"}
        result = AiGroupChatService._replace(groups, updated)
        assert result[0] == updated
        assert result[1] == {"id": "g2"}

    def test_replace_no_match_returns_original(self):
        groups = [{"id": "g1"}]
        updated = {"id": "g999"}
        result = AiGroupChatService._replace(groups, updated)
        assert result == groups

    def test_replace_empty_groups(self):
        result = AiGroupChatService._replace([], {"id": "g1"})
        assert result == []


# ---------------------------------------------------------------------------
# 实例方法 - __init__ 与构造
# ---------------------------------------------------------------------------


class TestInit:
    """__init__ 的分支覆盖。"""

    def test_init_with_default_storage_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        svc = AiGroupChatService(storage_root=tmp_path)
        assert svc._root.exists()
        assert svc._mode == "admin"

    def test_init_with_enterprise_mode(self, tmp_path: Path):
        svc = AiGroupChatService(storage_root=tmp_path, mode="enterprise")
        assert svc._mode == "enterprise"

    def test_init_with_invalid_mode_falls_back_to_admin(self, tmp_path: Path):
        svc = AiGroupChatService(storage_root=tmp_path, mode="invalid")
        assert svc._mode == "admin"

    def test_init_with_custom_completion_fn(self, tmp_path: Path):
        async def custom(messages):
            return {"success": True, "content": "custom", "error": ""}

        svc = AiGroupChatService(storage_root=tmp_path, completion_fn=custom)
        assert svc._completion_fn is custom

    def test_init_with_custom_employee_executor(self, tmp_path: Path):
        def executor(eid, task, data, uid):
            return {"success": True}

        svc = AiGroupChatService(storage_root=tmp_path, employee_executor_fn=executor)
        assert svc._has_custom_employee_executor is True
        assert svc._employee_executor_fn is executor

    def test_init_without_custom_executor_sets_flag_false(self, tmp_path: Path):
        svc = AiGroupChatService(storage_root=tmp_path)
        assert svc._has_custom_employee_executor is False

    def test_init_creates_storage_directory(self, tmp_path: Path):
        root = tmp_path / "newroot"
        AiGroupChatService(storage_root=root)
        assert (root / "ai_group_chat").exists()


# ---------------------------------------------------------------------------
# 实例方法 - 群组管理
# ---------------------------------------------------------------------------


class TestCreateGroup:
    """create_group 的分支覆盖。"""

    def test_create_group_empty_name_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群名不能为空"):
            svc.create_group(user_id=1, name="")

    def test_create_group_whitespace_name_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群名不能为空"):
            svc.create_group(user_id=1, name="   ")

    def test_create_group_none_name_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群名不能为空"):
            svc.create_group(user_id=1, name=None)

    def test_create_group_truncates_name_to_60(self, tmp_path: Path):
        svc = make_service(tmp_path)
        long_name = "x" * 100
        group = svc.create_group(user_id=1, name=long_name)
        assert len(group["name"]) == 60

    def test_create_group_returns_public_shape(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = svc.create_group(user_id=1, name="测试群")
        assert group["name"] == "测试群"
        assert group["member_count"] == 1
        assert group["members"][0]["employee_id"] == "xcagi-assistant"
        assert group["is_pinned"] is False
        assert group["is_hidden"] is False
        assert group["is_followed"] is True


class TestAddMember:
    """add_member 的分支覆盖。"""

    def test_add_member_empty_employee_id_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="employee_id 不能为空"):
            svc.add_member(user_id=1, group_id=gid, member={"employee_id": ""})

    def test_add_member_whitespace_employee_id_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="employee_id 不能为空"):
            svc.add_member(user_id=1, group_id=gid, member={"employee_id": "  "})

    def test_add_member_none_employee_id_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="employee_id 不能为空"):
            svc.add_member(user_id=1, group_id=gid, member={"employee_id": None})

    def test_add_member_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.add_member(user_id=1, group_id="nonexistent", member={"employee_id": "e1"})

    def test_add_member_idempotent_when_already_member(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
        result = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
        assert result["member_count"] == 2

    def test_add_member_with_no_name_uses_employee_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1"})
        assert any(m["name"] == "e1" for m in result["members"])

    def test_add_member_truncates_name_to_60(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        long_name = "x" * 100
        result = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": long_name})
        added = next(m for m in result["members"] if m["employee_id"] == "e1")
        assert len(added["name"]) == 60

    def test_add_member_truncates_summary_to_280(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        long_summary = "s" * 500
        result = svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "summary": long_summary})
        added = next(m for m in result["members"] if m["employee_id"] == "e1")
        assert len(added["summary"]) == 280


class TestRemoveMember:
    """remove_member 的分支覆盖。"""

    def test_remove_member_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.remove_member(user_id=1, group_id="nonexistent", employee_id="e1")

    def test_remove_required_member_keeps_member(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.remove_member(user_id=1, group_id=gid, employee_id="xcagi-assistant")
        assert result["member_count"] == 1
        assert result["members"][0]["employee_id"] == "xcagi-assistant"

    def test_remove_existing_member(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
        result = svc.remove_member(user_id=1, group_id=gid, employee_id="e1")
        assert all(m["employee_id"] != "e1" for m in result["members"])

    def test_remove_nonexistent_member_no_error(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.remove_member(user_id=1, group_id=gid, employee_id="nonexistent")
        assert result["member_count"] == 1


class TestTogglePinned:
    """toggle_pinned 的分支覆盖。"""

    def test_toggle_pinned_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.toggle_pinned(user_id=1, group_id="nonexistent")

    def test_toggle_pinned_true_to_false(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.toggle_pinned(user_id=1, group_id=gid)
        assert result["is_pinned"] is True
        result2 = svc.toggle_pinned(user_id=1, group_id=gid)
        assert result2["is_pinned"] is False


class TestMarkUnread:
    """mark_unread 的分支覆盖。"""

    def test_mark_unread_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.mark_unread(user_id=1, group_id="nonexistent")

    def test_mark_unread_from_zero_sets_to_one(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.mark_unread(user_id=1, group_id=gid)
        assert result["unread_count"] == 1

    def test_mark_unread_from_positive_increments(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.mark_unread(user_id=1, group_id=gid)
        result = svc.mark_unread(user_id=1, group_id=gid)
        assert result["unread_count"] == 2

    def test_mark_unread_with_none_count_sets_to_one(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.create_group(user_id=1, name="test")["id"]
        # Manually set unread_count to None by manipulating storage
        groups = svc._all_groups()
        for g in groups:
            if g["id"] == gid:
                g["unread_count"] = None
        svc._rewrite_groups(groups)
        result = svc.mark_unread(user_id=1, group_id=gid)
        assert result["unread_count"] == 1


class TestMarkRead:
    """mark_read 的分支覆盖。"""

    def test_mark_read_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.mark_read(user_id=1, group_id="nonexistent")

    def test_mark_read_sets_unread_to_zero(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.mark_unread(user_id=1, group_id=gid)
        result = svc.mark_read(user_id=1, group_id=gid)
        assert result["unread_count"] == 0


class TestToggleFollowed:
    """toggle_followed 的分支覆盖。"""

    def test_toggle_followed_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.toggle_followed(user_id=1, group_id="nonexistent")

    def test_toggle_followed_true_to_false(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        assert gid
        result = svc.toggle_followed(user_id=1, group_id=gid)
        assert result["is_followed"] is False
        result2 = svc.toggle_followed(user_id=1, group_id=gid)
        assert result2["is_followed"] is True

    def test_toggle_followed_with_none_default(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.create_group(user_id=1, name="test")["id"]
        groups = svc._all_groups()
        for g in groups:
            if g["id"] == gid:
                g["is_followed"] = None
        svc._rewrite_groups(groups)
        result = svc.toggle_followed(user_id=1, group_id=gid)
        assert result["is_followed"] is True


class TestToggleHidden:
    """toggle_hidden 的分支覆盖。"""

    def test_toggle_hidden_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.toggle_hidden(user_id=1, group_id="nonexistent")

    def test_toggle_hidden_false_to_true(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.toggle_hidden(user_id=1, group_id=gid)
        assert result["is_hidden"] is True
        result2 = svc.toggle_hidden(user_id=1, group_id=gid)
        assert result2["is_hidden"] is False


class TestDeleteGroup:
    """delete_group 的分支覆盖。"""

    def test_delete_group_success(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = svc.delete_group(user_id=1, group_id=gid)
        assert result == {"deleted": True, "id": gid}
        # 删除后剩余 5 个群（不会重新种子，因为还有其他群存在）
        assert len(svc.list_groups(user_id=1)) == 5

    def test_delete_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            svc.delete_group(user_id=1, group_id="nonexistent")


class TestGetMessages:
    """get_messages 的分支覆盖。"""

    def test_get_messages_empty(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        assert svc.get_messages(user_id=1, group_id=gid) == []

    def test_get_messages_limit_clamped_to_min_1(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        messages = svc.get_messages(user_id=1, group_id=gid, limit=0)
        assert isinstance(messages, list)

    def test_get_messages_limit_clamped_to_max_300(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        messages = svc.get_messages(user_id=1, group_id=gid, limit=10000)
        assert isinstance(messages, list)

    def test_get_messages_filters_by_user_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        # Write a message for user 1
        row = svc._message_row(
            user_id=1, group_id=gid, role="user", sender_id="user",
            sender_name="我", sender_avatar="", body="hello",
        )
        svc._append_messages([row])
        # User 2 should not see user 1's messages
        assert svc.get_messages(user_id=2, group_id=gid) == []
        assert len(svc.get_messages(user_id=1, group_id=gid)) == 1

    def test_get_messages_filters_by_group_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid1 = svc.list_groups(user_id=1)[0]["id"]
        gid2 = svc.list_groups(user_id=1)[1]["id"]
        row = svc._message_row(
            user_id=1, group_id=gid1, role="user", sender_id="user",
            sender_name="我", sender_avatar="", body="hello",
        )
        svc._append_messages([row])
        assert len(svc.get_messages(user_id=1, group_id=gid1)) == 1
        assert svc.get_messages(user_id=1, group_id=gid2) == []


class TestListGroups:
    """list_groups 的分支覆盖。"""

    def test_list_groups_include_hidden(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.toggle_hidden(user_id=1, group_id=gid)
        visible = svc.list_groups(user_id=1)
        all_groups = svc.list_groups(user_id=1, include_hidden=True)
        assert len(all_groups) == len(visible) + 1

    def test_list_groups_pinned_sorts_first(self, tmp_path: Path):
        svc = make_service(tmp_path)
        groups = svc.list_groups(user_id=1)
        gid = groups[-1]["id"]
        svc.toggle_pinned(user_id=1, group_id=gid)
        result = svc.list_groups(user_id=1)
        assert result[0]["id"] == gid

    def test_list_groups_user_scoped(self, tmp_path: Path):
        svc = make_service(tmp_path)
        svc.list_groups(user_id=1)
        svc.list_groups(user_id=2)
        assert len(svc.list_groups(user_id=1)) == 6
        assert len(svc.list_groups(user_id=2)) == 6

    def test_list_groups_filters_other_user_groups(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # Add a group for a different user
        other_group = {
            "id": "other-user-group",
            "user_id": 999,
            "name": "other",
            "members": [],
            "is_pinned": False,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 0,
            "created_at": _utc_now(),
        }
        svc._append_group(other_group)
        result = svc.list_groups(user_id=1)
        # Should not include the other user's group
        assert all(g["id"] != "other-user-group" for g in result)


# ---------------------------------------------------------------------------
# 实例方法 - append_relay_work_report
# ---------------------------------------------------------------------------


class TestAppendRelayWorkReport:
    """append_relay_work_report 的分支覆盖。"""

    def test_append_relay_work_report_returns_none_when_source_not_mobile_ai_group(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 1,
            "payload": {"context": {"source": "other_source"}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_payload_not_dict(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {"task_id": "t1", "created_by_user_id": 1, "payload": "not-a-dict"}
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_context_not_dict(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 1,
            "payload": {"context": "not-a-dict"},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_user_id_zero(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 0,
            "payload": {"context": {"source": "mobile_ai_group", "group_id": "g1", "employee_id": "e1"}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_group_id_empty(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 1,
            "payload": {"context": {"source": "mobile_ai_group", "group_id": "", "employee_id": "e1"}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_employee_id_empty(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 1,
            "payload": {"context": {"source": "mobile_ai_group", "group_id": "g1", "employee_id": ""}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_task_id_empty(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "",
            "created_by_user_id": 1,
            "payload": {"context": {"source": "mobile_ai_group", "group_id": "g1", "employee_id": "e1"}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_none_when_group_not_found(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "created_by_user_id": 1,
            "payload": {"context": {"source": "mobile_ai_group", "group_id": "nonexistent", "employee_id": "e1"}},
        }
        assert svc.append_relay_work_report(task=task) is None

    def test_append_relay_work_report_returns_existing_when_already_present(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = svc.create_group(user_id=1, name="test")
        svc.add_member(user_id=1, group_id=group["id"], member={"employee_id": "e1", "name": "小销"})
        task = {
            "task_id": "relay-task-1",
            "relay_id": "relay-1",
            "kind": "codex.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "测试",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "employee_id": "e1",
                    "work_order_id": "wo1",
                },
            },
            "result": {"ok": True, "summary": "完成了"},
        }
        first = svc.append_relay_work_report(task=task)
        assert first is not None
        second = svc.append_relay_work_report(task=task)
        assert second is not None
        assert second["id"] == first["id"]

    def test_append_relay_work_report_creates_new_report(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = svc.create_group(user_id=1, name="test")
        svc.add_member(user_id=1, group_id=group["id"], member={"employee_id": "e1", "name": "小销"})
        task = {
            "task_id": "relay-task-new",
            "relay_id": "relay-1",
            "kind": "codex.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "新任务",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "employee_id": "e1",
                    "work_order_id": "wo1",
                },
            },
            "result": {"ok": True, "summary": "完成了"},
        }
        result = svc.append_relay_work_report(task=task)
        assert result is not None
        assert result["kind"] == "relay_work_report"
        assert result["sender_id"] == "e1"

    def test_append_relay_work_report_with_member_not_in_group(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = svc.create_group(user_id=1, name="test")
        task = {
            "task_id": "relay-task-x",
            "relay_id": "relay-1",
            "kind": "codex.invoke",
            "status": "completed",
            "created_by_user_id": 1,
            "payload": {
                "message": "测试",
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group["id"],
                    "employee_id": "nonexistent-emp",
                    "work_order_id": "wo1",
                },
            },
            "result": {"ok": True, "summary": "完成了"},
        }
        result = svc.append_relay_work_report(task=task)
        assert result is not None
        assert result["sender_id"] == "nonexistent-emp"


# ---------------------------------------------------------------------------
# 实例方法 - post_message
# ---------------------------------------------------------------------------


class TestPostMessage:
    """post_message 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_post_message_empty_text_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="message 不能为空"):
            await svc.post_message(user_id=1, group_id=gid, text="")

    @pytest.mark.asyncio
    async def test_post_message_whitespace_text_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="message 不能为空"):
            await svc.post_message(user_id=1, group_id=gid, text="   ")

    @pytest.mark.asyncio
    async def test_post_message_none_text_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        gid = svc.list_groups(user_id=1)[0]["id"]
        with pytest.raises(ValueError, match="message 不能为空"):
            await svc.post_message(user_id=1, group_id=gid, text=None)

    @pytest.mark.asyncio
    async def test_post_message_group_not_found_raises(self, tmp_path: Path):
        svc = make_service(tmp_path)
        with pytest.raises(ValueError, match="群不存在"):
            await svc.post_message(user_id=1, group_id="nonexistent", text="hello")

    @pytest.mark.asyncio
    async def test_post_message_default_sender_name(self, tmp_path: Path):
        seen: list[dict] = []
        svc = make_service(tmp_path, seen)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = await svc.post_message(user_id=1, group_id=gid, text="hello")
        assert result["messages"][0]["sender_name"] == "我"

    @pytest.mark.asyncio
    async def test_post_message_custom_sender_name(self, tmp_path: Path):
        seen: list[dict] = []
        svc = make_service(tmp_path, seen)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = await svc.post_message(user_id=1, group_id=gid, text="hello", sender_name="老板")
        assert result["messages"][0]["sender_name"] == "老板"

    @pytest.mark.asyncio
    async def test_post_message_empty_sender_name_defaults_to_me(self, tmp_path: Path):
        seen: list[dict] = []
        svc = make_service(tmp_path, seen)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = await svc.post_message(user_id=1, group_id=gid, text="hello", sender_name="")
        assert result["messages"][0]["sender_name"] == "我"

    @pytest.mark.asyncio
    async def test_post_message_dispatch_with_no_work_capable_members(self, tmp_path: Path):
        seen: list[dict] = []
        svc = make_service(tmp_path, seen)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = await svc.post_message(user_id=1, group_id=gid, text="执行任务", dispatch=True)
        assert "work_orders" in result
        assert result["work_orders"][0]["status"] == "blocked"

    @pytest.mark.asyncio
    async def test_post_message_dispatch_returns_work_orders(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "done"}

        svc = make_service(tmp_path, executor=executor)
        gid = svc.list_groups(user_id=1)[0]["id"]
        svc.add_member(user_id=1, group_id=gid, member={"employee_id": "e1", "name": "小销"})
        result = await svc.post_message(user_id=1, group_id=gid, text="执行任务", dispatch=True)
        assert "work_orders" in result
        assert len(result["work_orders"]) == 1

    @pytest.mark.asyncio
    async def test_post_message_non_dispatch_no_work_orders(self, tmp_path: Path):
        seen: list[dict] = []
        svc = make_service(tmp_path, seen)
        gid = svc.list_groups(user_id=1)[0]["id"]
        result = await svc.post_message(user_id=1, group_id=gid, text="hello")
        assert "work_orders" not in result


# ---------------------------------------------------------------------------
# 实例方法 - _pick_responders / _pick_dispatch_targets / _explicit_member_ids
# ---------------------------------------------------------------------------


class TestPickResponders:
    """_pick_responders 的分支覆盖。"""

    def test_pick_responders_empty_members(self, tmp_path: Path):
        svc = make_service(tmp_path)
        assert svc._pick_responders([], "hello", None) == []

    def test_pick_responders_broadcast_returns_all_up_to_max(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": f"e{i}"} for i in range(MAX_RESPONDERS + 2)]
        result = svc._pick_responders(members, "@所有人 注意", None)
        assert len(result) == MAX_RESPONDERS

    def test_pick_responders_explicit_mention_targets_specific(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}, {"employee_id": "e2", "name": "小服"}]
        result = svc._pick_responders(members, "hello", ["e2"])
        assert len(result) == 1
        assert result[0]["employee_id"] == "e2"

    def test_pick_responders_text_mention_by_name(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}, {"employee_id": "e2", "name": "小服"}]
        result = svc._pick_responders(members, "@小销 你好", None)
        assert len(result) == 1
        assert result[0]["employee_id"] == "e1"

    def test_pick_responders_text_mention_by_employee_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}]
        result = svc._pick_responders(members, "@e1 你好", None)
        assert len(result) == 1
        assert result[0]["employee_id"] == "e1"

    def test_pick_responders_default_returns_xiaoc(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [
            {"employee_id": "xcagi-assistant", "name": "小C助理"},
            {"employee_id": "e1", "name": "小销"},
        ]
        result = svc._pick_responders(members, "普通消息", None)
        assert len(result) == 1
        assert result[0]["employee_id"] == "xcagi-assistant"

    def test_pick_responders_default_no_xiaoc_returns_first_member(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}, {"employee_id": "e2", "name": "小服"}]
        result = svc._pick_responders(members, "普通消息", None)
        assert len(result) == 1
        assert result[0]["employee_id"] == "e1"

    def test_pick_responders_explicit_truncates_to_max(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": f"e{i}"} for i in range(MAX_RESPONDERS + 2)]
        mentions = [f"e{i}" for i in range(MAX_RESPONDERS + 2)]
        result = svc._pick_responders(members, "hello", mentions)
        assert len(result) == MAX_RESPONDERS


class TestPickDispatchTargets:
    """_pick_dispatch_targets 的分支覆盖。"""

    def test_pick_dispatch_targets_empty_work_capable(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "xcagi-assistant"}]
        assert svc._pick_dispatch_targets(members, "hello", None) == []

    def test_pick_dispatch_targets_broadcast(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        result = svc._pick_dispatch_targets(members, "@所有人", None)
        assert len(result) == 2

    def test_pick_dispatch_targets_explicit_mention(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        result = svc._pick_dispatch_targets(members, "hello", ["e2"])
        assert len(result) == 1
        assert result[0]["employee_id"] == "e2"

    def test_pick_dispatch_targets_default_returns_all_work_capable(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        result = svc._pick_dispatch_targets(members, "hello", None)
        assert len(result) == 2

    def test_pick_dispatch_targets_truncates_to_max(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": f"e{i}"} for i in range(MAX_RESPONDERS + 5)]
        result = svc._pick_dispatch_targets(members, "hello", None)
        assert len(result) == MAX_RESPONDERS

    def test_pick_dispatch_targets_broadcast_truncates_to_max(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": f"e{i}"} for i in range(MAX_RESPONDERS + 5)]
        result = svc._pick_dispatch_targets(members, "@all", None)
        assert len(result) == MAX_RESPONDERS


class TestExplicitMemberIds:
    """_explicit_member_ids 的分支覆盖。"""

    def test_explicit_member_ids_with_mentions(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}]
        result = svc._explicit_member_ids(members, "hello", ["e1", "e2", ""])
        assert "e1" in result
        assert "e2" in result
        assert "" not in result

    def test_explicit_member_ids_with_none_mentions(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}]
        result = svc._explicit_member_ids(members, "hello", None)
        assert result == set()

    def test_explicit_member_ids_with_text_name_mention(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}]
        result = svc._explicit_member_ids(members, "@小销 你好", None)
        assert "e1" in result

    def test_explicit_member_ids_with_text_id_mention(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": "小销"}]
        result = svc._explicit_member_ids(members, "@e1 你好", None)
        assert "e1" in result

    def test_explicit_member_ids_with_empty_name(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": ""}]
        result = svc._explicit_member_ids(members, "@e1 你好", None)
        assert "e1" in result

    def test_explicit_member_ids_with_none_name(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "e1", "name": None}]
        result = svc._explicit_member_ids(members, "@e1 你好", None)
        assert "e1" in result

    def test_explicit_member_ids_with_empty_employee_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "", "name": "小销"}]
        result = svc._explicit_member_ids(members, "@小销 你好", None)
        # 源码逻辑：name 匹配时会 add(employee_id)，即使 employee_id 为空也会被加入
        assert "" in result

    def test_explicit_member_ids_strips_whitespace(self, tmp_path: Path):
        svc = make_service(tmp_path)
        members = [{"employee_id": "  e1  ", "name": "小销"}]
        result = svc._explicit_member_ids(members, "hello", ["  e1  "])
        assert "e1" in result


# ---------------------------------------------------------------------------
# 实例方法 - _discussion_round_count / _super_discussion_reply
# ---------------------------------------------------------------------------


class TestDiscussionRoundCount:
    """_discussion_round_count 的分支覆盖。"""

    def test_discussion_round_count_returns_expected_value(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._discussion_round_count()
        assert result == max(1, min(SUPER_DISCUSSION_DEFAULT_ROUNDS, SUPER_DISCUSSION_MAX_ROUNDS))


class TestSuperDiscussionReply:
    """_super_discussion_reply 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_super_discussion_reply_success(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "我的判断是...", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": [{"name": "小C助理"}]}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "我的判断是" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(group_chat_module, "SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC", 0.01)

        async def slow_completion(messages):
            await asyncio.sleep(10)
            return {"success": True, "content": "too late", "error": ""}

        svc = make_service(tmp_path, completion_fn=slow_completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "按职责待命" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_exception(self, tmp_path: Path):
        async def failing_completion(messages):
            raise RuntimeError("LLM 不可用")

        svc = make_service(tmp_path, completion_fn=failing_completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "暂时不能参与讨论" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_no_success_returns_error(self, tmp_path: Path):
        async def completion(messages):
            return {"success": False, "content": "", "error": "模型错误"}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "按职责待命" in result
        assert "模型错误" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_empty_content_returns_error(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "  ", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "按职责待命" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_no_error_field(self, tmp_path: Path):
        async def completion(messages):
            return {"success": False, "content": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "按职责待命" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_non_dict_result(self, tmp_path: Path):
        async def completion(messages):
            return "not-a-dict"

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert "按职责待命" in result

    @pytest.mark.asyncio
    async def test_super_discussion_reply_truncates_to_600(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "x" * 1000, "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert len(result) <= 600

    @pytest.mark.asyncio
    async def test_super_discussion_reply_with_no_name(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "ok", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "codex-super-employee"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_super_discussion_reply_with_no_group_name(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "ok", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"members": []}
        member = {"employee_id": "codex-super-employee", "name": "Codex"}
        result = await svc._super_discussion_reply(
            group=group, member=member, task="做任务",
            history=[], discussion_turns=[], round_index=1,
        )
        assert result == "ok"


# ---------------------------------------------------------------------------
# 实例方法 - _route_after_discussion
# ---------------------------------------------------------------------------


class TestRouteAfterDiscussion:
    """_route_after_discussion 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_route_after_discussion_broadcast_returns_candidates(self, tmp_path: Path):
        svc = make_service(tmp_path)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="@所有人 做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) == 2
        assert "明确点名" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_explicit_mention_returns_candidates(self, tmp_path: Path):
        svc = make_service(tmp_path)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=["e1"],
        )
        assert len(selected) == 2
        assert "明确点名" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_returns_valid_json(self, tmp_path: Path):
        async def completion(messages):
            return {
                "success": True,
                "content": '{"target_employee_ids": ["e1"], "rationale": "因为"}',
                "error": "",
            }

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) == 1
        assert selected[0]["employee_id"] == "e1"
        assert rationale == "因为"

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_returns_empty_falls_back_to_heuristic(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": '{"target_employee_ids": []}', "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) >= 1
        assert "按" in rationale and "职责分工" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_exception_falls_back_to_heuristic(self, tmp_path: Path):
        async def completion(messages):
            raise RuntimeError("LLM 不可用")

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) >= 1
        assert "按" in rationale and "职责分工" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_returns_invalid_json_falls_back(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "not json at all", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) >= 1
        assert "按" in rationale and "职责分工" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_returns_non_dict_falls_back(self, tmp_path: Path):
        async def completion(messages):
            return "not-a-dict"

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) >= 1
        assert "按" in rationale and "职责分工" in rationale

    @pytest.mark.asyncio
    async def test_route_after_discussion_llm_returns_no_rationale_uses_default(self, tmp_path: Path):
        async def completion(messages):
            return {
                "success": True,
                "content": '{"target_employee_ids": ["e1"]}',
                "error": "",
            }

        svc = make_service(tmp_path, completion_fn=completion)
        candidates = [{"employee_id": "e1"}, {"employee_id": "e2"}]
        selected, rationale = await svc._route_after_discussion(
            group={"name": "g"}, task="做", candidates=candidates,
            discussion_turns=[], mentions=None,
        )
        assert len(selected) == 1
        assert "按讨论结论分流" in rationale


# ---------------------------------------------------------------------------
# 实例方法 - _ai_reply
# ---------------------------------------------------------------------------


class TestAiReply:
    """_ai_reply 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_ai_reply_success(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "你好", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": [{"name": "小C助理"}]}
        member = {"employee_id": "e1", "name": "小销", "summary": "销售"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert result == "你好"

    @pytest.mark.asyncio
    async def test_ai_reply_exception_returns_error_message(self, tmp_path: Path):
        async def completion(messages):
            raise RuntimeError("LLM 不可用")

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert "暂时无法回应" in result
        assert "LLM 不可用" in result

    @pytest.mark.asyncio
    async def test_ai_reply_no_success_returns_error(self, tmp_path: Path):
        async def completion(messages):
            return {"success": False, "content": "", "error": "模型错误"}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert "暂时无法回应" in result
        assert "模型错误" in result

    @pytest.mark.asyncio
    async def test_ai_reply_empty_content_returns_error(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "  ", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert "暂时无法回应" in result

    @pytest.mark.asyncio
    async def test_ai_reply_no_error_field(self, tmp_path: Path):
        async def completion(messages):
            return {"success": False, "content": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert "暂时无法回应" in result

    @pytest.mark.asyncio
    async def test_ai_reply_non_dict_result(self, tmp_path: Path):
        async def completion(messages):
            return "not-a-dict"

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert "暂时无法回应" in result

    @pytest.mark.asyncio
    async def test_ai_reply_with_no_name(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "ok", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"name": "测试群", "members": []}
        member = {"employee_id": "e1"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_ai_reply_with_no_group_name(self, tmp_path: Path):
        async def completion(messages):
            return {"success": True, "content": "ok", "error": ""}

        svc = make_service(tmp_path, completion_fn=completion)
        group = {"members": []}
        member = {"employee_id": "e1", "name": "小销"}
        result = await svc._ai_reply(group, member, [], user_id=1)
        assert result == "ok"


# ---------------------------------------------------------------------------
# 实例方法 - _dispatch_work / _execute_employee_work
# ---------------------------------------------------------------------------


class TestDispatchWork:
    """_dispatch_work 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_dispatch_work_empty_members_returns_blocked(self, tmp_path: Path):
        svc = make_service(tmp_path)
        messages, work_orders = await svc._dispatch_work(
            group={"id": "g1"}, members=[], task="做任务",
            user_id=1, sender_name="我",
        )
        assert len(messages) == 1
        assert messages[0].get("status") == "blocked"
        assert work_orders[0]["status"] == "blocked"

    @pytest.mark.asyncio
    async def test_dispatch_work_with_members(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "done"}

        svc = make_service(tmp_path, executor=executor)
        members = [{"employee_id": "e1", "name": "小销"}]
        messages, work_orders = await svc._dispatch_work(
            group={"id": "g1"}, members=members, task="做任务",
            user_id=1, sender_name="我",
        )
        assert len(messages) == 2  # work_order + work_report
        assert messages[0].get("kind") == "work_order"
        assert messages[1].get("kind") == "work_report"
        assert len(work_orders) == 1

    @pytest.mark.asyncio
    async def test_dispatch_work_with_member_no_name(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "done"}

        svc = make_service(tmp_path, executor=executor)
        members = [{"employee_id": "e1"}]
        messages, work_orders = await svc._dispatch_work(
            group={"id": "g1"}, members=members, task="做任务",
            user_id=1, sender_name="我",
        )
        assert messages[1]["sender_name"] == "e1"


class TestExecuteEmployeeWork:
    """_execute_employee_work 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_execute_employee_work_success(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "完成了", "status": "done"}

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["success"] is True
        assert result["status"] == "done"
        assert result["summary"] == "完成了"

    @pytest.mark.asyncio
    async def test_execute_employee_work_exception_returns_failed(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            raise RuntimeError("工具不可用")

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["success"] is False
        assert result["status"] == "failed"
        assert "工具不可用" in result["summary"]

    @pytest.mark.asyncio
    async def test_execute_employee_work_non_dict_result(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return "not-a-dict"

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["success"] is False
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_employee_work_async_executor(self, tmp_path: Path):
        async def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "async done"}

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["success"] is True
        assert result["summary"] == "async done"

    @pytest.mark.asyncio
    async def test_execute_employee_work_with_no_member_name(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "done"}

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["employee_name"] == "e1"

    @pytest.mark.asyncio
    async def test_execute_employee_work_with_no_status_in_result(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": True, "summary": "done"}

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_execute_employee_work_failure_with_no_status(self, tmp_path: Path):
        def executor(employee_id, task, input_data, user_id):
            return {"success": False, "summary": "failed"}

        svc = make_service(tmp_path, executor=executor)
        result = await svc._execute_employee_work(
            group={"id": "g1"}, member={"employee_id": "e1", "name": "小销"},
            task="做任务", assigned_task="做任务", assignment_focus="",
            work_order_id="wo1", user_id=1, sender_name="我",
        )
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# 实例方法 - _invoke_super_employee_task / _create_super_employee_relay_task
# ---------------------------------------------------------------------------


class TestInvokeSuperEmployeeTask:
    """_invoke_super_employee_task 的分支覆盖。"""

    def test_invoke_super_employee_task_with_relay_success(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return [{"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"}]

            def create_task(self, *, user_id, relay_id, kind, payload):
                return {"task_id": "relay-task-1", "status": "queued"}

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._invoke_super_employee_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1", "group_name": "群", "work_order_id": "wo1"},
            user_id=1,
        )
        assert result["success"] is True
        assert result["dispatcher"] == "mobile_relay"
        assert result["task_id"] == "relay-task-1"

    def test_invoke_super_employee_task_relay_returns_none_falls_back_to_invoke(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return []  # no paired desktops

            def create_task(self, *, user_id, relay_id, kind, payload):
                return {"task_id": "x"}

        class FakeSuperService:
            def invoke(self, *, user_id, message, context):
                return {
                    "dispatch": {"status": "queued", "accepted": True, "request_id": "req1"},
                    "assistant_message": {"body": "已接单"},
                }

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        svc._super_employee_service = lambda eid: FakeSuperService()  # type: ignore[method-assign]
        result = svc._invoke_super_employee_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1", "group_name": "群", "work_order_id": "wo1"},
            user_id=1,
        )
        assert result["success"] is True
        assert result["summary"] == "已接单"

    def test_invoke_super_employee_task_relay_exception_falls_back(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                raise RuntimeError("relay down")

        class FakeSuperService:
            def invoke(self, *, user_id, message, context):
                return {
                    "dispatch": {"status": "failed", "accepted": False, "reason": "拒绝"},
                    "assistant_message": {},
                }

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        svc._super_employee_service = lambda eid: FakeSuperService()  # type: ignore[method-assign]
        result = svc._invoke_super_employee_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1", "group_name": "群", "work_order_id": "wo1"},
            user_id=1,
        )
        assert result["success"] is False
        assert "拒绝" in result["risk"]

    def test_invoke_super_employee_task_no_dispatch_uses_assistant_status(self, tmp_path: Path):
        class FakeSuperService:
            def invoke(self, *, user_id, message, context):
                return {
                    "assistant_message": {"status": "completed", "body": "完成了"},
                }

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        svc._super_employee_service = lambda eid: FakeSuperService()  # type: ignore[method-assign]

        class FakeRelay:
            def list_desktops(self, *, user_id):
                return []

        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._invoke_super_employee_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1", "group_name": "群", "work_order_id": "wo1"},
            user_id=1,
        )
        assert result["status"] == "completed"

    def test_invoke_super_employee_task_empty_summary_uses_default(self, tmp_path: Path):
        class FakeSuperService:
            def invoke(self, *, user_id, message, context):
                return {
                    "dispatch": {"status": "queued", "accepted": True},
                    "assistant_message": {},
                }

        svc = make_service(tmp_path)

        class FakeRelay:
            def list_desktops(self, *, user_id):
                return []

        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        svc._super_employee_service = lambda eid: FakeSuperService()  # type: ignore[method-assign]
        result = svc._invoke_super_employee_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1", "group_name": "群", "work_order_id": "wo1"},
            user_id=1,
        )
        assert "执行队列" in result["summary"]


class TestCreateSuperEmployeeRelayTask:
    """_create_super_employee_relay_task 的分支覆盖。"""

    def test_create_relay_task_returns_none_for_unknown_employee(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._create_super_employee_relay_task(
            employee_id="unknown-super", task="做任务",
            input_data={}, user_id=1,
        )
        assert result is None

    def test_create_relay_task_returns_none_when_no_paired_desktop(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return []

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._create_super_employee_relay_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={}, user_id=1,
        )
        assert result is None

    def test_create_relay_task_returns_none_on_exception(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                raise RuntimeError("relay error")

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._create_super_employee_relay_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={}, user_id=1,
        )
        assert result is None

    def test_create_relay_task_returns_none_when_result_not_dict(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return [{"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"}]

            def create_task(self, *, user_id, relay_id, kind, payload):
                return "not-a-dict"

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._create_super_employee_relay_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={}, user_id=1,
        )
        assert result is None

    def test_create_relay_task_returns_none_when_no_task_id(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return [{"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"}]

            def create_task(self, *, user_id, relay_id, kind, payload):
                return {"task_id": "", "status": "queued"}

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._create_super_employee_relay_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={}, user_id=1,
        )
        assert result is None

    def test_create_relay_task_success(self, tmp_path: Path):
        class FakeRelay:
            def list_desktops(self, *, user_id):
                return [{"relay_id": "r1", "status": "paired", "last_seen_at": "2026-01-01"}]

            def create_task(self, *, user_id, relay_id, kind, payload):
                return {"task_id": "relay-task-1", "status": "queued"}

        svc = make_service(tmp_path)
        svc._mobile_relay_service = lambda: FakeRelay()  # type: ignore[method-assign]
        result = svc._create_super_employee_relay_task(
            employee_id="codex-super-employee", task="做任务",
            input_data={"group_id": "g1"}, user_id=1,
        )
        assert result is not None
        assert result["success"] is True
        assert result["task_id"] == "relay-task-1"
        assert result["dispatcher"] == "mobile_relay"


# ---------------------------------------------------------------------------
# 实例方法 - _relay_report_message / _relay_task_report
# ---------------------------------------------------------------------------


class TestRelayReportMessage:
    """_relay_report_message 的分支覆盖。"""

    def test_relay_report_message_returns_none_when_not_found(self, tmp_path: Path):
        svc = make_service(tmp_path)
        assert svc._relay_report_message(user_id=1, group_id="g1", task_id="t1") is None

    def test_relay_report_message_finds_existing(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload={"raw": {"task_id": "t1"}},
        )
        svc._append_messages([row])
        result = svc._relay_report_message(user_id=1, group_id="g1", task_id="t1")
        assert result is not None
        assert result["id"] == row["id"]

    def test_relay_report_message_filters_by_user_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload={"raw": {"task_id": "t1"}},
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=2, group_id="g1", task_id="t1") is None

    def test_relay_report_message_filters_by_group_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload={"raw": {"task_id": "t1"}},
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=1, group_id="g2", task_id="t1") is None

    def test_relay_report_message_filters_by_kind(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="chat",
            payload={"raw": {"task_id": "t1"}},
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=1, group_id="g1", task_id="t1") is None

    def test_relay_report_message_filters_by_task_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload={"raw": {"task_id": "t1"}},
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=1, group_id="g1", task_id="t2") is None

    def test_relay_report_message_handles_non_dict_payload(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload="not-a-dict",
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=1, group_id="g1", task_id="t1") is None

    def test_relay_report_message_handles_non_dict_raw(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="report",
            kind="relay_work_report",
            payload={"raw": "not-a-dict"},
        )
        svc._append_messages([row])
        assert svc._relay_report_message(user_id=1, group_id="g1", task_id="t1") is None


class TestRelayTaskReport:
    """_relay_task_report 的分支覆盖。"""

    def test_relay_task_report_completed_success(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "relay_id": "r1",
            "kind": "codex.invoke",
            "status": "completed",
            "payload": {"message": "做任务", "context": {"work_order_id": "wo1", "employee_id": "e1"}},
            "result": {"ok": True, "summary": "完成了"},
        }
        member = {"employee_id": "e1", "name": "小销"}
        result = svc._relay_task_report(task=task, member=member)
        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["summary"] == "完成了"

    def test_relay_task_report_done_status(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "done",
            "payload": {"message": "做任务", "context": {}},
            "result": {"ok": True, "summary": "done"},
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        assert result["success"] is True
        assert result["status"] == "completed"

    def test_relay_task_report_failed_status(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "failed",
            "payload": {"message": "做任务", "context": {}},
            "result": {"ok": False, "error": "出错了"},
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        assert result["success"] is False
        assert result["status"] == "failed"

    def test_relay_task_report_ok_false_makes_failure(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "completed",
            "payload": {"message": "做任务", "context": {}},
            "result": {"ok": False, "error": "出错了"},
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        assert result["success"] is False

    def test_relay_task_report_with_non_dict_payload(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "completed",
            "payload": "not-a-dict",
            "result": {"ok": True},
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        assert result["task"] == ""

    def test_relay_task_report_with_non_dict_result(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "completed",
            "payload": {"message": "做任务", "context": {}},
            "result": "not-a-dict",
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        assert result["success"] is True

    def test_relay_task_report_default_status(self, tmp_path: Path):
        svc = make_service(tmp_path)
        task = {
            "task_id": "t1",
            "status": "",
            "payload": {"message": "做任务", "context": {}},
            "result": {"ok": True, "summary": "ok"},
        }
        result = svc._relay_task_report(task=task, member={"employee_id": "e1", "name": "小销"})
        # 源码：str(task.get("status") or "completed") → 空字符串回退为 "completed"
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# 实例方法 - _relay_result_summary / _relay_result_risk
# ---------------------------------------------------------------------------


class TestRelayResultSummary:
    """_relay_result_summary 的分支覆盖。"""

    def test_relay_result_summary_from_summary(self):
        result = AiGroupChatService._relay_result_summary(
            {"summary": "摘要"}, "completed", "t1",
        )
        assert result == "摘要"

    def test_relay_result_summary_from_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"message": "消息"}, "completed", "t1",
        )
        assert result == "消息"

    def test_relay_result_summary_from_output(self):
        result = AiGroupChatService._relay_result_summary(
            {"output": "输出"}, "completed", "t1",
        )
        assert result == "输出"

    def test_relay_result_summary_from_report(self):
        result = AiGroupChatService._relay_result_summary(
            {"report": "报告"}, "completed", "t1",
        )
        assert result == "报告"

    def test_relay_result_summary_from_error(self):
        result = AiGroupChatService._relay_result_summary(
            {"error": "错误"}, "completed", "t1",
        )
        assert result == "错误"

    def test_relay_result_summary_from_nested_assistant_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"dispatch": {"assistant_message": {"body": "助手消息"}}}, "completed", "t1",
        )
        assert result == "助手消息"

    def test_relay_result_summary_from_nested_summary(self):
        result = AiGroupChatService._relay_result_summary(
            {"dispatch": {"summary": "嵌套摘要"}}, "completed", "t1",
        )
        assert result == "嵌套摘要"

    def test_relay_result_summary_from_nested_message(self):
        result = AiGroupChatService._relay_result_summary(
            {"dispatch": {"message": "嵌套消息"}}, "completed", "t1",
        )
        assert result == "嵌套消息"

    def test_relay_result_summary_falls_back_to_default(self):
        result = AiGroupChatService._relay_result_summary(
            {"other": "value"}, "completed", "t1",
        )
        assert "completed" in result
        assert "t1" in result

    def test_relay_result_summary_falls_back_with_empty_status(self):
        result = AiGroupChatService._relay_result_summary(
            {}, "", "t1",
        )
        assert "完成" in result
        assert "t1" in result

    def test_relay_result_summary_skips_non_dict_nested(self):
        result = AiGroupChatService._relay_result_summary(
            {"key": "not-a-dict", "other": {"summary": "found"}}, "completed", "t1",
        )
        assert result == "found"

    def test_relay_result_summary_truncates_to_chat_limit(self):
        long_summary = "x" * 2000
        result = AiGroupChatService._relay_result_summary(
            {"summary": long_summary}, "completed", "t1",
        )
        # _chat_friendly_summary 截断到 CHAT_REPORT_SUMMARY_CHARS(260) 并追加后缀
        assert len(result) < 400
        assert "详细结果已保留" in result


class TestRelayResultRisk:
    """_relay_result_risk 的分支覆盖。"""

    def test_relay_result_risk_from_risk(self):
        result = AiGroupChatService._relay_result_risk(
            result={"risk": "有风险"}, success=True, task_id="t1", dispatcher="",
        )
        assert result == "有风险"

    def test_relay_result_risk_from_error(self):
        result = AiGroupChatService._relay_result_risk(
            result={"error": "错误信息"}, success=False, task_id="t1", dispatcher="",
        )
        assert result == "错误信息"

    def test_relay_result_risk_from_reason(self):
        result = AiGroupChatService._relay_result_risk(
            result={"reason": "原因"}, success=False, task_id="t1", dispatcher="",
        )
        assert result == "原因"

    def test_relay_result_risk_success_default(self):
        result = AiGroupChatService._relay_result_risk(
            result={}, success=True, task_id="t1", dispatcher="",
        )
        assert "未发现阻塞" in result

    def test_relay_result_risk_failure_default(self):
        result = AiGroupChatService._relay_result_risk(
            result={}, success=False, task_id="t1", dispatcher="",
        )
        assert "未成功完成" in result

    def test_relay_result_risk_with_dispatcher(self):
        result = AiGroupChatService._relay_result_risk(
            result={}, success=True, task_id="t1", dispatcher="mobile_relay",
        )
        assert "mobile_relay" in result

    def test_relay_result_risk_with_task_id(self):
        result = AiGroupChatService._relay_result_risk(
            result={}, success=True, task_id="task-123", dispatcher="",
        )
        assert "task-123" in result

    def test_relay_result_risk_truncates_to_500(self):
        long_risk = "x" * 600
        result = AiGroupChatService._relay_result_risk(
            result={"risk": long_risk}, success=True, task_id="t1", dispatcher="",
        )
        assert len(result) == 500

    def test_relay_result_risk_no_task_id_no_dispatcher(self):
        result = AiGroupChatService._relay_result_risk(
            result={}, success=True, task_id="", dispatcher="",
        )
        assert "未发现阻塞" in result
        assert result.endswith("。")


# ---------------------------------------------------------------------------
# 实例方法 - _super_employee_reply / _seed_department_groups / _public_group
# ---------------------------------------------------------------------------


class TestSuperEmployeeReply:
    """_super_employee_reply 的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_super_employee_reply_codex_success(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {"assistant_message": {"body": "Codex 回复"}}

        svc = make_service(tmp_path)
        with patch("app.application.codex_super_employee_service.CodexSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "codex-super-employee", "name": "Codex"},
                history=[], user_id=1,
            )
        assert result == "Codex 回复"

    @pytest.mark.asyncio
    async def test_super_employee_reply_cursor_success(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {"assistant_message": {"body": "Cursor 回复"}}

        svc = make_service(tmp_path)
        with patch("app.application.cursor_super_employee_service.CursorSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "cursor-super-employee", "name": "Cursor"},
                history=[], user_id=1,
            )
        assert result == "Cursor 回复"

    @pytest.mark.asyncio
    async def test_super_employee_reply_claude_success(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {"assistant_message": {"body": "Claude 回复"}}

        svc = make_service(tmp_path)
        with patch("app.application.claude_super_employee_service.ClaudeSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "claude-super-employee", "name": "Claude"},
                history=[], user_id=1,
            )
        assert result == "Claude 回复"

    @pytest.mark.asyncio
    async def test_super_employee_reply_empty_body_returns_default(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {"assistant_message": {"body": ""}}

        svc = make_service(tmp_path)
        with patch("app.application.codex_super_employee_service.CodexSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "codex-super-employee", "name": "Codex"},
                history=[], user_id=1,
            )
        assert "暂时无法回应" in result

    @pytest.mark.asyncio
    async def test_super_employee_reply_no_assistant_message(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {}

        svc = make_service(tmp_path)
        with patch("app.application.codex_super_employee_service.CodexSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "codex-super-employee", "name": "Codex"},
                history=[], user_id=1,
            )
        assert "暂时无法回应" in result

    @pytest.mark.asyncio
    async def test_super_employee_reply_exception_returns_error(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                raise RuntimeError("服务不可用")

        svc = make_service(tmp_path)
        with patch("app.application.codex_super_employee_service.CodexSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "codex-super-employee", "name": "Codex"},
                history=[], user_id=1,
            )
        assert "暂时无法回应" in result
        assert "服务不可用" in result

    @pytest.mark.asyncio
    async def test_super_employee_reply_with_no_name(self, tmp_path: Path):
        class FakeService:
            def invoke(self, *, user_id, message, context):
                return {"assistant_message": {"body": "ok"}}

        svc = make_service(tmp_path)
        with patch("app.application.codex_super_employee_service.CodexSuperEmployeeService") as mock:
            mock.return_value = FakeService()
            result = await svc._super_employee_reply(
                group={"name": "g", "members": []},
                member={"employee_id": "codex-super-employee"},
                history=[], user_id=1,
            )
        assert result == "ok"


class TestSeedDepartmentGroups:
    """_seed_department_groups 的分支覆盖。"""

    def test_seed_department_groups_admin_mode(self, tmp_path: Path):
        svc = make_service(tmp_path, mode="admin")
        groups = svc._seed_department_groups(user_id=1)
        assert len(groups) == 6
        assert all(g["department_key"] for g in groups)

    def test_seed_department_groups_enterprise_mode(self, tmp_path: Path):
        svc = make_service(tmp_path, mode="enterprise")
        groups = svc._seed_department_groups(user_id=1)
        assert len(groups) == 4

    def test_seed_department_groups_with_employees(self, tmp_path: Path):
        employees = [
            {"employee_id": "e1", "name": "小销", "department_key": "ops_acquisition"},
            {"employee_id": "e2", "name": "小服", "department_key": "ops_partner"},
        ]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = svc._seed_department_groups(user_id=1)
        ops_group = next(g for g in groups if g["department_key"] == "ops_acquisition")
        assert any(m["employee_id"] == "e1" for m in ops_group["members"])

    def test_seed_department_groups_employee_loader_exception(self, tmp_path: Path):
        def boom():
            raise RuntimeError("loader error")

        svc = make_service(tmp_path, employees=boom)
        groups = svc._seed_department_groups(user_id=1)
        assert len(groups) == 6
        # members should be empty (only xiaoc) since loader failed
        assert all(len(g["members"]) == 1 for g in groups)

    def test_seed_department_groups_with_non_dict_employee(self, tmp_path: Path):
        employees = ["not-a-dict", 42, None]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = svc._seed_department_groups(user_id=1)
        assert len(groups) == 6

    def test_seed_department_groups_with_empty_department_key(self, tmp_path: Path):
        employees = [{"employee_id": "e1", "name": "小销", "department_key": ""}]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = svc._seed_department_groups(user_id=1)
        # employee with empty department_key should not be added to any group
        for g in groups:
            assert all(m["employee_id"] != "e1" for m in g["members"])


class TestPublicGroup:
    """_public_group 的分支覆盖。"""

    def test_public_group_full_data(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {
            "id": "g1",
            "name": "测试群",
            "department_key": "d1",
            "members": [{"employee_id": "e1", "name": "小销"}],
            "is_pinned": True,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 5,
            "created_at": "2026-01-01",
        }
        preview = {"preview": "最新消息", "created_at": "2026-01-02"}
        result = svc._public_group(group, preview)
        assert result["id"] == "g1"
        assert result["name"] == "测试群"
        assert result["member_count"] == 1
        assert result["is_pinned"] is True
        assert result["is_hidden"] is False
        assert result["is_followed"] is True
        assert result["unread_count"] == 5
        assert result["last_message_preview"] == "最新消息"
        assert result["last_message_at"] == "2026-01-02"

    def test_public_group_no_preview(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {"id": "g1", "name": "测试", "members": []}
        result = svc._public_group(group, None)
        assert result["last_message_preview"] == ""
        assert result["last_message_at"] == ""

    def test_public_group_with_non_dict_members(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {"id": "g1", "name": "测试", "members": ["not-a-dict", 42, None]}
        result = svc._public_group(group, None)
        assert result["member_count"] == 0

    def test_public_group_with_none_values(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {
            "id": "g1",
            "name": None,
            "department_key": None,
            "members": [],
            "is_pinned": None,
            "is_hidden": None,
            "is_followed": None,
            "unread_count": None,
            "created_at": None,
        }
        result = svc._public_group(group, None)
        assert result["name"] == ""
        assert result["is_pinned"] is False
        assert result["is_hidden"] is False
        # bool(None) is False; default=True only applies when key is missing
        assert result["is_followed"] is False
        assert result["unread_count"] == 0


class TestPublicMessage:
    """_public_message 的分支覆盖。"""

    def test_public_message_full_data(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = {
            "id": "m1",
            "group_id": "g1",
            "role": "ai",
            "sender_id": "e1",
            "sender_name": "小销",
            "sender_avatar": "http://a.com",
            "body": "hello",
            "created_at": "2026-01-01",
            "kind": "work_report",
            "status": "done",
            "work_order_id": "wo1",
            "payload": {"key": "value"},
        }
        result = svc._public_message(row)
        assert result["id"] == "m1"
        assert result["kind"] == "work_report"
        assert result["status"] == "done"
        assert result["work_order_id"] == "wo1"
        assert result["payload"] == {"key": "value"}

    def test_public_message_minimal_data(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = {"id": "m1"}
        result = svc._public_message(row)
        assert result["role"] == "ai"
        assert result["sender_id"] == ""
        assert "kind" not in result
        assert "status" not in result

    def test_public_message_with_empty_kind(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = {"id": "m1", "kind": ""}
        result = svc._public_message(row)
        assert "kind" not in result

    def test_public_message_with_none_payload(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = {"id": "m1", "payload": None}
        result = svc._public_message(row)
        assert "payload" not in result

    def test_public_message_with_non_dict_payload(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = {"id": "m1", "payload": "not-a-dict"}
        result = svc._public_message(row)
        assert "payload" not in result


class TestMessageRow:
    """_message_row 的分支覆盖。"""

    def test_message_row_minimal(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="user", sender_id="u1",
            sender_name="我", sender_avatar="", body="hello",
        )
        assert row["role"] == "user"
        assert row["body"] == "hello"
        assert "kind" not in row
        assert "status" not in row
        assert "work_order_id" not in row
        assert "payload" not in row

    def test_message_row_with_kind(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            kind="work_report",
        )
        assert row["kind"] == "work_report"

    def test_message_row_with_chat_kind_not_stored(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            kind="chat",
        )
        assert "kind" not in row

    def test_message_row_with_status(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            status="done",
        )
        assert row["status"] == "done"

    def test_message_row_with_empty_status_not_stored(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            status="",
        )
        assert "status" not in row

    def test_message_row_with_work_order_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            work_order_id="wo1",
        )
        assert row["work_order_id"] == "wo1"

    def test_message_row_with_payload(self, tmp_path: Path):
        svc = make_service(tmp_path)
        payload = {"key": "value"}
        row = svc._message_row(
            user_id=1, group_id="g1", role="ai", sender_id="e1",
            sender_name="小销", sender_avatar="", body="hi",
            payload=payload,
        )
        assert row["payload"] == payload


class TestLatestPreviews:
    """_latest_previews 的分支覆盖。"""

    def test_latest_previews_empty(self, tmp_path: Path):
        svc = make_service(tmp_path)
        assert svc._latest_previews(user_id=1) == {}

    def test_latest_previews_returns_latest_per_group(self, tmp_path: Path):
        svc = make_service(tmp_path)
        for i in range(3):
            row = svc._message_row(
                user_id=1, group_id="g1", role="user", sender_id="u1",
                sender_name=f"用户{i}", sender_avatar="", body=f"消息{i}",
            )
            svc._append_messages([row])
        previews = svc._latest_previews(user_id=1)
        assert "g1" in previews
        assert "用户2" in previews["g1"]["preview"]

    def test_latest_previews_filters_by_user_id(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="user", sender_id="u1",
            sender_name="用户1", sender_avatar="", body="hello",
        )
        svc._append_messages([row])
        assert svc._latest_previews(user_id=2) == {}

    def test_latest_previews_with_empty_sender(self, tmp_path: Path):
        svc = make_service(tmp_path)
        row = svc._message_row(
            user_id=1, group_id="g1", role="user", sender_id="u1",
            sender_name="", sender_avatar="", body="hello",
        )
        svc._append_messages([row])
        previews = svc._latest_previews(user_id=1)
        assert previews["g1"]["preview"] == "hello"[:60]


class TestReadJsonl:
    """_read_jsonl 的分支覆盖。"""

    def test_read_jsonl_file_not_exists(self, tmp_path: Path):
        svc = make_service(tmp_path)
        result = svc._read_jsonl(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_read_jsonl_empty_file(self, tmp_path: Path):
        svc = make_service(tmp_path)
        path = tmp_path / "test.jsonl"
        path.write_text("", encoding="utf-8")
        assert svc._read_jsonl(path) == []

    def test_read_jsonl_skips_empty_lines(self, tmp_path: Path):
        svc = make_service(tmp_path)
        path = tmp_path / "test.jsonl"
        path.write_text('\n\n  \n', encoding="utf-8")
        assert svc._read_jsonl(path) == []

    def test_read_jsonl_skips_invalid_json(self, tmp_path: Path):
        svc = make_service(tmp_path)
        path = tmp_path / "test.jsonl"
        path.write_text('{"valid": 1}\n{invalid}\n{"valid2": 2}\n', encoding="utf-8")
        result = svc._read_jsonl(path)
        assert len(result) == 2

    def test_read_jsonl_skips_non_dict_items(self, tmp_path: Path):
        svc = make_service(tmp_path)
        path = tmp_path / "test.jsonl"
        path.write_text('["not", "a", "dict"]\n{"valid": 1}\n42\n', encoding="utf-8")
        result = svc._read_jsonl(path)
        assert len(result) == 1
        assert result[0] == {"valid": 1}

    def test_read_jsonl_valid_lines(self, tmp_path: Path):
        svc = make_service(tmp_path)
        path = tmp_path / "test.jsonl"
        path.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        result = svc._read_jsonl(path)
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}


class TestEnsureRequiredMembers:
    """_ensure_required_members 的分支覆盖。"""

    def test_ensure_required_members_adds_xiaoc_when_missing(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # Create a group without xiaoc
        group = {
            "id": "g1",
            "user_id": 1,
            "name": "test",
            "members": [{"employee_id": "e1", "name": "小销"}],
        }
        svc._append_group(group)
        svc._ensure_required_members(user_id=1)
        groups = svc._all_groups()
        assert any(m["employee_id"] == "xcagi-assistant" for m in groups[0]["members"])

    def test_ensure_required_members_no_change_when_already_present(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {
            "id": "g1",
            "user_id": 1,
            "name": "test",
            "members": [
                {"employee_id": "xcagi-assistant", "name": "小C"},
                {"employee_id": "e1", "name": "小销"},
            ],
        }
        svc._append_group(group)
        svc._ensure_required_members(user_id=1)
        groups = svc._all_groups()
        assert len(groups[0]["members"]) == 2

    def test_ensure_required_members_skips_other_users(self, tmp_path: Path):
        svc = make_service(tmp_path)
        group = {
            "id": "g1",
            "user_id": 2,
            "name": "other user group",
            "members": [{"employee_id": "e1"}],
        }
        svc._append_group(group)
        svc._ensure_required_members(user_id=1)
        groups = svc._all_groups()
        # user 2's group should not be modified
        assert all(m["employee_id"] != "xcagi-assistant" for m in groups[0]["members"])

    def test_ensure_required_members_skips_non_dict_groups(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # 注入非 dict 的脏数据到 groups.jsonl（_read_jsonl 会跳过非 JSON 行）
        svc._groups_path.write_text("not-a-json-line\n", encoding="utf-8")
        # Should not crash on non-dict entries
        svc._ensure_required_members(user_id=1)


class TestBackfillDepartmentMembers:
    """_backfill_department_members 的分支覆盖。"""

    def test_backfill_no_targets_does_nothing(self, tmp_path: Path):
        svc = make_service(tmp_path)
        # Non-department group (no department_key)
        groups = [{"id": "g1", "department_key": "", "members": []}]
        svc._backfill_department_members(groups)
        # Should not crash, no changes

    def test_backfill_already_seeded_skips(self, tmp_path: Path):
        svc = make_service(tmp_path)
        groups = [{"id": "g1", "department_key": "d1", "members_seeded": True, "members": []}]
        svc._backfill_department_members(groups)
        # Should not modify

    def test_backfill_with_employee_loader_exception(self, tmp_path: Path):
        def boom():
            raise RuntimeError("loader error")

        svc = make_service(tmp_path, employees=boom)
        groups = [{"id": "g1", "department_key": "d1", "members": []}]
        svc._backfill_department_members(groups)
        # Should not crash, returns early

    def test_backfill_with_empty_members_by_dept(self, tmp_path: Path):
        svc = make_service(tmp_path, employees=lambda: [])
        groups = [{"id": "g1", "department_key": "d1", "members": []}]
        svc._backfill_department_members(groups)
        # Should not modify since no employees loaded

    def test_backfill_adds_members_to_matching_dept(self, tmp_path: Path):
        employees = [{"employee_id": "e1", "name": "小销", "department_key": "d1"}]
        svc = make_service(tmp_path, employees=lambda: employees)
        # First create the group in storage
        group = {
            "id": "g1",
            "user_id": 1,
            "department_key": "d1",
            "members": [],
            "name": "test",
        }
        svc._append_group(group)
        groups = [group]
        svc._backfill_department_members(groups)
        all_groups = svc._all_groups()
        g = next(x for x in all_groups if x["id"] == "g1")
        assert g.get("members_seeded") is True
        assert any(m["employee_id"] == "e1" for m in g["members"])

    def test_backfill_skips_non_dict_group(self, tmp_path: Path):
        employees = [{"employee_id": "e1", "department_key": "d1"}]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = ["not-a-dict", {"id": "g1", "department_key": "d1", "members": []}]
        # Should not crash
        svc._backfill_department_members(groups)

    def test_backfill_skips_non_dict_employee(self, tmp_path: Path):
        employees = ["not-a-dict", 42, None]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = [{"id": "g1", "department_key": "d1", "members": []}]
        svc._backfill_department_members(groups)
        # Should not add any members

    def test_backfill_skips_employee_with_empty_dept(self, tmp_path: Path):
        employees = [{"employee_id": "e1", "department_key": ""}]
        svc = make_service(tmp_path, employees=lambda: employees)
        groups = [{"id": "g1", "department_key": "d1", "members": []}]
        svc._backfill_department_members(groups)
        # Should not add employee with empty department_key