"""Exercise the real pinned SDK against a deterministic process, without a model."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.infrastructure.codex import CodexTransport, CodexTransportConfig, CodexTransportError
from app.infrastructure.codex.launcher import launch_arguments, runtime_environment


@pytest.fixture
def config(tmp_path: Path) -> CodexTransportConfig:
    return CodexTransportConfig(
        runtime_root=tmp_path / "runtime",
        scope_id="tenant:u:run",
        model="private-model",
        provider_url="http://127.0.0.1:19101/v1",
        provider_token="scoped-model-token",
        mcp_url="http://127.0.0.1:19102/api/agent-runtime/codex/mcp",
        mcp_token="scoped-mcp-token",
        context_window=32768,
        auto_compact_token_limit=24000,
        timeout_seconds=3,
    )


def test_environment_and_configuration_do_not_inherit_host_authority(config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "host-secret")
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted-proxy")
    monkeypatch.setenv("CODEX_HOME", "/host/config-with-mcp")
    transport = CodexTransport(config)
    transport._prepare()
    import tomllib

    settings = tomllib.loads((transport.runtime_dir / "config.toml").read_text())
    assert settings["project_doc_max_bytes"] == 0
    assert settings["features"]["shell_tool"] is False
    assert settings["features"]["plugins"] is False
    assert settings["features"]["memories"] is False
    for name in (
        "api_key_model_discovery",
        "api_key_cyber_access_programs",
        "goals",
        "view_image",
        "browser_use",
        "computer_use",
        "image_generation",
        "code_mode",
        "remote_plugin",
        "hooks",
        "multi_agent_v2",
        "default_mode_request_user_input",
        "memory_tool",
        "shell_snapshot",
        "unified_exec",
        "apply_patch_freeform",
        "tool_search",
        "skill_search",
    ):
        assert settings["features"][name] is False
    assert settings["features"]["skip_host_skill_discovery"] is True
    assert settings["agents"]["enabled"] is False
    assert settings["tools"]["experimental_request_user_input"]["enabled"] is False
    assert settings["tools"]["update_plan"]["enabled"] is False
    assert settings["web_search"] == "disabled"
    assert list(settings["mcp_servers"]) == ["xcmax"]
    server = settings["mcp_servers"]["xcmax"]
    assert server["default_tools_approval_mode"] == "prompt"
    assert server["tools"] == {name: {"approval_mode": "approve"} for name in config.mcp_tools}
    provider = settings["model_providers"]["xcmax_gateway"]
    assert provider["requires_openai_auth"] is False
    assert provider["capabilities"]["remote_compaction"] == "unsupported"
    assert provider["request_max_retries"] == provider["stream_max_retries"] == 0
    env = runtime_environment(
        {
            "state_dir": str(transport.runtime_dir),
            "binary": "/managed/bin/codex",
            "provider_token": config.provider_token,
            "mcp_token": config.mcp_token,
        }
    )
    assert not (
        {"OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "HTTP_PROXY", "PYTHONPATH"} & env.keys()
    )
    assert env["CODEX_HOME"] == str(transport.runtime_dir)
    assert os.environ["CODEX_HOME"] == "/host/config-with-mcp"
    assert "scoped-model-token" not in (transport.runtime_dir / "config.toml").read_text()
    assert "scoped-mcp-token" not in repr(config)
    if os.name != "nt":
        assert (transport.runtime_dir / "config.toml").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_url": "https://api.openai.com/v1"},
        {"provider_url": "http://localhost:8000/v1"},
        {"mcp_url": "http://untrusted.example/mcp"},
        {"mcp_url": "https://user:secret@example.com/mcp"},
        {"mcp_tools": ("api_call",)},
        {"context_window": 0},
        {"scope_id": ""},
    ],
)
def test_invalid_configuration_fails_before_launch(config, overrides):
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_frozen_launcher_reenters_backend_without_starting_the_server(monkeypatch, tmp_path):
    from app.infrastructure.codex import launcher
    from XCAGI import run_fastapi

    plan = tmp_path / "launch.json"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    arguments = launch_arguments(plan)
    assert arguments == (sys.executable, "--xcagi-codex-launch", str(plan))
    launched = []
    monkeypatch.setattr(launcher, "main", lambda path: launched.append(path))

    def forbidden(*_args):
        raise AssertionError("Codex subprocess initialized the application server")

    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", forbidden)
    monkeypatch.setattr(run_fastapi, "_apply_no_console_child_defaults", forbidden)
    monkeypatch.setattr(run_fastapi, "_load_dotenv_if_present", forbidden)
    run_fastapi.main(list(arguments[1:]))
    assert launched == [str(plan)]


@pytest.fixture
def fake_runtime(tmp_path):
    # The integration speaks the actual SDK protocol. It never talks to a model
    # provider; this test does not substitute for packaged-runtime acceptance.
    if os.name == "nt":
        pytest.skip("The process contract fixture uses a POSIX executable script")
    pytest.importorskip("openai_codex")
    path = tmp_path / "fake-codex"
    log = tmp_path / "protocol.jsonl"
    source = """
