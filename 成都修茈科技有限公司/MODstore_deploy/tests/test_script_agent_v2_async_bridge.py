from __future__ import annotations

import asyncio
import inspect
import json
import sys
import types
from dataclasses import dataclass, replace
from typing import Any

import pytest

from modstore_server.script_agent.brief import Brief, ContextBundle
from modstore_server.script_agent.sandbox_runner import SandboxResult


def _install_fake_vibe_agent_loop(
    monkeypatch, *, codes=None, final_code="print('ok')", event_only=False
) -> None:
    codes = ["print('ok')"] if codes is None else codes
    vibe_mod = types.ModuleType("vibe_coding")
    vibe_mod.__path__ = []
    agent_mod = types.ModuleType("vibe_coding.agent")
    agent_mod.__path__ = []
    react_mod = types.ModuleType("vibe_coding.agent.react")
    react_mod.__path__ = []
    loop_mod = types.ModuleType("vibe_coding.agent.loop")
    tools_mod = types.ModuleType("vibe_coding.agent.react.tools")

    @dataclass
    class _FakeV2Event:
        type: str
        step_index: int
        payload: dict[str, Any]

    class _FakeTool:
        def __init__(self, name: str, func: Any) -> None:
            self.name = name
            self.func = func

    class _FakeToolRegistry:
        def __init__(self) -> None:
            self._tools: dict[str, _FakeTool] = {}

        def register(self, tool_obj: _FakeTool) -> _FakeTool:
            self._tools[tool_obj.name] = tool_obj
            return tool_obj

        def get(self, name: str) -> _FakeTool:
            return self._tools[name]

    def _fake_tool(name: str | None = None, **_kwargs: Any):
        def _decorate(fn: Any) -> _FakeTool:
            return _FakeTool(name or fn.__name__, fn)

        return _decorate

    class _FakeAgentLoop:
        def __init__(self, llm: Any, tools: _FakeToolRegistry, **_kwargs: Any) -> None:
            self.llm = llm
            self.tools = tools

        async def arun(self, goal: str, *, run_id: str):
            llm_call = self.llm.chat("system", goal, json_mode=True)
            assert inspect.isawaitable(llm_call)
            await llm_call

            for index, code in enumerate(codes, 1):
                if event_only:
                    sandbox_output = {
                        "ok": True,
                        "returncode": 0,
                        "outputs": [{"filename": "forged.txt"}],
                    }
                else:
                    sandbox_call = self.tools.get("run_sandbox").func(code)
                    assert inspect.isawaitable(sandbox_call)
                    sandbox_output = await sandbox_call
                yield _FakeV2Event(
                    "tool_call_end",
                    index,
                    {"tool": "run_sandbox", "output": sandbox_output, "observation": "ok"},
                )
            yield _FakeV2Event(
                "final_answer",
                len(codes) + 1,
                {"answer": f"```python\n{final_code}\n```"},
            )

    loop_mod.AgentLoop = _FakeAgentLoop
    tools_mod.ToolRegistry = _FakeToolRegistry
    tools_mod.tool = _fake_tool

    monkeypatch.setitem(sys.modules, "vibe_coding", vibe_mod)
    monkeypatch.setitem(sys.modules, "vibe_coding.agent", agent_mod)
    monkeypatch.setitem(sys.modules, "vibe_coding.agent.react", react_mod)
    monkeypatch.setitem(sys.modules, "vibe_coding.agent.loop", loop_mod)
    monkeypatch.setitem(sys.modules, "vibe_coding.agent.react.tools", tools_mod)


class _AsyncLlm:
    def __init__(self, *, verdict=True, observer_error=False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.verdict, self.observer_error = verdict, observer_error

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1024) -> str:
        await asyncio.sleep(0)
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if "验收官" in messages[0]["content"]:
            if self.observer_error:
                raise TimeoutError("observer timed out")
            return json.dumps(
                {"ok": self.verdict, "reason": "accepted" if self.verdict else "rejected"}
            )
        return '{"tool": "run_sandbox", "args": {"code": "print(1)"}}'


async def _sandbox_runner(**kwargs: Any) -> SandboxResult:
    await asyncio.sleep(0)
    _sandbox_runner.calls.append(kwargs)
    return SandboxResult(
        ok=True,
        work_dir="/tmp/fake",
        returncode=0,
        stdout="ok",
        stderr="",
        outputs=[{"path": "outputs/result.txt", "filename": "result.txt", "size": 2}],
        errors=[],
        timed_out=False,
    )


_sandbox_runner.calls = []


