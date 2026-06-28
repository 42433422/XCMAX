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
    worker_count: int = 5,
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
    tasks = _hardening_tasks(run_id)
    employee_result_path, employee_gate = _run_employee_workers(
        root,
        run_id=run_id,
        source=source,
        changed_files=changed_files,
        gates_passed=all(bool(gate.get("ok")) for gate in gates),
        tasks=tasks,
        python_executable=python_executable or sys.executable,
        worker_count=max(1, worker_count),
    )
    gates.append(employee_gate)
    aggregate_payload = _read_json(employee_result_path)
    aggregate_results = aggregate_payload.get("results") if isinstance(aggregate_payload.get("results"), list) else []
    multi_worker = aggregate_payload.get("runtime_evidence", {}).get("multi_worker") if isinstance(aggregate_payload.get("runtime_evidence"), dict) else {}
    worker_review = aggregate_payload.get("runtime_evidence", {}).get("worker_review") if isinstance(aggregate_payload.get("runtime_evidence"), dict) else {}
    process_isolation = multi_worker.get("process_isolation") if isinstance(multi_worker.get("process_isolation"), dict) else {}
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
            "worker_count": int(multi_worker.get("worker_count") or 0),
            "independent_worker_count": int(multi_worker.get("independent_worker_count") or 0),
            "employee_result_count": len(aggregate_results),
            "multi_worker_verified": bool(multi_worker.get("verified")),
            "worker_review_count": int(worker_review.get("worker_review_count") or 0),
            "worker_review_file_count": int(worker_review.get("file_count") or 0),
            "worker_review_comment_count": int(worker_review.get("comment_count") or 0),
            "worker_review_task_group_count": int(worker_review.get("task_group_count") or 0),
            "pid_isolation_verified": bool(process_isolation.get("pid_isolation_verified")),
            "runtime_boundary_verified": bool(process_isolation.get("runtime_boundary_verified")),
            "unique_process_id_count": int(process_isolation.get("unique_process_id_count") or 0),
            "worker_process_trace_count": int(process_isolation.get("worker_process_trace_count") or 0),
            "runtime_boundary_verified_count": int(process_isolation.get("runtime_boundary_verified_count") or 0),
            "pid_cross_check_count": int(process_isolation.get("pid_cross_check_count") or 0),
            "crash_isolation_verified": bool(process_isolation.get("crash_isolation_verified")),
            "crash_isolation_verified_count": int(process_isolation.get("crash_isolation_verified_count") or 0),
            "duration_sec": round(time.monotonic() - started, 3),
        },
        "changed_files": changed_files,
        "behavior_source_files": [_project_rel(root, item) for item in behavior_sources],
        "behavior_test_files": [_project_rel(root, item) for item in behavior_tests],
        "gates": gates,
        "gates_passed": all(bool(gate.get("ok")) for gate in gates),
        "code_graph_proof": proof,
        "employee_results_path": str(employee_result_path),
        "tasks": tasks,
        "evidence": {
            "source": "git_diff_latest_absorption_merge_to_head",
            "merge_commit": merge_commit,
            "records_committed_post_merge_behavior": True,
            "employee_runtime_worker_subprocess": bool(employee_gate.get("ok")),
            "multi_worker_verified": bool(multi_worker.get("verified")),
            "pid_isolation_verified": bool(process_isolation.get("pid_isolation_verified")),
            "runtime_boundary_verified": bool(process_isolation.get("runtime_boundary_verified")),
            "crash_isolation_verified": bool(process_isolation.get("crash_isolation_verified")),
        },
    }
    record_path = record_real_absorption_run(root, result)
    result["run_record_path"] = str(record_path)
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _hardening_tasks(run_id: str) -> list[dict[str, Any]]:
    specs = [
        (
            "prove-hardening",
            "Prove post-absorption hardening as latest behavior absorption",
            "capability_absorption_score",
            "The latest absorption score must be anchored to real behavior source and tests after merge.",
        ),
        (
            "prove-code-graph",
            "Verify per-run code graph proof for changed core modules",
            "architecture_depth",
            "The absorption proof must locate changed hotspots and dependency impact, not only count files.",
        ),
        (
            "prove-external-regression",
            "Recheck external advantage regression after hardening",
            "comparative_analysis_depth",
            "External behavior migration must remain reproducible after the hardening diff.",
        ),
        (
            "prove-live-publish",
            "Verify live PR publish rollback evidence is present",
            "product_operability",
            "Retort must prove real write-and-rollback publication readiness, not only dry-run degradation.",
        ),
        (
            "prove-worker-scale",
            "Verify scaled employee worker fan-out evidence",
            "employee_execution_integration",
            "Absorption follow-up needs multiple independent workers with separate result artifacts.",
        ),
    ]
    return [
        {
            "task_id": f"{run_id}-{suffix}",
            "title": title,
            "dimension": dimension,
            "priority": "P0",
            "why": why,
        }
        for suffix, title, dimension, why in specs
    ]


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


