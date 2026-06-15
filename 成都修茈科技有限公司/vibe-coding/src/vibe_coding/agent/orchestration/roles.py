"""Role implementations for the multi-agent orchestrator.

Every role is a small class with one public method (``handle``) that
takes an :class:`AgentMessage` and returns the next message(s) it
wants to publish. Roles are deliberately stateless so they can be
re-used across runs; per-run state lives on the orchestrator's
:class:`MessageBus`.

Roles share the same underlying :class:`LLMClient` so test runs can
swap in :class:`MockLLM` and replay deterministic responses.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ...nl.llm import LLMClient
from ...nl.parsing import JSONParseError, safe_parse_json_object
from .messages import AgentMessage, AgentTask


@runtime_checkable
class AgentRole(Protocol):
    """Minimum contract every orchestrated role must satisfy."""

    @property
    def name(self) -> str: ...

    def handle(self, message: AgentMessage) -> list[AgentMessage]: ...


# ----------------------------------------------------------------- prompts


_PLANNER_SYSTEM = textwrap.dedent(
    """\
    你是 **Planner**：把用户的总目标拆成 1-5 条具体子任务。

    输出严格 JSON：
    {
      "plan_summary": "一句话计划摘要",
      "tasks": [
        {
          "task_id": "t-1",
          "brief": "子任务 1 的明确指令",
          "rationale": "为什么要做这个",
          "focus_paths": ["src/foo.py"],
          "depends_on": []
        }
      ]
    }
    """
)

_REVIEWER_SYSTEM = textwrap.dedent(
    """\
    你是 **Reviewer**：审查 Coder 提交的 patch / 结果，给出明确决定。

    输出严格 JSON：
    {
      "verdict": "approve" | "revise" | "reject",
      "score": 0-100,
      "reasons": ["...", "..."],
      "suggestions": ["如果 revise / reject，给出修改建议"]
    }
    """
)

_RESEARCHER_SYSTEM = textwrap.dedent(
    """\
    你是 **Researcher**：根据问题给出 ≤500 字的"现有代码 / 最佳实践"摘要。

    输出严格 JSON：
    {
      "findings": ["...", "..."],
      "open_questions": ["..."]
    }
    """
)

_TESTER_SYSTEM = textwrap.dedent(
    """\
    你是 **Tester**：根据 brief 和 patch 推断需要的关键测试用例（边界 / 失败 / 并发 / 异常）。

    输出严格 JSON：
    {
      "tests": [
        {"name": "test_xxx", "input": "...", "expected": "..."}
      ],
      "rationale": "..."
    }
    """
)


# ----------------------------------------------------------------- planner


@dataclass
class PlannerAgent:
    """LLM-backed planner — turns a brief into a list of :class:`AgentTask`."""

    llm: LLMClient
    name: str = "planner"
    max_tasks: int = 5

    def handle(self, message: AgentMessage) -> list[AgentMessage]:
        brief = (message.content.get("brief") or "").strip()
        if not brief:
            return [
                _failure(
                    sender=self.name,
                    recipient=message.sender,
                    parent_id=message.msg_id,
                    reason="planner received empty brief",
                )
            ]
        try:
            raw = self.llm.chat(_PLANNER_SYSTEM, brief, json_mode=True)
            payload = safe_parse_json_object(raw)
        except (JSONParseError, Exception) as exc:  # noqa: BLE001
            return [
                _failure(
                    sender=self.name,
                    recipient=message.sender,
                    parent_id=message.msg_id,
                    reason=f"planner failed: {exc}",
                )
            ]
        tasks_raw = payload.get("tasks") or []
        if not isinstance(tasks_raw, list) or not tasks_raw:
            return [
                _failure(
                    sender=self.name,
                    recipient=message.sender,
                    parent_id=message.msg_id,
                    reason="planner returned no tasks",
                )
            ]
        tasks = [AgentTask.from_dict(t) for t in tasks_raw[: self.max_tasks] if isinstance(t, dict)]
        return [
            AgentMessage(
                sender=self.name,
                recipient=message.content.get("router") or "coder",
                kind="plan",
                parent_id=message.msg_id,
                summary=str(payload.get("plan_summary") or ""),
                content={
                    "plan_summary": str(payload.get("plan_summary") or ""),
                    "tasks": [t.to_dict() for t in tasks],
                    "original_brief": brief,
                },
            )
        ]


# ------------------------------------------------------------------ coder


@dataclass
class CoderAgent:
    """Adapter around :class:`ProjectVibeCoder.edit_project`.

    ``project_coder`` is the :class:`ProjectVibeCoder` (or any object
    quacking like one — the tests pass a stub).
    """

    project_coder: Any
    name: str = "coder"
    apply_patches: bool = False

    def handle(self, message: AgentMessage) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        for raw_task in message.content.get("tasks") or []:
            task = AgentTask.from_dict(raw_task) if isinstance(raw_task, dict) else None
            if task is None or not task.brief:
                continue
            try:
                patch = self.project_coder.edit_project(
                    task.brief, focus_paths=task.focus_paths or None
                )
            except Exception as exc:  # noqa: BLE001
                out.append(
                    AgentMessage(
                        sender=self.name,
                        recipient="reviewer",
                        kind="patch",
                        parent_id=message.msg_id,
                        summary=f"task {task.task_id} failed: {exc}",
                        content={
                            "task": task.to_dict(),
                            "patch": None,
                            "error": str(exc),
                        },
                    )
                )
                continue
            apply_result = None
            if self.apply_patches:
                apply_result = self.project_coder.apply_patch(patch, dry_run=False)
            out.append(
                AgentMessage(
                    sender=self.name,
                    recipient="reviewer",
                    kind="patch",
                    parent_id=message.msg_id,
                    summary=patch.summary,
                    content={
                        "task": task.to_dict(),
                        "patch": patch.to_dict(),
                        "apply_result": (
                            apply_result.to_dict() if apply_result is not None else None
                        ),
                    },
                )
            )
        return out


# ----------------------------------------------------------------- reviewer


@dataclass
class ReviewerAgent:
    """LLM-backed reviewer; emits either an approve message or a revise hint."""

    llm: LLMClient
    name: str = "reviewer"
    min_score: int = 70

    def handle(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "patch":
            return []
        patch = message.content.get("patch")
        task = message.content.get("task") or {}
        prompt = (
            "## 任务\n"
            + str(task.get("brief") or "")
            + "\n\n## Patch\n"
            + (str(patch)[:6_000] if patch else "(empty)")
        )
        try:
            raw = self.llm.chat(_REVIEWER_SYSTEM, prompt, json_mode=True)
            payload = safe_parse_json_object(raw)
        except (JSONParseError, Exception) as exc:  # noqa: BLE001
            return [
                _failure(
                    sender=self.name,
                    recipient="planner",
                    parent_id=message.msg_id,
                    reason=f"reviewer failed: {exc}",
                )
            ]
        verdict = str(payload.get("verdict") or "revise").lower()
        score = int(payload.get("score") or 0)
        reasons = [str(x) for x in payload.get("reasons") or []]
        suggestions = [str(x) for x in payload.get("suggestions") or []]
        kind = "approval" if verdict == "approve" and score >= self.min_score else "revise"
        recipient = "orchestrator" if kind == "approval" else "coder"
        return [
            AgentMessage(
                sender=self.name,
                recipient=recipient,
                kind=kind,
                parent_id=message.msg_id,
                summary=f"verdict={verdict} score={score}",
                content={
                    "verdict": verdict,
                    "score": score,
                    "reasons": reasons,
                    "suggestions": suggestions,
                    "task": task,
                    "patch_msg_id": message.msg_id,
                },
            )
        ]


# ----------------------------------------------------------------- researcher


@dataclass
class ResearcherAgent:
    """Optional pre-coder step: gathers context the coder will need.

    For the agent path that already has a ``RepoIndex`` this is mostly
    advisory — but for greenfield projects (``brief`` mentions a library
    the codebase doesn't use yet) the researcher's "open_questions"
    section gives the coder a clear list of API choices to make.
    """

    llm: LLMClient
    name: str = "researcher"

    def handle(self, message: AgentMessage) -> list[AgentMessage]:
        question = message.content.get("question") or message.content.get("brief") or ""
        if not question:
            return []
        try:
            raw = self.llm.chat(_RESEARCHER_SYSTEM, question, json_mode=True)
            payload = safe_parse_json_object(raw)
        except (JSONParseError, Exception):  # noqa: BLE001
            payload = {}
        return [
            AgentMessage(
                sender=self.name,
                recipient=message.sender,
                kind="research",
                parent_id=message.msg_id,
                summary="; ".join(str(f) for f in (payload.get("findings") or [])[:2]),
                content=dict(payload),
            )
        ]


# ------------------------------------------------------------------ tester


@dataclass
class TesterAgent:
    """Designs tests for a patch; useful as a sanity layer before merge."""

    llm: LLMClient
    name: str = "tester"

    def handle(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "patch":
            return []
        patch = message.content.get("patch")
        task = message.content.get("task") or {}
        body = (
            "## 任务\n"
            + str(task.get("brief") or "")
            + "\n\n## Patch\n"
            + (str(patch)[:6_000] if patch else "(empty)")
        )
        try:
            raw = self.llm.chat(_TESTER_SYSTEM, body, json_mode=True)
            payload = safe_parse_json_object(raw)
        except (JSONParseError, Exception):  # noqa: BLE001
            payload = {"tests": []}
        return [
            AgentMessage(
                sender=self.name,
                recipient="reviewer",
                kind="tests_proposal",
                parent_id=message.msg_id,
                summary=f"proposed {len(payload.get('tests') or [])} tests",
                content=dict(payload),
            )
        ]


# ------------------------------------------------------------------ helpers


def _failure(*, sender: str, recipient: str, parent_id: str, reason: str) -> AgentMessage:
    return AgentMessage(
        sender=sender,
        recipient=recipient,
        kind="failure",
        parent_id=parent_id,
        summary=reason,
        content={"reason": reason},
    )


__all__ = [
    "AgentRole",
    "CoderAgent",
    "PlannerAgent",
    "ResearcherAgent",
    "ReviewerAgent",
    "TesterAgent",
]
