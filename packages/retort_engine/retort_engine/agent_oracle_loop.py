"""Bounded agent loop wired to heldout fail-to-pass oracles and process safety."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from retort_engine.bounded_agent_loop import run_bounded_agent_loop
from retort_engine.issue_capability_benchmark import run_heldout_oracle_suite
from retort_engine.process_safety import run_command_with_process_group


def run_agent_oracle_loop(
    project: str | Path,
    *,
    run_id: str = "agent-oracle",
    max_steps: int = 3,
    wall_time_limit_sec: float = 120.0,
) -> dict[str, Any]:
    """Prove completion only when heldout pytest cases fail-before and pass-after.

    Uses process-group-safe command execution for the probe step so absorbed
    agent paths cannot leave orphan children on timeout.
    """
    root = Path(project).expanduser().resolve()
    state: dict[str, Any] = {"oracle": {}, "probe": {}}

    def planner(_objective: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        if not trajectory:
            return {
                "phase": "process_probe",
                "command": [sys.executable, "-c", "print('retort-oracle-probe')"],
            }
        if len(trajectory) == 1:
            return {"phase": "heldout_oracle", "command": ["heldout_oracle"]}
        return {"phase": "done", "command": ["done"]}

    def executor(action: dict[str, Any]) -> dict[str, Any]:
        phase = str(action.get("phase") or "")
        if phase == "process_probe":
            command = action.get("command")
            if isinstance(command, list):
                probe = run_command_with_process_group(
                    [str(item) for item in command], timeout_sec=10.0
                )
            else:
                probe = run_command_with_process_group(
                    [sys.executable, "-c", "print('retort-oracle-probe')"],
                    timeout_sec=10.0,
                )
            state["probe"] = probe
            return {
                "ok": int(probe.get("returncode") or 1) == 0,
                "returncode": int(probe.get("returncode") or 1),
                "process_group_killed": bool(probe.get("process_group_killed")),
                "stdout_tail": str(probe.get("stdout_tail") or ""),
                "phase": phase,
            }
        if phase == "heldout_oracle":
            oracle = run_heldout_oracle_suite(root)
            state["oracle"] = oracle
            resolved = bool(oracle.get("summary", {}).get("all_resolved"))
            return {
                "ok": resolved,
                "returncode": 0 if resolved else 1,
                "oracle_summary": oracle.get("summary") or {},
                "phase": phase,
            }
        return {"ok": True, "returncode": 0, "phase": phase}

    def judge(_objective: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        resolved = bool(
            (state.get("oracle") or {}).get("summary", {}).get("all_resolved")
        )
        probed = any(
            row.get("observation", {}).get("phase") == "process_probe"
            for row in trajectory
        )
        return {
            "complete": resolved and probed,
            "score": 100.0 if resolved and probed else 0.0,
            "missing": "" if resolved and probed else "heldout_fail_to_pass_incomplete",
        }

    loop = run_bounded_agent_loop(
        "repair heldout oracle cases with process-safe execution",
        planner=planner,
        executor=executor,
        judge=judge,
        max_steps=max_steps,
        wall_time_limit_sec=wall_time_limit_sec,
        run_id=run_id,
        command_runner=None,
    )
    return {
        "status": "ready" if loop.get("status") == "complete" else "needs_attention",
        "summary": {
            "completed": loop.get("status") == "complete",
            "loop_status": loop.get("status"),
            "oracle_all_resolved": bool(
                (state.get("oracle") or {}).get("summary", {}).get("all_resolved")
            ),
            "process_group_runner": True,
            "process_group_killed": bool(
                (state.get("probe") or {}).get("process_group_killed")
            ),
            "step_count": (loop.get("summary") or {}).get("step_count"),
        },
        "oracle": state.get("oracle") or {},
        "probe": state.get("probe") or {},
        "loop": loop,
    }
