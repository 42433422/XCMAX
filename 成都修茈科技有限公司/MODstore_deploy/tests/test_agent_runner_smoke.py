"""Smoke tests for mod_employee_agent_runner.EmployeeAgentRunner.

Tests the ReAct loop end-to-end with a fully mocked LLM so no real API calls
are made.  Also tests individual tool implementations against a tmp workspace.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(llm_responses: List[str], workspace: str) -> Dict[str, Any]:
    queue = list(llm_responses)

    async def mock_llm(messages, **kwargs):
        if not queue:
            return {"ok": False, "content": "", "error": "MockLLM 队列空了"}
        return {"ok": True, "content": queue.pop(0), "error": ""}

    async def mock_http_get(url, **kwargs):
        return {
            "ok": True,
            "status": 200,
            "text": f"<html>mock response for {url}</html>",
            "error": "",
        }

    async def mock_http_post(url, **kwargs):
        return {"ok": True, "status": 200, "text": '{"ok":true}', "error": ""}

    return {
        "call_llm": mock_llm,
        "http_get": mock_http_get,
        "http_post": mock_http_post,
        "workspace_root": workspace,
        "employee_id": "test-emp",
        "bypass_change_request": True,
    }


# ---------------------------------------------------------------------------
# 1. ReAct loop basics
# ---------------------------------------------------------------------------


def test_agent_runner_immediate_answer(tmp_path):
    """LLM gives answer on first round — no tool calls."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    ctx = _make_ctx(
        [json.dumps({"thought": "直接回答", "answer": "你好！"})],
        str(tmp_path),
    )
    result = asyncio.run(EmployeeAgentRunner(ctx).run("打个招呼"))
    assert result["ok"] is True
    assert result["summary"] == "你好！"
    assert result["rounds"] == 1
    assert result["tool_calls"] == []


def test_agent_runner_one_tool_then_answer(tmp_path):
    """LLM calls list_workspace_dir once then gives final answer."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    ctx = _make_ctx(
        [
            json.dumps(
                {"thought": "先列目录", "tool": "list_workspace_dir", "input": {"path": "."}}
            ),
            json.dumps({"thought": "目录已列", "answer": "工作区内容已获取"}),
        ],
        str(tmp_path),
    )
    result = asyncio.run(EmployeeAgentRunner(ctx).run("列出工作区"))
    assert result["ok"] is True
    assert result["rounds"] == 2
    assert len(result["tool_calls"]) == 1
    tc = result["tool_calls"][0]
    assert tc["tool"] == "list_workspace_dir"
    assert tc["result"]["ok"] is True


def test_agent_runner_read_and_write(tmp_path):
    """LLM reads a file then writes a new file."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    # Prepare a file to read
    src = tmp_path / "input.txt"
    src.write_text("Hello, agent!", encoding="utf-8")

    ctx = _make_ctx(
        [
            json.dumps(
                {
                    "thought": "读原文件",
                    "tool": "read_workspace_file",
                    "input": {"path": "input.txt"},
                }
            ),
            json.dumps(
                {
                    "thought": "写新文件",
                    "tool": "write_workspace_file",
                    "input": {"path": "output.txt", "content": "Processed!"},
                }
            ),
            json.dumps({"thought": "完成", "answer": "文件已处理"}),
        ],
        str(tmp_path),
    )
    result = asyncio.run(EmployeeAgentRunner(ctx).run("处理 input.txt"))
    assert result["ok"] is True
    assert result["rounds"] == 3
    assert len(result["tool_calls"]) == 2
    # Check file was actually written
    out = tmp_path / "output.txt"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "Processed!"


def test_agent_runner_llm_failure_returned_as_error(tmp_path):
    """LLM failure on first call should propagate as ok=False."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    ctx = _make_ctx([], str(tmp_path))  # empty queue → immediate failure
    result = asyncio.run(EmployeeAgentRunner(ctx).run("任何任务"))
    assert result["ok"] is False


def test_agent_runner_unknown_tool_returns_error_observation(tmp_path):
    """Unknown tool name → observation has ok=False but loop continues."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    ctx = _make_ctx(
        [
            json.dumps({"thought": "调用神秘工具", "tool": "magic_wand", "input": {}}),
            json.dumps({"thought": "工具不存在，直接回答", "answer": "无法使用该工具"}),
        ],
        str(tmp_path),
    )
    result = asyncio.run(EmployeeAgentRunner(ctx).run("用神秘工具"))
    assert result["ok"] is True
    # The tool_calls log should record the failed tool call
    assert result["tool_calls"][0]["result"]["ok"] is False
    assert "magic_wand" in result["tool_calls"][0]["result"]["error"]


# ---------------------------------------------------------------------------
# 2. Tool implementations
# ---------------------------------------------------------------------------


def test_tool_read_workspace_file_ok(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_read_workspace_file

    (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
    result = asyncio.run(tool_read_workspace_file(str(tmp_path), "hello.txt"))
    assert result["ok"] is True
    assert result["content"] == "world"
    assert result["truncated"] is False


def test_tool_read_workspace_file_path_escape(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_read_workspace_file

    result = asyncio.run(tool_read_workspace_file(str(tmp_path), "../../etc/passwd"))
    assert result["ok"] is False
    assert "越界" in result["error"]


def test_tool_write_workspace_file_creates_dirs(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    result = asyncio.run(tool_write_workspace_file(str(tmp_path), "sub/dir/file.txt", "content"))
    assert result["ok"] is True
    assert (tmp_path / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "content"


def test_tool_list_workspace_dir(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_list_workspace_dir

    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b").mkdir()
    result = asyncio.run(tool_list_workspace_dir(str(tmp_path), "."))
    assert result["ok"] is True
    names = [e["name"] for e in result["entries"]]
    assert "a.txt" in names
    assert "b" in names


def test_tool_run_sandboxed_python_basic(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_run_sandboxed_python

    result = asyncio.run(tool_run_sandboxed_python("print(1 + 1)"))
    assert result["ok"] is True
    assert "2" in result["stdout"]


def test_tool_run_sandboxed_python_blocks_dangerous(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_run_sandboxed_python

    result = asyncio.run(tool_run_sandboxed_python("import subprocess; subprocess.run(['ls'])"))
    assert result["ok"] is False
    assert "不允许" in result["error"]


# ---------------------------------------------------------------------------
# 3. blueprints template injects workspace tools
# ---------------------------------------------------------------------------


def test_blueprints_template_renders_workspace_code():
    """blueprints.py must inject workspace tools and agent_runner into ctx."""
    from modstore_server.employee_pack_blueprints_template import render_employee_pack_blueprints_py

    src = render_employee_pack_blueprints_py(
        pack_id="test-pack",
        employee_id="test-emp",
        stem="test_emp",
        label="测试员工",
    )
    assert "workspace_root" in src
    assert "_read_workspace_file" in src
    assert "_write_workspace_file" in src
    assert "_list_workspace_dir" in src
    assert "_run_sandboxed_python" in src
    assert "agent_runner" in src


def test_employee_template_renders_agent_handler():
    """employees/<stem>.py must include _handle_agent and 'agent' in _DISPATCH."""
    from modstore_server.employee_pack_blueprints_template import render_employee_pack_employee_py

    src = render_employee_pack_employee_py(
        employee_id="test-emp",
        stem="test_emp",
        label="测试员工",
    )
    assert "_handle_agent" in src
    assert "'agent': _handle_agent" in src
    assert "agent_runner" in src
    assert "SYSTEM_PROMPT =" in src
    assert "cfg['system_prompt'] or SYSTEM_PROMPT" in src
