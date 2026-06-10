"""ReAct loop: Thought → Action → Observation → … → Final Answer.

Wire format the LLM is asked to produce on every turn:

    {
      "thought": "1-3 sentences of reasoning",
      "action": {
        "tool": "tool_name",        // empty string → no tool, finish
        "args": {"k": "v"}
      },
      "final_answer": "..."          // present iff action is empty
    }

The agent loops until either ``final_answer`` is non-empty or
``max_steps`` is exhausted. Tool failures don't break the loop — they
become observations the LLM can react to (this is the whole point of
ReAct).

Two safety nets keep runs cheap:

- :attr:`max_steps` caps the number of LLM round-trips.
- :attr:`step_budget_tokens` is informational; provider-side budgets
  are enforced by the LLM client itself (``max_tokens=…``).

The agent records every step so the caller can inspect / replay /
visualise the run. Plug a ``Tracer`` (``vibe_coding.agent.observability``)
in via ``tracer=`` to ship spans to OpenTelemetry-compatible backends.
"""

from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ...nl.llm import LLMClient, LLMError
from ...nl.parsing import JSONParseError, safe_parse_json_object
from .tools import ToolNotFoundError, ToolRegistry, ToolResult


_REACT_SYSTEM_PROMPT = textwrap.dedent(
    """\
    你是一个**自主规划的工具调用 Agent**。每一轮你必须严格输出一个 JSON 对象（**不要 markdown 围栏**）：

    ```json
    {{
      "thought": "1-3 句你目前的推理（用中文/英文都可以，但务必清晰）",
      "action": {{
        "tool": "若需要继续调用工具，写工具名；否则写空串 \\\"\\\"",
        "args": {{ "param1": "value1", "...": "..." }}
      }},
      "final_answer": "若不再调用工具，则在这里给出最终回答；否则留空串"
    }}
    ```

    规则：

    1. 每轮**必须**输出 JSON 对象，且只包含 `thought`、`action`、`final_answer` 三个字段。
    2. `action.tool` 与 `final_answer` 是互斥的：要么继续工具调用，要么给最终答案。
    3. 工具的可用清单和参数见下文 `## Tools`。**不要**调用未列出的工具。
    4. 工具返回的内容会以 `## Observation N` 的形式追加到下一轮的 user prompt。
    5. 注意逐步推进：一次只调用一个工具，根据观测结果再决定下一步。

    超过 {max_steps} 步必须终止；优先在你确信已经达到目标时返回 `final_answer`。
    """
)


class ReActAgentError(RuntimeError):
    """Raised when the agent cannot produce or parse a valid step."""


@dataclass(slots=True)
class AgentStep:
    """One Thought / Action / Observation triple."""

    index: int
    thought: str
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    output: Any = None
    error: str = ""
    duration_ms: float = 0.0
    final_answer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "thought": self.thought,
            "tool": self.tool,
            "args": dict(self.args),
            "observation": self.observation,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "final_answer": self.final_answer,
        }


@dataclass(slots=True)
class AgentRunResult:
    """Outcome of :meth:`ReActAgent.run`."""

    success: bool
    goal: str
    final_answer: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    error: str = ""
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "goal": self.goal,
            "final_answer": self.final_answer,
            "steps": [s.to_dict() for s in self.steps],
            "error": self.error,
            "total_duration_ms": self.total_duration_ms,
        }


StepCallback = Callable[[AgentStep], None]