def test_agent_loop_v2_bridge_awaits_llm_and_sandbox_inside_arun(monkeypatch):
    _install_fake_vibe_agent_loop(monkeypatch)

    from modstore_server.script_agent import agent_loop

    async def _ctx(brief: Brief, *, user_id: int, upload_items=None, **_kwargs: Any):
        return ContextBundle(
            brief_md=brief.goal,
            inputs_summary="",
            kb_chunks_md="",
            allowlist_packages=[],
        )

    monkeypatch.setattr(agent_loop, "collect_context", _ctx)
    monkeypatch.setattr(agent_loop, "validate_script", lambda code: [])
    _sandbox_runner.calls = []
    llm = _AsyncLlm()
    brief = Brief(goal="write script", outputs="outputs/result.txt", acceptance="sandbox ok")

    async def _collect():
        out = []
        async for ev in agent_loop.run_agent_loop_v2(
            brief,
            llm=llm,
            user_id=7,
            session_id="sess",
            sandbox_runner=_sandbox_runner,
            max_iterations=1,
        ):
            out.append(ev)
        return out

    events = asyncio.run(_collect())

    assert [ev.type for ev in events] == ["context", "plan", "run", "observe", "done"]
    assert llm.calls
    assert _sandbox_runner.calls
    assert _sandbox_runner.calls[0]["session_id"] == "sess_v2"
    outcome = events[-1].payload["outcome"]
    assert outcome["ok"] is True and outcome["last_verdict"]["ok"] is True
    assert outcome["last_result"]["outputs"] == events[-1].payload["outputs"]


@pytest.mark.parametrize(
    "case",
    [
        "no_sandbox",
        "forged_event",
        "changed_final",
        "newer_failure",
        "returncode",
        "timeout",
        "no_outputs",
        "result_failed",
        "observer_reject",
        "observer_error",
        "static_reject",
    ],
)
def test_v2_final_answer_requires_current_real_verification(monkeypatch, case):
    from modstore_server.script_agent import agent_loop

    original, changed = "print('ok')", "print('changed')"
    codes = [] if case == "no_sandbox" else [original]
    final_code = changed if case == "changed_final" else original
    if case == "newer_failure":
        codes.append(changed)
    if case == "static_reject":
        codes = ["import subprocess\nsubprocess.run(['pwd'])"]
        final_code = codes[0]
    _install_fake_vibe_agent_loop(
        monkeypatch, codes=codes, final_code=final_code, event_only=case == "forged_event"
    )

    async def context(*args, **kwargs):
        return ContextBundle(brief_md="write result", inputs_summary="")

    monkeypatch.setattr(agent_loop, "collect_context", context)
    calls = []

    async def sandbox(**kwargs):
        calls.append(kwargs["script_text"])
        result = await _sandbox_runner(**kwargs)
        if case == "newer_failure" and len(calls) == 2:
            return replace(result, ok=False, returncode=1, stderr="latest failed")
        changes = {
            "returncode": {"returncode": 1},
            "timeout": {"timed_out": True},
            "no_outputs": {"outputs": []},
            "result_failed": {"ok": False},
        }
        return replace(result, **changes.get(case, {}))

    async def collect():
        return [
            ev
            async for ev in agent_loop.run_agent_loop_v2(
                Brief(
                    goal="write script",
                    outputs="result.txt",
                    acceptance="sandbox and acceptance pass",
                ),
                llm=_AsyncLlm(
                    verdict=case != "observer_reject", observer_error=case == "observer_error"
                ),
                user_id=7,
                session_id="verification",
                sandbox_runner=sandbox,
                max_iterations=2,
            )
        ]

    events = asyncio.run(collect())
    assert events[-1].type == "error"
    outcome = events[-1].payload["outcome"]
    assert outcome["ok"] is False and outcome["outcome"] == "unverified"
    assert outcome["retryable"] is False and outcome["error"]
    assert not any(ev.type == "done" for ev in events)
    if case in {"no_sandbox", "forged_event", "static_reject"}:
        assert not calls
    else:
        assert len(calls) == (2 if case == "newer_failure" else 1)
    if case == "newer_failure":
        assert outcome["last_result"]["returncode"] == 1


