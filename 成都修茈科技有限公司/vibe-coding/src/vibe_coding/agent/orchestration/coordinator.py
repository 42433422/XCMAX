"""Orchestrators: sequential pipeline + best-of-N parallel race.

Both orchestrators share the same input / output contract:

- Input: a brief (free-form NL describing the goal) plus a fully-wired
  set of role agents.
- Output: an :class:`OrchestrationResult` with the final approved patch
  (if any), the full message log, and per-round telemetry.

They diverge in the middle. The sequential orchestrator runs:

    Planner → (Researcher) → Coder → Reviewer → ⟲ Coder if revise

The best-of-N orchestrator instead spawns ``n`` Coder runs (the same
Coder may be reused; thread-safety is the user's responsibility), asks
the Reviewer to score each result, and surfaces only the winner.

Neither orchestrator does any I/O of its own — every action goes
through one of the supplied agents, so unit tests can swap in fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .messages import AgentMessage, MessageBus
from .roles import (
    CoderAgent,
    PlannerAgent,
    ResearcherAgent,
    ReviewerAgent,
    TesterAgent,
)


@dataclass(slots=True)
class OrchestrationResult:
    """Outcome of one orchestrator run."""

    success: bool
    brief: str
    final_patch: dict[str, Any] | None = None
    final_review: dict[str, Any] | None = None
    rounds: int = 0
    error: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "brief": self.brief,
            "final_patch": self.final_patch,
            "final_review": self.final_review,
            "rounds": self.rounds,
            "error": self.error,
            "messages": list(self.messages),
        }


# --------------------------------------------------------- sequential


class MultiAgentOrchestrator:
    """Planner → (Researcher) → Coder → Reviewer pipeline."""

    def __init__(
        self,
        *,
        planner: PlannerAgent,
        coder: CoderAgent,
        reviewer: ReviewerAgent,
        researcher: ResearcherAgent | None = None,
        tester: TesterAgent | None = None,
        max_rounds: int = 3,
        bus: MessageBus | None = None,
    ) -> None:
        self.planner = planner
        self.coder = coder
        self.reviewer = reviewer
        self.researcher = researcher
        self.tester = tester
        self.max_rounds = max(1, int(max_rounds))
        # NOTE: ``bus or MessageBus()`` would wrongly create a fresh bus
        # when the caller passed an empty (newly-constructed) one because
        # MessageBus implements __len__ and thus answers ``bool() == False``.
        self.bus = bus if bus is not None else MessageBus()

    def run(
        self,
        brief: str,
        *,
        researcher_question: str | None = None,
    ) -> OrchestrationResult:
        result = OrchestrationResult(success=False, brief=brief)
        kickoff = self.bus.publish(
            AgentMessage(
                sender="orchestrator",
                recipient=self.planner.name,
                kind="kickoff",
                summary="kickoff",
                content={"brief": brief},
            )
        )
        plan_messages = self.planner.handle(kickoff)
        for msg in plan_messages:
            self.bus.publish(msg)
        plan_msg = next((m for m in plan_messages if m.kind == "plan"), None)
        if plan_msg is None:
            failure = next((m for m in plan_messages if m.kind == "failure"), None)
            result.error = failure.summary if failure else "planner produced no plan"
            result.messages = [m.to_dict() for m in self.bus.snapshot()]
            return result

        if self.researcher is not None:
            r_msg = self.bus.publish(
                AgentMessage(
                    sender="orchestrator",
                    recipient=self.researcher.name,
                    kind="research_request",
                    parent_id=plan_msg.msg_id,
                    content={"question": researcher_question or brief},
                )
            )
            for r in self.researcher.handle(r_msg):
                self.bus.publish(r)

        current_plan = plan_msg
        last_patch_msg: AgentMessage | None = None
        last_review_msg: AgentMessage | None = None
        for round_idx in range(1, self.max_rounds + 1):
            result.rounds = round_idx
            patch_messages = self.coder.handle(current_plan)
            for msg in patch_messages:
                self.bus.publish(msg)
            patch_msg = next(
                (m for m in patch_messages if m.kind == "patch" and m.content.get("patch")),
                None,
            )
            if patch_msg is None:
                err = next(
                    (m for m in patch_messages if m.kind == "patch"), None
                )
                result.error = (err.content.get("error") if err else "coder produced no patch") or "no patch"
                break
            last_patch_msg = patch_msg
            review_messages = self.reviewer.handle(patch_msg)
            if self.tester is not None:
                review_messages = list(review_messages) + list(self.tester.handle(patch_msg))
            for msg in review_messages:
                self.bus.publish(msg)
            review_msg = next(
                (m for m in review_messages if m.kind in {"approval", "revise"}),
                None,
            )
            if review_msg is None:
                result.error = "reviewer produced no verdict"
                break
            last_review_msg = review_msg
            if review_msg.kind == "approval":
                result.success = True
                break
            # ``revise`` → splice the reviewer's suggestions into every
            # task brief so the coder rewrites with the feedback in mind.
            feedback_block = "\n\n## Reviewer 反馈\n" + "\n".join(
                review_msg.content.get("suggestions") or ["请改善 patch"]
            )
            revised_tasks: list[dict[str, Any]] = []
            for raw_task in current_plan.content.get("tasks") or []:
                if not isinstance(raw_task, dict):
                    continue
                cloned = dict(raw_task)
                cloned["brief"] = (str(cloned.get("brief") or "")).rstrip() + feedback_block
                revised_tasks.append(cloned)
            current_plan = AgentMessage(
                sender="orchestrator",
                recipient=self.coder.name,
                kind="plan",
                parent_id=review_msg.msg_id,
                summary="revision-round",
                content={
                    "plan_summary": "revision-round",
                    "tasks": revised_tasks,
                    "original_brief": (
                        (current_plan.content.get("original_brief") or brief).strip()
                        + feedback_block
                    ),
                    "reviewer_feedback": review_msg.content,
                },
            )
            self.bus.publish(current_plan)

        if last_patch_msg is not None:
            result.final_patch = dict(last_patch_msg.content.get("patch") or {})
        if last_review_msg is not None:
            result.final_review = dict(last_review_msg.content)
        result.messages = [m.to_dict() for m in self.bus.snapshot()]
        return result


# --------------------------------------------------------- best-of-N


class BestOfNOrchestrator:
    """Run the Coder ``n`` times in parallel; pick the highest-scored patch."""

    def __init__(
        self,
        *,
        planner: PlannerAgent,
        coders: list[CoderAgent],
        reviewer: ReviewerAgent,
        bus: MessageBus | None = None,
    ) -> None:
        if not coders:
            raise ValueError("BestOfNOrchestrator requires at least one CoderAgent")
        self.planner = planner
        self.coders = list(coders)
        self.reviewer = reviewer
        self.bus = bus if bus is not None else MessageBus()

    def run(self, brief: str) -> OrchestrationResult:
        result = OrchestrationResult(success=False, brief=brief, rounds=1)
        kickoff = self.bus.publish(
            AgentMessage(
                sender="orchestrator",
                recipient=self.planner.name,
                kind="kickoff",
                content={"brief": brief},
            )
        )
        plan_messages = self.planner.handle(kickoff)
        for msg in plan_messages:
            self.bus.publish(msg)
        plan_msg = next((m for m in plan_messages if m.kind == "plan"), None)
        if plan_msg is None:
            failure = next((m for m in plan_messages if m.kind == "failure"), None)
            result.error = failure.summary if failure else "planner produced no plan"
            result.messages = [m.to_dict() for m in self.bus.snapshot()]
            return result

        scored: list[tuple[int, AgentMessage, AgentMessage]] = []
        for idx, coder in enumerate(self.coders, 1):
            patch_messages = coder.handle(plan_msg)
            for msg in patch_messages:
                msg.summary = (msg.summary or "") + f" [coder #{idx}]"
                self.bus.publish(msg)
            for patch_msg in patch_messages:
                if patch_msg.kind != "patch" or not patch_msg.content.get("patch"):
                    continue
                review_messages = self.reviewer.handle(patch_msg)
                for r in review_messages:
                    self.bus.publish(r)
                review_msg = next(
                    (m for m in review_messages if m.kind in {"approval", "revise"}),
                    None,
                )
                if review_msg is None:
                    continue
                score = int(review_msg.content.get("score") or 0)
                scored.append((score, patch_msg, review_msg))

        if not scored:
            result.error = "no coder produced a reviewable patch"
            result.messages = [m.to_dict() for m in self.bus.snapshot()]
            return result
        scored.sort(key=lambda triple: triple[0], reverse=True)
        winning_score, winning_patch, winning_review = scored[0]
        result.final_patch = dict(winning_patch.content.get("patch") or {})
        result.final_review = dict(winning_review.content)
        result.success = winning_review.kind == "approval"
        result.messages = [m.to_dict() for m in self.bus.snapshot()]
        return result


__all__ = [
    "BestOfNOrchestrator",
    "MultiAgentOrchestrator",
    "OrchestrationResult",
]
