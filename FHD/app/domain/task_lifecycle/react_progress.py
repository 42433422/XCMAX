"""Progress/repair contracts stored inside the existing AgentRun SQL checkpoint.

SDK messages are proposals. Only settled host receipts advance a business repair;
this module owns neither execution, authorization, billing nor another scheduler.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest, goal_answers
from app.domain.task_lifecycle.agent_runtime_results import receipt_verified
from app.domain.task_lifecycle.goal_review_models import GoalReview, goal_source_catalogue

CONTROL_KEY = "react_progress"
STRATEGIES = ("native_repair", "tool_constraint", "context_repair", "compatible_route")


class ProgressLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    execution: int = Field(ge=1, le=1000)
    repair: int = Field(ge=0, le=6)
    no_progress: int = Field(ge=1, le=4)
    strategy_switches: int = Field(ge=0, le=3)


class ProgressCheckpoint(BaseModel):
    # Recovery records are extensible; authority and counters are not permissive.
    model_config = ConfigDict(extra="allow", strict=True)
    version: Literal[1, 2]
    strategy: int = Field(ge=0, lt=len(STRATEGIES))
    execution_turns: int = Field(ge=0)
    repair_turns: int = Field(ge=0)
    no_progress: int = Field(ge=0)
    strategy_switches: int = Field(ge=0)
    facts: list[str]
    limits: ProgressLimits

    @model_validator(mode="after")
    def bounded(self) -> ProgressCheckpoint:
        for counter, budget in (
            ("execution_turns", "execution"),
            ("repair_turns", "repair"),
            ("no_progress", "no_progress"),
            ("strategy_switches", "strategy_switches"),
        ):
            if getattr(self, counter) > getattr(self.limits, budget):
                raise ValueError("Saved progress exceeds the original budget")
        return self


class RepairStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal[
        "discover_authorized_capability",
        "execute_with_schema",
        "independent_readback",
        "deliver_reply",
    ]
    depends_on: list[int] = Field(default_factory=list)


class RepairTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal_id: str
    source_id: str
    requirement: str
    kind: Literal["reply", "read", "write", "constraint", "planned_action"]
    evidence: Literal["host_receipt", "reply"]
    completed: bool = False
    steps: list[RepairStep] = Field(default_factory=list)


class RepairContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol: Literal["xcagi.react-repair.v1"] = "xcagi.react-repair.v1"
    goal_digest: str
    original_request: str = ""
    review_digest: str
    tasks: list[RepairTask]
    preserved_receipts: list[str]
    strategy: str
    # These constraints never confer authority; ordinary bridge checks still apply.
    required_channel: Literal["host_tools", "reply"]


def output_channel(text: str) -> str:
    """Distinguish internal envelopes, without rejecting ordinary JSON replies."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return "reply"
    if not isinstance(value, dict):
        return "reply"
    capability = str(value.get("capability") or "")
    if capability.startswith(("memory_v2.", "user_memory.")):
        return "memory_candidate"
    if "." in capability and isinstance(value.get("params"), dict):
        return "action_proposal"
    if {"goals", "violations", "feedback"}.issubset(value):
        return "verification"
    return "reply"


def receipt_facts(rows: list[dict[str, Any]]) -> list[str]:
    """Deduplicate verified effects, not call ids, timestamps or tool invocations."""
    facts = set()
    for row in rows:
        if row.get("tool_id") in {
            "memory_v2",
            "user_memory",
            "user_memory_rag",
            "planner",
            "task_planner",
        } or not receipt_verified(row):
            continue
        receipt = row.get("receipt") or {}
        calls = receipt.get("tool_calls") or []
        outputs = [call.get("output") for call in calls if call.get("status") == "completed"]
        artifacts = [
            (item.get("metadata") or {}).get("sha256") for item in receipt.get("artifacts") or []
        ]
        if not outputs and not any(artifacts):
            continue
        facts.add(
            canonical_digest(
                {
                    "tool": row.get("tool_id"),
                    "action": row.get("action"),
                    "params": row.get("params"),
                    "outputs": outputs,
                    "artifacts": sorted(item for item in artifacts if item),
                }
            )
        )
    return sorted(facts)