@pytest.mark.parametrize("repair", ["none", "static", "runtime"])
def test_v2_keeps_real_sandbox_artifacts_after_verified_final_answer(tmp_path, monkeypatch, repair):
    from pathlib import Path

    from modstore_server.script_agent import agent_loop
    from modstore_server.script_agent.sandbox_runner import run_in_sandbox

    code = "from pathlib import Path\nPath('outputs/result.txt').write_text('verified', encoding='utf-8')"
    codes = {"none": [], "static": ["print("], "runtime": ["raise RuntimeError('repair this')"]}[
        repair
    ] + [code]
    _install_fake_vibe_agent_loop(monkeypatch, codes=codes, final_code=code)

    async def context(*args, **kwargs):
        return ContextBundle(brief_md="write result", inputs_summary="")

    monkeypatch.setattr(agent_loop, "collect_context", context)

    async def collect():
        return [
            ev
            async for ev in agent_loop.run_agent_loop_v2(
                Brief(
                    goal="write result", outputs="result.txt", acceptance="file contains verified"
                ),
                llm=_AsyncLlm(),
                user_id=7,
                session_id="real-sandbox",
                sandbox_runner=run_in_sandbox,
                sandbox_kwargs={"script_root": tmp_path},
                max_iterations=1,
            )
        ]

    events = asyncio.run(collect())
    assert events[-1].type == "done", events[-1].payload
    outcome = events[-1].payload["outcome"]
    assert outcome["ok"] is True and outcome["last_result"]["returncode"] == 0
    assert outcome["last_verdict"]["ok"] is True
    assert outcome["final_code"] == code
    assert len(events[-1].payload["outputs"]) == 1
    assert Path(events[-1].payload["outputs"][0]["path"]).read_text() == "verified"


@pytest.mark.parametrize(
    "failure",
    ["timeout", "runner_exception", "unknown_sdk", "nonretryable_sdk", "employee_without_receipt"],
)
def test_v2_does_not_restart_sandbox_after_uncertain_effect(monkeypatch, failure):
    from modstore_server.script_agent import agent_loop

    original, changed = "print('ok')", "print('changed')"
    _install_fake_vibe_agent_loop(monkeypatch, codes=[original, changed], final_code=original)

    async def context(*args, **kwargs):
        return ContextBundle(brief_md="write result", inputs_summary="")

    monkeypatch.setattr(agent_loop, "collect_context", context)
    calls = []

    async def sandbox(**kwargs):
        calls.append(kwargs["script_text"])
        if failure == "runner_exception":
            raise TimeoutError("sandbox receipt lost")
        result = await _sandbox_runner(**kwargs)
        if failure == "timeout":
            return replace(result, ok=False, timed_out=True, returncode=-9)
        sdk_call = {
            "unknown_sdk": {"method": "ai", "ok": False, "outcome": "unknown"},
            "nonretryable_sdk": {"method": "http_get", "ok": False, "retryable": False},
            "employee_without_receipt": {"method": "employee_run", "ok": True},
        }[failure]
        return replace(result, sdk_calls=[sdk_call])

    async def collect():
        return [
            ev
            async for ev in agent_loop.run_agent_loop_v2(
                Brief(goal="write result", outputs="result.txt", acceptance="verified output"),
                llm=_AsyncLlm(),
                user_id=7,
                session_id="no-replay",
                sandbox_runner=sandbox,
            )
        ]

    events = asyncio.run(collect())
    assert calls == [original]
    assert events[-1].type == "error"
    outcome = events[-1].payload["outcome"]
    assert (
        outcome["ok"] is False
        and outcome["outcome"] == "unverified"
        and outcome["retryable"] is False
    )
    if failure == "timeout":
        assert outcome["last_result"]["timed_out"] is True
        assert outcome["last_result"]["returncode"] == -9


def test_v2_real_employee_effect_then_timeout_is_not_replayed(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace

    from modstore_server.script_agent import agent_loop
    from modstore_server.script_agent.sandbox_runner import run_in_sandbox

    marker = tmp_path / "employee-effect.txt"

    def execute_task(**kwargs):
        with marker.open("a", encoding="utf-8") as stream:
            stream.write("effect\n")
            stream.flush()
        time.sleep(2)
        return {"ok": True, "completed": True}

    monkeypatch.setattr(
        "modstore_server.services.employee.get_default_employee_client",
        lambda: SimpleNamespace(execute_task=execute_task),
    )
    code = "from modstore_runtime import employee_run\nemployee_run('test-employee', 'synthetic effect')"
    _install_fake_vibe_agent_loop(monkeypatch, codes=[code, code], final_code=code)

    async def context(*args, **kwargs):
        return ContextBundle(brief_md="run employee", inputs_summary="")

    monkeypatch.setattr(agent_loop, "collect_context", context)

    async def collect():
        return [
            ev
            async for ev in agent_loop.run_agent_loop_v2(
                Brief(goal="run employee", outputs="result.txt", acceptance="confirmed result"),
                llm=_AsyncLlm(),
                user_id=7,
                session_id="employee-timeout",
                sandbox_runner=run_in_sandbox,
                sandbox_kwargs={
                    "script_root": tmp_path / "sandbox",
                    "timeout_seconds": 1,
                    "employee_run_allowlist": ["test-employee"],
                },
            )
        ]

    events = asyncio.run(collect())
    assert marker.read_text() == "effect\n"
    assert events[-1].type == "error"
    outcome = events[-1].payload["outcome"]
    assert outcome["last_result"]["timed_out"] is True
    assert outcome["outcome"] == "unverified" and outcome["retryable"] is False
