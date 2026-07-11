from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


Planner = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
Executor = Callable[[dict[str, Any]], dict[str, Any]]
Judge = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


def run_bounded_agent_loop(
    objective: str,
    *,
    planner: Planner,
    executor: Executor,
    judge: Judge,
    max_steps: int = 12,
    wall_time_limit_sec: float = 300.0,
    repeat_limit: int = 3,
) -> dict[str, Any]:
    """Execute, audit and persist a bounded agent trajectory.

    The loop combines mini-SWE-agent's explicit budgets/trajectory with
    OpenHands' separate goal judge and repetitive-action stuck detection.
    """
    if not objective.strip():
        raise ValueError("objective must not be empty")
    if max_steps < 1 or wall_time_limit_sec <= 0 or repeat_limit < 2:
        raise ValueError("invalid agent-loop limits")
    started = time.monotonic()
    trajectory: list[dict[str, Any]] = []
    status = "step_limit"
    verdict: dict[str, Any] = {"complete": False, "score": 0.0, "missing": "not audited"}
    for step in range(1, max_steps + 1):
        if time.monotonic() - started >= wall_time_limit_sec:
            status = "time_limit"
            break
        action = dict(planner(objective, list(trajectory)))
        observation = dict(executor(action))
        event = {"step": step, "action": action, "observation": observation}
        trajectory.append(event)
        if _is_repeating(trajectory, repeat_limit):
            status = "stuck"
            break
        verdict = dict(judge(objective, list(trajectory)))
        event["verdict"] = verdict
        if verdict.get("complete") is True:
            status = "complete"
            break
    return {
        "status": status,
        "objective": objective,
        "summary": {
            "completed": status == "complete",
            "step_count": len(trajectory),
            "max_steps": max_steps,
            "elapsed_sec": round(time.monotonic() - started, 6),
            "final_score": float(verdict.get("score") or 0.0),
        },
        "verdict": verdict,
        "trajectory": trajectory,
        "evidence": {
            "budget_source": "https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py",
            "goal_and_stuck_source": "https://github.com/OpenHands/software-agent-sdk/tree/main/openhands-sdk/openhands/sdk/conversation",
        },
    }


def _is_repeating(trajectory: list[dict[str, Any]], repeat_limit: int) -> bool:
    if len(trajectory) < repeat_limit:
        return False
    recent = trajectory[-repeat_limit:]
    first = {"action": recent[0].get("action"), "observation": recent[0].get("observation")}
    return all({"action": row.get("action"), "observation": row.get("observation")} == first for row in recent[1:])
