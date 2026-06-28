from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def public_absorption_state(root: Path) -> dict[str, Any]:
    state = load_absorption_state(root)
    if not state:
        return {"active": False, "status": "empty"}
    public = {key: state.get(key) for key in ("active", "status", "source", "external_path", "pending_dimensions", "resolved_round", "resolved_dimensions") if key in state}
    public["closed_loop_proof"] = closed_loop_proof(root)
    return public


def closed_loop_proof(root: Path) -> dict[str, Any]:
    state = load_absorption_state(root)
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    flags = {
        "branch_diff_verified": bool(proof.get("branch_diff_verified")),
        "employee_execution_verified": bool(proof.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(proof.get("post_absorption_tests_passed")),
        "merge_verified": bool(proof.get("merge_verified")),
        "external_advantage_reassessed": bool(proof.get("external_advantage_reassessed")),
    }
    missing = [key for key, value in flags.items() if not value]
    return {"verified": not missing, "missing": missing, "flags": flags, "evidence": list(proof.get("evidence") or [])}


def load_absorption_state(root: Path) -> dict[str, Any]:
    path = root / ".retort" / "absorption_state.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_absorption_state(root: Path, state: dict[str, Any]) -> None:
    path = root / ".retort" / "absorption_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
