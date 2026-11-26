"""Exercise the real pinned SDK against a deterministic process, without a model."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.xiaox import XiaoxTransport, XiaoxTransportConfig, XiaoxTransportError
from app.infrastructure.xiaox.launcher import launch_arguments, runtime_environment


@pytest.fixture
def config(tmp_path: Path) -> XiaoxTransportConfig:
    return XiaoxTransportConfig(
        runtime_root=tmp_path / "runtime",
        scope_id="tenant:u:run",
        model="private-model",
        provider_url="http://127.0.0.1:19101/v1",
        provider_token="scoped-model-token",
        mcp_url="http://127.0.0.1:19102/api/agent-runtime/xiaox/mcp",
        mcp_token="scoped-mcp-token",
        context_window=32768,
        auto_compact_token_limit=24000,
        timeout_seconds=3,
    )


def test_environment_and_configuration_do_not_inherit_host_authority(config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "host-secret")
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted-proxy")
    monkeypatch.setenv("NO_PROXY", "host.example")
    monkeypatch.setenv("no_proxy", "host.example")
    monkeypatch.setenv("CODEX_HOME", "/host/config-with-mcp")
    transport = XiaoxTransport(config)
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
            "binary": "/managed/bin/xiaox",
            "provider_token": config.provider_token,
            "mcp_token": config.mcp_token,
        }
    )
    assert not (
        {"OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "HTTP_PROXY", "PYTHONPATH"} & env.keys()
    )
    assert env["CODEX_HOME"] == str(transport.runtime_dir)
    assert env["NO_PROXY"] == env["no_proxy"] == "127.0.0.1,localhost,::1"
    assert os.environ["NO_PROXY"] == os.environ["no_proxy"] == "host.example"
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
    from app.infrastructure.xiaox import launcher
    from XCAGI import run_fastapi

    plan = tmp_path / "launch.json"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    arguments = launch_arguments(plan)
    assert arguments == (sys.executable, "--xcagi-xiaox-launch", str(plan))
    launched = []
    monkeypatch.setattr(launcher, "main", lambda path: launched.append(path))

    def forbidden(*_args):
        raise AssertionError("Xiaox subprocess initialized the application server")

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
    path = tmp_path / "fake-xiaox"
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
    return {"id": "turn-1", "items": [], "itemsView": "full", "status": status}
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
        send({"id":msg["id"],"result":{"userAgent":"xiaox/0.171.0"}})
    elif method in ("thread/start", "thread/resume"):
        p = msg["params"]
        send({"id":msg["id"],"result":{"thread":thread(),"model":p["model"],
          "modelProvider":p["modelProvider"],"cwd":os.getcwd(),"approvalPolicy":"never",
          "approvalsReviewer":"user","sandbox":{"type":"readOnly"},"instructionSources":[]}})
    elif method == "turn/start":
        inputs = msg["params"]["input"]
        mode = inputs[0]["text"] if inputs else "tool-output"
        if mode == "tool-output" and msg["params"].get("toolOutput", {}).get("output") == "__reject_tool_output__":
            send({"id":msg["id"],"error":{"code":-32602,"message":"Unsupported toolOutput"}})
            continue
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
    elif method == "thread/compact/start":
        send({"id":msg["id"],"result":{}})
        notify("turn/started", {"threadId":"thread-1", "turn":turn()})
        notify("item/completed", {"threadId":"thread-1","turnId":"turn-1",
          "item":{"type":"contextCompaction","id":"compact-1"}})
        finish()
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
        async with XiaoxTransport(config) as runtime:
            thread_id = await runtime.start_thread(developer_instructions="Only authorized tools")
            events = [event async for event in runtime.stream_turn("approval")]
            assert events[-1]["payload"]["turn"]["status"] == "completed"
            assert not (runtime.runtime_dir / "launch.json").exists()
        async with XiaoxTransport(config) as runtime:
            assert await runtime.resume_thread(thread_id) == thread_id
            events = [event async for event in runtime.stream_turn("failure")]
            assert events[-1]["payload"]["turn"]["status"] == "failed"
            assert (
                next(e for e in events if e["method"] == "item/completed")["item_id"] == "message-1"
            )
        async with XiaoxTransport(config) as runtime:
            with pytest.raises(XiaoxTransportError, match="not bound"):
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


def test_goal_feedback_is_sdk_tool_output_not_user_input(config, fake_runtime):
    binary, log = fake_runtime

    async def scenario():
        async with XiaoxTransport(replace(config, codex_bin=str(binary))) as runtime:
            await runtime.start_thread()
            _ = [event async for event in runtime.stream_turn("Revise the email")]
            _ = [event async for event in runtime.stream_turn(None, goal_feedback="Keep English")]

    asyncio.run(scenario())
    turns = [
        m["params"]
        for line in log.read_text().splitlines()
        if (m := json.loads(line)).get("method") == "turn/start"
    ]
    first, retry = turns
    assert first["threadId"] == retry["threadId"]
    assert first["input"][0]["text"] == "Revise the email"
    assert "toolOutput" not in first
    assert retry["input"] == []
    assert retry["toolOutput"]["name"] == "verify_runtime_goal"
    assert retry["toolOutput"]["output"] == "Keep English"
    assert retry["toolOutput"]["retain"] is False


def test_goal_feedback_carries_host_output_schema(config, fake_runtime):
    binary, log = fake_runtime
    schema = {
        "type": "object",
        "required": ["tool_id", "action", "params"],
        "properties": {"tool_id": {"type": "string"}},
    }

    async def scenario():
        async with XiaoxTransport(replace(config, codex_bin=str(binary))) as runtime:
            await runtime.start_thread()
            _ = [event async for event in runtime.stream_turn("Write the workbook")]
            _ = [
                event
                async for event in runtime.stream_turn(
                    None, goal_feedback="Submit one action", output_schema=schema
                )
            ]

    asyncio.run(scenario())
    turns = [
        m["params"]
        for line in log.read_text().splitlines()
        if (m := json.loads(line)).get("method") == "turn/start"
    ]
    first, retry = turns
    assert "outputSchema" not in first
    assert retry["outputSchema"] == schema
    assert retry["toolOutput"]["name"] == "verify_runtime_goal"


def test_interruption_is_a_terminal_event_not_business_success(config, fake_runtime):
    binary, _ = fake_runtime

    async def scenario():
        async with XiaoxTransport(replace(config, codex_bin=str(binary))) as runtime:
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
        async with XiaoxTransport(replace(config, codex_bin=str(binary))) as runtime:
            await runtime.start_thread()
            with pytest.raises(XiaoxTransportError) as caught:
                _ = [event async for event in runtime.stream_turn("disconnect")]
            assert caught.value.code == "xiaox_connection_lost"
            assert caught.value.outcome_unknown is True

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([m for m in messages if m.get("method") == "turn/start"]) == 1


def test_timeout_closes_runtime_without_starting_another_turn(config, fake_runtime):
    binary, log = fake_runtime

    async def scenario():
        async with XiaoxTransport(
            replace(config, codex_bin=str(binary), turn_timeout_seconds=0.1)
        ) as runtime:
            await runtime.start_thread()
            with pytest.raises(XiaoxTransportError) as caught:
                _ = [event async for event in runtime.stream_turn("wait")]
            assert caught.value.code == "xiaox_timeout"
            assert caught.value.outcome_unknown is True

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([m for m in messages if m.get("method") == "turn/start"]) == 1


@pytest.mark.parametrize("cancellation", ["caller", "total_deadline"])
def test_compaction_completion_cannot_swallow_cancellation(
    config, fake_runtime, monkeypatch, cancellation
):
    binary, log = fake_runtime
    config = replace(config, codex_bin=str(binary), turn_timeout_seconds=2)

    async def scenario():
        async with XiaoxTransport(config) as runtime:
            await runtime.start_thread()
            client, process = runtime._client, runtime._client._proc
            original_to_thread, original_timeout = asyncio.to_thread, asyncio.timeout
            original_unregister = client.unregister_goal_operation
            deadlines, unregistered = [], []

            def observe_timeout(delay):
                deadline = original_timeout(delay)
                if delay == config.turn_timeout_seconds:
                    deadlines.append(deadline)
                return deadline

            def unregister(subscription):
                unregistered.append(subscription)
                original_unregister(subscription)

            async def deliver_at_cancellation(fn, *args, **kwargs):
                result = await original_to_thread(fn, *args, **kwargs)
                if fn.__name__ == "next_goal_notification" and result.method == "turn/completed":
                    # The real SDK result is ready. Deliver it and cancellation
                    # in one loop iteration, before the awaiting task resumes.
                    loop = asyncio.get_running_loop()
                    handoff = loop.create_future()
                    loop.call_soon(handoff.set_result, result)
                    if cancellation == "caller":
                        loop.call_soon(compacting.cancel)
                    else:
                        deadlines[0].reschedule(loop.time())
                    return await handoff
                return result

            with monkeypatch.context() as timing:
                timing.setattr(asyncio, "timeout", observe_timeout)
                timing.setattr(asyncio, "to_thread", deliver_at_cancellation)
                timing.setattr(client, "unregister_goal_operation", unregister)
                compacting = asyncio.create_task(runtime.compact_thread())
                async with original_timeout(10):
                    if cancellation == "caller":
                        with pytest.raises(asyncio.CancelledError):
                            await compacting
                        assert compacting.cancelled()
                    else:
                        with pytest.raises(XiaoxTransportError) as caught:
                            await compacting
                        assert caught.value.code == "xiaox_timeout"
                        assert deadlines[0].expired()
            assert len(unregistered) == 1
            assert runtime._client is None and runtime._streaming is False
            assert process.poll() is not None

    asyncio.run(scenario())
    messages = [json.loads(line) for line in log.read_text().splitlines()]
    assert len([m for m in messages if m.get("method") == "thread/compact/start"]) == 1
    assert not any(m.get("method") == "turn/start" for m in messages)


def test_unpinned_runtime_is_rejected_before_creating_thread(config, fake_runtime):
    binary, log = fake_runtime
    binary.write_text(binary.read_text().replace("0.171.0", "0.172.0-alpha.2"))

    async def scenario():
        with pytest.raises(XiaoxTransportError) as caught:
            async with XiaoxTransport(replace(config, codex_bin=str(binary))):
                pytest.fail("wrong runtime entered")
        assert caught.value.code == "xiaox_runtime_version_mismatch"

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
        async with XiaoxTransport(replace(config, codex_bin=str(binary))) as runtime:
            with pytest.raises(XiaoxTransportError) as caught:
                await runtime.start_thread()
            assert caught.value.code == "xiaox_policy_mismatch"

    asyncio.run(scenario())
    assert not any(
        json.loads(line).get("method") == "turn/start" for line in log.read_text().splitlines()
    )


@pytest.mark.parametrize("orphan_writer", [False, True])
def test_initialize_timeout_releases_sdk_waiters_and_exits_process(tmp_path, orphan_writer):
    """Bound asyncio.run itself, including its non-daemon SDK request thread."""
    if os.name == "nt":
        pytest.skip("POSIX orphan-pipe fixture; the frozen Windows probe exercises its job")
    binary = tmp_path / "silent-runtime"
    descendant_pid = tmp_path / "descendant.pid"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, subprocess, sys, time\n"
        "sys.stdin.readline()\n"
        + (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
            "stdin=subprocess.DEVNULL, start_new_session=True)\n"
            f"pathlib.Path({str(descendant_pid)!r}).write_text(str(child.pid))\n"
            if orphan_writer
            else "time.sleep(30)\n"
        ),
        encoding="utf-8",
    )
    binary.chmod(0o700)
    scenario = """