def input_revision(run: Any) -> str:
    """A new answer, frozen goal or authority change can legitimately reopen review."""
    return canonical_digest(
        {
            "goal": run.metadata.get("runtime_goal_digest"),
            "answers": goal_answers(run),
            "authority": (run.metadata.get("xiaox_runtime") or {}).get("identity_digest"),
        }
    )


def requires_actions(state: dict[str, Any]) -> bool:
    return any(
        task["evidence"] == "host_receipt" and not task["completed"]
        for task in (state.get("repair") or {}).get("tasks", [])
    )


def review_signature(run: Any, rows: list[dict[str, Any]], output: str) -> str:
    state = (run.metadata.get("xiaox_runtime") or {}).get(CONTROL_KEY) or {}
    # Changed wording cannot manufacture a new business evidence revision.
    return canonical_digest(
        {
            "input": input_revision(run),
            "facts": receipt_facts(rows),
            "reply": None if requires_actions(state) else output,
        }
    )


def ensure_control(metadata: dict[str, Any], max_calls: int) -> dict[str, Any]:
    """Never replenish counters during coordinator recovery or task resume."""
    if CONTROL_KEY not in metadata:
        review_slots = int(
            (metadata.get("verification_budget") or {}).get(
                "model_calls", min(3, max(1, max_calls // 4))
            )
        )
        repair_slots = min(6, max(0, (max_calls - review_slots) // 3))
        metadata[CONTROL_KEY] = {
            "version": 2,
            "strategy": 0,
            "execution_turns": 0,
            "repair_turns": 0,
            "no_progress": 0,
            "strategy_switches": 0,
            "facts": [],
            "limits": {
                "execution": max(1, max_calls - review_slots - repair_slots),
                "repair": repair_slots,
                "no_progress": 4,
                "strategy_switches": len(STRATEGIES) - 1,
            },
        }
    ProgressCheckpoint.model_validate(metadata[CONTROL_KEY])
    return cast(dict[str, Any], metadata[CONTROL_KEY])


def bind_repair(
    run: Any,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    grounded_review: GoalReview | None = None,
) -> dict[str, Any]:
    report = run.metadata.get("runtime_goal_verification") or {}
    review = grounded_review or GoalReview.model_validate(report["review"])
    state = metadata[CONTROL_KEY]
    tasks = [
        RepairTask(
            goal_id=goal.goal_id,
            source_id=goal.source_id,
            requirement=goal.source,
            kind=goal.kind,
            completed=goal.status != "unmet",
            evidence="host_receipt" if goal.kind in {"read", "write"} else "reply",
            steps=(
                [
                    RepairStep(operation="discover_authorized_capability"),
                    RepairStep(operation="execute_with_schema", depends_on=[0]),
                ]
                + (
                    [RepairStep(operation="independent_readback", depends_on=[1])]
                    if goal.kind == "write"
                    else []
                )
                if goal.kind in {"read", "write"}
                else [RepairStep(operation="deliver_reply")]
            ),
        )
        for goal in review.goals
        if goal.status != "not_applicable"
    ]
    contract = RepairContract(
        goal_digest=run.metadata["runtime_goal_digest"],
        original_request=run.metadata["runtime_goal_contract"]["request"]["text"],
        review_digest=report["report_digest"],
        tasks=tasks,
        preserved_receipts=receipt_facts(rows),
        strategy=STRATEGIES[state["strategy"]],
        required_channel="host_tools"
        if any(task.evidence == "host_receipt" and not task.completed for task in tasks)
        else "reply",
    ).model_dump()
    state.update(
        repairing=True,
        repair=contract,
        facts=receipt_facts(rows),
        input_revision=input_revision(run),
    )
    return contract


def _grounded_invalid_review(run: Any) -> GoalReview | None:
    """Recover execution, never accept a broken review as a completion verdict.

    Only unmet operations quoted from the frozen user's authority may drive
    recovery. Attachment, history and invented goals remain non-authoritative;
    the complete invalid report stays in SQL for the next independent review.
    """
    report = run.metadata.get("runtime_goal_verification") or {}
    if (
        report.get("error_code") != "goal_verification_invalid_gap"
        or report.get("accepted") is not False
        or not isinstance(report.get("review"), dict)
        or report.get("goal_digest") != run.metadata.get("runtime_goal_digest")
    ):
        return None
    try:
        review = GoalReview.model_validate(report["review"])
    except ValueError:
        return None
    sources = goal_source_catalogue(run.metadata["runtime_goal_contract"], goal_answers(run))
    grounded = [
        goal
        for goal in review.goals
        if goal.status == "unmet"
        and goal.kind in {"read", "write"}
        and (goal.source_id in {"request", "objective"} or goal.source_id.startswith("answer:"))
        and goal.source_id in sources
        and goal.source in sources[goal.source_id]["text"]
        and goal.kind in sources[goal.source_id]["allowed_kinds"]
    ]
    if not grounded:
        return None
    return review.model_copy(update={"goals": grounded})


def replan_invalid_review(run: Any, metadata: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    review = _grounded_invalid_review(run)
    if review is None:
        return False
    report = run.metadata["runtime_goal_verification"]
    bind_repair(run, metadata, rows, grounded_review=review)
    metadata[CONTROL_KEY]["invalid_review"] = {
        "report_digest": report["report_digest"],
        "error_code": report["error_code"],
    }
    return True


def invalid_review_recoverable(
    run: Any, metadata: dict[str, Any], rows: list[dict[str, Any]]
) -> bool:
    """Re-derive the saved recovery contract on restart; never trust extra tasks."""
    report = run.metadata.get("runtime_goal_verification") or {}
    state = metadata.get(CONTROL_KEY) or {}
    if report.get("status") != "unavailable" or state.get("invalid_review") != {
        "report_digest": report.get("report_digest"),
        "error_code": "goal_verification_invalid_gap",
    }:
        return False
    try:
        expected = copy.deepcopy(metadata)
        return replan_invalid_review(run, expected, rows) and expected[CONTROL_KEY][
            "repair"
        ] == state.get("repair")
    except (KeyError, TypeError, ValueError):
        return False


def admit_turn(metadata: dict[str, Any]) -> None:
    state = metadata[CONTROL_KEY]
    if state.get("blocked_reason"):
        raise ValueError(state["blocked_reason"])
    key = "repair_turns" if state.get("repairing") else "execution_turns"
    budget = "repair" if state.get("repairing") else "execution"
    if state[key] >= state["limits"][budget]:
        raise ValueError("react_repair_budget_exhausted")
    state[key] += 1


def note_no_progress(
    run: Any, metadata: dict[str, Any], rows: list[dict[str, Any]], channel: str
) -> str:
    """Each stalled attempt changes strategy once, using the original SQL CAS."""
    state = metadata[CONTROL_KEY]
    facts = receipt_facts(rows)
    if set(facts) - set(state["facts"]):
        state.update(facts=facts, no_progress=0)
        return "progress"
    state["repairing"] = True
    state["no_progress"] += 1
    run.add_event(
        "runtime.progress.stalled",
        "未获得新的已核验业务证据",
        {
            "attempt": state["no_progress"],
            "channel": channel,
            "strategy": STRATEGIES[state["strategy"]],
        },
    )
    if state["no_progress"] >= state["limits"]["no_progress"] or (
        state["strategy_switches"] >= state["limits"]["strategy_switches"]
    ):
        state["blocked_reason"] = "react_no_progress_exhausted"
        return "blocked"
    state["strategy"] += 1
    state["strategy_switches"] += 1
    if state.get("repair"):
        state["repair"]["strategy"] = STRATEGIES[state["strategy"]]
    run.add_event(
        "runtime.recovery.strategy_changed",
        "原任务切换有界恢复策略",
        {
            "strategy": STRATEGIES[state["strategy"]],
            "sequence": state["strategy_switches"],
        },
    )
    return STRATEGIES[state["strategy"]]
