"""Tests for project-analysis employee capabilities.

Covers:
  - employee_ai_pipeline: project-analysis intent detection, agent handler forcing,
    workspace config injection, structured skills with kind.
  - mod_employee_agent_runner: new scan/identify/analyze tools, path-escape rejection.
  - employee_executor: agent handler dispatches EmployeeAgentRunner, missing
    project_root returns clear error, read_only workspace config respected.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── employee_ai_pipeline ──────────────────────────────────────────────────────


@pytest.fixture()
def _proj_intent():
    from modstore_server.employee_ai_pipeline import Intent

    return Intent(
        id="project-doc-gen",
        name="项目文档生成助手",
        role="项目文档生成",
        scenario="扫描代码库目录，识别技术栈，生成 README 文档",
        industry="通用",
        complexity="medium",
    )


@pytest.fixture()
def _non_proj_intent():
    from modstore_server.employee_ai_pipeline import Intent

    return Intent(
        id="refund-assistant",
        name="退款助手",
        role="退款流程处理",
        scenario="处理用户退款申请",
        industry="电商",
        complexity="medium",
    )


def test_is_project_analysis_intent_positive(_proj_intent):
    from modstore_server.employee_ai_pipeline import _is_project_analysis_intent

    assert _is_project_analysis_intent(_proj_intent) is True


def test_is_project_analysis_intent_negative(_non_proj_intent):
    from modstore_server.employee_ai_pipeline import _is_project_analysis_intent

    assert _is_project_analysis_intent(_non_proj_intent) is False


def test_build_runtime_prompt_agent_project_includes_scan_tools(_proj_intent):
    from modstore_server.employee_ai_pipeline import _build_employee_runtime_prompt

    prompt = _build_employee_runtime_prompt(_proj_intent, None, [], handlers=["agent"])
    assert "analyze_project_summary" in prompt
    assert "scan_project_tree" in prompt
    assert "identify_file_types" in prompt
    # Must mention steps order constraint
    assert "必须先" in prompt or "必须按顺序" in prompt or "先调用" in prompt


def test_build_runtime_prompt_agent_generic_no_scan_tools(_non_proj_intent):
    from modstore_server.employee_ai_pipeline import _build_employee_runtime_prompt

    prompt = _build_employee_runtime_prompt(_non_proj_intent, None, [], handlers=["agent"])
    # Generic agent still has list_workspace_dir but not the specialized project tools in header
    assert "list_workspace_dir" in prompt
    # scan_project_tree and analyze_project_summary are only listed in project-analysis mode
    assert "scan_project_tree" not in prompt
    assert "analyze_project_summary" not in prompt


@pytest.mark.asyncio
async def test_stage_design_v2_forces_agent_for_project_intent(_proj_intent):
    """For a project-analysis intent, stage_design_v2 must force handler=agent."""
    from modstore_server.employee_ai_pipeline import stage_design_v2

    # LLM returns llm_md handler — should be upgraded to agent
    llm_response = json.dumps(
        {
            "perception": {"type": "document"},
            "memory": {"type": "session"},
            "cognition": {
                "agent": {
                    "system_prompt": (
                        "你是项目文档生成助手，专注于扫描代码库生成技术文档。"
                        "工作步骤：1.扫描目录 2.读取配置文件 3.生成文档。"
                        "可用工具：read_workspace_file, list_workspace_dir。"
                        "禁止：捏造文件内容或不存在的依赖。"
                    ),
                    "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
                }
            },
            "actions": {"handlers": ["llm_md"]},
        }
    )

    class StubLlm:
        async def chat(self, messages, **kw):
            return llm_response

    v2, err = await stage_design_v2(_proj_intent, None, StubLlm())
    assert err == ""
    assert v2 is not None
    assert "agent" in v2.actions.get("handlers", [])
    # Workspace config must be present
    agent_cfg = v2.actions.get("agent") or {}
    ws = agent_cfg.get("workspace") or {}
    assert ws.get("requires_project_root") is True
    assert ws.get("read_only") is True


@pytest.mark.asyncio
async def test_stage_suggest_skills_parses_kind_field():
    from modstore_server.employee_ai_pipeline import Intent, stage_suggest_skills

    intent = Intent(
        id="doc-gen",
        name="文档助手",
        role="文档生成",
        scenario="生成项目 README",
        industry="通用",
        complexity="low",
    )
    skills_json = json.dumps(
        [
            {"name": "目录扫描", "brief": "递归扫描项目目录", "kind": "project_directory_scan"},
            {"name": "README生成", "brief": "生成项目 README", "kind": "readme_generation"},
        ]
    )

    class StubLlm:
        async def chat(self, messages, **kw):
            return skills_json

    skills, err = await stage_suggest_skills(intent, StubLlm())
    assert err == ""
    assert len(skills) == 2
    assert skills[0].kind == "project_directory_scan"
    assert skills[1].kind == "readme_generation"


# ── mod_employee_agent_runner new tools ───────────────────────────────────────


def test_scan_project_tree_basic(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_scan_project_tree

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / "node_modules").mkdir()  # should be skipped
    (tmp_path / "node_modules" / "pkg.js").write_text("x")

    result = asyncio.get_event_loop().run_until_complete(tool_scan_project_tree(str(tmp_path), "."))
    assert result["ok"] is True
    paths = [e["path"] for e in result["files"]]
    assert any("main.py" in p for p in paths)
    assert any("README.md" in p for p in paths)
    # node_modules must be excluded
    assert not any("node_modules" in p for p in paths)


def test_scan_project_tree_path_escape(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_scan_project_tree

    result = asyncio.get_event_loop().run_until_complete(
        tool_scan_project_tree(str(tmp_path), "../../etc")
    )
    assert result["ok"] is False
    assert "越界" in result["error"]


def test_identify_file_types(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_identify_file_types

    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.ts").write_text("")

    result = asyncio.get_event_loop().run_until_complete(
        tool_identify_file_types(str(tmp_path), ".")
    )
    assert result["ok"] is True
    ft = result["file_types"]
    assert ft.get(".py", 0) == 2
    assert ft.get(".ts", 0) == 1


def test_analyze_project_summary_fallback(tmp_path):
    from modstore_server.mod_employee_agent_runner import tool_analyze_project_summary

    (tmp_path / "package.json").write_text('{"name":"test","version":"1.0.0"}')
    (tmp_path / "README.md").write_text("# My Project\nHello world.")

    result = asyncio.get_event_loop().run_until_complete(
        tool_analyze_project_summary(str(tmp_path), ".")
    )
    assert result["ok"] is True
    assert "manifests" in result or "top_level" in result
    # README snippet
    assert "Hello world" in (result.get("readme_snippet") or "")


def test_agent_runner_dispatches_scan_project_tree(tmp_path):
    """Runner correctly routes scan_project_tree to the new tool."""
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    (tmp_path / "src.py").write_text("x = 1")

    queue = [
        json.dumps(
            {
                "thought": "先扫描目录",
                "tool": "scan_project_tree",
                "input": {"path": "."},
            }
        ),
        json.dumps(
            {
                "thought": "扫描完毕",
                "answer": "项目共 1 个 Python 文件",
            }
        ),
    ]

    async def mock_llm(messages, **kw):
        if not queue:
            return {"ok": False, "content": ""}
        return {"ok": True, "content": queue.pop(0)}

    ctx = {
        "call_llm": mock_llm,
        "workspace_root": str(tmp_path),
        "employee_id": "test",
    }
    result = asyncio.get_event_loop().run_until_complete(EmployeeAgentRunner(ctx).run("扫描项目"))
    assert result["ok"] is True
    # Tool call was scan_project_tree
    assert result["tool_calls"][0]["tool"] == "scan_project_tree"
    assert result["tool_calls"][0]["result"]["ok"] is True


# ── employee_executor agent handler ──────────────────────────────────────────


def test_action_agent_runner_missing_project_root_when_required():
    """When requires_project_root=True and no project_root in input, return clear error."""
    from modstore_server.employee_executor import _action_agent_runner

    actions_cfg = {
        "handlers": ["agent"],
        "agent": {
            "workspace": {
                "mode": "user_project",
                "requires_project_root": True,
                "read_only": True,
            }
        },
    }
    reasoning = {"input": {}, "provider": "deepseek", "model": "deepseek-chat", "system_prompt": ""}

    result = _action_agent_runner(actions_cfg, reasoning, "analyze project", "emp1", 1)
    assert result["ok"] is False
    assert "project_root" in result["error"].lower() or "项目根" in result["error"]


def test_action_agent_runner_invalid_project_root(tmp_path):
    """An out-of-workspace project_root must be rejected."""
    from modstore_server.employee_executor import _action_agent_runner

    actions_cfg = {
        "handlers": ["agent"],
        "agent": {"workspace": {"requires_project_root": False, "read_only": True}},
    }
    reasoning = {
        "input": {"project_root": "../../etc/passwd"},
        "provider": "deepseek",
        "model": "deepseek-chat",
        "system_prompt": "",
    }

    # The vibe_adapter.ensure_within_workspace should reject this path.
    # We mock it to simulate the rejection without real filesystem checks.
    with patch(
        "modstore_server.integrations.vibe_adapter.ensure_within_workspace",
        side_effect=Exception("路径越界: ../../etc/passwd"),
    ):
        result = _action_agent_runner(actions_cfg, reasoning, "task", "emp1", 1)
    assert result["ok"] is False
    assert "project_root" in result["error"].lower() or "路径" in result["error"]
