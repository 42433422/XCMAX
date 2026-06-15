"""Autonomous tool-using agent (ReAct loop) for vibe-coding.

The agents we shipped so far operate in **fixed pipelines**: each role
has a hard-coded responsibility and order. That works well for known
workflows (planner → coder → reviewer) but falls down on open-ended
tasks where the agent needs to *decide* what to do next based on
intermediate observations:

- "审查一下这个仓库，找出最容易出 bug 的模块并修复"
- "从 npm 上找最近发布的 framer-motion 版本，把所有 import 升级"
- "排查为什么 `pytest -k user_service` 第 3 次后会偶发失败"

These need a **ReAct loop**: the LLM picks a tool, observes its output,
reasons, picks the next tool, … until it can produce a final answer.

Components:

- :class:`Tool` Protocol + :class:`tool` decorator — write a Python
  function, decorate it, expose it to the agent.
- :class:`ToolRegistry` — collection that produces JSON schemas for the
  LLM and dispatches calls.
- :class:`ReActAgent` — the loop. Plug in any :class:`LLMClient`.
- :func:`builtin_tools` — ready-made tools (file I/O, shell via
  sandbox, grep, git, repo index, web search) that the user's
  ProjectVibeCoder backs onto.

The loop's prompt format is intentionally simple (JSON-only) so it
works with **any** LLM, not just OpenAI's function-calling models.
Vendors that *do* support native tool-calling (OpenAI, Qwen, Claude)
get the same answer; the JSON-only path is the lowest common
denominator.
"""

from __future__ import annotations

from .agent import (
    AgentRunResult,
    AgentStep,
    ReActAgent,
    ReActAgentError,
)
from .builtins import builtin_tools, register_project_tools
from .tools import (
    Tool,
    ToolError,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    tool,
)

__all__ = [
    "AgentRunResult",
    "AgentStep",
    "ReActAgent",
    "ReActAgentError",
    "Tool",
    "ToolError",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolResult",
    "builtin_tools",
    "register_project_tools",
    "tool",
]
