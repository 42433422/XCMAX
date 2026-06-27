from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.architecture_refactor import build_core_refactor_plan
from retort_engine.codebase_graph import build_codebase_graph


def build_evolution_map(project: str | Path, *, max_files: int = 140) -> dict[str, Any]:
    """Build the UI-facing map of Retort's external-evolution loop."""
    root = Path(project).expanduser().resolve()
    code_graph = build_codebase_graph(root, include_tests=True, max_files=max_files)
    memory = _read_json(root / "docs" / "retort_architecture_memory.json")
    refactor_plan = build_core_refactor_plan(memory, project_root=root, max_tasks=8)
    state = _read_json(root / ".retort" / "absorption_state.json")
    latest_run = _latest_real_absorption_run(root)
    latest_code_graph_proof = latest_run.get("code_graph_proof") if isinstance(latest_run.get("code_graph_proof"), dict) else {}
    return {
        "status": "ready" if code_graph.get("status") != "empty" else "empty",
        "project": str(root),
        "code_graph": {
            "status": code_graph.get("status"),
            "summary": code_graph.get("summary") or {},
            "hotspots": list(code_graph.get("hotspots") or [])[:8],
        },
        "latest_absorption": {
            "source": str(latest_run.get("source") or state.get("source") or ""),
            "status": str(latest_run.get("status") or state.get("status") or ""),
            "run_id": str(latest_run.get("run_id") or ""),
            "closed_loop_status": str(state.get("status") or ""),
            "closed_loop_evidence": list(((state.get("closed_loop_proof") or {}).get("evidence") or []))[-10:],
            "pre_absorption_focus": latest_run.get("pre_absorption_focus") or {},
            "code_graph_proof": latest_code_graph_proof or _missing_per_run_proof(latest_run, state),
        },
        "core_refactor_plan": {
            "summary": refactor_plan.get("summary") or {},
            "gate": refactor_plan.get("gate") or {},
            "tasks": list(refactor_plan.get("tasks") or [])[:8],
            "code_graph_summary": refactor_plan.get("code_graph_summary") or {},
        },
        "evidence": {
            "style": "retort_external_evolution_map",
            "sources": ["codebase_graph", "absorption_state", "architecture_memory", "real_absorption_runs"],
        },
    }


def _latest_real_absorption_run(root: Path) -> dict[str, Any]:
    run_dir = root / ".retort" / "real_absorption_runs"
    if not run_dir.is_dir():
        return {}
    candidates = sorted(run_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        parsed = _read_json(path)
        if parsed:
            return parsed
    return {}


def _missing_per_run_proof(latest_run: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    evidence = [str(item) for item in ((state.get("closed_loop_proof") or {}).get("evidence") or [])]
    graph_smoke = next((item for item in evidence if item.startswith("codebase_graph_smoke=")), "")
    return {
        "passed": False,
        "status": "missing_per_run_code_graph_proof" if latest_run else "not_available",
        "changed_hotspots": [],
        "changed_focus_files": [],
        "hotspot_files": [],
        "focus_files": [],
        "summary": {"graph_smoke": graph_smoke, "run_id": str(latest_run.get("run_id") or "")},
        "evidence": {"style": "missing_per_run_code_graph_proof", "items": evidence[-10:]},
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
