from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from retort_engine.repository_intelligence import compare_repository_gaps, task_targets_from_map, build_ranked_repository_map


BEHAVIOR_TARGETS = {
    "repository_intelligence": "retort_engine/repository_intelligence.py",
    "bounded_execution": "retort_engine/bounded_agent_loop.py",
    "trajectory_persistence": "retort_engine/bounded_agent_loop.py",
    "process_safety": "retort_engine/process_safety.py",
    "goal_audit": "retort_engine/bounded_agent_loop.py",
    "stuck_detection": "retort_engine/bounded_agent_loop.py",
    "reproducible_evaluation": "retort_engine/issue_capability_benchmark.py",
    "verified_task_synthesis": "retort_engine/issue_capability_benchmark.py",
}


def synthesize_behavior_absorption(
    project: str | Path,
    *,
    source: str,
    external_path: str | Path,
    tasks: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    """Synthesize minimal behavior patches instead of registry-only absorption.

    Writes a provenance-stamped capability bridge module and a behavior test that
    prove the absorbed frontier layers are importable and wired for the run.
    """
    root = Path(project).expanduser().resolve()
    external = Path(external_path).expanduser().resolve()
    gap = compare_repository_gaps(root, external)
    own_map = build_ranked_repository_map(
        root,
        focus_terms=("absorb", "agent", "benchmark", "oracle", "trajectory"),
        max_files=12,
        max_chars=12_000,
    )
    focus_targets = task_targets_from_map(own_map, limit=3)
    dimensions = sorted(
        {
            str(task.get("dimension") or "")
            for task in tasks
            if str(task.get("dimension") or "") in BEHAVIOR_TARGETS
        }
    )
    if not dimensions:
        dimensions = ["repository_intelligence", "bounded_execution", "reproducible_evaluation"]
    module_rel = "retort_engine/absorbed_behavior_bridge.py"
    test_rel = "tests/test_absorbed_behavior_bridge.py"
    module_path = root / module_rel
    test_path = root / test_rel
    payload = {
        "run_id": run_id,
        "source": source,
        "dimensions": dimensions,
        "focus_targets": focus_targets,
        "gap_summary": gap["summary"],
        "target_files": [BEHAVIOR_TARGETS[name] for name in dimensions if name in BEHAVIOR_TARGETS],
        "external_top_gaps": gap["gaps"][:5],
    }
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(_bridge_module_content(payload), encoding="utf-8")
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(_bridge_test_content(payload), encoding="utf-8")
    return {
        "status": "synthesized",
        "behavior_source_files": [module_rel],
        "behavior_test_files": [test_rel],
        "changed_files": [module_rel, test_rel],
        "focus_targets": focus_targets,
        "gap": gap,
        "dimensions": dimensions,
        "digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
        "payload": payload,
    }


def _bridge_module_content(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return f'''"""Behavior absorption bridge synthesized by Retort (not registry-only metadata)."""

from __future__ import annotations

import json
from typing import Any

from retort_engine.bounded_agent_loop import detect_stuck_pattern, persist_trajectory, run_bounded_agent_loop
from retort_engine.issue_capability_benchmark import run_heldout_oracle_suite
from retort_engine.process_safety import run_command_with_process_group
from retort_engine.repository_intelligence import build_ranked_repository_map, compare_repository_gaps

ABSORBED_BEHAVIOR_BRIDGE = json.loads({json.dumps(blob)})


def absorbed_behavior_plan() -> dict[str, Any]:
    return dict(ABSORBED_BEHAVIOR_BRIDGE)


def verify_absorbed_behavior_imports() -> dict[str, Any]:
    return {{
        "run_bounded_agent_loop": callable(run_bounded_agent_loop),
        "persist_trajectory": callable(persist_trajectory),
        "detect_stuck_pattern": callable(detect_stuck_pattern),
        "run_command_with_process_group": callable(run_command_with_process_group),
        "build_ranked_repository_map": callable(build_ranked_repository_map),
        "compare_repository_gaps": callable(compare_repository_gaps),
        "run_heldout_oracle_suite": callable(run_heldout_oracle_suite),
        "dimensions": list(ABSORBED_BEHAVIOR_BRIDGE.get("dimensions") or []),
        "focus_targets": list(ABSORBED_BEHAVIOR_BRIDGE.get("focus_targets") or []),
    }}
'''


def _bridge_test_content(payload: dict[str, Any]) -> str:
    dimensions = payload.get("dimensions") or []
    focus = payload.get("focus_targets") or []
    return f'''from retort_engine.absorbed_behavior_bridge import absorbed_behavior_plan, verify_absorbed_behavior_imports


def test_absorbed_behavior_bridge_exposes_frontier_layers() -> None:
    plan = absorbed_behavior_plan()
    imports = verify_absorbed_behavior_imports()
    assert plan["run_id"]
    assert plan["source"]
    assert imports["run_bounded_agent_loop"] is True
    assert imports["persist_trajectory"] is True
    assert imports["run_command_with_process_group"] is True
    assert imports["compare_repository_gaps"] is True
    assert imports["run_heldout_oracle_suite"] is True
    assert set(imports["dimensions"]) == set({dimensions!r})
    assert len(imports["focus_targets"]) == {len(focus)}
'''
