from __future__ import annotations

import asyncio
import json
import socket
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from modstore_server import employee_specialized_tools as specialized
from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

ROLE_ROOT = Path(__file__).resolve().parents[3] / "FHD" / "mods" / "_employees"
AGENT_ROLES = {
    "self-checker",
}
DIRECT_AUDIT_ROLES = {
    "ecosystem-investor-portal-officer",
    "ecosystem-joint-catalog-officer",
    "employee-planner",
    "enterprise-adoption-officer",
    "host-checker",
    "intent-analyst",
    "marketing-site-builder",
}


def test_reviewed_roles_declare_their_bounded_real_capability() -> None:
    for employee_id in sorted(AGENT_ROLES):
        manifest = json.loads(
            (ROLE_ROOT / employee_id / "manifest.json").read_text(encoding="utf-8")
        )
        actions = manifest["employee_config_v2"]["actions"]
        assert actions["handlers"] == ["agent"]
        assert actions["agent"]["workspace"]["requires_project_root"] is True

    for employee_id in sorted(DIRECT_AUDIT_ROLES):
        manifest = json.loads(
            (ROLE_ROOT / employee_id / "manifest.json").read_text(encoding="utf-8")
        )
        actions = manifest["employee_config_v2"]["actions"]
        direct = actions["direct_python"]
        assert actions["handlers"] == ["direct_python"]
        assert direct["implementation"] == "employee_module"
        assert direct["execution_mode"] == "deterministic"
        assert direct["read_only"] is True

    self_checker = json.loads(
        (ROLE_ROOT / "self-checker" / "manifest.json").read_text(encoding="utf-8")
    )
    assert self_checker["employee_config_v2"]["actions"]["agent"]["capabilities"] == [
        "xcemp_validate"
    ]


def test_host_probe_rejects_unapproved_host_before_network() -> None:
    with pytest.raises(ValueError, match="白名单"):
        asyncio.run(
            specialized.probe_mod_host(
                "https://unapproved.example.test",
                allowed_hosts={"approved.example.test"},
            )
        )


def test_host_probe_rejects_allowlisted_dns_name_resolving_private_network() -> None:
    with patch.object(
        socket,
        "getaddrinfo",
        return_value=[(0, 0, 0, "", ("169.254.169.254", 0))],
    ):
        with pytest.raises(ValueError, match="禁用网段"):
            asyncio.run(
                specialized.probe_mod_host(
                    "https://approved.example.test",
                    allowed_hosts={"approved.example.test"},
                )
            )


def test_host_probe_always_rejects_metadata_literal() -> None:
    with pytest.raises(ValueError, match="永久禁用网段"):
        asyncio.run(
            specialized.probe_mod_host(
                "http://169.254.169.254",
                allowed_hosts={"169.254.169.254"},
            )
        )


def test_specialized_tools_are_employee_scoped_and_blocked_in_burn_in(tmp_path) -> None:
    ordinary = EmployeeAgentRunner(
        {
            "employee_id": "intent-analyst",
            "employee_capabilities": [],
            "workspace_root": str(tmp_path),
        },
        workspace_root=str(tmp_path),
    )
    denied = asyncio.run(ordinary._dispatch_tool("probe_mod_host", {}))
    assert denied["ok"] is False
    assert "无权" in denied["error"]

    burn_in = EmployeeAgentRunner(
        {
            "employee_id": "host-checker",
            "employee_capabilities": ["host_probe"],
            "read_only": True,
            "workspace_root": str(tmp_path),
        },
        workspace_root=str(tmp_path),
    )
    blocked = asyncio.run(burn_in._dispatch_tool("probe_mod_host", {}))
    assert blocked["ok"] is False
    assert blocked["blocked"] is True


def test_read_only_protocol_does_not_advertise_unavailable_tools(tmp_path) -> None:
    captured: list[list[dict]] = []

    async def call_llm(messages, **_kwargs):
        captured.append(messages)
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "thought": "已完成真实只读观察并整理证据。",
                    "answer": json.dumps(
                        {
                            "status": "success",
                            "summary": "已完成只读观察并保留真实证据。",
                            "evidence": ["workspace"],
                        },
                        ensure_ascii=False,
                    ),
                },
                ensure_ascii=False,
            ),
        }

    runner = EmployeeAgentRunner(
        {
            "employee_id": "host-checker",
            "employee_capabilities": ["host_probe"],
            "read_only": True,
            "workspace_root": str(tmp_path),
            "call_llm": call_llm,
        },
        workspace_root=str(tmp_path),
    )
    result = asyncio.run(runner.run("只读巡检"))

    protocol = "\n".join(
        str(message.get("content") or "")
        for message in captured[0]
        if message.get("role") == "system"
    )
    assert result["ok"] is True
    assert "probe_mod_host" not in protocol
    assert "http_get" not in protocol
    assert "write_workspace_file" not in protocol
    assert "run_sandboxed_python" not in protocol


def test_xcemp_validation_runs_real_validate_in_isolated_cwd(tmp_path) -> None:
    archive = tmp_path / "sample.xcemp"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "__main__.py",
            "import sys\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'validate':\n"
            "    print('validated')\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(2)\n",
        )
        zf.writestr(
            "sample/manifest.json",
            json.dumps({"id": "sample", "version": "1.0.0"}),
        )
        zf.writestr("sample/skills/check/SKILL.md", "# check\n")

    result = asyncio.run(
        specialized.validate_xcemp_package(str(tmp_path), archive.name, timeout_seconds=5)
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["archive"]["pack_id"] == "sample"
    assert result["archive"]["skill_file_count"] == 1
    assert len(result["sha256"]) == 64
    assert result["isolation"] == "isolated_cwd_clean_env"


def test_xcemp_validation_rejects_workspace_escape(tmp_path) -> None:
    result = asyncio.run(specialized.validate_xcemp_package(str(tmp_path), "../outside.xcemp"))
    assert result["ok"] is False
    assert result["stage"] == "archive_inspection"
    assert "相对路径" in result["error"]
