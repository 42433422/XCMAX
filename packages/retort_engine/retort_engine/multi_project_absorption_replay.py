from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.real_absorption_run_proof import per_run_code_graph_proof_missing


def build_multi_project_absorption_replay(project: str | Path, *, min_projects: int = 5, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    candidates = _latest_successful_runs_by_source(root)
    projects = [_project_replay(root, run) for run in candidates[: max(min_projects, 1)]]
    ready_projects = [project for project in projects if project["checks"]["ready"]]
    summary = {
        "external_project_count": len(projects),
        "ready_project_count": len(ready_projects),
        "min_project_count": min_projects,
        "distinct_source_count": len({project["source"] for project in projects}),
        "all_have_behavior_diff": all(project["checks"]["behavior_diff"] for project in projects) if projects else False,
        "all_have_behavior_tests": all(project["checks"]["behavior_tests"] for project in projects) if projects else False,
        "all_have_employee_results": all(project["checks"]["employee_results"] for project in projects) if projects else False,
        "all_have_gates_passed": all(project["checks"]["gates_passed"] for project in projects) if projects else False,
        "all_have_per_run_code_graph_proof": all(project["checks"]["per_run_code_graph_proof"] for project in projects) if projects else False,
        "latest_project_differs_from_previous": len(projects) >= 2 and projects[0]["source"] != projects[1]["source"],
    }
    status = "ready" if summary["ready_project_count"] >= min_projects and summary["distinct_source_count"] >= min_projects else "needs_more_replay"
    result = {
        "status": status,
        "project": str(root),
        "summary": summary,
        "projects": projects,
        "evidence": {
            "run_dir": str(root / ".retort" / "real_absorption_runs"),
            "source_order": [project["source"] for project in projects],
            "latest_run_id": projects[0]["run_id"] if projects else "",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _latest_successful_runs_by_source(root: Path) -> list[dict[str, Any]]:
    runs = []
    run_dir = root / ".retort" / "real_absorption_runs"
    for path in sorted(run_dir.glob("*.json"), reverse=True) if run_dir.is_dir() else []:
        payload = _read_json(path)
        if not payload or not payload.get("gates_passed"):
            continue
        source = str(payload.get("source") or "").strip()
        if not source:
            continue
        payload["_run_file"] = str(path)
        runs.append(payload)
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for run in runs:
        source = str(run.get("source") or "")
        if source in seen:
            continue
        seen.add(source)
        selected.append(run)
    return selected


def _project_replay(root: Path, run: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(item) for item in run.get("changed_files") or []]
    behavior_source_files = [item for item in changed_files if _is_behavior_source(root, item)]
    behavior_test_files = [item for item in changed_files if _is_behavior_test(root, item)]
    employee_results_path = Path(str(run.get("employee_results_path") or ""))
    employee_payload = _read_json(employee_results_path)
    employee_results = employee_payload.get("results") if isinstance(employee_payload.get("results"), list) else []
    worker_runtime = employee_payload.get("runtime_evidence") if isinstance(employee_payload.get("runtime_evidence"), dict) else {}
    worker_review = worker_runtime.get("worker_review") if isinstance(worker_runtime.get("worker_review"), dict) else {}
    proof = run.get("code_graph_proof") if isinstance(run.get("code_graph_proof"), dict) else {}
    proof_missing = per_run_code_graph_proof_missing(proof, run_id=str(run.get("run_id") or ""))
    checks = {
        "gates_passed": bool(run.get("gates_passed")),
        "behavior_diff": bool(behavior_source_files),
        "behavior_tests": bool(behavior_test_files),
        "employee_results": employee_results_path.is_file() and bool(employee_results),
        "worker_review": str(worker_review.get("status") or "") == "reviewed",
        "per_run_code_graph_proof": bool(proof.get("passed")) and not proof_missing,
    }
    checks["ready"] = all(checks.values())
    return {
        "run_id": str(run.get("run_id") or Path(str(run.get("_run_file") or "")).stem),
        "source": str(run.get("source") or ""),
        "run_file": str(run.get("_run_file") or ""),
        "changed_file_count": len(changed_files),
        "behavior_source_files": [_project_relative(root, item) for item in behavior_source_files],
        "behavior_test_files": [_project_relative(root, item) for item in behavior_test_files],
        "employee_result_count": len(employee_results),
        "worker_review_status": str(worker_review.get("status") or ""),
        "code_graph_proof_status": str(proof.get("status") or ""),
        "code_graph_proof_missing": proof_missing,
        "checks": checks,
    }


def _is_behavior_source(root: Path, item: str) -> bool:
    rel = _project_relative(root, item)
    path = Path(rel)
    return path.suffix == ".py" and "tests" not in path.parts and path.name not in {"absorbed_external_patterns.py", "absorbed_capabilities.py"}


def _is_behavior_test(root: Path, item: str) -> bool:
    rel = _project_relative(root, item)
    path = Path(rel)
    return path.suffix == ".py" and ("tests" in path.parts or path.name.startswith("test_"))


def _project_relative(root: Path, item: str) -> str:
    path = Path(item)
    try:
        return str(path.expanduser().resolve().relative_to(root))
    except (OSError, ValueError):
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