class ReActAgent:
    """Tool-using LLM agent.

    Construction takes:

    - ``llm`` — any :class:`vibe_coding.nl.LLMClient` (Mock / OpenAI /
      Qwen / Claude / …).
    - ``tools`` — a :class:`ToolRegistry` exposing the actions the
      agent is allowed to take.
    - ``max_steps`` — hard upper bound on LLM round-trips.
    - ``on_step`` — optional callback called after every step (handy
      to stream the run into a Web UI / logger).
    - ``tracer`` — optional callable taking a :class:`AgentStep` and
      a "phase" (``"start"`` / ``"end"``) so OTel instrumentation can
      open / close spans without coupling to a specific tracer
      implementation.
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        *,
        max_steps: int = 10,
        on_step: StepCallback | None = None,
        tracer: Callable[[AgentStep, str], None] | None = None,
        system_addendum: str = "",
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_steps = max(1, int(max_steps))
        self.on_step = on_step
        self.tracer = tracer
        self.system_addendum = system_addendum

    # -------------------------------------------------------------- public

    def run(self, goal: str, *, context: str = "") -> AgentRunResult:
        if not goal or not goal.strip():
            raise ReActAgentError("`goal` is required")
        result = AgentRunResult(success=False, goal=goal)
        t_start = time.perf_counter()
        observations: list[tuple[int, str]] = []
        for idx in range(1, self.max_steps + 1):
            user_prompt = self._build_user_prompt(goal, context, observations)
            step_start = time.perf_counter()
            raw: str = ""
            llm_failure: str = ""
            try:
                raw = self.llm.chat(self._system_prompt(), user_prompt, json_mode=True)
            except LLMError as exc:
                # Non-JSON responses raise LLMError when ``json_mode=True``
                # is enforced by the provider (MockLLM, OpenAI). Treat this
                # as a parse-recoverable observation so the loop can retry.
                llm_failure = f"parse_error: {exc}"
            if llm_failure:
                step = AgentStep(
                    index=idx,
                    thought="",
                    observation=llm_failure,
                    error=llm_failure,
                    duration_ms=round((time.perf_counter() - step_start) * 1000, 3),
                )
                result.steps.append(step)
                self._notify(step)
                observations.append((idx, llm_failure))
                continue
            try:
                payload = safe_parse_json_object(raw)
            except JSONParseError as exc:
                step = AgentStep(
                    index=idx,
                    thought="",
                    observation=f"parse_error: {exc}",
                    error=f"parse_error: {exc}",
                    duration_ms=round((time.perf_counter() - step_start) * 1000, 3),
                )
                result.steps.append(step)
                self._notify(step)
                observations.append((idx, step.observation))
                continue
            step = self._make_step(idx, payload, step_start)
            self._trace(step, "start")

            if step.final_answer or not step.tool:
                # Final answer path.
                if not step.final_answer:
                    step.final_answer = "(empty answer)"
                step.duration_ms = round((time.perf_counter() - step_start) * 1000, 3)
                result.steps.append(step)
                self._notify(step)
                self._trace(step, "end")
                result.final_answer = step.final_answer
                result.success = True
                break

            tool_result = self._invoke_tool(step.tool, step.args)
            step.observation = tool_result.observation
            step.output = tool_result.output
            if not tool_result.success:
                step.error = tool_result.error
            step.duration_ms = round((time.perf_counter() - step_start) * 1000, 3)
            result.steps.append(step)
            observations.append((idx, step.observation))
            self._notify(step)
            self._trace(step, "end")
        else:
            # max_steps exhausted without final_answer.
            result.error = f"max_steps={self.max_steps} reached without a final answer"

        result.total_duration_ms = round((time.perf_counter() - t_start) * 1000, 3)
        return result

    # -------------------------------------------------------------- internals

    def _system_prompt(self) -> str:
        base = _REACT_SYSTEM_PROMPT.format(max_steps=self.max_steps)
        tools_block = "## Tools\n\n" + self.tools.to_prompt_schema()
        addendum = (
            "\n\n## Extra instructions\n\n" + self.system_addendum.strip()
            if self.system_addendum
            else ""
        )
        return base + "\n\n" + tools_block + addendum

    def _build_user_prompt(
        self,
        goal: str,
        context: str,
        observations: list[tuple[int, str]],
    ) -> str:
        sections = [f"## Goal\n{goal.strip()}"]
        if context:
            sections.append(f"## Context\n{context.strip()[:6_000]}")
        for idx, obs in observations[-12:]:  # cap history to avoid blow-up
            sections.append(f"## Observation {idx}\n```\n{obs[:4_000]}\n```")
        return "\n\n".join(sections)

    def _make_step(
        self, idx: int, payload: dict[str, Any], started_at: float
    ) -> AgentStep:
        thought = str(payload.get("thought") or "")
        action = payload.get("action") or {}
        tool_name = ""
        args: dict[str, Any] = {}
        if isinstance(action, dict):
            tool_name = str(action.get("tool") or "")
            raw_args = action.get("args") or {}
            if isinstance(raw_args, dict):
                args = raw_args
        final_answer = str(payload.get("final_answer") or "").strip()
        return AgentStep(
            index=idx,
            thought=thought,
            tool=tool_name,
            args=args,
            final_answer=final_answer,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )

    def _invoke_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        try:
            return self.tools.call(name, args)
        except ToolNotFoundError as exc:
            return ToolResult(
                success=False,
                observation=(
                    f"[error] tool {name!r} is not in the registry. "
                    f"Available: {', '.join(self.tools.names())}"
                ),
                error=str(exc),
            )

    def _notify(self, step: AgentStep) -> None:
        if self.on_step is None:
            return
        try:
            self.on_step(step)
        except Exception:  # noqa: BLE001
            # User callbacks must never break the loop.
            pass

    def _trace(self, step: AgentStep, phase: str) -> None:
        if self.tracer is None:
            return
        try:
            self.tracer(step, phase)
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "AgentRunResult",
    "AgentStep",
    "ReActAgent",
    "ReActAgentError",
]
