from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskRecord, ImprovementTask


DEFAULT_DIMENSIONS = (
    "comparative_analysis_depth",
    "feedback_loop_closure",
    "operational_readiness",
    "product_operability",
    "architecture_depth",
)


def run_employee_scheduler_stress(project: str | Path, *, round_count: int = 10, tasks_per_round: int = 3, workers_per_round: int = 1) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    run_id = datetime.now(timezone.utc).strftime("scheduler-stress-%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    queue_path = root / ".retort" / "employee_queue.jsonl"
    history_path = root / ".retort" / "retort_history.sqlite"
    request_dir = root / ".retort" / "employee_runtime_requests"
    result_dir = root / ".retort" / "employee_results"
    request_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    store = RetortHistoryStore(history_path)
    rounds = []
    failed_process_count = 0
    process_invocation_count = 0
    expected_task_ids: list[str] = []
    worker_count = max(1, workers_per_round)
    worker_runs: list[dict[str, Any]] = []
    for round_index in range(1, max(1, round_count) + 1):
        tasks = [_stress_task(run_id, round_index, task_index) for task_index in range(1, max(1, tasks_per_round) + 1)]
        for task in tasks:
            expected_task_ids.append(str(task["task_id"]))
            _append_queue_record(queue_path, run_id, task)
            store.record_employee_task(_employee_task_record(run_id, task))
        payloads = []
        for worker_index, task_batch in enumerate(_split_tasks(tasks, worker_count), start=1):
            payload_path = request_dir / f"{run_id}-round-{round_index:02d}-worker-{worker_index:02d}.json"
            result_path = result_dir / f"{run_id}-round-{round_index:02d}-worker-{worker_index:02d}.json"
            payload = {
                "run_id": f"{run_id}-round-{round_index:02d}-worker-{worker_index:02d}",
                "source": "employee_scheduler_stress",
                "tasks": task_batch,
                "gates_passed": True,
                "changed_files": ["retort_engine/pr_review.py", "retort_engine/task_prioritization.py", "retort_engine/employee_scheduler_stress.py"],
                "review_report_path": str(root / "docs" / "retort_task_prioritization_report.json"),
                "diff_text": _stress_diff(round_index, worker_index),
                "queue_path": str(queue_path),
                "history_store": str(history_path),
                "output_path": str(result_path),
            }
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            payloads.append({"worker_index": worker_index, "task_count": len(task_batch), "payload_path": payload_path, "result_path": result_path})
        processes = _run_workers(root, [Path(item["payload_path"]) for item in payloads])
        process_invocation_count += len(processes)
        payload_results = []
        for payload_info, process in zip(payloads, processes, strict=True):
            result_path = Path(payload_info["result_path"])
            worker_run = {
                "round_index": round_index,
                "worker_index": payload_info["worker_index"],
                "task_count": payload_info["task_count"],
                "payload_path": str(payload_info["payload_path"]),
                "result_path": str(result_path),
                "process": process,
                "result_exists": result_path.is_file(),
            }
            worker_runs.append(worker_run)
            payload_results.append(worker_run)
        failed_process_count += sum(1 for item in payload_results if item["process"]["returncode"] != 0 or not item["result_exists"])
        rounds.append(
            {
                "round_index": round_index,
                "task_count": len(tasks),
                "worker_count": len(payload_results),
                "workers": payload_results,
                "round_completed": all(item["result_exists"] for item in payload_results),
            }
        )
    result_task_ids = _result_task_ids(result_dir, run_id)
    history_task_ids = _history_task_ids(history_path)
    missing_result_ids = sorted(set(expected_task_ids) - set(result_task_ids))
    missing_history_ids = sorted(set(expected_task_ids) - set(history_task_ids))
    summary = {
        "run_id": run_id,
        "round_count": len(rounds),
        "tasks_per_round": max(1, tasks_per_round),
        "workers_per_round": worker_count,
        "queued_task_count": len(expected_task_ids),
        "completed_result_count": len(set(result_task_ids) & set(expected_task_ids)),
        "history_task_result_count": len(set(history_task_ids) & set(expected_task_ids)),
        "process_invocation_count": process_invocation_count,
        "failed_process_count": failed_process_count,
        "missing_result_count": len(missing_result_ids),
        "missing_history_count": len(missing_history_ids),
        "unique_task_id_count": len(set(expected_task_ids)),
        "all_rounds_completed": all(item["round_completed"] for item in rounds),
        "independent_process_verified": process_invocation_count == len(worker_runs) and all("-c" in (item["process"].get("command") or []) for item in worker_runs),
        "concurrent_workers_verified": worker_count > 1 and process_invocation_count == len(worker_runs) and all(item["result_exists"] for item in worker_runs),
        "queue_result_history_consistent": not missing_result_ids and not missing_history_ids,
    }
    status = (
        "ready"
        if summary["round_count"] >= 10
        and summary["queued_task_count"] >= 30
        and summary["failed_process_count"] == 0
        and summary["queue_result_history_consistent"]
        and (worker_count == 1 or summary["concurrent_workers_verified"])
        else "needs_more_evidence"
    )
    return {
        "status": status,
        "project": str(root),
        "summary": summary,
        "rounds": rounds,
        "missing_result_ids": missing_result_ids,
        "missing_history_ids": missing_history_ids,
        "evidence": {
            "queue_path": str(queue_path),
            "history_store": str(history_path),
            "employee_results_dir": str(result_dir),
            "worker": "retort_engine.employee_runtime_worker",
            "launch_mode": "concurrent_popen" if worker_count > 1 else "single_process_per_round",
        },
    }


def _stress_task(run_id: str, round_index: int, task_index: int) -> dict[str, Any]:
    dimension = DEFAULT_DIMENSIONS[(round_index + task_index - 2) % len(DEFAULT_DIMENSIONS)]
    task_id = f"{run_id}-r{round_index:02d}-t{task_index:02d}"
    return {
        "task_id": task_id,
        "title": f"stress verify {dimension} round {round_index}",
        "dimension": dimension,
        "why": "Prove employee runtime can repeatedly dispatch, complete, and record Retort absorption follow-up tasks.",
        "action": "Run independent worker and write queue/result/history evidence.",
        "acceptance": "Task appears in queue, employee result, and history with completed status.",
        "owner_hint": "employee-runtime",
        "priority": "P1",
    }


def _employee_task_record(run_id: str, task: dict[str, Any]) -> EmployeeTaskRecord:
    improvement = ImprovementTask(
        task_id=str(task["task_id"]),
        title=str(task["title"]),
        dimension=str(task["dimension"]),
        why=str(task["why"]),
        action=str(task["action"]),
        acceptance=str(task["acceptance"]),
        owner_hint=str(task["owner_hint"]),
        priority=str(task["priority"]),
    )
    return EmployeeTaskRecord(queue_id=str(uuid.uuid4()), task=improvement, source=run_id, status="executing")


def _append_queue_record(queue_path: Path, run_id: str, task: dict[str, Any]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"queue_id": str(uuid.uuid4()), "run_id": run_id, "source": "employee_scheduler_stress", "status": "executing", "task": task}
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _split_tasks(tasks: list[dict[str, Any]], worker_count: int) -> list[list[dict[str, Any]]]:
    batches = [[] for _ in range(max(1, min(worker_count, len(tasks) or 1)))]
    for index, task in enumerate(tasks):
        batches[index % len(batches)].append(task)
    return [batch for batch in batches if batch]


def _run_workers(root: Path, payload_paths: list[Path]) -> list[dict[str, Any]]:
    if len(payload_paths) <= 1:
        return [_run_worker(root, payload_paths[0])] if payload_paths else []
    package_root, env = _worker_runtime_env()
    processes = []
    for payload_path in payload_paths:
        command = _worker_command(package_root, payload_path)
        processes.append({"payload_path": payload_path, "command": command, "process": subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)})
    results = []
    for item in processes:
        process = item["process"]
        try:
            stdout, stderr = process.communicate(timeout=120)
            returncode = int(process.returncode)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            returncode = 124
        results.append({"command": item["command"], "returncode": returncode, "stdout": (stdout or "")[-2000:], "stderr": (stderr or "")[-2000:]})
    return results


