from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ABSORPTION_STATE_RELATIVE_PATH = Path(".retort") / "absorption_state.json"
SELF_EVOLUTION_ACTIONS_RELATIVE_PATH = Path(".retort") / "self_evolution_actions.jsonl"
CLOSED_LOOP_FLAGS = (
    "branch_diff_verified",
    "employee_execution_verified",
    "post_absorption_tests_passed",
    "merge_verified",
    "external_advantage_reassessed",
)


def record_absorption_shock(own: Path, source: str, external_path: Path | None, tasks: list[dict[str, str]]) -> dict[str, Any]:
    task_dimensions = {task["dimension"] for task in tasks}
    state = {
        "active": True,
        "status": "pending_llm_reassessment",
        "source": source,
        "external_path": "" if external_path is None else str(external_path),
        "pending_dimensions": sorted(task_dimensions),
        "tasks": tasks,
    }
    save_absorption_state(own, state)
    return public_absorption_state(own)


def advance_absorption_state(root: Path, weak_dimensions: list[str], round_index: int, tasks: list[dict[str, str]]) -> bool:
    state = load_absorption_state(root)
    if not state.get("active"):
        return False
    state["active"] = True
    state["status"] = "awaiting_execution_evidence"
    state["resolved_round"] = round_index
    state["resolved_dimensions"] = sorted(set(weak_dimensions) | set(state.get("pending_dimensions") or []))
    state["self_evolution_tasks"] = tasks
    save_absorption_state(root, state)
    log_path = root / SELF_EVOLUTION_ACTIONS_RELATIVE_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "round_index": round_index,
                    "source": state.get("source", ""),
                    "resolved_dimensions": state["resolved_dimensions"],
                    "tasks": tasks,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
    return False


def public_absorption_state(root: Path) -> dict[str, Any]:
    state = load_absorption_state(root)
    if not state:
        return {"active": False, "status": "empty"}
    public = {
        key: state.get(key)
        for key in (
            "active",
            "status",
            "source",
            "external_path",
            "pending_dimensions",
            "resolved_round",
            "resolved_dimensions",
        )
        if key in state
    }
    public["closed_loop_proof"] = closed_loop_proof(root)
    return public


def closed_loop_proof(root: Path) -> dict[str, Any]:
    state = load_absorption_state(root)
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    flags = {name: bool(proof.get(name)) for name in CLOSED_LOOP_FLAGS}
    missing = tuple(key for key, value in flags.items() if not value)
    return {
        "verified": not missing,
        "missing": missing,
        "flags": flags,
        "evidence": [str(item) for item in proof.get("evidence") or []],
    }


def load_absorption_state(root: Path) -> dict[str, Any]:
    path = root / ABSORPTION_STATE_RELATIVE_PATH
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_absorption_state(root: Path, state: dict[str, Any]) -> None:
    path = root / ABSORPTION_STATE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
