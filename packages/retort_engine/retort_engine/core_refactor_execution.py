from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


EXTRACTED_BOUNDARY_MODULES = {
    "automation_surface": ("retort_engine/project_assessment.py", "retort_engine/service.py", "retort_engine/ui_server.py", "retort_engine/cli.py"),
    "benchmark_eval": ("retort_engine/review_quality_benchmark.py", "retort_engine/absorption_quality.py"),
    "command_contract": ("retort_engine/contracts.py", "retort_engine/absorption_workflow.py"),
    "evaluation_loop": ("retort_engine/absorption_quality.py", "retort_engine/review_quality_benchmark.py"),
    "model_adapter": ("retort_engine/paibi_llm.py", "retort_engine/paibi_prompting.py", "retort_engine/prompts.py"),
    "provider_boundary": ("retort_engine/paibi_llm.py", "retort_engine/service.py"),
    "regression_oracle": ("retort_engine/capability_audit.py", "retort_engine/absorption_quality.py", "retort_engine/architecture_refactor.py"),
    "review_pipeline": ("retort_engine/devour_session.py", "retort_engine/review_pipeline.py", "retort_engine/pr_review.py"),
    "safety_policy": ("retort_engine/capability_audit.py", "retort_engine/license_gate.py", "retort_engine/git_status.py", "retort_engine/proof.py"),
    "workflow_ci": ("retort_engine/capability_audit.py", "retort_engine/absorption_workflow.py", "retort_engine/proof.py", "retort_engine/git_status.py"),
    "context_localization": ("retort_engine/review_context_bias.py", "retort_engine/pr_review.py"),
}


def load_core_refactor_plan(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    path = root / "docs" / "retort_core_refactor_plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"summary": {}, "gate": {"passed": False, "status": "missing_plan"}, "tasks": []}
    return payload if isinstance(payload, dict) else {"summary": {}, "gate": {"passed": False, "status": "invalid_plan"}, "tasks": []}


def verify_core_refactor_execution(project_root: str | Path, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root)
    payload = plan or load_core_refactor_plan(root)
    tasks = [task for task in payload.get("tasks") or [] if isinstance(task, dict) and task.get("ready_for_core_refactor")]
    component_results = [_verify_task(root, task) for task in tasks]
    missing = [item for result in component_results for item in result["missing"]]
    return {
        "status": "implemented" if not missing and component_results else "blocked",
        "task_count": len(tasks),
        "implemented_task_count": sum(1 for result in component_results if result["implemented"]),
        "missing": missing,
        "components": component_results,
    }


def _verify_task(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    component = str(task.get("component") or "")
    declared_modules = [str(item) for item in task.get("modules") or []]
    declared_tests = [str(item) for item in task.get("tests") or []]
    boundary_modules = list(EXTRACTED_BOUNDARY_MODULES.get(component, ()))
    modules = sorted(set(declared_modules + boundary_modules))
    tests = sorted(set(declared_tests))
    missing_modules = [rel for rel in modules if not (root / rel).is_file()]
    missing_tests = [rel for rel in tests if not (root / rel).is_file()]
    empty_tests = [rel for rel in tests if (root / rel).is_file() and _test_function_count(root / rel) == 0]
    single_module_boundary = component in EXTRACTED_BOUNDARY_MODULES and len([rel for rel in boundary_modules if (root / rel).is_file()]) < 2
    missing: list[str] = []
    missing.extend(f"{component}:missing_module:{rel}" for rel in missing_modules)
    missing.extend(f"{component}:missing_test:{rel}" for rel in missing_tests)
    missing.extend(f"{component}:empty_test:{rel}" for rel in empty_tests)
    if single_module_boundary:
        missing.append(f"{component}:boundary_not_split")
    return {
        "component": component,
        "implemented": not missing,
        "modules": modules,
        "tests": tests,
        "test_function_count": sum(_test_function_count(root / rel) for rel in tests if (root / rel).is_file()),
        "missing": missing,
    }


def _test_function_count(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return 0
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))