def _run_worker(root: Path, payload_path: Path) -> dict[str, Any]:
    package_root, env = _worker_runtime_env()
    command = _worker_command(package_root, payload_path)
    try:
        completed = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "returncode": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "timeout"}
    return {"command": command, "returncode": completed.returncode, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]}


def _worker_runtime_env() -> tuple[str, dict[str, str]]:
    package_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    return package_root, env


def _worker_command(package_root: str, payload_path: Path) -> list[str]:
    worker_code = f"import sys; sys.path.insert(0, {package_root!r}); from retort_engine.employee_runtime_worker import main; raise SystemExit(main())"
    return [sys.executable, "-c", worker_code, "--payload-file", str(payload_path)]


def _stress_diff(round_index: int, worker_index: int = 1) -> str:
    path = f"stress/round_{round_index:02d}_worker_{worker_index:02d}.py"
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1,3 @@\n"
        f"+# TODO: verify employee stress round {round_index} worker {worker_index}\n"
        f"+ROUND_TOKEN_{round_index}_{worker_index} = \"redacted-in-test\"\n"
        f"+print(\"stress round {round_index} worker {worker_index}\")\n"
    )


def _result_task_ids(result_dir: Path, run_id: str) -> list[str]:
    task_ids: list[str] = []
    for path in sorted(result_dir.glob(f"{run_id}-round-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("results") or []:
            if isinstance(item, dict) and item.get("status") == "completed":
                task_ids.append(str(item.get("task_id") or ""))
    return task_ids


def _history_task_ids(history_path: Path) -> list[str]:
    if not history_path.is_file():
        return []
    with sqlite3.connect(history_path) as conn:
        rows = conn.execute("SELECT payload_json FROM task_results").fetchall()
    task_ids: list[str] = []
    for (payload_json,) in rows:
        try:
            payload = json.loads(str(payload_json))
        except json.JSONDecodeError:
            continue
        task_ids.append(str(payload.get("task_id") or ""))
    return task_ids
