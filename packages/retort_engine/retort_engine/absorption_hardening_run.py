from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.capability_audit import is_behavior_test_file, is_project_behavior_source_file, latest_absorption_merge_commit
from retort_engine.real_absorption_run_proof import build_per_run_code_graph_proof, code_graph_proof_gate, record_real_absorption_run


def record_post_absorption_hardening_run(
    project: str | Path,
    *,
    output: str | Path = "",
    python_executable: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    merge_commit = latest_absorption_merge_commit(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S-hardening")
    changed_files = _post_merge_changed_files(root, merge_commit)
    behavior_sources = [item for item in changed_files if is_project_behavior_source_file(_project_rel(root, item))]
    behavior_tests = [item for item in changed_files if is_behavior_test_file(_project_rel(root, item))]
    source = f"retort://post-absorption-hardening/{merge_commit or 'no-merge'}"
    proof = build_per_run_code_graph_proof(
        root,
        run_id=run_id,
        changed_files=changed_files,
        pre_absorption_focus={
            "mode": "post_absorption_hardening",
            "merge_commit": merge_commit,
            "own_focus_files": [_project_rel(root, item) for item in behavior_sources[:20]],
        },
    )
    gates = [
        _quality_gate_from_report(root),
        code_graph_proof_gate(proof, run_id=run_id),
    ]
    task = {
        "task_id": f"{run_id}-prove-hardening",
        "title": "Prove post-absorption hardening as latest behavior absorption",
        "dimension": "capability_absorption_score",
        "priority": "P0",
        "why": "The latest absorption score must be anchored to real behavior source and tests after merge.",
    }
    employee_result_path, employee_gate = _run_employee_worker(
        root,
        run_id=run_id,
        source=source,
        changed_files=changed_files,
        gates_passed=all(bool(gate.get("ok")) for gate in gates),
        tasks=[task],
        python_executable=python_executable or sys.executable,
    )
    gates.append(employee_gate)
    result = {
        "run_id": run_id,
        "status": "applied" if changed_files else "noop",
        "source": source,
        "summary": {
            "mode": "post_absorption_hardening",
            "merge_commit": merge_commit,
            "changed_file_count": len(changed_files),
            "behavior_source_file_count": len(behavior_sources),
            "behavior_test_file_count": len(behavior_tests),
            "duration_sec": round(time.monotonic() - started, 3),
        },
        "changed_files": changed_files,
        "behavior_source_files": [_project_rel(root, item) for item in behavior_sources],
        "behavior_test_files": [_project_rel(root, item) for item in behavior_tests],
        "gates": gates,
        "gates_passed": all(bool(gate.get("ok")) for gate in gates),
        "code_graph_proof": proof,
        "employee_results_path": str(employee_result_path),
        "tasks": [task],
        "evidence": {
            "source": "git_diff_latest_absorption_merge_to_head",
            "merge_commit": merge_commit,
            "records_committed_post_merge_behavior": True,
            "employee_runtime_worker_subprocess": bool(employee_gate.get("ok")),
        },
    }
    record_path = record_real_absorption_run(root, result)
    result["run_record_path"] = str(record_path)
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _post_merge_changed_files(root: Path, merge_commit: str) -> list[str]:
    git_root = _git_root(root)
    if not git_root:
        return []
    pathspec = _pathspec(root, git_root)
    if merge_commit:
        command = ["git", "diff", "--name-only", f"{merge_commit}..HEAD", "--", *pathspec]
    else:
        command = ["git", "diff", "--name-only", "HEAD~1..HEAD", "--", *pathspec]
    completed = subprocess.run(command, cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode != 0:
        return []
    files: list[str] = []
    for line in completed.stdout.splitlines():
        path = (git_root / line.strip()).resolve()
        if path.is_file() and path.is_relative_to(root):
            files.append(str(path))
    return sorted(set(files))


def _quality_gate_from_report(root: Path) -> dict[str, Any]:
    report = _read_json(root / "docs" / "retort_quality_gate_bundle.json")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    ok = report.get("status") == "ready" and summary.get("all_gates_passed") is True
    return {
        "command": ["retort", "quality-gates", "--project", str(root)],
        "cwd": str(root),
        "exit_code": 0 if ok else 1,
        "ok": ok,
        "duration_sec": 0.0,
        "stdout_tail": f"quality_gate_bundle_status={report.get('status', '')}; all_gates_passed={summary.get('all_gates_passed', '')}",
        "stderr_tail": "",
    }


def _run_employee_worker(
    root: Path,
    *,
    run_id: str,
    source: str,
    changed_files: list[str],
    gates_passed: bool,
    tasks: list[dict[str, Any]],
    python_executable: str,
) -> tuple[Path, dict[str, Any]]:
    payload_path = root / ".retort" / "employee_runtime_requests" / f"{run_id}.json"
    output_path = root / ".retort" / "employee_results" / f"{run_id}.json"
    queue_path = root / ".retort" / "employee_queue.jsonl"
    history_store = root / ".retort" / "retort_history.sqlite"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "project": str(root),
        "source": source,
        "output_path": str(output_path),
        "queue_path": str(queue_path),
        "history_store": str(history_store),
        "tasks": tasks,
        "changed_files": changed_files,
        "gates_passed": gates_passed,
        "review_report_path": str(root / "docs" / "retort_external_advantage_matrix.json"),
        "diff_text": _git_diff(root, changed_files),
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    started = time.monotonic()
    completed = subprocess.run(
        [python_executable, "-m", "retort_engine.employee_runtime_worker", "--payload-file", str(payload_path)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": _worker_pythonpath(root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=240,
    )
    gate = {
        "command": [python_executable, "-m", "retort_engine.employee_runtime_worker", "--payload-file", str(payload_path)],
        "cwd": str(root),
        "exit_code": completed.returncode,
        "ok": completed.returncode == 0 and output_path.is_file(),
        "duration_sec": round(time.monotonic() - started, 3),
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }
    return output_path, gate


def _worker_pythonpath(root: Path) -> str:
    current = os.environ.get("PYTHONPATH", "")
    entries = [str(Path(item).expanduser().resolve()) for item in (current.split(os.pathsep) if current else []) if item]
    package_root = str(Path(__file__).resolve().parents[1])
    root_text = str(root.resolve())
    for item in (package_root, root_text):
        if item not in entries:
            entries.append(item)
    return os.pathsep.join(entries)


def _git_diff(root: Path, changed_files: list[str]) -> str:
    git_root = _git_root(root)
    if not git_root or not changed_files:
        return ""
    rels = [str(Path(item).resolve().relative_to(git_root)) for item in changed_files if Path(item).resolve().is_relative_to(git_root)]
    completed = subprocess.run(["git", "diff", "HEAD", "--", *rels], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.stdout.strip():
        return completed.stdout
    completed = subprocess.run(["git", "show", "--format=", "--", *rels], cwd=git_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return completed.stdout[-200000:]


def _git_root(root: Path) -> Path | None:
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def _pathspec(root: Path, git_root: Path) -> list[str]:
    rel = root.relative_to(git_root) if root != git_root and root.is_relative_to(git_root) else Path(".")
    prefix = "" if str(rel) == "." else str(rel).rstrip("/") + "/"
    return [f"{prefix}retort_engine", f"{prefix}tests", f"{prefix}docs"]


def _project_rel(root: Path, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
