"""Tests for the multi-agent orchestrator pipeline.

Roles are driven by :class:`MockLLM` so the runs are fully
deterministic. The coder uses a stub ``ProjectVibeCoder`` that records
its calls — no real filesystem / patcher / sandbox is touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from vibe_coding.agent.orchestration import (
    AgentMessage,
    BestOfNOrchestrator,
    CoderAgent,
    MessageBus,
    MultiAgentOrchestrator,
    PlannerAgent,
    ResearcherAgent,
    ReviewerAgent,
)
from vibe_coding.nl.llm import MockLLM


# ---------------------------------------------------- shared stubs


@dataclass
class _StubPatch:
    patch_id: str = "p-1"
    summary: str = "stub patch"
    edits: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "summary": self.summary, "edits": []}


@dataclass
class _StubProjectCoder:
    patches: list[_StubPatch] = field(default_factory=lambda: [_StubPatch()])
    edit_calls: list[tuple[str, list[str]]] = field(default_factory=list)
    apply_calls: list[str] = field(default_factory=list)

    def edit_project(self, brief: str, *, focus_paths=None):
        self.edit_calls.append((brief, list(focus_paths or [])))
        if not self.patches:
            raise RuntimeError("no patches scripted")
        return self.patches.pop(0)

    def apply_patch(self, patch, dry_run: bool = False):  # noqa: ARG002
        self.apply_calls.append(patch.patch_id)

        @dataclass
        class _Result:
            patch_id: str
            applied: bool = True

            def to_dict(self) -> dict[str, Any]:
                return {"patch_id": self.patch_id, "applied": self.applied}

        return _Result(patch_id=patch.patch_id)


def _planner_llm(plan: dict[str, Any]) -> MockLLM:
    return MockLLM({"default": json.dumps(plan)})


def _reviewer_llm(verdict: str, score: int = 80) -> MockLLM:
    return MockLLM(
        {
            "default": json.dumps(
                {
                    "verdict": verdict,
                    "score": score,
                    "reasons": ["looks ok"],
                    "suggestions": ["use more docstrings"] if verdict == "revise" else [],
                }
            )
        }
    )


# --------------------------------------------------- happy path (sequential)


def test_orchestrator_completes_on_first_approval() -> None:
    plan_payload = {
        "plan_summary": "rename foo → bar",
        "tasks": [
            {
                "task_id": "t-1",
                "brief": "rename function foo to bar",
                "rationale": "naming convention",
                "focus_paths": ["src/foo.py"],
            }
        ],
    }
    planner = PlannerAgent(llm=_planner_llm(plan_payload))
    project_coder = _StubProjectCoder()
    coder = CoderAgent(project_coder=project_coder)
    reviewer = ReviewerAgent(llm=_reviewer_llm("approve", score=92))
    orch = MultiAgentOrchestrator(
        planner=planner, coder=coder, reviewer=reviewer, max_rounds=2
    )
    result = orch.run("把 foo 改名成 bar")
    assert result.success is True
    assert result.rounds == 1
    assert result.final_patch is not None
    assert result.final_review["verdict"] == "approve"
    # Coder was asked once with the planner's task.
    assert project_coder.edit_calls == [("rename function foo to bar", ["src/foo.py"])]


def test_orchestrator_runs_revision_round_when_reviewer_rejects() -> None:
    plan_payload = {
        "plan_summary": "p",
        "tasks": [
            {"task_id": "t-1", "brief": "do thing", "rationale": "...", "focus_paths": []}
        ],
    }
    planner = PlannerAgent(llm=_planner_llm(plan_payload))
    project_coder = _StubProjectCoder(
        patches=[_StubPatch(patch_id="p-1"), _StubPatch(patch_id="p-2", summary="refined")]
    )
    coder = CoderAgent(project_coder=project_coder)
    # First reviewer call returns 'revise', second returns 'approve' — the
    # MockLLM cycles through responses in order.
    reviewer_llm = MockLLM(
        responses=[
            json.dumps(
                {
                    "verdict": "revise",
                    "score": 50,
                    "reasons": ["missing tests"],
                    "suggestions": ["add a unit test"],
                }
            ),
            json.dumps(
                {
                    "verdict": "approve",
                    "score": 90,
                    "reasons": ["clean"],
                    "suggestions": [],
                }
            ),
        ]
    )
    reviewer = ReviewerAgent(llm=reviewer_llm)
    orch = MultiAgentOrchestrator(
        planner=planner, coder=coder, reviewer=reviewer, max_rounds=3
    )
    result = orch.run("do something")
    assert result.success is True
    assert result.rounds == 2
    # Coder was called twice — once original, once with revision-feedback brief.
    assert len(project_coder.edit_calls) == 2
    assert "Reviewer 反馈" in project_coder.edit_calls[1][0]


def test_orchestrator_gives_up_after_max_rounds() -> None:
    plan_payload = {
        "plan_summary": "p",
        "tasks": [
            {"task_id": "t-1", "brief": "do thing", "rationale": "...", "focus_paths": []}
        ],
    }
    planner = PlannerAgent(llm=_planner_llm(plan_payload))
    project_coder = _StubProjectCoder(
        patches=[_StubPatch(patch_id=f"p-{i}") for i in range(5)]
    )
    coder = CoderAgent(project_coder=project_coder)
    reviewer = ReviewerAgent(llm=_reviewer_llm("revise", score=40))
    orch = MultiAgentOrchestrator(
        planner=planner, coder=coder, reviewer=reviewer, max_rounds=2
    )
    result = orch.run("do something")
    assert result.success is False
    assert result.rounds == 2
    assert result.final_review is not None
    assert result.final_review["verdict"] == "revise"


def test_orchestrator_records_planner_failure() -> None:
    # Bad JSON from the planner should surface as a clean error.
    planner = PlannerAgent(llm=MockLLM({"default": "not-json-at-all"}))
    project_coder = _StubProjectCoder()
    coder = CoderAgent(project_coder=project_coder)
    reviewer = ReviewerAgent(llm=_reviewer_llm("approve"))
    orch = MultiAgentOrchestrator(planner=planner, coder=coder, reviewer=reviewer)
    result = orch.run("anything")
    assert result.success is False
    assert "planner" in result.error.lower()


def test_orchestrator_publishes_full_message_log() -> None:
    plan_payload = {
        "plan_summary": "p",
        "tasks": [{"task_id": "t-1", "brief": "do", "rationale": "...", "focus_paths": []}],
    }
    bus = MessageBus()
    planner = PlannerAgent(llm=_planner_llm(plan_payload))
    project_coder = _StubProjectCoder()
    coder = CoderAgent(project_coder=project_coder)
    reviewer = ReviewerAgent(llm=_reviewer_llm("approve"))
    orch = MultiAgentOrchestrator(
        planner=planner, coder=coder, reviewer=reviewer, bus=bus
    )
    orch.run("do")
    kinds = {m.kind for m in bus.snapshot()}
    assert {"kickoff", "plan", "patch", "approval"} <= kinds


# --------------------------------------------------- best-of-N


def test_best_of_n_picks_highest_scoring_patch() -> None:
    plan_payload = {
        "plan_summary": "p",
        "tasks": [{"task_id": "t-1", "brief": "do", "rationale": "...", "focus_paths": []}],
    }
    planner = PlannerAgent(llm=_planner_llm(plan_payload))
    coders = [
        CoderAgent(project_coder=_StubProjectCoder(patches=[_StubPatch(patch_id="p-A")])),
        CoderAgent(project_coder=_StubProjectCoder(patches=[_StubPatch(patch_id="p-B")])),
        CoderAgent(project_coder=_StubProjectCoder(patches=[_StubPatch(patch_id="p-C")])),
    ]
    # First reviewer call → 60, second → 90 (winner), third → 70.
    reviewer_llm = MockLLM(
        responses=[
            json.dumps({"verdict": "revise", "score": 60, "reasons": [], "suggestions": []}),
            json.dumps({"verdict": "approve", "score": 90, "reasons": ["best"], "suggestions": []}),
            json.dumps({"verdict": "revise", "score": 70, "reasons": [], "suggestions": []}),
        ]
    )
    orch = BestOfNOrchestrator(
        planner=planner, coders=coders, reviewer=ReviewerAgent(llm=reviewer_llm)
    )
    result = orch.run("anything")
    assert result.success is True
    assert result.final_patch == {"patch_id": "p-B", "summary": "stub patch", "edits": []}
    assert result.final_review["score"] == 90


def test_best_of_n_requires_at_least_one_coder() -> None:
    planner = PlannerAgent(llm=_planner_llm({"plan_summary": "p", "tasks": []}))
    reviewer = ReviewerAgent(llm=_reviewer_llm("approve"))
    with pytest.raises(ValueError):
        BestOfNOrchestrator(planner=planner, coders=[], reviewer=reviewer)


# --------------------------------------------------- researcher integration


def test_researcher_runs_before_coder_when_provided() -> None:
    plan_payload = {
        "plan_summary": "p",
        "tasks": [{"task_id": "t-1", "brief": "do", "rationale": "...", "focus_paths": []}],
    }
    bus = MessageBus()
    researcher_llm = MockLLM(
        {
            "default": json.dumps(
                {
                    "findings": ["lib X already vendored"],
                    "open_questions": ["which version?"],
                }
            )
        }
    )
    orch = MultiAgentOrchestrator(
        planner=PlannerAgent(llm=_planner_llm(plan_payload)),
        coder=CoderAgent(project_coder=_StubProjectCoder()),
        reviewer=ReviewerAgent(llm=_reviewer_llm("approve")),
        researcher=ResearcherAgent(llm=researcher_llm),
        bus=bus,
    )
    orch.run("integrate library X")
    research_msgs = [m for m in bus.snapshot() if m.kind == "research"]
    assert research_msgs, "researcher should have run"
    assert "lib X" in research_msgs[0].summary