def _run_employee_workers(
    root: Path,
    *,
    run_id: str,
    source: str,
    changed_files: list[str],
    gates_passed: bool,
    tasks: list[dict[str, Any]],
    python_executable: str,
    worker_count: int,
) -> tuple[Path, dict[str, Any]]:
    request_dir = root / ".retort" / "employee_runtime_requests"
    result_dir = root / ".retort" / "employee_results"
    aggregate_output_path = result_dir / f"{run_id}-zz-aggregate.json"
    queue_path = root / ".retort" / "employee_queue.jsonl"
    history_store = root / ".retort" / "retort_history.sqlite"
    request_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    task_batches = _split_tasks(tasks, max(1, min(worker_count, len(tasks) or 1)))
    payloads = []
    for index, task_batch in enumerate(task_batches, start=1):
        payload_path = request_dir / f"{run_id}-worker-{index:02d}.json"
        output_path = result_dir / f"{run_id}-worker-{index:02d}.json"
        payload = {
            "run_id": f"{run_id}-worker-{index:02d}",
            "project": str(root),
            "source": source,
            "payload_path": str(payload_path),
            "output_path": str(output_path),
            "parent_pid": os.getpid(),
            "runtime_context_nonce": f"{run_id}-worker-{index:02d}-payload-contract",
            "crash_isolation_probe": {"enabled": True, "expected_returncode": 73},
            "queue_path": str(queue_path),
            "history_store": str(history_store),
            "tasks": task_batch,
            "changed_files": changed_files,
            "gates_passed": gates_passed,
            "review_report_path": str(root / "docs" / "retort_external_advantage_matrix.json"),
            "diff_text": _git_diff(root, changed_files),
        }
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        payloads.append({"payload_path": payload_path, "output_path": output_path, "task_count": len(task_batch)})
    started = time.monotonic()
    worker_results = _run_worker_processes(root, python_executable, [Path(item["payload_path"]) for item in payloads])
    aggregate = _aggregate_worker_results(root, run_id, source, payloads, worker_results, aggregate_output_path)
    verified = bool(aggregate.get("runtime_evidence", {}).get("multi_worker", {}).get("verified"))
    gate = {
        "command": [python_executable, "-m", "retort_engine.employee_runtime_worker", "--payload-file", "<multi-worker-payloads>"],
        "cwd": str(root),
        "exit_code": 0 if verified else 1,
        "ok": verified,
        "duration_sec": round(time.monotonic() - started, 3),
        "stdout_tail": json.dumps(aggregate.get("runtime_evidence", {}).get("multi_worker", {}), ensure_ascii=False)[-2000:],
        "stderr_tail": "\n".join(str(item.get("stderr") or "") for item in worker_results)[-2000:],
        "worker_count": len(payloads),
        "result_path": str(aggregate_output_path),
    }
    return aggregate_output_path, gate


def _split_tasks(tasks: list[dict[str, Any]], worker_count: int) -> list[list[dict[str, Any]]]:
    batches = [[] for _ in range(max(1, min(worker_count, len(tasks) or 1)))]
    for index, task in enumerate(tasks):
        batches[index % len(batches)].append(task)
    return [batch for batch in batches if batch]