import json, os, sys
from pathlib import Path
log = Path(LOG_PATH)
with log.open("a") as out:
    out.write(json.dumps({"runtime_env":dict(os.environ), "cwd":os.getcwd()}) + "\\n")
def send(value):
    print(json.dumps(value), flush=True)
def notify(method, params):
    send({"method": method, "params": params})
def turn(status="inProgress"):
    return {"id": "turn-1", "items": [], "status": status}
def finish(status="completed"):
    notify("turn/completed", {"threadId": "thread-1", "turn": turn(status)})
def thread():
    return {"id":"thread-1","sessionId":"thread-1","cliVersion":"0.171.0", "createdAt":1,
      "updatedAt":1,"cwd":os.getcwd(),"ephemeral":False,"modelProvider":"xcmax_gateway",
      "preview":"","source":"unknown","status":{"type":"idle"},"turns":[]}
for line in sys.stdin:
    msg = json.loads(line)
    with log.open("a") as out:
        out.write(json.dumps(msg) + "\\n")
    method = msg.get("method")
    if method == "initialize":
        send({"id":msg["id"],"result":{"userAgent":"codex/0.171.0"}})
    elif method in ("thread/start", "thread/resume"):
        p = msg["params"]
        send({"id":msg["id"],"result":{"thread":thread(),"model":p["model"],
          "modelProvider":p["modelProvider"],"cwd":os.getcwd(),"approvalPolicy":"never",
          "approvalsReviewer":"user","sandbox":{"type":"readOnly"},"instructionSources":[]}})
    elif method == "turn/start":
        mode = msg["params"]["input"][0]["text"]
        send({"id":msg["id"],"result":{"turn":turn()}})
        if mode == "disconnect":
            sys.exit(0)
        if mode == "approval":
            send({"id":"approval-1","method":"item/commandExecution/requestApproval",
              "params":{"threadId":"thread-1","turnId":"turn-1","itemId":"shell-1"}})
        elif mode != "wait":
            notify("item/completed", {"threadId":"thread-1","turnId":"turn-1",
              "item":{"type":"agentMessage","id":"message-1","text":"verified receipt","phase":"final_answer"}})
            finish("failed" if mode == "failure" else "completed")
    elif method == "turn/interrupt":
        send({"id":msg["id"],"result":{}})
        finish("interrupted")
    elif msg.get("id") == "approval-1":
        finish()
