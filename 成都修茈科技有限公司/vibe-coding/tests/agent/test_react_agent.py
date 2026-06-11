"""Tests for the ReAct loop, tool registry, and built-in tools.

Uses :class:`MockLLM` to script deterministic Thought→Action→Observation
turns. Filesystem / shell tools run inside a real ``tmp_path`` so the
path-guard and side effects are exercised end-to-end.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from vibe_coding.agent.react import (
    AgentStep,
    ReActAgent,
    Tool,
    ToolError,
    ToolRegistry,
    ToolResult,
    builtin_tools,
    tool,
)
from vibe_coding.agent.sandbox import MockSandboxDriver, SandboxResult
from vibe_coding.nl import MockLLM


# -------------------------------------------------------------- registry


def test_tool_decorator_infers_arguments() -> None:
    @tool("greet", description="Say hello")
    def greet_(name: str, *, loud: bool = False) -> str:
        return f"hi {name}{'!' if loud else ''}"

    assert greet_.name == "greet"
    arg_names = [a["name"] for a in greet_.arguments]
    assert "name" in arg_names
    assert "loud" in arg_names
    types = {a["name"]: a["type"] for a in greet_.arguments}
    assert types["loud"] == "boolean"


def test_tool_run_returns_tool_result() -> None:
    @tool("add")
    def add(a: int, b: int) -> int:
        return a + b

    res = add.run(a=2, b=3)
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert res.output == 5
    assert "5" in res.observation


def test_tool_run_captures_exceptions() -> None:
    @tool("boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    res = boom.run()
    assert res.success is False
    assert "kaboom" in res.observation


def test_tool_explicit_tool_error_observation_clean() -> None:
    @tool("guard")
    def guard(x: int) -> None:
        if x < 0:
            raise ToolError("x must be non-negative")

    res = guard.run(x=-1)
    assert res.success is False
    assert res.observation == "[guard] failed: x must be non-negative"


def test_registry_dispatch_and_listing() -> None:
    @tool("echo")
    def echo_(text: str) -> str:
        return text

    reg = ToolRegistry([echo_])
    assert "echo" in reg.names()
    res = reg.call("echo", {"text": "hi"})
    assert res.output == "hi"


def test_registry_unknown_tool_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(Exception):
        reg.call("missing", {})


# -------------------------------------------------------------- ReAct loop


def _llm_step(thought: str, *, tool: str = "", args: dict | None = None,
               final_answer: str = "") -> str:
    return json.dumps(
        {
            "thought": thought,
            "action": {"tool": tool, "args": args or {}},
            "final_answer": final_answer,
        }
    )


def test_agent_returns_final_answer_immediately() -> None:
    reg = ToolRegistry()
    llm = MockLLM([_llm_step("answer is 42", final_answer="42")])
    agent = ReActAgent(llm=llm, tools=reg, max_steps=3)
    result = agent.run("what is the answer?")
    assert result.success is True
    assert result.final_answer == "42"
    assert len(result.steps) == 1


def test_agent_invokes_tool_then_finishes() -> None:
    @tool("magic")
    def magic_(x: int) -> int:
        return x * 2

    reg = ToolRegistry([magic_])
    llm = MockLLM(
        [
            _llm_step("call magic", tool="magic", args={"x": 21}),
            _llm_step("got it", final_answer="42"),
        ]
    )
    agent = ReActAgent(llm=llm, tools=reg, max_steps=5)
    result = agent.run("compute")
    assert result.success is True
    assert result.final_answer == "42"
    assert result.steps[0].tool == "magic"
    assert result.steps[0].output == 42
    assert result.steps[1].tool == ""


def test_agent_records_step_callback() -> None:
    @tool("noop")
    def noop_() -> str:
        return "ok"

    seen: list[AgentStep] = []
    reg = ToolRegistry([noop_])
    llm = MockLLM(
        [
            _llm_step("step 1", tool="noop"),
            _llm_step("done", final_answer="finished"),
        ]
    )
    agent = ReActAgent(
        llm=llm, tools=reg, max_steps=5, on_step=lambda s: seen.append(s)
    )
    agent.run("do thing")
    assert len(seen) == 2
    assert seen[0].tool == "noop"


def test_agent_max_steps_exhausted_records_error() -> None:
    @tool("loop")
    def loop_() -> str:
        return "still going"

    reg = ToolRegistry([loop_])
    llm = MockLLM([_llm_step("keep going", tool="loop")])
    agent = ReActAgent(llm=llm, tools=reg, max_steps=3)
    result = agent.run("infinite")
    assert result.success is False
    assert "max_steps=3" in result.error
    assert len(result.steps) == 3


def test_agent_handles_unknown_tool_as_observation() -> None:
    reg = ToolRegistry()
    llm = MockLLM(
        [
            _llm_step("try unknown", tool="ghost", args={"x": 1}),
            _llm_step("recovered", final_answer="ok"),
        ]
    )
    agent = ReActAgent(llm=llm, tools=reg, max_steps=4)
    result = agent.run("explore")
    assert result.success is True
    assert "not in the registry" in result.steps[0].observation


def test_agent_recovers_from_parse_error() -> None:
    reg = ToolRegistry()
    llm = MockLLM(
        [
            "definitely not json",
            _llm_step("recovered", final_answer="ok"),
        ]
    )
    agent = ReActAgent(llm=llm, tools=reg, max_steps=4)
    result = agent.run("anything")
    assert result.success is True
    # First step recorded the parse error, second step finished.
    assert "parse_error" in result.steps[0].observation
    assert result.steps[1].final_answer == "ok"


def test_agent_records_tracer_phases() -> None:
    @tool("noop")
    def noop_() -> str:
        return "ok"

    reg = ToolRegistry([noop_])
    llm = MockLLM(
        [
            _llm_step("call", tool="noop"),
            _llm_step("done", final_answer="done"),
        ]
    )
    phases: list[tuple[int, str]] = []
    agent = ReActAgent(
        llm=llm,
        tools=reg,
        tracer=lambda step, phase: phases.append((step.index, phase)),
    )
    agent.run("anything")
    # Expect start+end for each step.
    assert (1, "start") in phases and (1, "end") in phases
    assert (2, "start") in phases and (2, "end") in phases


# -------------------------------------------------------------- builtin tools


def test_builtin_filesystem_tools(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("hello", encoding="utf-8")
    reg = builtin_tools(root=tmp_path)
    res = reg.call("read_file", {"path": "src/a.txt"})
    assert res.success is True
    assert res.output == "hello"

    res = reg.call("list_dir", {"path": "src"})
    names = {e["name"] for e in res.output["entries"]}
    assert names == {"a.txt"}

    res = reg.call("write_file", {"path": "src/b.txt", "contents": "world"})
    assert (tmp_path / "src" / "b.txt").read_text() == "world"

    res = reg.call(
        "apply_edit",
        {"path": "src/a.txt", "old_text": "hello", "new_text": "HELLO"},
    )
    assert (tmp_path / "src" / "a.txt").read_text() == "HELLO"
    assert "applied edit" in res.observation


def test_builtin_path_guard_rejects_traversal(tmp_path: Path) -> None:
    reg = builtin_tools(root=tmp_path)
    res = reg.call("read_file", {"path": "../etc/passwd"})
    assert res.success is False
    assert "unsafe path" in res.observation


def test_builtin_apply_edit_unique_match_required(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("foo foo bar", encoding="utf-8")
    reg = builtin_tools(root=tmp_path)
    res = reg.call("apply_edit", {"path": "x.txt", "old_text": "foo", "new_text": "baz"})
    assert res.success is False
    assert "appears 2 times" in res.observation


def test_builtin_grep_finds_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        textwrap.dedent(
            """
            import logging
            logger = logging.getLogger(__name__)
            print('hello')
            """
        ),
        encoding="utf-8",
    )
    reg = builtin_tools(root=tmp_path)
    res = reg.call("grep", {"pattern": r"print\(", "include": "*.py"})
    assert res.success is True
    matches = res.output["matches"]
    assert any(m["file"] == "a.py" for m in matches)


def test_builtin_run_command_uses_sandbox(tmp_path: Path) -> None:
    drv = MockSandboxDriver(
        response=SandboxResult(success=True, stdout="hello\n", exit_code=0)
    )
    reg = builtin_tools(root=tmp_path, sandbox=drv)
    res = reg.call("run_command", {"command": ["echo", "hello"]})
    assert res.success is True
    assert res.output["stdout"].startswith("hello")
    drv.assert_called_with_command("echo")


def test_builtin_shell_allowlist_rejects_other_commands(tmp_path: Path) -> None:
    reg = builtin_tools(root=tmp_path, shell_allowlist=("pytest", "ruff"))
    res = reg.call("run_command", {"command": ["rm", "-rf", "/"]})
    assert res.success is False
    assert "not in allowlist" in res.observation


def test_builtin_web_disabled_by_default(tmp_path: Path) -> None:
    reg = builtin_tools(root=tmp_path)
    assert "http_fetch" not in reg.names()


def test_builtin_web_enabled_via_flag(tmp_path: Path) -> None:
    reg = builtin_tools(root=tmp_path, allow_network=True)
    assert "http_fetch" in reg.names()
