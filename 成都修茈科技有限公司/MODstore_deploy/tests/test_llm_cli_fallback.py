from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from modstore_server import llm_cli_fallback
from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner


def test_four_cli_profiles_match_super_employee_ssot():
    assert [profile.cli_id for profile in llm_cli_fallback.CLI_PROFILES] == [
        "codex",
        "cursor",
        "claude",
        "trae",
    ]


def test_cli_environment_does_not_receive_platform_secrets(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sensitive")
    monkeypatch.setenv("MODSTORE_JWT_SECRET", "sensitive")
    monkeypatch.setenv("NORMAL_SETTING", "kept")

    env = llm_cli_fallback._safe_process_env()

    assert "MINIMAX_API_KEY" not in env
    assert "MODSTORE_JWT_SECRET" not in env
    assert env["NORMAL_SETTING"] == "kept"


def test_invoke_codex_reads_last_message_in_isolated_read_only_mode(monkeypatch):
    profile = llm_cli_fallback.profile_by_id("codex")
    assert profile is not None
    commands = []
    monkeypatch.setattr(llm_cli_fallback, "find_cli_path", lambda _profile: "/bin/codex")

    def fake_run(command, *, cwd, timeout):
        commands.append((command, cwd, timeout))
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("CLI response", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(llm_cli_fallback, "_run", fake_run)

    result = llm_cli_fallback.invoke_cli(
        profile,
        [{"role": "user", "content": "hello"}],
        timeout=30,
    )

    assert result["ok"] is True
    assert result["content"] == "CLI response"
    command = commands[0][0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert Path(commands[0][1]).name.startswith("xcagi-llm-cli-codex-")


def test_cursor_command_uses_isolated_plan_workspace():
    profile = llm_cli_fallback.profile_by_id("cursor")
    assert profile is not None

    command = profile.command_builder(
        "/bin/cursor-agent", "hello", Path("/tmp/out"), "/tmp/isolated"
    )

    assert command[command.index("--mode") + 1] == "plan"
    assert command[command.index("--workspace") + 1] == "/tmp/isolated"
    assert "--force" not in command
    assert "--yolo" not in command


def test_cli_json_output_parsing():
    assert llm_cli_fallback._parse_cli_output('{"result":"CLI_OK"}') == "CLI_OK"
    assert (
        llm_cli_fallback._parse_cli_output('{"type":"progress"}\n{"message":{"content":"done"}}')
        == "done"
    )


@pytest.mark.asyncio
async def test_cli_fallback_tries_configured_order_until_success(monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_CLI_FALLBACK_ORDER", "claude,codex")
    monkeypatch.setattr(llm_cli_fallback, "find_cli_path", lambda profile: f"/bin/{profile.cli_id}")

    def fake_invoke(profile, messages, *, timeout):
        if profile.cli_id == "claude":
            return {"ok": False, "error": "not logged in"}
        return {"ok": True, "content": "fallback answer", "latency_ms": 12}

    monkeypatch.setattr(llm_cli_fallback, "invoke_cli", fake_invoke)

    result = await llm_cli_fallback.chat_via_cli_fallback([{"role": "user", "content": "hello"}])

    assert result["ok"] is True
    assert result["provider"] == "codex_cli"
    assert result["content"] == "fallback answer"
    assert [attempt["cli"] for attempt in result["attempts"]] == ["claude", "codex"]


@pytest.mark.asyncio
async def test_llm_ops_runner_uses_cli_only_after_primary_failure(monkeypatch):
    calls = []

    async def primary(_messages, **_kwargs):
        return {"ok": False, "error": "platform unavailable", "content": ""}

    async def fallback(messages, **kwargs):
        calls.append((messages, kwargs))
        return {"ok": True, "content": "cli answer", "provider": "codex_cli"}

    monkeypatch.setattr(llm_cli_fallback, "chat_via_cli_fallback", fallback)
    runner = EmployeeAgentRunner(
        {
            "employee_id": "llm-ops-engineer",
            "call_llm": primary,
            "cli_fallback_enabled": True,
        },
        workspace_root=".",
    )

    result = await runner._call_llm([{"role": "user", "content": "hello"}])

    assert result["ok"] is True
    assert result["content"] == "cli answer"
    assert result["primary_error"] == "platform unavailable"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_other_employee_cannot_query_cli_status():
    result = await EmployeeAgentRunner(
        {"employee_id": "daily-orchestrator"}, workspace_root="."
    )._dispatch_tool("list_llm_cli_status", {"live_probe": False})

    assert result["ok"] is False
    assert "无权" in result["error"]


@pytest.mark.asyncio
async def test_other_employee_cannot_run_llm_route_autopilot():
    result = await EmployeeAgentRunner(
        {"employee_id": "daily-orchestrator"}, workspace_root="."
    )._dispatch_tool("run_llm_route_autopilot", {})

    assert result["ok"] is False
    assert "无权" in result["error"]
