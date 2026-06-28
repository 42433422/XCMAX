from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from retort_engine.real_absorption_run_proof import per_run_code_graph_proof_missing


def build_absorption_continuity_probe(project: str | Path, *, min_runs: int = 5, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    runs = _latest_distinct_successful_runs(root, limit=max(min_runs, 1))
    inspected = [_inspect_run(root, run, latest=(index == 0)) for index, run in enumerate(runs)]
    ready_runs = [item for item in inspected if item["checks"]["ready"]]
    latest_closed_loop = _latest_closed_loop(root, inspected[0] if inspected else {})
    timestamps = [_run_time(item["run_id"]) for item in inspected]
    timestamps = [item for item in timestamps if item is not None]
    span_minutes = int((max(timestamps) - min(timestamps)).total_seconds() // 60) if len(timestamps) >= 2 else 0
    summary = {
        "selected_run_count": len(inspected),
        "min_run_count": min_runs,
        "ready_run_count": len(ready_runs),
        "distinct_source_count": len({item["source"] for item in inspected}),
        "all_have_behavior_diff": all(item["checks"]["behavior_diff"] for item in inspected) if inspected else False,
        "all_have_behavior_tests": all(item["checks"]["behavior_tests"] for item in inspected) if inspected else False,
        "all_have_employee_results": all(item["checks"]["employee_results"] for item in inspected) if inspected else False,
        "all_have_gates_passed": all(item["checks"]["gates_passed"] for item in inspected) if inspected else False,
        "all_have_per_run_code_graph_proof": all(item["checks"]["per_run_code_graph_proof"] for item in inspected) if inspected else False,
        "latest_closed_loop_verified": latest_closed_loop["verified"],
        "latest_merge_commit": latest_closed_loop["merge_commit"],
        "continuity_span_minutes": span_minutes,
        "counting_model_separated": True,
    }
    summary["continuity_gate_passed"] = (
        summary["ready_run_count"] >= min_runs
        and summary["distinct_source_count"] >= min_runs
        and summary["all_have_per_run_code_graph_proof"]
        and summary["latest_closed_loop_verified"]
    )
    result = {
        "status": "ready" if summary["continuity_gate_passed"] else "needs_more_continuity",
        "project": str(root),
        "summary": summary,
        "runs": inspected,
        "latest_closed_loop": latest_closed_loop,
        "evidence": {
            "run_dir": str(root / ".retort" / "real_absorption_runs"),
            "scope": "latest_distinct_successful_real_absorption_runs",
            "source_order": [item["source"] for item in inspected],
            "counting_model": {
                "latest_absorption_run": "changed behavior files in the latest run only",
                "post_absorption_hardening": "git diff from latest merge commit to HEAD",
                "support_inventory": "all supported Retort behavior modules and tests",
            },
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _latest_distinct_successful_runs(root: Path, *, limit: int) -> list[dict[str, Any]]:
    run_dir = root / ".retort" / "real_absorption_runs"
    runs: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("*.json"), reverse=True) if run_dir.is_dir() else []:
        payload = _read_json(path)
        if not payload or not payload.get("gates_passed"):
            continue
        source = str(payload.get("source") or "").strip()
        if not source:
            continue
        payload["_run_file"] = str(path)
        runs.append(payload)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for run in runs:
        source = str(run.get("source") or "")
        if source in seen:
            continue
        seen.add(source)
        selected.append(run)
        if len(selected) >= limit:
            break
    return selected


def _inspect_run(root: Path, run: dict[str, Any], *, latest: bool) -> dict[str, Any]:
    run_id = str(run.get("run_id") or Path(str(run.get("_run_file") or "")).stem)
    changed_files = [str(item) for item in run.get("changed_files") or []]
    behavior_source_files = [item for item in changed_files if _is_behavior_source(root, item)]
    behavior_test_files = [item for item in changed_files if _is_behavior_test(root, item)]
    employee_path = Path(str(run.get("employee_results_path") or ""))
    employee_payload = _read_json(employee_path)
    employee_results = employee_payload.get("results") if isinstance(employee_payload.get("results"), list) else []
    proof = run.get("code_graph_proof") if isinstance(run.get("code_graph_proof"), dict) else {}
    proof_missing = per_run_code_graph_proof_missing(proof, run_id=run_id)
    gates = run.get("gates") if isinstance(run.get("gates"), list) else []
    checks = {
        "gates_passed": bool(run.get("gates_passed")) and (all(bool(gate.get("ok")) for gate in gates if isinstance(gate, dict)) if gates else True),
        "behavior_diff": bool(behavior_source_files),
        "behavior_tests": bool(behavior_test_files),
        "employee_results": employee_path.is_file() and bool(employee_results),
        "per_run_code_graph_proof": bool(proof.get("passed")) and not proof_missing,
    }
    checks["ready"] = all(checks.values())
    return {
        "run_id": run_id,
        "source": str(run.get("source") or ""),
        "latest": latest,
        "run_file": str(run.get("_run_file") or ""),
        "changed_file_count": len(changed_files),
        "behavior_source_files": [_project_relative(root, item) for item in behavior_source_files],
        "behavior_test_files": [_project_relative(root, item) for item in behavior_test_files],
        "employee_result_count": len(employee_results),
        "gate_count": len(gates),
        "code_graph_proof_status": str(proof.get("status") or ""),
        "code_graph_proof_missing": proof_missing,
        "checks": checks,
    }


def _latest_closed_loop(root: Path, latest_run: dict[str, Any]) -> dict[str, Any]:
    state = _read_json(root / ".retort" / "absorption_state.json")
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    evidence = [str(item) for item in proof.get("evidence") or []]
    run_id = str(latest_run.get("run_id") or "")
    checks = latest_run.get("checks") if isinstance(latest_run.get("checks"), dict) else {}
    hardening_merge_commit = _hardening_merge_commit(str(latest_run.get("source") or ""))
    merge_commit = hardening_merge_commit or _evidence_value(evidence, "merge_commit")
    code_graph_verified = "code_graph_proof_passed=True" in evidence or bool(checks.get("per_run_code_graph_proof"))
    latest_run_referenced = not run_id or any(run_id in item for item in evidence) or bool(hardening_merge_commit)
    hardening_ready = not hardening_merge_commit or bool(checks.get("ready"))
    verified = (
        bool(proof.get("branch_diff_verified"))
        and bool(proof.get("employee_execution_verified"))
        and bool(proof.get("post_absorption_tests_passed"))
        and bool(proof.get("merge_verified"))
        and bool(proof.get("external_advantage_reassessed"))
        and bool(merge_commit)
        and latest_run_referenced
        and code_graph_verified
        and hardening_ready
    )
    return {
        "verified": verified,
        "run_id": run_id,
        "merge_commit": merge_commit,
        "state_status": str(state.get("status") or ""),
        "source": str(state.get("source") or ""),
        "required_flags": {
            "branch_diff_verified": bool(proof.get("branch_diff_verified")),
            "employee_execution_verified": bool(proof.get("employee_execution_verified")),
            "post_absorption_tests_passed": bool(proof.get("post_absorption_tests_passed")),
            "merge_verified": bool(proof.get("merge_verified")),
            "external_advantage_reassessed": bool(proof.get("external_advantage_reassessed")),
            "code_graph_proof_passed": code_graph_verified,
            "latest_run_referenced": latest_run_referenced,
            "post_absorption_hardening_ready": hardening_ready,
        },
    }


def _hardening_merge_commit(source: str) -> str:
    prefix = "retort://post-absorption-hardening/"
    return source.removeprefix(prefix).strip() if source.startswith(prefix) else ""


def _evidence_value(evidence: list[str], key: str) -> str:
    prefix = f"{key}="
    for item in evidence:
        if item.startswith(prefix):
            return item.split("=", 1)[1].strip()
    return ""


def _run_time(run_id: str) -> datetime | None:
    try:
        return datetime.strptime(run_id.split("-", 1)[0], "%Y%m%d%H%M%S")
    except ValueError:
        return None


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
