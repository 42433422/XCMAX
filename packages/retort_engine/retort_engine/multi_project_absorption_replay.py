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
    selected_families = sorted({project["source_family"] for project in projects if project.get("source_family")})
    historical_inventory = _historical_source_inventory(candidates)
    summary = {
        "external_project_count": len(projects),
        "ready_project_count": len(ready_projects),
        "min_project_count": min_projects,
        "distinct_source_count": len({project["source"] for project in projects}),
        "source_family_count": len(selected_families),
        "source_families": selected_families,
        "non_ts_source_count": sum(1 for project in projects if project.get("source_family") != "typescript_pr_bot"),
        "heterogeneous_absorption_verified": len(selected_families) >= min(3, max(1, min_projects)) and any(project.get("source_family") != "typescript_pr_bot" for project in projects),
        "historical_successful_source_count": historical_inventory["successful_source_count"],
        "historical_source_family_count": historical_inventory["source_family_count"],
        "historical_non_ts_source_count": historical_inventory["non_ts_source_count"],
        "historical_architecture_source_count": historical_inventory["architecture_source_count"],
        "historical_benchmark_source_count": historical_inventory["benchmark_source_count"],
        "historical_security_source_count": historical_inventory["security_source_count"],
        "historical_heterogeneous_absorption_verified": historical_inventory["heterogeneous_absorption_verified"],
        "all_have_behavior_diff": all(project["checks"]["behavior_diff"] for project in projects) if projects else False,
        "all_have_behavior_tests": all(project["checks"]["behavior_tests"] for project in projects) if projects else False,
        "all_have_employee_results": all(project["checks"]["employee_results"] for project in projects) if projects else False,
        "all_have_gates_passed": all(project["checks"]["gates_passed"] for project in projects) if projects else False,
        "all_have_per_run_code_graph_proof": all(project["checks"]["per_run_code_graph_proof"] for project in projects) if projects else False,
        "latest_project_differs_from_previous": len(projects) >= 2 and projects[0]["source"] != projects[1]["source"],
    }
    status = (
        "ready"
        if summary["ready_project_count"] >= min_projects
        and summary["distinct_source_count"] >= min_projects
        and summary["heterogeneous_absorption_verified"]
        and (min_projects < 5 or summary["historical_heterogeneous_absorption_verified"])
        else "needs_more_replay"
    )
    result = {
        "status": status,
        "project": str(root),
        "summary": summary,
        "projects": projects,
        "evidence": {
            "run_dir": str(root / ".retort" / "real_absorption_runs"),
            "source_order": [project["source"] for project in projects],
            "source_family_order": [project["source_family"] for project in projects],
            "latest_run_id": projects[0]["run_id"] if projects else "",
            "historical_source_families": historical_inventory["source_families"],
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
        "source_family": _source_family(str(run.get("source") or "")),
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


def _historical_source_inventory(runs: list[dict[str, Any]]) -> dict[str, Any]:
    sources = [str(run.get("source") or "") for run in runs if str(run.get("source") or "")]
    families = [_source_family(source) for source in sources]
    source_families = sorted({family for family in families if family})
    architecture_families = {"architecture_governance", "architecture_graph", "rust_code_graph"}
    benchmark_families = {"benchmark_harness", "agentic_benchmark"}
    security_families = {"security_static_analysis"}
    return {
        "successful_source_count": len(sources),
        "source_family_count": len(source_families),
        "source_families": source_families,
        "non_ts_source_count": sum(1 for family in families if family != "typescript_pr_bot"),
        "architecture_source_count": sum(1 for family in families if family in architecture_families),
        "benchmark_source_count": sum(1 for family in families if family in benchmark_families),
        "security_source_count": sum(1 for family in families if family in security_families),
        "heterogeneous_absorption_verified": len(source_families) >= 5
        and any(family in architecture_families for family in families)
        and any(family in benchmark_families for family in families)
        and any(family in security_families for family in families)
        and any(family == "python_pr_agent" for family in families)
        and any(family == "typescript_pr_bot" for family in families),
    }


def _source_family(source: str) -> str:
    normalized = source.lower()
    if normalized.startswith("retort://post-absorption-hardening"):
        return "post_absorption_hardening"
    if "qodo-ai/pr-agent" in normalized:
        return "python_pr_agent"
    if any(marker in normalized for marker in ("mopemope/pr-ai-review-bot", "chatgpt-codereview", "ai-pr-reviewer", "local-ai-pr-reviewer")):
        return "typescript_pr_bot"
    if "reviewdog/reviewdog" in normalized:
        return "go_ci_review_publisher"
    if "swe-bench" in normalized or "lm-evaluation-harness" in normalized:
        return "benchmark_harness"
    if "agentless" in normalized:
        return "agentic_benchmark"
    if "import-linter" in normalized:
        return "architecture_governance"
    if "pydeps" in normalized or "madge" in normalized:
        return "architecture_graph"
    if "codegraph-rust" in normalized:
        return "rust_code_graph"
    if "bandit" in normalized or "semgrep" in normalized:
        return "security_static_analysis"
    if "repomix" in normalized:
        return "context_packager"
    if "reviewscope" in normalized or "openrabbit" in normalized:
        return "review_reasoning"
    return "other_external_project"


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
