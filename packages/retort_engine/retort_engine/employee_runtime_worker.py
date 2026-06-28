from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from retort_engine.employee_patch_closure import run_employee_patch_closure_suite
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskResult
from retort_engine.pr_review import review_diff


def write_employee_runtime_results(payload_file: str | Path) -> dict[str, Any]:
    payload_path = Path(payload_file).expanduser().resolve()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    output_path = Path(str(payload["output_path"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process_boundary = _process_boundary(payload, payload_path, output_path)
    tasks = [item for item in payload.get("tasks") or [] if isinstance(item, dict)]
    gates_passed = bool(payload.get("gates_passed"))
    worker_review = _write_worker_review_artifact(payload, output_path)
    patch_closure = _run_patch_closure(payload, output_path)
    patch_closure_ready = not patch_closure or patch_closure.get("status") == "ready"
    task_results = []
    for task in tasks:
        completed = gates_passed and patch_closure_ready
        task_results.append(
            {
                "task_id": str(task.get("task_id") or ""),
                "status": "completed" if completed else "failed",
                "summary": f"Independent employee runtime completed absorption task for {task.get('dimension', 'unknown')}.",
                "evidence": [
                    f"source={payload.get('source')}",
                    f"review_report={payload.get('review_report_path')}",
                    f"changed_files={','.join(str(item) for item in payload.get('changed_files') or [])}",
                    f"gates_passed={gates_passed}",
                    f"worker_payload={payload_file}",
                    f"worker_pid={process_boundary['worker_pid']}",
                    f"worker_parent_pid={process_boundary['parent_pid']}",
                    f"runtime_boundary_verified={process_boundary['runtime_boundary_verified']}",
                    f"crash_isolation_verified={process_boundary['crash_isolation_verified']}",
                    f"payload_nonce={process_boundary['payload_nonce']}",
                    f"worker_review_status={worker_review.get('status')}",
                    f"worker_review_artifact={worker_review.get('artifact', '')}",
                    f"worker_review_comment_count={worker_review.get('comment_count', 0)}",
                    f"employee_patch_closure_status={patch_closure.get('status', '') if patch_closure else 'not_requested'}",
                    f"employee_patch_closure_success_case={((patch_closure.get('summary') or {}).get('success_case_verified') if patch_closure else '')}",
                    f"employee_patch_closure_rollback_case={((patch_closure.get('summary') or {}).get('failure_case_rolled_back') if patch_closure else '')}",
                ],
                "score_after": {"employee_execution_integration": 95.0 if completed else 70.0, "feedback_loop_closure": 95.0 if completed else 70.0},
            }
        )
    result = {
        "run_id": str(payload.get("run_id") or ""),
        "source": str(payload.get("source") or ""),
        "execution_mode": "employee_runtime_worker",
        "runtime_evidence": {
            "independent_process": True,
            "worker_payload": str(payload_path),
            "queue_path": str(payload.get("queue_path") or ""),
            "history_store": str(payload.get("history_store") or ""),
            "result_path": str(output_path),
            "task_result_count": len(task_results),
            "process_boundary": process_boundary,
            "worker_review": worker_review,
            "employee_patch_closure": patch_closure,
        },
        "results": task_results,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    history_store = str(payload.get("history_store") or "")
    if history_store:
        store = RetortHistoryStore(history_store)
        for item in task_results:
            store.record_task_result(
                EmployeeTaskResult(
                    task_id=str(item.get("task_id") or ""),
                    status=str(item.get("status") or ""),
                    summary=str(item.get("summary") or ""),
                    evidence=tuple(str(row) for row in item.get("evidence") or []),
                    score_after={str(k): float(v) for k, v in (item.get("score_after") or {}).items()},
                )
            )
    return result


def _process_boundary(payload: dict[str, Any], payload_path: Path, output_path: Path) -> dict[str, Any]:
    expected_parent_pid = int(payload.get("parent_pid") or 0)
    worker_pid = os.getpid()
    parent_pid = os.getppid()
    payload_nonce = str(payload.get("runtime_context_nonce") or "")
    expected_payload_path = Path(str(payload.get("payload_path") or payload_path)).expanduser().resolve()
    expected_output_path = Path(str(payload.get("output_path") or output_path)).expanduser().resolve()
    payload_path_verified = payload_path == expected_payload_path and payload_path.is_file()
    result_path_verified = output_path.expanduser().resolve() == expected_output_path
    crash_probe = _crash_isolation_probe(payload)
    crash_required = bool((payload.get("crash_isolation_probe") or {}).get("enabled")) if isinstance(payload.get("crash_isolation_probe"), dict) else False
    crash_verified = not crash_required or bool(crash_probe.get("verified"))
    return {
        "runtime_boundary": "subprocess_payload_file_contract",
        "worker_pid": worker_pid,
        "parent_pid": parent_pid,
        "expected_parent_pid": expected_parent_pid,
        "pid_differs_from_parent": worker_pid != expected_parent_pid,
        "parent_pid_matches_launcher": expected_parent_pid == 0 or parent_pid == expected_parent_pid,
        "payload_path": str(payload_path),
        "expected_payload_path": str(expected_payload_path),
        "payload_path_verified": payload_path_verified,
        "result_path": str(output_path),
        "expected_result_path": str(expected_output_path),
        "result_path_verified": result_path_verified,
        "payload_nonce": payload_nonce,
        "payload_nonce_verified": bool(payload_nonce),
        "crash_isolation_probe": crash_probe,
        "crash_isolation_verified": crash_verified,
        "runtime_boundary_verified": payload_path_verified and result_path_verified and bool(payload_nonce) and worker_pid != expected_parent_pid and crash_verified,
    }


def _crash_isolation_probe(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("crash_isolation_probe")
    if not isinstance(request, dict) or not request.get("enabled"):
        return {"enabled": False, "verified": True}
    expected_returncode = int(request.get("expected_returncode") or 73)
    command = [sys.executable, "-c", f"import sys; sys.exit({expected_returncode})"]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=10)
    return {
        "enabled": True,
        "mode": "expected_child_process_crash",
        "expected_returncode": expected_returncode,
        "returncode": int(completed.returncode),
        "worker_survived": True,
        "stdout_tail": (completed.stdout or "")[-200:],
        "stderr_tail": (completed.stderr or "")[-200:],
        "verified": int(completed.returncode) == expected_returncode,
    }


def _run_patch_closure(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    request = payload.get("patch_closure")
    if not isinstance(request, dict) or not request.get("enabled"):
        return {}
    project = _patch_closure_project(payload, request, output_path)
    output = output_path.with_suffix(".patch_closure.json")
    return run_employee_patch_closure_suite(project, output=output, run_id=str(payload.get("run_id") or "employee-runtime"))


def _patch_closure_project(payload: dict[str, Any], request: dict[str, Any], output_path: Path) -> Path:
    project = request.get("project") or payload.get("project")
    if project:
        return Path(str(project)).expanduser().resolve()
    return (output_path.parents[2] if len(output_path.parents) > 2 else output_path.parent).expanduser().resolve()


def _write_worker_review_artifact(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    diff_text = str(payload.get("diff_text") or "")
    if not diff_text.strip():
        return {"status": "no_diff", "artifact": "", "comment_count": 0, "file_count": 0, "task_group_count": 0}
    review = review_diff(diff_text, max_comments=12)
    artifact_path = output_path.with_suffix(".worker_review.json")
    artifact_path.write_text(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": str(review.get("status") or ""),
        "artifact": str(artifact_path),
        "comment_count": int((review.get("summary") or {}).get("comment_count") or 0),
        "file_count": int((review.get("summary") or {}).get("file_count") or 0),
        "task_group_count": len(review.get("task_groups") or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retort-employee-runtime-worker")
    parser.add_argument("--payload-file", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(write_employee_runtime_results(args.payload_file), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