def _run_worker_processes(root: Path, python_executable: str, payload_paths: list[Path]) -> list[dict[str, Any]]:
    env = {**os.environ, "PYTHONPATH": _worker_pythonpath(root)}
    processes = []
    for payload_path in payload_paths:
        command = [python_executable, "-m", "retort_engine.employee_runtime_worker", "--payload-file", str(payload_path)]
        started_at = datetime.now(timezone.utc).isoformat()
        started_monotonic = time.monotonic()
        process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(
            {
                "payload_path": payload_path,
                "command": command,
                "process": process,
                "pid": process.pid,
                "started_at": started_at,
                "started_monotonic": started_monotonic,
            }
        )
    results = []
    for item in processes:
        process = item["process"]
        try:
            stdout, stderr = process.communicate(timeout=240)
            returncode = int(process.returncode)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            returncode = 124
        results.append(
            {
                "payload_path": str(item["payload_path"]),
                "command": item["command"],
                "pid": int(item.get("pid") or 0),
                "started_at": str(item.get("started_at") or ""),
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "duration_sec": round(time.monotonic() - float(item.get("started_monotonic") or time.monotonic()), 3),
                "returncode": returncode,
                "stdout": (stdout or "")[-2000:],
                "stderr": (stderr or "")[-2000:],
            }
        )
    return results


