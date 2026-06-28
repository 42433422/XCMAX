from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from retort_engine.contracts import contract_names, validate_contract


GateRunner = Callable[[list[str], Path], dict[str, Any]]


def run_quality_gate_bundle(
    project: str | Path,
    *,
    output: str | Path = "",
    python_executable: str = "",
    runner: GateRunner | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    python = python_executable or sys.executable
    command_runner = runner or _run_command
    gates = [
        _command_gate("lint", [python, "-m", "ruff", "check", "."], root, command_runner),
        _command_gate("pytest", [python, "-m", "pytest", "tests", "-q"], root, command_runner),
        _contract_gate(),
    ]
    passed = [gate for gate in gates if gate["ok"]]
    summary = {
        "gate_count": len(gates),
        "passed_count": len(passed),
        "all_gates_passed": len(passed) == len(gates),
        "lint_passed": _gate_ok(gates, "lint"),
        "pytest_passed": _gate_ok(gates, "pytest"),
        "contract_passed": _gate_ok(gates, "contract"),
        "contract_schema_count": len(contract_names()),
        "single_command_surface": True,
        "command_name": "quality-gates",
        "duration_sec": round(time.monotonic() - started, 3),
    }
    result = {
        "status": "ready" if summary["all_gates_passed"] else "failed",
        "project": str(root),
        "summary": summary,
        "gates": gates,
        "evidence": {
            "runner": "retort_quality_gate_bundle",
            "python": python,
            "gate_names": [str(gate["name"]) for gate in gates],
            "failure_names": [str(gate["name"]) for gate in gates if not gate["ok"]],
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _command_gate(name: str, command: list[str], root: Path, runner: GateRunner) -> dict[str, Any]:
    completed = runner(command, root)
    return {
        "name": name,
        "kind": "subprocess",
        "command": command,
        "ok": int(completed.get("returncode") or 0) == 0,
        "returncode": int(completed.get("returncode") or 0),
        "stdout_tail": str(completed.get("stdout") or "")[-2000:],
        "stderr_tail": str(completed.get("stderr") or "")[-2000:],
    }


def _contract_gate() -> dict[str, Any]:
    fixtures = _contract_fixtures()
    checks = []
    for name in contract_names():
        payload = fixtures.get(name, {})
        check = validate_contract(name, payload)
        checks.append(check)
    failed = [check for check in checks if not check["valid"]]
    return {
        "name": "contract",
        "kind": "in_process",
        "command": ["retort", "contract-sanity"],
        "ok": not failed,
        "returncode": 0 if not failed else 1,
        "schema_count": len(checks),
        "failed": failed,
        "stdout_tail": f"validated {len(checks)} Retort contracts",
        "stderr_tail": "",
    }


def _run_command(command: list[str], root: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"returncode": 124, "stdout": str(exc.stdout or ""), "stderr": str(exc.stderr or "timeout")}
    except OSError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}
    return {"returncode": int(completed.returncode), "stdout": completed.stdout or "", "stderr": completed.stderr or ""}


def _gate_ok(gates: list[dict[str, Any]], name: str) -> bool:
    return any(str(gate.get("name") or "") == name and bool(gate.get("ok")) for gate in gates)


def _contract_fixtures() -> dict[str, dict[str, Any]]:
    return {
        "assessment": {"project": "p", "scores": [], "evidence": [], "metadata": {}},
        "absorption_result": {
            "status": "ready",
            "summary": {},
            "own_assessment": {},
            "external_assessment": {},
            "tasks": [],
            "execution": {},
            "branch_workflow": {},
        },
        "execution_result": {"status": "applied", "changed_files": [], "gates": [], "gates_passed": True, "review_report_path": "r", "employee_results_path": "e"},
        "review_report": {"run_id": "r", "source": "s", "external_snapshot": {}, "license_review": {}, "review_pipeline": {}, "replay": {}},
        "pr_review_result": {"status": "reviewed", "summary": {}, "files": [], "comments": [], "task_groups": [], "incremental": {}},
        "pr_dry_run_result": {"status": "reviewed", "pr_url": "u", "diff_url": "d", "summary": {}, "review": {}},
        "pr_publish_dry_run_result": {"status": "dry_run_ready", "pr_url": "u", "summary": {}, "comments": [], "rollback": {}},
        "pr_publish_sandbox_result": {"status": "sandbox_rolled_back", "pr_url": "u", "summary": {}, "created_receipts": [], "rollback_receipts": []},
        "pr_live_publish_probe_result": {"status": "live_rolled_back", "pr_url": "u", "summary": {}, "created_receipts": [], "rollback_receipts": [], "evidence": {}},
        "pr_readonly_degradation_probe_result": {
            "status": "read_only_degraded",
            "pr_url": "u",
            "summary": {},
            "created_receipts": [],
            "rollback_receipts": [],
            "evidence": {},
        },
        "pr_long_run_review_result": {"status": "ready", "project": "p", "summary": {}, "pull_requests": [], "publish_safety_matrix": {}, "evidence": {}},
        "cross_project_replay_result": {"status": "ready", "project": "p", "summary": {}, "projects": [], "checks": []},
        "multi_project_absorption_replay_result": {"status": "ready", "project": "p", "summary": {}, "projects": [], "evidence": {}},
        "absorption_continuity_probe_result": {"status": "ready", "project": "p", "summary": {}, "runs": [], "latest_closed_loop": {}, "evidence": {}},
        "complex_pr_replay_result": {"status": "ready", "project": "p", "summary": {}, "pull_requests": [], "evidence": {}},
        "task_prioritization_result": {"status": "ready", "project": "p", "summary": {}, "priorities": [], "evidence": {}},
        "task_dispatch_plan_result": {"status": "ready", "project": "p", "summary": {}, "tasks": [], "evidence": {}},
        "review_quality_benchmark_result": {"status": "ready", "project": "p", "summary": {}, "samples": [], "evidence": {}},
        "review_adjudication_calibration_result": {"status": "ready", "project": "p", "summary": {}, "cases": [], "evidence": {}},
        "review_pipeline_diff_replay_result": {
            "status": "ready",
            "pipeline_stages": [],
            "summary": {},
            "context_groups": [],
            "comments": [],
            "task_groups": [],
            "evidence": {},
        },
        "issue_patch_benchmark_result": {"status": "ready", "summary": {}, "cases": [], "evidence": {}},
        "codebase_graph_result": {"status": "ready", "project": "p", "summary": {}, "nodes": [], "edges": [], "hotspots": [], "evidence": {}},
        "architecture_contract_result": {"status": "passed", "project": "p", "summary": {}, "contracts": [], "violations": [], "evidence": {}},
        "employee_scheduler_stress_result": {"status": "ready", "project": "p", "summary": {}, "rounds": [], "evidence": {}},
        "employee_patch_closure_result": {"status": "ready", "project": "p", "summary": {}, "cases": [], "evidence": {}},
        "production_recovery_drill_result": {"status": "ready", "project": "p", "summary": {}, "scenarios": [], "evidence": {}},
        "absorption_release_decision_result": {"status": "ready", "project": "p", "summary": {}, "decisions": [], "evidence": {}},
        "quality_gate_bundle_result": {"status": "ready", "project": "p", "summary": {}, "gates": [], "evidence": {}},
        "llm_score": {"dimension": "d", "value": 1, "reason": "r"},
    }