import asyncio, secrets, sys
from pathlib import Path
from app.infrastructure.xiaox import XiaoxTransport, XiaoxTransportConfig, XiaoxTransportError
async def check():
    config = XiaoxTransportConfig(
        runtime_root=Path(sys.argv[2]), scope_id="timeout-probe", model="no-model",
        provider_url="http://127.0.0.1:1/v1", provider_token=secrets.token_urlsafe(32),
        mcp_url="http://127.0.0.1:1/mcp", mcp_token=secrets.token_urlsafe(32),
        context_window=32768, timeout_seconds=0.2, codex_bin=sys.argv[1],
    )
    try:
        async with XiaoxTransport(config):
            raise AssertionError("silent runtime initialized")
    except XiaoxTransportError as exc:
        assert exc.code == "xiaox_timeout", exc.code
asyncio.run(check())
print("request worker released; asyncio.run exited")
"""
    runner = subprocess.Popen(
        [sys.executable, "-c", scenario, str(binary), str(tmp_path / "runtime")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = runner.communicate(timeout=10)
        assert runner.returncode == 0, stderr
        assert "asyncio.run exited" in stdout
    finally:
        groups = [runner.pid]
        if descendant_pid.is_file():
            groups.append(int(descendant_pid.read_text()))
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        runner.wait(timeout=3)


@pytest.mark.parametrize("pipe_available", [True, False])
def test_windowed_launcher_uses_only_sdk_win32_pipes_and_owned_job(
    monkeypatch, tmp_path, pipe_available
):
    from app.infrastructure.xiaox import launcher

    events, spawned = [], []
    plan = {
        "state_dir": str(tmp_path),
        "workspace": str(tmp_path),
        "job_name": "owned-job",
        "binary": "C:\\managed\\xiaox.exe",
        "provider_token": "scope",
        "mcp_token": "scope",
    }
    kernel = SimpleNamespace(
        OpenJobObjectW=lambda *_: events.append("open") or 99,
        AssignProcessToJobObject=lambda *_: events.append("assign") or True,
        GetCurrentProcess=lambda: -1,
        CloseHandle=lambda *_: events.append("close") or True,
        SetDllDirectoryW=lambda *_: events.append("dll") or True,
        GetStdHandle=lambda number: {-10: 100, -11: 101, -12: 102}[number],
        GetFileType=lambda handle: 3 if pipe_available or handle != 100 else 0,
    )

    def create_process(arguments, **kwargs):
        events.append("spawn")
        spawned.append((arguments, kwargs))
        return SimpleNamespace(pid=4242, wait=lambda: 0)

    monkeypatch.setattr(launcher, "_windows_kernel", lambda: kernel)
    monkeypatch.setattr(subprocess, "Popen", create_process)
    monkeypatch.setattr(
        subprocess, "STARTUPINFO", lambda: SimpleNamespace(dwFlags=0), raising=False
    )
    monkeypatch.setattr(subprocess, "STARTF_USESTDHANDLES", 0x100, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(os, "get_handle_inheritable", lambda _: False, raising=False)
    monkeypatch.setattr(os, "set_handle_inheritable", lambda *_: None, raising=False)
    with monkeypatch.context() as windowed:
        windowed.setattr(sys, "platform", "win32")
        windowed.setattr(sys, "frozen", True, raising=False)
        for stream in ("stdin", "stdout", "stderr"):
            windowed.setattr(sys, stream, None)
        with pytest.raises(SystemExit) as stopped:
            launcher._run_windows(plan, plan["binary"], {"PATH": "managed"})
    assert stopped.value.code == (0 if pipe_available else 1)
    if not pipe_available:
        assert not spawned
        assert json.loads((tmp_path / "launcher-status.json").read_text())["phase"] == "failed"
        return
    assert events == ["open", "assign", "close", "dll", "spawn"]
    arguments, options = spawned[0]
    assert arguments == [plan["binary"], "app-server", "--listen", "stdio://"]
    assert options["env"] == {"PATH": "managed"}
    assert options["cwd"] == plan["workspace"]
    assert options["close_fds"] is True
    assert options["creationflags"] == 0x08000000
    startup = options["startupinfo"]
    assert startup.dwFlags & 0x100
    assert [startup.hStdInput, startup.hStdOutput, startup.hStdError] == [100, 101, 102]
    assert startup.lpAttributeList == {"handle_list": [100, 101, 102]}
    diagnostic = json.loads((tmp_path / "launcher-status.json").read_text())
    assert diagnostic["stdio_pipes"] == [True, True, True]
    assert diagnostic["cli_pid"] == 4242
    assert not {"provider_token", "mcp_token", "job_name", "env"} & diagnostic.keys()
