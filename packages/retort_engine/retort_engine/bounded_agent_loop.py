from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
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
    trajectory_dir: str | Path | None = None,
    run_id: str = "",
    command_runner: Callable[[list[str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute, audit and persist a bounded agent trajectory.

    The loop combines mini-SWE-agent's explicit budgets/trajectory with
    OpenHands' separate goal judge and repetitive-action stuck detection.
    Optional command_runner lets absorbed paths inject process-group-safe
    subprocess execution (see process_safety.run_command_with_process_group).
    """
    if not objective.strip():
        raise ValueError("objective must not be empty")
    if max_steps < 1 or wall_time_limit_sec <= 0 or repeat_limit < 2:
        raise ValueError("invalid agent-loop limits")
    started = time.monotonic()
    trajectory: list[dict[str, Any]] = []
    status = "step_limit"
    verdict: dict[str, Any] = {
        "complete": False,
        "score": 0.0,
        "missing": "not audited",
    }
    for step in range(1, max_steps + 1):
        if time.monotonic() - started >= wall_time_limit_sec:
            status = "time_limit"
            break
        action = dict(planner(objective, list(trajectory)))
        if command_runner is not None and isinstance(action.get("command"), list):
            observation = dict(command_runner(list(action["command"])))
        else:
            observation = dict(executor(action))
        event = {"step": step, "action": action, "observation": observation}
        trajectory.append(event)
        stuck_kind = detect_stuck_pattern(trajectory, repeat_limit=repeat_limit)
        if stuck_kind:
            status = "stuck"
            event["stuck_kind"] = stuck_kind
            break
        verdict = dict(judge(objective, list(trajectory)))
        event["verdict"] = verdict
        if verdict.get("complete") is True:
            status = "complete"
            break
    payload = {
        "status": status,
        "objective": objective,
        "summary": {
            "completed": status == "complete",
            "step_count": len(trajectory),
            "max_steps": max_steps,
            "elapsed_sec": round(time.monotonic() - started, 6),
            "final_score": float(verdict.get("score") or 0.0),
            "trajectory_persisted": False,
            "trajectory_path": "",
            "command_runner_injected": command_runner is not None,
        },
        "verdict": verdict,
        "trajectory": trajectory,
        "evidence": {
            "budget_source": "https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py",
            "goal_and_stuck_source": "https://github.com/OpenHands/software-agent-sdk/tree/main/openhands-sdk/openhands/sdk/conversation",
        },
    }
    if trajectory_dir is not None:
        path = persist_trajectory(payload, trajectory_dir, run_id=run_id or status)
        payload["summary"]["trajectory_persisted"] = True
        payload["summary"]["trajectory_path"] = str(path)
        payload["trajectory_path"] = str(path)
    return payload


def persist_trajectory(
    payload: dict[str, Any], trajectory_dir: str | Path, *, run_id: str = ""
) -> Path:
    root = Path(trajectory_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = run_id or uuid.uuid4().hex[:12]
    path = root / f"trajectory-{stamp}.json"
    record = {
        "schema_version": 1,
        "run_id": stamp,
        "objective": payload.get("objective"),
        "status": payload.get("status"),
        "summary": payload.get("summary"),
        "verdict": payload.get("verdict"),
        "trajectory": payload.get("trajectory"),
        "evidence": payload.get("evidence"),
    }
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def load_trajectory(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("trajectory artifact must be an object")
    return payload


def detect_stuck_pattern(
    trajectory: list[dict[str, Any]], *, repeat_limit: int = 3
) -> str:
    """Detect repeated action/observation, repeated errors, and alternating cycles."""
    if _is_repeating(trajectory, repeat_limit):
        return "repeated_action_observation"
    if _is_repeating_errors(trajectory, repeat_limit):
        return "repeated_error"
    if _is_alternating(trajectory, repeat_limit):
        return "alternating_cycle"
    return ""


def _is_repeating(trajectory: list[dict[str, Any]], repeat_limit: int) -> bool:
    if len(trajectory) < repeat_limit:
        return False
    recent = trajectory[-repeat_limit:]
    first = {
        "action": recent[0].get("action"),
        "observation": recent[0].get("observation"),
    }
    return all(
        {"action": row.get("action"), "observation": row.get("observation")} == first
        for row in recent[1:]
    )


def _is_repeating_errors(trajectory: list[dict[str, Any]], repeat_limit: int) -> bool:
    if len(trajectory) < repeat_limit:
        return False
    recent = trajectory[-repeat_limit:]
    signatures: list[str] = []
    for row in recent:
        observation = row.get("observation") or {}
        if not _observation_is_error(observation):
            return False
        signatures.append(_error_signature(observation))
    return len(set(signatures)) == 1


def _is_alternating(trajectory: list[dict[str, Any]], repeat_limit: int) -> bool:
    window = max(repeat_limit * 2, 4)
    if len(trajectory) < window:
        return False
    recent = trajectory[-window:]
    signatures = [
        json.dumps(
            {"action": row.get("action"), "observation": row.get("observation")},
            sort_keys=True,
            default=str,
        )
        for row in recent
    ]
    if len(set(signatures)) != 2:
        return False
    return all(signatures[index] == signatures[index % 2] for index in range(window))


def _observation_is_error(observation: dict[str, Any]) -> bool:
    if observation.get("ok") is False:
        return True
    code = observation.get("returncode")
    if isinstance(code, int) and code != 0:
        return True
    text = str(observation.get("output") or observation.get("error") or "").lower()
    return "error" in text or "failed" in text or "traceback" in text


def _error_signature(observation: dict[str, Any]) -> str:
    return json.dumps(
        {
            "returncode": observation.get("returncode"),
            "error": observation.get("error"),
            "output": observation.get("output"),
            "ok": observation.get("ok"),
        },
        sort_keys=True,
        default=str,
    )