""".replace("LOG_PATH", repr(str(log)))
    path.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path, log


def test_pinned_sdk_stream_resume_and_denied_approval(config, fake_runtime, monkeypatch):
    binary, log = fake_runtime
    monkeypatch.setenv("XCMAX_TEST_HOST_SECRET", "do-not-inherit")
    config = replace(config, codex_bin=str(binary))

    async def scenario():
        async with CodexTransport(config) as runtime:
            thread_id = await runtime.start_thread(developer_instructions="Only authorized tools")
            events = [event async for event in runtime.stream_turn("approval")]
            assert events[-1]["payload"]["turn"]["status"] == "completed"
            assert not (runtime.runtime_dir / "launch.json").exists()
        async with CodexTransport(config) as runtime:
            assert await runtime.resume_thread(thread_id) == thread_id
            events = [event async for event in runtime.stream_turn("failure")]
            assert events[-1]["payload"]["turn"]["status"] == "failed"
            assert (
                next(e for e in events if e["method"] == "item/completed")["item_id"] == "message-1"
            )
        async with CodexTransport(config) as runtime:
            with pytest.raises(CodexTransportError, match="not bound"):
                await runtime.resume_thread("another-thread")

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(
        "XCMAX_TEST_HOST_SECRET" not in m["runtime_env"] for m in messages if "runtime_env" in m
    )
    assert next(m for m in messages if m.get("id") == "approval-1")["result"] == {
        "decision": "decline"
    }
    assert len([m for m in messages if m.get("method") == "thread/start"]) == 1
    assert all(
        m["params"]["capabilities"]["experimentalApi"] is False
        for m in messages
        if m.get("method") == "initialize"
    )


def test_interruption_is_a_terminal_event_not_business_success(config, fake_runtime):
    binary, _ = fake_runtime

    async def scenario():
        async with CodexTransport(replace(config, codex_bin=str(binary))) as runtime:
            await runtime.start_thread()
            events = []
            async for event in runtime.stream_turn("wait"):
                events.append(event)
                if event["method"] == "turn/started":
                    await runtime.interrupt()
            assert events[-1]["payload"]["turn"]["status"] == "interrupted"

    asyncio.run(scenario())


def test_disconnect_never_replays_turn(config, fake_runtime):
    binary, log = fake_runtime

    async def scenario():
        async with CodexTransport(replace(config, codex_bin=str(binary))) as runtime:
            await runtime.start_thread()
            with pytest.raises(CodexTransportError) as caught:
                _ = [event async for event in runtime.stream_turn("disconnect")]
            assert caught.value.code == "codex_connection_lost"
            assert caught.value.outcome_unknown is True

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([m for m in messages if m.get("method") == "turn/start"]) == 1


def test_timeout_closes_runtime_without_starting_another_turn(config, fake_runtime):
    binary, log = fake_runtime

    async def scenario():
        async with CodexTransport(
            replace(config, codex_bin=str(binary), turn_timeout_seconds=0.1)
        ) as runtime:
            await runtime.start_thread()
            with pytest.raises(CodexTransportError) as caught:
                _ = [event async for event in runtime.stream_turn("wait")]
            assert caught.value.code == "codex_timeout"
            assert caught.value.outcome_unknown is True

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([m for m in messages if m.get("method") == "turn/start"]) == 1


def test_unpinned_runtime_is_rejected_before_creating_thread(config, fake_runtime):
    binary, log = fake_runtime
    binary.write_text(binary.read_text().replace("0.171.0", "0.172.0-alpha.2"))

    async def scenario():
        with pytest.raises(CodexTransportError) as caught:
            async with CodexTransport(replace(config, codex_bin=str(binary))):
                pytest.fail("wrong runtime entered")
        assert caught.value.code == "codex_runtime_version_mismatch"

    asyncio.run(scenario())
    assert not any(
        json.loads(line).get("method") == "thread/start" for line in log.read_text().splitlines()
    )


def test_inherited_instruction_sources_are_rejected(config, fake_runtime):
    binary, log = fake_runtime
    binary.write_text(
        binary.read_text().replace(
            '"instructionSources":[]', '"instructionSources":["/host/AGENTS.md"]'
        )
    )

    async def scenario():
        async with CodexTransport(replace(config, codex_bin=str(binary))) as runtime:
            with pytest.raises(CodexTransportError) as caught:
                await runtime.start_thread()
            assert caught.value.code == "codex_policy_mismatch"

    asyncio.run(scenario())
    assert not any(
        json.loads(line).get("method") == "turn/start" for line in log.read_text().splitlines()
    )