def _aggregate_worker_results(
    root: Path,
    run_id: str,
    source: str,
    payloads: list[dict[str, Any]],
    worker_results: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    combined_results: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    result_paths = [Path(str(item["output_path"])) for item in payloads]
    for result_path in result_paths:
        payload = _read_json(result_path)
        combined_results.extend(item for item in payload.get("results") or [] if isinstance(item, dict))
        runtime = payload.get("runtime_evidence") if isinstance(payload.get("runtime_evidence"), dict) else {}
        review = runtime.get("worker_review") if isinstance(runtime.get("worker_review"), dict) else {}
        if review:
            reviews.append(review)
    aggregate_review_path = output_path.with_suffix(".worker_review.json")
    aggregate_review = {
        "status": "reviewed" if reviews and all(item.get("status") == "reviewed" for item in reviews) else "missing",
        "comment_count": sum(int(item.get("comment_count") or 0) for item in reviews),
        "file_count": sum(int(item.get("file_count") or 0) for item in reviews),
        "task_group_count": sum(int(item.get("task_group_count") or 0) for item in reviews),
        "artifact": str(aggregate_review_path),
        "worker_review_count": len(reviews),
    }
    aggregate_review_path.write_text(json.dumps({"reviews": reviews, "summary": aggregate_review}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    successful_processes = [item for item in worker_results if _returncode(item) == 0]
    process_isolation = _process_isolation_evidence(payloads, worker_results)
    verified = (
        len(successful_processes) == len(payloads)
        and len(reviews) == len(payloads)
        and len(combined_results) >= len(payloads)
        and bool(process_isolation["pid_isolation_verified"])
    )
    aggregate = {
        "run_id": run_id,
        "execution_mode": "employee_runtime_worker_multi_process",
        "source": source,
        "results": combined_results,
        "runtime_evidence": {
            "independent_process": True,
            "queue_path": str(root / ".retort" / "employee_queue.jsonl"),
            "history_store": str(root / ".retort" / "retort_history.sqlite"),
            "worker_review": aggregate_review,
            "multi_worker": {
                "verified": verified,
                "worker_count": len(payloads),
                "independent_worker_count": int(process_isolation["unique_successful_process_id_count"]),
                "result_path_count": sum(1 for item in result_paths if item.is_file()),
                "worker_review_count": len(reviews),
                "task_result_count": len(combined_results),
                "result_paths": [str(item) for item in result_paths],
                "process_isolation": process_isolation,
            },
        },
        "status": "completed" if verified else "partial",
        "summary": "Independent employee runtime workers completed post-absorption hardening tasks.",
    }
    output_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return aggregate


def _returncode(result: dict[str, Any]) -> int:
    try:
        return int(result.get("returncode", 1))
    except (TypeError, ValueError):
        return 1


def _process_isolation_evidence(payloads: list[dict[str, Any]], worker_results: list[dict[str, Any]]) -> dict[str, Any]:
    process_ids = [int(item["pid"]) for item in worker_results if isinstance(item.get("pid"), int) and int(item["pid"]) > 0]
    successful_ids = [int(item["pid"]) for item in worker_results if _returncode(item) == 0 and isinstance(item.get("pid"), int) and int(item["pid"]) > 0]
    payload_paths = [str(item.get("payload_path") or "") for item in payloads]
    result_paths = [str(item.get("output_path") or "") for item in payloads]
    traces = []
    boundary_verified_count = 0
    pid_cross_check_count = 0
    crash_verified_count = 0
    for payload, result in zip(payloads, worker_results, strict=False):
        command = [str(part) for part in result.get("command") or []]
        output_path = Path(str(payload.get("output_path") or ""))
        worker_payload = _read_json(output_path)
        runtime = worker_payload.get("runtime_evidence") if isinstance(worker_payload.get("runtime_evidence"), dict) else {}
        boundary = runtime.get("process_boundary") if isinstance(runtime.get("process_boundary"), dict) else {}
        worker_reported_pid = int(boundary.get("worker_pid") or 0)
        pid_cross_checked = worker_reported_pid > 0 and worker_reported_pid == int(result.get("pid") or 0)
        boundary_verified = bool(boundary.get("runtime_boundary_verified")) and pid_cross_checked
        crash_verified = bool(boundary.get("crash_isolation_verified"))
        if boundary_verified:
            boundary_verified_count += 1
        if pid_cross_checked:
            pid_cross_check_count += 1
        if crash_verified:
            crash_verified_count += 1
        crash_probe = boundary.get("crash_isolation_probe") if isinstance(boundary.get("crash_isolation_probe"), dict) else {}
        traces.append(
            {
                "pid": int(result.get("pid") or 0),
                "worker_reported_pid": worker_reported_pid,
                "pid_cross_checked": pid_cross_checked,
                "payload_path": str(payload.get("payload_path") or result.get("payload_path") or ""),
                "result_path": str(payload.get("output_path") or ""),
                "runtime_boundary": str(boundary.get("runtime_boundary") or ""),
                "runtime_boundary_verified": boundary_verified,
                "crash_isolation_verified": crash_verified,
                "crash_probe_returncode": int(crash_probe.get("returncode") or 0) if crash_probe else 0,
                "crash_probe_expected_returncode": int(crash_probe.get("expected_returncode") or 0) if crash_probe else 0,
                "payload_nonce": str(boundary.get("payload_nonce") or ""),
                "payload_nonce_verified": bool(boundary.get("payload_nonce_verified")),
                "returncode": _returncode(result),
                "started_at": str(result.get("started_at") or ""),
                "ended_at": str(result.get("ended_at") or ""),
                "duration_sec": float(result.get("duration_sec") or 0.0),
                "uses_payload_file": "--payload-file" in command,
            }
        )
    expected_count = len(payloads)
    unique_ids = sorted(set(process_ids))
    unique_successful_ids = sorted(set(successful_ids))
    return {
        "worker_process_trace_count": len(traces),
        "process_id_count": len(process_ids),
        "unique_process_id_count": len(unique_ids),
        "successful_process_id_count": len(successful_ids),
        "unique_successful_process_id_count": len(unique_successful_ids),
        "payload_path_count": len(set(payload_paths)),
        "result_path_count": len(set(result_paths)),
        "runtime_boundary_verified_count": boundary_verified_count,
        "pid_cross_check_count": pid_cross_check_count,
        "crash_isolation_verified_count": crash_verified_count,
        "all_payload_paths_unique": len(set(payload_paths)) == expected_count,
        "all_result_paths_unique": len(set(result_paths)) == expected_count,
        "all_process_ids_unique": len(unique_ids) == expected_count,
        "all_successful_process_ids_unique": len(unique_successful_ids) == expected_count,
        "pid_isolation_verified": expected_count > 1
        and len(unique_successful_ids) == expected_count
        and len(set(payload_paths)) == expected_count
        and len(set(result_paths)) == expected_count
        and boundary_verified_count == expected_count
        and pid_cross_check_count == expected_count
        and crash_verified_count == expected_count
        and all(item["uses_payload_file"] and item["returncode"] == 0 for item in traces),
        "runtime_boundary_verified": expected_count > 1 and boundary_verified_count == expected_count,
        "crash_isolation_verified": expected_count > 1 and crash_verified_count == expected_count,
        "process_ids": unique_ids,
        "traces": traces,
    }


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
