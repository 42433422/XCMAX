"""写审批流闭环测试。

验证 fhd-core-maintainer 的代码修改工具（patch_file/write_file）全链路：
1. 工具注册完整性（TOOL_REGISTRY / EMPLOYEE_TOOLS / CODE_WRITE_TOOLS）
2. handle_specialized 对写工具走 gate 检查（拦截/放行）
3. write_file/patch_file 工具实际执行（confirm / 路径越界 / 缺参）
4. risk_gate 把代码修改工具判为 high 风险
5. workspace_guard 对代码修改工具强制 scope_globs / forbidden_globs
6. write_approval gate 对代码修改工具强制审批
7. manifest handlers 已改为 agent
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.application.employee_runtime.risk_gate import gate_action_or_block
from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS
from app.application.employee_runtime.workspace_guard import build_employee_gate
from app.application.employee_runtime.write_approval import build_write_approval_gate
from app.mod_sdk.employee_specialized_tools import (
    EMPLOYEE_TOOLS,
    TOOL_REGISTRY,
    _code_write_tools,
    handle_specialized,
    tool_patch_file,
    tool_write_file,
)

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "mods"
    / "_employees"
    / "fhd-core-maintainer"
    / "manifest.json"
)


class TestCodeWriteToolsRegistration:
    """代码修改工具注册完整性。"""

    def test_patch_file_and_write_file_registered(self):
        assert "patch_file" in TOOL_REGISTRY
        assert "write_file" in TOOL_REGISTRY
        assert callable(TOOL_REGISTRY["patch_file"])
        assert callable(TOOL_REGISTRY["write_file"])

    def test_fhd_core_maintainer_has_code_write_tools(self):
        tools = EMPLOYEE_TOOLS.get("fhd-core-maintainer", [])
        assert "patch_file" in tools, "fhd-core-maintainer 应有 patch_file 工具"
        assert "write_file" in tools, "fhd-core-maintainer 应有 write_file 工具"

    def test_code_write_tools_lazy_resolver(self):
        cwt = _code_write_tools()
        assert "patch_file" in cwt
        assert "write_file" in cwt

    def test_code_write_tools_in_tool_scope(self):
        assert "patch_file" in CODE_WRITE_TOOLS
        assert "write_file" in CODE_WRITE_TOOLS


class TestWriteFileTool:
    """write_file 工具执行测试。"""

    def test_without_confirm_rejected(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(tool_write_file({"path": "test.txt", "content": "hi"}, ctx))
        assert not result["ok"]
        assert "confirm" in result["error"]

    def test_with_confirm_writes_file(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(
            tool_write_file({"path": "test.txt", "content": "hello", "confirm": True}, ctx)
        )
        assert result["ok"], result.get("error", "")
        assert (tmp_path / "test.txt").read_text() == "hello"

    def test_path_traversal_blocked(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(
            tool_write_file({"path": "../escape.txt", "content": "evil", "confirm": True}, ctx)
        )
        assert not result["ok"]
        assert "越出" in result["error"]

    def test_missing_path_rejected(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(tool_write_file({"content": "hi", "confirm": True}, ctx))
        assert not result["ok"]

    def test_creates_parent_dirs(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(
            tool_write_file({"path": "sub/dir/test.txt", "content": "nested", "confirm": True}, ctx)
        )
        assert result["ok"], result.get("error", "")
        assert (tmp_path / "sub" / "dir" / "test.txt").read_text() == "nested"


class TestPatchFileTool:
    """patch_file 工具执行测试。"""

    def test_without_confirm_rejected(self, tmp_path):
        (tmp_path / "target.py").write_text("x = 1\n")
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(tool_patch_file({"path": "target.py", "patch": "fake patch"}, ctx))
        assert not result["ok"]
        assert "confirm" in result["error"]

    def test_missing_params_rejected(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(tool_patch_file({"confirm": True}, ctx))
        assert not result["ok"]

    def test_nonexistent_target_rejected(self, tmp_path):
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(
            tool_patch_file({"path": "nope.py", "patch": "fake", "confirm": True}, ctx)
        )
        assert not result["ok"]
        assert "不存在" in result["error"]

    def test_path_traversal_blocked(self, tmp_path):
        (tmp_path / "target.py").write_text("x = 1\n")
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(
            tool_patch_file({"path": "../escape.py", "patch": "fake", "confirm": True}, ctx)
        )
        assert not result["ok"]
        assert "越出" in result["error"]


class TestWriteGateEnforcement:
    """handle_specialized 对代码修改工具走 gate 检查。"""

    def test_write_file_blocked_by_gate(self, monkeypatch):
        async def fake_gate(eid, tool, params, ctx):
            return {"ok": False, "reason": "scope 不允许"}

        monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake_gate)
        payload = {
            "handler": "specialized",
            "tool": "write_file",
            "params": {"path": "x.py", "content": "y", "confirm": True},
        }
        result = asyncio.run(handle_specialized("fhd-core-maintainer", payload, {}))
        assert not result["ok"]
        assert result.get("blocked") is True
        assert "scope" in result["error"]

    def test_write_file_passes_gate_when_authorized(self, monkeypatch, tmp_path):
        async def fake_gate(eid, tool, params, ctx):
            return {"ok": True}

        monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake_gate)
        payload = {
            "handler": "specialized",
            "tool": "write_file",
            "params": {"path": "ok.txt", "content": "done", "confirm": True},
        }
        ctx = {"workspace_root": str(tmp_path)}
        result = asyncio.run(handle_specialized("fhd-core-maintainer", payload, ctx))
        assert result["ok"], result.get("error", "")
        assert (tmp_path / "ok.txt").read_text() == "done"

    def test_patch_file_blocked_by_gate(self, monkeypatch):
        async def fake_gate(eid, tool, params, ctx):
            return {"ok": False, "reason": "forbidden_globs 命中"}

        monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake_gate)
        payload = {
            "handler": "specialized",
            "tool": "patch_file",
            "params": {"path": "x.py", "patch": "diff", "confirm": True},
        }
        result = asyncio.run(handle_specialized("fhd-core-maintainer", payload, {}))
        assert not result["ok"]
        assert result.get("blocked") is True

    def test_non_write_tool_skips_gate(self, monkeypatch):
        gate_called: list[str] = []

        async def fake_gate(eid, tool, params, ctx):
            gate_called.append(tool)
            return {"ok": True}

        monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake_gate)
        payload = {"handler": "specialized", "tool": "git_status", "params": {}}
        asyncio.run(handle_specialized("site-content-editor", payload, {}))
        assert gate_called == []

    def test_gate_pending_approval_propagated(self, monkeypatch):
        async def fake_gate(eid, tool, params, ctx):
            return {
                "ok": False,
                "reason": "待审批",
                "pending_approval": True,
                "approval_request_ids": ["req-123"],
            }

        monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake_gate)
        payload = {
            "handler": "specialized",
            "tool": "write_file",
            "params": {"path": "x.py", "content": "y", "confirm": True},
        }
        result = asyncio.run(handle_specialized("fhd-core-maintainer", payload, {}))
        assert not result["ok"]
        assert result.get("pending_approval") is True
        assert "req-123" in result.get("approval_request_ids", [])


class TestRiskGateCodeWrite:
    """risk_gate 把代码修改工具判为 high 风险。"""

    def test_patch_file_judged_high(self, monkeypatch):
        monkeypatch.delenv("FHD_RISK_HIGH_GATE_TOKEN", raising=False)
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer", manifest, ["agent"], {"tool": "patch_file"}
        )
        assert result["risk_level"] == "high"

    def test_write_file_judged_high(self, monkeypatch):
        monkeypatch.delenv("FHD_RISK_HIGH_GATE_TOKEN", raising=False)
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer", manifest, ["agent"], {"tool": "write_file"}
        )
        assert result["risk_level"] == "high"

    def test_high_risk_blocked_without_flag(self, monkeypatch):
        monkeypatch.delenv("FHD_RISK_HIGH_GATE_TOKEN", raising=False)
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer", manifest, ["agent"], {"tool": "patch_file"}
        )
        assert not result["ok"]
        assert result.get("blocked") is True

    def test_high_risk_allowed_with_allow_flag(self, monkeypatch):
        monkeypatch.delenv("FHD_RISK_HIGH_GATE_TOKEN", raising=False)
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer",
            manifest,
            ["agent"],
            {"tool": "write_file", "allow_high_risk_real_run": True},
        )
        assert result["ok"]

    def test_high_risk_blocked_with_wrong_token(self, monkeypatch):
        monkeypatch.setenv("FHD_RISK_HIGH_GATE_TOKEN", "secret123")
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer",
            manifest,
            ["agent"],
            {
                "tool": "patch_file",
                "allow_high_risk_real_run": True,
                "high_risk_gate_token": "wrong",
            },
        )
        assert not result["ok"]

    def test_high_risk_allowed_with_correct_token(self, monkeypatch):
        monkeypatch.setenv("FHD_RISK_HIGH_GATE_TOKEN", "secret123")
        manifest = {"employee_config_v2": {}}
        result = gate_action_or_block(
            "fhd-core-maintainer",
            manifest,
            ["agent"],
            {
                "tool": "patch_file",
                "allow_high_risk_real_run": True,
                "high_risk_gate_token": "secret123",
            },
        )
        assert result["ok"]


class TestWorkspaceGuardCodeWrite:
    """workspace_guard 对代码修改工具强制 scope_globs / forbidden_globs。"""

    @staticmethod
    def _manifest(scope_globs, forbidden_globs):
        return {
            "employee_config_v2": {
                "workspace_policy": {
                    "scope_globs": scope_globs,
                    "forbidden_globs": forbidden_globs,
                }
            }
        }

    def test_write_file_in_scope_allowed(self):
        manifest = self._manifest(["FHD/app/**"], [])
        config = manifest["employee_config_v2"]
        gate = build_employee_gate("fhd-core-maintainer", manifest, config, "/workspace")
        assert gate is not None
        result = gate("write_file", {"path": "FHD/app/test.py"})
        assert result["ok"], result.get("reason", "")

    def test_write_file_outside_scope_blocked(self):
        manifest = self._manifest(["FHD/app/**"], [])
        config = manifest["employee_config_v2"]
        gate = build_employee_gate("fhd-core-maintainer", manifest, config, "/workspace")
        result = gate("write_file", {"path": "MODstore_deploy/evil.py"})
        assert not result["ok"]
        assert "scope_globs" in result["reason"]

    def test_write_file_forbidden_glob_blocked(self):
        manifest = self._manifest(["FHD/app/**"], ["*.vue"])
        config = manifest["employee_config_v2"]
        gate = build_employee_gate("fhd-core-maintainer", manifest, config, "/workspace")
        result = gate("write_file", {"path": "FHD/app/Component.vue"})
        assert not result["ok"]
        assert "forbidden_globs" in result["reason"]

    def test_patch_file_enforced_by_scope(self):
        manifest = self._manifest(["FHD/tests/**"], [])
        config = manifest["employee_config_v2"]
        gate = build_employee_gate("fhd-core-maintainer", manifest, config, "/workspace")
        result = gate("patch_file", {"path": "FHD/tests/test_x.py"})
        assert result["ok"]
        result2 = gate("patch_file", {"path": "FHD/app/evil.py"})
        assert not result2["ok"]


class TestWriteApprovalGateCodeWrite:
    """write_approval gate 对代码修改工具强制审批。"""

    def test_write_file_requires_approval(self):
        gate = build_write_approval_gate("fhd-core-maintainer", {})
        result = gate("write_file", {"path": "x.py"})
        assert not result["ok"]

    def test_write_file_approved_write_passes(self):
        gate = build_write_approval_gate("fhd-core-maintainer", {"approved_write": True})
        result = gate("write_file", {"path": "x.py"})
        assert result["ok"]

    def test_write_file_allow_write_passes(self):
        gate = build_write_approval_gate("fhd-core-maintainer", {"allow_write": True})
        result = gate("write_file", {"path": "x.py"})
        assert result["ok"]

    def test_patch_file_requires_approval(self):
        gate = build_write_approval_gate("fhd-core-maintainer", {})
        result = gate("patch_file", {"path": "x.py"})
        assert not result["ok"]

    def test_non_write_tool_passes(self):
        gate = build_write_approval_gate("fhd-core-maintainer", {})
        result = gate("git_status", {})
        assert result["ok"]


class TestManifestHandler:
    """fhd-core-maintainer manifest 配置验证。"""

    def test_handlers_is_agent(self):
        manifest = json.loads(_MANIFEST_PATH.read_text())
        handlers = manifest["employee_config_v2"]["actions"]["handlers"]
        assert "agent" in handlers
        assert "direct_python" not in handlers

    def test_workspace_policy_intact(self):
        manifest = json.loads(_MANIFEST_PATH.read_text())
        wp = manifest["employee_config_v2"]["workspace_policy"]
        assert "FHD/app/**" in wp["scope_globs"]
        assert "FHD/tests/**" in wp["scope_globs"]
        assert "*.vue" in wp["forbidden_globs"]
        assert "MODstore_deploy/**" in wp["forbidden_globs"]

    def test_triggers_declared(self):
        manifest = json.loads(_MANIFEST_PATH.read_text())
        triggers = manifest.get("triggers", {})
        assert triggers.get("on_error") is True
        assert triggers.get("on_quality_fail") is True
        assert triggers.get("on_coverage_miss") is True
