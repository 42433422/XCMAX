from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CORE_COMPONENT_CONTRACTS = {
    "review_pipeline": {
        "modules": ["retort_engine/review_pipeline.py", "retort_engine/pr_review.py"],
        "tests": ["tests/test_review_pipeline.py", "tests/test_pr_review.py"],
        "contract": "Review stages, context localization, and PR comments share one component contract.",
    },
    "workflow_ci": {
        "modules": ["retort_engine/real_absorption.py", "retort_engine/proof.py", "retort_engine/git_status.py"],
        "tests": ["tests/test_retort_engine.py", "tests/test_branching_git_status.py"],
        "contract": "Absorption, merge proof, rollback proof, and local gates must fail closed together.",
    },
    "safety_policy": {
        "modules": ["retort_engine/license_gate.py", "retort_engine/git_status.py", "retort_engine/proof.py"],
        "tests": ["tests/test_retort_engine.py", "tests/test_branching_git_status.py"],
        "contract": "License, dirty-worktree, generated evidence, and rollback policies share one safety boundary.",
    },
    "evaluation_loop": {
        "modules": ["retort_engine/absorption_quality.py", "retort_engine/review_quality_benchmark.py", "retort_engine/swe_bench_oracle.py"],
        "tests": ["tests/test_absorbed_capabilities.py", "tests/test_review_quality_benchmark.py", "tests/test_swe_bench_oracle.py"],
        "contract": "Every absorbed behavior has benchmark counters and regression gates.",
    },
    "regression_oracle": {
        "modules": ["retort_engine/absorption_quality.py", "retort_engine/architecture_refactor.py"],
        "tests": ["tests/test_absorbed_capabilities.py", "tests/test_architecture_refactor.py"],
        "contract": "Architecture refactors need a pass/fail oracle before merge.",
    },
    "provider_boundary": {
        "modules": ["retort_engine/paibi_llm.py", "retort_engine/service.py"],
        "tests": ["tests/test_retort_engine.py"],
        "contract": "LLM providers stay behind one dispatch/status contract.",
    },
    "model_adapter": {
        "modules": ["retort_engine/paibi_llm.py", "retort_engine/prompts.py"],
        "tests": ["tests/test_retort_engine.py"],
        "contract": "Prompt construction and provider IO stay separable and testable.",
    },
    "context_localization": {
        "modules": ["retort_engine/review_context_bias.py", "retort_engine/pr_review.py"],
        "tests": ["tests/test_review_context_bias.py", "tests/test_pr_review.py"],
        "contract": "Context grouping feeds PR review without leaking broad, irrelevant files.",
    },
    "automation_surface": {
        "modules": ["retort_engine/cli.py", "retort_engine/ui_server.py", "retort_engine/service.py"],
        "tests": ["tests/test_retort_engine.py"],
        "contract": "CLI, API, and UI expose the same absorption/refactor workflow.",
    },
    "command_contract": {
        "modules": ["retort_engine/contracts.py", "retort_engine/cli.py"],
        "tests": ["tests/test_contracts_feedback.py", "tests/test_retort_engine.py"],
        "contract": "Command results stay schema-checked and replayable.",
    },
    "benchmark_eval": {
        "modules": ["retort_engine/review_quality_benchmark.py", "retort_engine/absorption_quality.py", "retort_engine/swe_bench_oracle.py"],
        "tests": ["tests/test_review_quality_benchmark.py", "tests/test_absorbed_capabilities.py", "tests/test_swe_bench_oracle.py"],
        "contract": "Review quality and absorption quality share benchmark evidence.",
    },
}


def build_core_refactor_plan(memory: dict[str, Any], *, project_root: str | Path = ".", max_tasks: int = 12) -> dict[str, Any]:
    root = Path(project_root)
    component_index = memory.get("component_index") if isinstance(memory.get("component_index"), dict) else {}
    architecture_tasks = [task for task in memory.get("deep_architecture_tasks") or [] if isinstance(task, dict)]
    task_components = [_component_from_task(task) for task in architecture_tasks]
    ready_components = [name for name, row in component_index.items() if isinstance(row, dict) and row.get("ready_for_deep_refactor")]
    selected = _ordered_unique([*task_components, *ready_components])
    items = []
    for component in selected:
        contract = CORE_COMPONENT_CONTRACTS.get(component)
        if not contract:
            continue
        index_row = component_index.get(component) if isinstance(component_index.get(component), dict) else {}
        modules = [str(item) for item in contract["modules"]]
        tests = [str(item) for item in contract["tests"]]
        missing_modules = [item for item in modules if not (root / item).is_file()]
        missing_tests = [item for item in tests if not (root / item).is_file()]
        items.append(
            {
                "component": component,
                "priority": _priority_for(component, architecture_tasks),
                "contract": str(contract["contract"]),
                "modules": modules,
                "tests": tests,
                "missing_modules": missing_modules,
                "missing_tests": missing_tests,
                "supporting_source_count": int(index_row.get("source_count") or 0),
                "gate_pass_rate": float(index_row.get("gate_pass_rate") or 0),
                "architecture_depth_score": int(index_row.get("architecture_depth_score") or 0),
                "ready_for_core_refactor": not missing_modules and not missing_tests and int(index_row.get("source_count") or 0) >= 2,
                "refactor_steps": _refactor_steps(component),
            }
        )
    items = sorted(items, key=lambda item: (str(item["priority"]), -int(item["supporting_source_count"]), str(item["component"])))[:max_tasks]
    gate = core_refactor_gate(items)
    return {
        "schema_version": 1,
        "summary": {
            "task_count": len(items),
            "ready_task_count": sum(1 for item in items if item["ready_for_core_refactor"]),
            "blocked_task_count": sum(1 for item in items if not item["ready_for_core_refactor"]),
            "source_count": int((memory.get("summary") or {}).get("source_count") or 0),
            "ready_component_count": int((memory.get("summary") or {}).get("ready_component_count") or 0),
        },
        "tasks": items,
        "gate": gate,
    }


def core_refactor_gate(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if not tasks:
        return {
            "passed": True,
            "status": "not_ready",
            "missing": [],
            "ready_task_count": 0,
            "task_count": 0,
            "missing_modules": [],
            "missing_tests": [],
        }
    missing_modules = sorted({item for task in tasks for item in task.get("missing_modules", [])})
    missing_tests = sorted({item for task in tasks for item in task.get("missing_tests", [])})
    ready_tasks = [task for task in tasks if task.get("ready_for_core_refactor")]
    missing = []
    if not ready_tasks:
        missing.append("no_ready_core_refactor_tasks")
    if missing_modules:
        missing.append("missing_core_modules")
    if missing_tests:
        missing.append("missing_core_tests")
    return {
        "passed": not missing,
        "status": "ready" if not missing else "blocked",
        "missing": missing,
        "ready_task_count": len(ready_tasks),
        "task_count": len(tasks),
        "missing_modules": missing_modules,
        "missing_tests": missing_tests,
    }


def write_core_refactor_plan(path: Path, plan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _component_from_task(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "")
    return task_id.removeprefix("retort-architecture-").replace("-", "_")


def _priority_for(component: str, tasks: list[dict[str, Any]]) -> str:
    task_id = f"retort-architecture-{component.replace('_', '-')}"
    for task in tasks:
        if task.get("task_id") == task_id:
            return str(task.get("priority") or "P2")
    return "P2"


def _refactor_steps(component: str) -> list[str]:
    return [
        f"extract_{component}_contract",
        f"wire_{component}_runtime_gate",
        f"prove_{component}_with_tests",
    ]


def _ordered_unique(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
