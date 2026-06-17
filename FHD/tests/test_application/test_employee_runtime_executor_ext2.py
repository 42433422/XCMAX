"""Tests for app.application.employee_runtime.executor — coverage ramp ext2.

Covers helper functions and the action handlers (echo / direct_python /
vendor convert / agent / llm_md), cognition, perception, memory, and
``execute_employee_task_local`` delegation.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime import executor as exec_mod


# ── _get_section / _normalize_actions_cfg / _handler_list ────────────────────


class TestGetSection:
    def test_returns_dict_when_present(self):
        assert exec_mod._get_section({"actions": {"a": 1}}, "actions") == {"a": 1}

    def test_returns_empty_when_missing(self):
        assert exec_mod._get_section({}, "actions") == {}

    def test_returns_empty_when_not_dict(self):
        assert exec_mod._get_section({"actions": [1, 2]}, "actions") == {}

    def test_returns_empty_when_config_not_dict(self):
        assert exec_mod._get_section(None, "actions") == {}  # type: ignore[arg-type]


class TestNormalizeActionsCfg:
    def test_inner_actions_dict(self):
        cfg = {"actions": {"actions": {"handlers": ["echo"]}}}
        assert exec_mod._normalize_actions_cfg(cfg) == {"handlers": ["echo"]}

    def test_outer_actions_when_inner_not_dict(self):
        cfg = {"actions": {"handlers": ["echo"]}}
        assert exec_mod._normalize_actions_cfg(cfg) == {"handlers": ["echo"]}

    def test_empty_config(self):
        assert exec_mod._normalize_actions_cfg({}) == {}


class TestHandlerList:
    def test_default_echo(self):
        assert exec_mod._handler_list({}) == ["echo"]

    def test_strips_and_filters(self):
        assert exec_mod._handler_list({"handlers": ["  echo  ", "", "  direct_python  "]}) == [
            "echo",
            "direct_python",
        ]

    def test_coerces_non_str(self):
        assert exec_mod._handler_list({"handlers": [1, 2]}) == ["1", "2"]


# ── _perception_real / _memory_light ─────────────────────────────────────────


class TestPerceptionReal:
    def test_default_text_type(self):
        out = exec_mod._perception_real({}, {"q": "hi"})
        assert out["type"] == "text"
        assert out["normalized_input"] == {"q": "hi"}

    def test_explicit_type(self):
        out = exec_mod._perception_real({"perception": {"type": "voice"}}, {})
        assert out["type"] == "voice"

    def test_none_input(self):
        out = exec_mod._perception_real({}, None)
        assert out["normalized_input"] == {}


class TestMemoryLight:
    def test_returns_session_with_employee_id(self):
        out = exec_mod._memory_light({"employee_id": "emp-1"})
        assert out["session"]["employee_id"] == "emp-1"
        assert out["long_term"] is None

    def test_missing_employee_id(self):
        out = exec_mod._memory_light({})
        assert out["session"]["employee_id"] is None


# ── _resolve_file_path ───────────────────────────────────────────────────────


class TestResolveFilePath:
    def test_empty_returns_none(self, tmp_path):
        assert exec_mod._resolve_file_path({}, str(tmp_path)) is None

    def test_absolute_existing_file(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hi")
        out = exec_mod._resolve_file_path({"file_path": str(f)}, str(tmp_path))
        assert out == f.resolve()

    def test_relative_under_workspace(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hi")
        out = exec_mod._resolve_file_path({"path": "x.txt"}, str(tmp_path))
        assert out == f.resolve()

    def test_missing_returns_none(self, tmp_path):
        out = exec_mod._resolve_file_path({"file_path": "missing.txt"}, str(tmp_path))
        assert out is None


# ── _import_module_from_path / _run_maybe_async ──────────────────────────────


class TestImportModuleFromPath:
    def test_loads_module(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("VALUE = 42\n")
        mod = exec_mod._import_module_from_path(f, "m_label")
        assert mod is not None
        assert mod.VALUE == 42

    def test_returns_none_when_spec_missing(self, tmp_path):
        # Non-existent file → spec_from_file_location returns a spec with loader,
        # but exec_module raises FileNotFoundError (not caught by the function).
        # The function only returns None when spec or loader is None.
        # For a directory (not a .py file), spec_from_file_location returns None.
        out = exec_mod._import_module_from_path(tmp_path, "nope")
        assert out is None


class TestRunMaybeAsync:
    def test_sync_function(self):
        assert exec_mod._run_maybe_async(lambda x: x * 2, 3) == 6

    def test_async_function_no_running_loop(self):
        async def coro(x):
            return x + 1

        assert exec_mod._run_maybe_async(coro, 10) == 11

    def test_async_function_with_running_loop(self):
        async def coro(x):
            return x + 1

        async def runner():
            return exec_mod._run_maybe_async(coro, 10)

        assert asyncio.run(runner()) == 11


# ── _find_vendor_convert_module / _load_rule_spec ────────────────────────────


class TestFindVendorConvertModule:
    def test_finds_vendor_convert(self, tmp_path):
        backend = tmp_path / "backend"
        vendor = backend / "vendor" / "csv_read"
        vendor.mkdir(parents=True)
        (vendor / "convert.py").write_text("# stub")
        out = exec_mod._find_vendor_convert_module(tmp_path)
        assert out is not None
        assert out.name == "convert.py"

    def test_no_backend_dir(self, tmp_path):
        assert exec_mod._find_vendor_convert_module(tmp_path) is None

    def test_no_convert_py(self, tmp_path):
        (tmp_path / "backend").mkdir()
        assert exec_mod._find_vendor_convert_module(tmp_path) is None


class TestLoadRuleSpec:
    def test_loads_dict(self, tmp_path):
        (tmp_path / "rule_spec.json").write_text(json.dumps({"k": "v"}))
        assert exec_mod._load_rule_spec(tmp_path) == {"k": "v"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert exec_mod._load_rule_spec(tmp_path) == {}

    def test_non_dict_returns_empty(self, tmp_path):
        (tmp_path / "rule_spec.json").write_text(json.dumps([1, 2]))
        assert exec_mod._load_rule_spec(tmp_path) == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        (tmp_path / "rule_spec.json").write_text("not json")
        assert exec_mod._load_rule_spec(tmp_path) == {}


# ── _action_vendor_convert ───────────────────────────────────────────────────


class TestActionVendorConvert:
    def test_no_vendor_module(self, tmp_path):
        out = exec_mod._action_vendor_convert(tmp_path, "emp-1", {}, None)
        assert out["ok"] is False
        assert out["handler"] == "direct_python"
        assert "error" in out

    def test_invalid_module_no_convert_file(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text("# no convert_file")
        out = exec_mod._action_vendor_convert(tmp_path, "emp-1", {}, None)
        assert out["ok"] is False
        assert "vendor convert" in out["error"]

    def test_missing_file_path_for_non_generate(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text(
            "def convert_file(*a, **k):\n    return {'ok': True}\n"
        )
        out = exec_mod._action_vendor_convert(tmp_path, "emp-1", {}, None)
        assert out["ok"] is False
        assert "file_path" in out["error"]

    def test_generate_employee_without_input(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text(
            "def convert_file(*a, **k):\n    return {'ok': True}\n"
        )
        out = exec_mod._action_vendor_convert(tmp_path, "emp-generate-1", {}, None)
        assert out["ok"] is False
        assert "JSON 输入" in out["error"] or "user_request" in out["error"]

    def test_generate_employee_with_user_request(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text(
            "def convert_file(src, out, *, template_path=None, payload=None, ctx=None, rule_spec=None):\n"
            "    return {'ok': True, 'src': str(src)}\n"
        )
        out = exec_mod._action_vendor_convert(
            tmp_path, "emp-generate-1", {"user_request": "hi"}, None
        )
        assert out["ok"] is True
        assert out["handler"] == "direct_python"

    def test_convert_failure_returns_error(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text(
            "def convert_file(*a, **k):\n    raise RuntimeError('boom')\n"
        )
        # Provide a file_path so we get past the missing-file check
        src = tmp_path / "src.txt"
        src.write_text("hi")
        out = exec_mod._action_vendor_convert(
            tmp_path, "emp-1", {"file_path": str(src)}, None
        )
        assert out["ok"] is False
        assert "boom" in out["error"]

    def test_convert_with_explicit_output_path(self, tmp_path):
        backend = tmp_path / "backend" / "vendor" / "csv"
        backend.mkdir(parents=True)
        (backend / "convert.py").write_text(
            "def convert_file(src, out, *, template_path=None, payload=None, ctx=None, rule_spec=None):\n"
            "    return {'ok': True}\n"
        )
        src = tmp_path / "src.txt"
        src.write_text("hi")
        out_path = tmp_path / "out.json"
        out = exec_mod._action_vendor_convert(
            tmp_path, "emp-1", {"file_path": str(src), "output_path": str(out_path)}, None
        )
        assert out["ok"] is True
        assert str(out_path) in out["output_path"] or out["output_path"] == str(out_path)


# ── _action_direct_python_module ─────────────────────────────────────────────


class TestActionDirectPythonModule:
    def test_no_module_and_no_vendor(self, tmp_path):
        # No backend/employees, no vendor convert → missing runtime
        out = exec_mod._action_direct_python_module(
            tmp_path, "emp-1", {}, {"input": {}}, "task", None
        )
        assert out["ok"] is False
        assert "error" in out

    def test_falls_back_to_vendor_convert(self, tmp_path):
        # No backend/employees dir but vendor convert present
        vendor = tmp_path / "backend" / "vendor" / "csv"
        vendor.mkdir(parents=True)
        (vendor / "convert.py").write_text(
            "def convert_file(*a, **k):\n    return {'ok': True}\n"
        )
        # Provide file_path via reasoning
        src = tmp_path / "src.txt"
        src.write_text("hi")
        out = exec_mod._action_direct_python_module(
            tmp_path,
            "emp-1",
            {},
            {"input": {}, "file_path": str(src)},
            "task",
            None,
        )
        # Either ok or error, but should have attempted vendor convert
        assert out["handler"] == "direct_python"

    def test_module_no_run_function(self, tmp_path):
        employees = tmp_path / "backend" / "employees"
        employees.mkdir(parents=True)
        (employees / "worker.py").write_text("# no run function")
        out = exec_mod._action_direct_python_module(
            tmp_path, "emp-1", {}, {"input": {}}, "task", None
        )
        assert out["ok"] is False
        assert "run" in out["error"]

    def test_module_run_returns_dict(self, tmp_path):
        employees = tmp_path / "backend" / "employees"
        employees.mkdir(parents=True)
        (employees / "worker.py").write_text(
            "def run(payload, ctx):\n    return {'ok': True, 'data': 1}\n"
        )
        out = exec_mod._action_direct_python_module(
            tmp_path, "emp-1", {}, {"input": {}}, "task", None
        )
        assert out["ok"] is True
        assert out["output"]["data"] == 1

    def test_module_run_returns_non_dict(self, tmp_path):
        employees = tmp_path / "backend" / "employees"
        employees.mkdir(parents=True)
        (employees / "worker.py").write_text(
            "def run(payload, ctx):\n    return 'plain string'\n"
        )
        out = exec_mod._action_direct_python_module(
            tmp_path, "emp-1", {}, {"input": {}}, "task", None
        )
        assert out["ok"] is True
        assert out["output"] == "plain string"

    def test_module_load_failure(self, tmp_path):
        employees = tmp_path / "backend" / "employees"
        employees.mkdir(parents=True)
        # worker.py exists but cannot be loaded (syntax error)
        (employees / "worker.py").write_text("def broken(:\n")
        # The function does not catch SyntaxError from exec_module, so it propagates
        with pytest.raises(SyntaxError):
            exec_mod._action_direct_python_module(
                tmp_path, "emp-1", {}, {"input": {}}, "task", None
            )


# ── _cognition_fhd ───────────────────────────────────────────────────────────


class TestCognitionFhd:
    def test_returns_reasoning_on_success(self):
        with patch(
            "app.application.employee_runtime.agent_runner._run_async",
            return_value={"choices": [{"message": {"content": "hello"}}]},
        ):
            out = exec_mod._cognition_fhd({}, {"normalized_input": {"q": 1}}, {}, "task")
            assert out["reasoning"] == "hello"
            assert out["system_prompt"]

    def test_returns_error_on_failure(self):
        with patch(
            "app.application.employee_runtime.agent_runner._run_async",
            side_effect=RuntimeError("llm down"),
        ):
            out = exec_mod._cognition_fhd({}, {"normalized_input": {}}, {}, "task")
            assert out["reasoning"] == ""
            assert "llm down" in out["error"]

    def test_returns_error_when_raw_has_error(self):
        with patch(
            "app.application.employee_runtime.agent_runner._run_async",
            return_value={"error": "bad request"},
        ):
            out = exec_mod._cognition_fhd({}, {"normalized_input": {}}, {}, "task")
            assert out["reasoning"] == ""
            assert "bad request" in out["error"]

    def test_empty_choices(self):
        with patch(
            "app.application.employee_runtime.agent_runner._run_async",
            return_value={"choices": []},
        ):
            out = exec_mod._cognition_fhd({}, {"normalized_input": {}}, {}, "task")
            assert out["reasoning"] == ""


# ── _actions_fhd ─────────────────────────────────────────────────────────────


class TestActionsFhd:
    def test_echo_handler(self):
        out = exec_mod._actions_fhd(
            {"actions": {"handlers": ["echo"]}},
            {"reasoning": "result text"},
            "task",
            "emp-1",
            Path("/tmp"),
            None,
        )
        assert out["handlers"] == ["echo"]
        assert out["outputs"][0]["handler"] == "echo"
        assert out["outputs"][0]["output"] == "result text"

    def test_unsupported_handler(self):
        out = exec_mod._actions_fhd(
            {"actions": {"handlers": ["unknown_handler"]}},
            {},
            "task",
            "emp-1",
            Path("/tmp"),
            None,
        )
        assert out["outputs"][0]["error"] == "unsupported handler in FHD local executor"

    def test_direct_python_no_runtime(self, tmp_path):
        out = exec_mod._actions_fhd(
            {"actions": {"handlers": ["direct_python"]}},
            {},
            "task",
            "emp-1",
            tmp_path,
            None,
        )
        assert out["outputs"][0]["ok"] is False

    def test_llm_md_handler(self):
        out = exec_mod._actions_fhd(
            {"actions": {"handlers": ["llm_md"]}},
            {"reasoning": "md text"},
            "task",
            "emp-1",
            Path("/tmp"),
            None,
        )
        assert out["outputs"][0]["handler"] == "llm_md"
        assert out["outputs"][0]["output"] == "md text"

    def test_agent_handler_delegates(self):
        with patch("app.application.employee_runtime.executor.run_agent_handler") as mock_run:
            mock_run.return_value = {"handler": "agent", "ok": True}
            out = exec_mod._actions_fhd(
                {"actions": {"handlers": ["agent"]}},
                {},
                "task",
                "emp-1",
                Path("/tmp"),
                None,
            )
            assert out["outputs"][0]["ok"] is True
            mock_run.assert_called_once()


# ── _handlers_execution_ok ───────────────────────────────────────────────────


class TestHandlersExecutionOk:
    def test_empty_outputs(self):
        assert exec_mod._handlers_execution_ok({}) is True

    def test_all_ok(self):
        assert exec_mod._handlers_execution_ok({"outputs": [{"ok": True}]}) is True

    def test_one_failed(self):
        assert (
            exec_mod._handlers_execution_ok(
                {"outputs": [{"ok": True}, {"ok": False, "error": "x"}]}
            )
            is False
        )

    def test_no_ok_key_treated_as_ok(self):
        assert exec_mod._handlers_execution_ok({"outputs": [{"output": "x"}]}) is True


# ── execute_employee_task_local ──────────────────────────────────────────────


class TestExecuteEmployeeTaskLocal:
    def test_delegates_to_employee_agent(self):
        with patch("app.application.employee_runtime.agent.EmployeeAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run.return_value = {"ok": True}
            mock_agent_cls.return_value = mock_agent
            out = exec_mod.execute_employee_task_local(
                "emp-1", "task", input_data={"q": 1}, user_id=5
            )
            assert out == {"ok": True}
            mock_agent_cls.assert_called_once_with("emp-1")
            mock_agent.run.assert_called_once()

    def test_passes_workspace_and_session(self):
        with patch("app.application.employee_runtime.agent.EmployeeAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run.return_value = {}
            mock_agent_cls.return_value = mock_agent
            exec_mod.execute_employee_task_local(
                "emp-1",
                "task",
                None,
                user_id=0,
                workspace_root="/tmp",
                session_id="s1",
            )
            args, kwargs = mock_agent.run.call_args
            assert kwargs.get("workspace_root") == "/tmp"
            assert kwargs.get("session_id") == "s1"
