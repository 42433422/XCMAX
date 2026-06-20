"""专属工具调用库 employee_specialized_tools 的单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.mod_sdk.employee_specialized_tools import (
    EMPLOYEE_TOOLS,
    TOOL_REGISTRY,
    get_employee_tools,
    handle_specialized,
    list_all_tool_names,
)


class TestToolRegistry:
    """工具注册表完整性测试。"""

    def test_all_52_employees_have_tools(self):
        """52 个编制员工每个都至少注册了 1 个专属工具。"""
        assert len(EMPLOYEE_TOOLS) >= 52
        for eid, tools in EMPLOYEE_TOOLS.items():
            assert len(tools) > 0, f"员工 {eid} 没有注册任何专属工具"

    def test_all_referenced_tools_are_registered(self):
        """EMPLOYEE_TOOLS 中引用的工具名都在 TOOL_REGISTRY 中有实现。"""
        for eid, tools in EMPLOYEE_TOOLS.items():
            for t in tools:
                assert t in TOOL_REGISTRY, f"员工 {eid} 引用了未注册的工具 {t}"

    def test_all_tool_implementations_are_callable(self):
        """TOOL_REGISTRY 中每个工具都是可调用对象。"""
        for name, fn in TOOL_REGISTRY.items():
            assert callable(fn), f"工具 {name} 不可调用"

    def test_get_employee_tools_returns_copy(self):
        """get_employee_tools 返回列表副本，修改不影响原注册表。"""
        tools = get_employee_tools("fhd-core-maintainer")
        assert len(tools) > 0
        tools.append("fake_tool")
        tools2 = get_employee_tools("fhd-core-maintainer")
        assert "fake_tool" not in tools2

    def test_get_employee_tools_unknown_employee_returns_empty(self):
        """未知员工返回空列表。"""
        assert get_employee_tools("nonexistent-employee") == []

    def test_list_all_tool_names_sorted(self):
        """list_all_tool_names 返回排序后的工具名列表。"""
        names = list_all_tool_names()
        assert names == sorted(names)
        assert len(names) >= 40


class TestHandleSpecialized:
    """handle_specialized 调度入口测试。"""

    @pytest.mark.asyncio
    async def test_no_tool_returns_available_list(self):
        """未指定 tool 时返回该员工可用工具清单。"""
        result = await handle_specialized("fhd-core-maintainer", {"handler": "specialized"}, {})
        assert result["ok"] is True
        assert result["employee_id"] == "fhd-core-maintainer"
        assert "available_tools" in result
        assert len(result["available_tools"]) > 0

    @pytest.mark.asyncio
    async def test_tool_not_in_employee_allowlist_rejected(self):
        """员工不能调用未注册给自己的工具。"""
        # intent-analyst 没有注册 run_pytest
        result = await handle_specialized(
            "intent-analyst",
            {"handler": "specialized", "tool": "run_pytest", "params": {}},
            {},
        )
        assert result["ok"] is False
        assert "不在员工" in result["error"]
        assert "available_tools" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_rejected(self):
        """调用不存在的工具名被拒绝。"""
        result = await handle_specialized(
            "fhd-core-maintainer",
            {"handler": "specialized", "tool": "nonexistent_tool", "params": {}},
            {},
        )
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_params_not_dict_rejected(self):
        """params 非对象被拒绝。"""
        result = await handle_specialized(
            "fhd-core-maintainer",
            {"handler": "specialized", "tool": "git_diff", "params": "not_a_dict"},
            {},
        )
        assert result["ok"] is False
        assert "params" in result["error"]

    @pytest.mark.asyncio
    async def test_git_status_real_execution(self):
        """git_status 工具真实执行（项目根有 git 仓库）。"""
        result = await handle_specialized(
            "site-content-editor",
            {"handler": "specialized", "tool": "git_status", "params": {}},
            {"employee_id": "site-content-editor", "workspace_root": "."},
        )
        assert result["ok"] is True
        assert result["tool"] == "git_status"
        assert result["employee_id"] == "site-content-editor"
        assert "files" in result

    @pytest.mark.asyncio
    async def test_git_log_real_execution(self):
        """git_log 工具真实执行。"""
        result = await handle_specialized(
            "deploy-release-officer",
            {"handler": "specialized", "tool": "git_log", "params": {"n": 5}},
            {},
        )
        assert result["ok"] is True
        assert "commits" in result

    @pytest.mark.asyncio
    async def test_list_employee_packs_real_execution(self):
        """list_employee_packs 工具真实扫描 _employees 目录。"""
        result = await handle_specialized(
            "mods-and-eskill-curator",
            {"handler": "specialized", "tool": "list_employee_packs", "params": {}},
            {},
        )
        assert result["ok"] is True
        assert "packs" in result
        assert len(result["packs"]) > 0

    @pytest.mark.asyncio
    async def test_list_employees_real_execution(self):
        """list_employees 工具真实读取 duty_roster.json。"""
        result = await handle_specialized(
            "daily-orchestrator",
            {"handler": "specialized", "tool": "list_employees", "params": {}},
            {},
        )
        assert result["ok"] is True
        assert "employees" in result
        assert len(result["employees"]) >= 52

    @pytest.mark.asyncio
    async def test_validate_employee_pack_valid(self):
        """validate_employee_pack 验证合法员工包。"""
        result = await handle_specialized(
            "employee-pack-curator",
            {
                "handler": "specialized",
                "tool": "validate_employee_pack",
                "params": {"pack_id": "fhd-core-maintainer"},
            },
            {},
        )
        assert result["ok"] is True
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_employee_pack_not_found(self):
        """validate_employee_pack 验证不存在的员工包。"""
        result = await handle_specialized(
            "employee-pack-curator",
            {
                "handler": "specialized",
                "tool": "validate_employee_pack",
                "params": {"pack_id": "nonexistent-pack"},
            },
            {},
        )
        assert result["ok"] is False
        assert "manifest" in result["error"]

    @pytest.mark.asyncio
    async def test_read_file_within_project(self):
        """read_file 读取项目内文件。"""
        result = await handle_specialized(
            "doc-knowledge-curator",
            {"handler": "specialized", "tool": "read_file", "params": {"path": "pyproject.toml"}},
            {},
        )
        assert result["ok"] is True
        assert "content" in result

    @pytest.mark.asyncio
    async def test_read_file_path_traversal_blocked(self):
        """read_file 拒绝路径越界。"""
        result = await handle_specialized(
            "doc-knowledge-curator",
            {
                "handler": "specialized",
                "tool": "read_file",
                "params": {"path": "../../../etc/passwd"},
            },
            {},
        )
        assert result["ok"] is False
        assert "越界" in result["error"]

    @pytest.mark.asyncio
    async def test_sandbox_python_restricted_import_blocked(self):
        """sandbox_python 拒绝危险 import（无 confirm）。"""
        result = await handle_specialized(
            "artifact-generator",
            {
                "handler": "specialized",
                "tool": "sandbox_python",
                "params": {"code": "import os; print(os.getcwd())"},
            },
            {},
        )
        assert result["ok"] is False
        assert "confirm" in result["error"]

    @pytest.mark.asyncio
    async def test_sandbox_python_safe_code_executes(self):
        """sandbox_python 执行安全代码。"""
        result = await handle_specialized(
            "artifact-generator",
            {"handler": "specialized", "tool": "sandbox_python", "params": {"code": "print(1+1)"}},
            {},
        )
        assert result["ok"] is True
        assert "2" in result["stdout"]

    @pytest.mark.asyncio
    async def test_pack_release_requires_confirm(self):
        """pack_release 需 confirm 确认。"""
        result = await handle_specialized(
            "deploy-release-officer",
            {"handler": "specialized", "tool": "pack_release", "params": {}},
            {},
        )
        assert result["ok"] is False
        assert result.get("requires_confirm") is True

    @pytest.mark.asyncio
    async def test_list_docs_returns_markdown_files(self):
        """list_docs 返回 markdown 文件列表。"""
        result = await handle_specialized(
            "doc-knowledge-curator",
            {"handler": "specialized", "tool": "list_docs", "params": {}},
            {},
        )
        assert result["ok"] is True
        assert "docs" in result

    @pytest.mark.asyncio
    async def test_list_scripts_returns_python_and_shell(self):
        """list_scripts 返回 python 和 shell 脚本列表。"""
        result = await handle_specialized(
            "retention-officer",
            {"handler": "specialized", "tool": "list_scripts", "params": {"category": "deploy"}},
            {},
        )
        assert result["ok"] is True
        assert "python" in result
        assert "shell" in result
        assert len(result["shell"]) > 0

    @pytest.mark.asyncio
    async def test_result_includes_metadata(self):
        """工具结果包含 tool/employee_id/handler 元数据。"""
        result = await handle_specialized(
            "deploy-release-officer",
            {"handler": "specialized", "tool": "git_log", "params": {"n": 5}},
            {},
        )
        assert result["tool"] == "git_log"
        assert result["employee_id"] == "deploy-release-officer"
        assert result["handler"] == "specialized"
