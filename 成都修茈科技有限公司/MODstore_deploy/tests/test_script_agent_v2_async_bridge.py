from __future__ import annotations

import asyncio
import inspect
import sys
import types
from dataclasses import dataclass
from typing import Any

from modstore_server.script_agent.brief import Brief, ContextBundle
from modstore_server.script_agent.sandbox_runner import SandboxResult


def _install_fake_vibe_agent_loop(monkeypatch) -> None:
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

            sandbox_call = self.tools.get("run_sandbox").func("print('ok')")
            assert inspect.isawaitable(sandbox_call)
            sandbox_output = await sandbox_call
            yield _FakeV2Event(
                "tool_call_end",
                1,
                {"tool": "run_sandbox", "output": sandbox_output, "observation": "ok"},
            )
            yield _FakeV2Event(
                "final_answer",
                2,
                {"answer": "```python\nprint('ok')\n```"},
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
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1024) -> str:
        await asyncio.sleep(0)
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
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
        outputs=[{"path": "outputs/result.txt"}],
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

    assert [ev.type for ev in events] == ["context", "plan", "run", "done"]
    assert llm.calls
    assert _sandbox_runner.calls
    assert _sandbox_runner.calls[0]["session_id"] == "sess_v2"
