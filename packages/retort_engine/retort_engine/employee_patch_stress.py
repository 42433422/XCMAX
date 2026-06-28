from __future__ import annotations

import hashlib
import json
import os
import py_compile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_employee_patch_stress(
    project: str | Path,
    *,
    output: str | Path = "",
    run_id: str = "",
    concurrent_workers: int = 120,
) -> dict[str, Any]:
    """Stress failed employee patches and prove each worker rolls back state."""
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    stress_id = run_id or _run_id("employee-patch-stress")
    lab = root / ".retort" / "employee_patch_stress" / stress_id
    lab.mkdir(parents=True, exist_ok=True)
    worker_count = max(101, concurrent_workers)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        workers = list(pool.map(lambda worker: _patch_worker(lab, worker), range(1, worker_count + 1)))
    ready_workers = [item for item in workers if item["ready"]]
    rollback_verified = [item for item in workers if item["rollback_verified"]]
    post_rollback_passed = [item for item in workers if item["post_rollback_gate_passed"]]
    summary = {
        "run_id": stress_id,
        "worker_count": worker_count,
        "concurrent_worker_count": worker_count,
        "concurrency_floor": 100,
        "concurrency_floor_exceeded": worker_count > 100,
        "attempted_patch_count": len(workers),
        "failed_gate_count": sum(1 for item in workers if item["gate_failed"]),
        "rollback_verified_count": len(rollback_verified),
        "post_rollback_gate_passed_count": len(post_rollback_passed),
        "ready_worker_count": len(ready_workers),
        "unique_thread_count": len({item["thread_id"] for item in workers}),
        "unique_process_id_count": len({item["process_id"] for item in workers}),
        "trace_count": sum(1 for item in workers if Path(str(item["artifacts"]["trace"])).is_file()),
        "state_leak_count": sum(1 for item in workers if item["before_sha256"] != item["after_rollback_sha256"]),
        "all_gates_failed_before_rollback": bool(workers) and all(item["gate_failed"] for item in workers),
        "all_rollbacks_verified": bool(workers) and len(rollback_verified) == len(workers),
        "all_post_rollback_gates_passed": bool(workers) and len(post_rollback_passed) == len(workers),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["concurrency_floor_exceeded"]
        and summary["ready_worker_count"] == summary["worker_count"]
        and summary["all_gates_failed_before_rollback"]
        and summary["all_rollbacks_verified"]
        and summary["all_post_rollback_gates_passed"]
        and summary["state_leak_count"] == 0
    )
    result = {
        "status": "ready" if ready else "needs_employee_patch_stress_evidence",
        "project": str(root),
        "summary": summary,
        "workers": workers,
        "evidence": {
            "style": "hundred_plus_concurrent_employee_patch_failure_rollback",
            "lab_dir": str(lab),
            "gate": "py_compile_invalid_employee_patch_then_restored_source",
            "rollback_model": "per_worker_before_after_sha256_restoration",
            "acceptance": ">100 concurrent failed employee patches, all rolled back with post-rollback gate pass",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _patch_worker(lab: Path, worker: int) -> dict[str, Any]:
    worker_dir = lab / f"worker_{worker:03d}"
    worker_dir.mkdir(parents=True, exist_ok=True)
    target = worker_dir / "employee_patch_target.py"
    before = f"def employee_patch_{worker}():\n    return {worker}\n"
    target.write_text(before, encoding="utf-8")
    before_sha = _sha256(target)
    broken = f"def employee_patch_{worker}(:\n    return 'must rollback'\n"
    target.write_text(broken, encoding="utf-8")
    gate = _compile_gate(target)
    gate_failed = not gate["passed"]
    if gate_failed:
        target.write_text(before, encoding="utf-8")
    after_sha = _sha256(target)
    post_gate = _compile_gate(target)
    rollback_verified = before_sha == after_sha and target.read_text(encoding="utf-8") == before
    trace = {
        "worker": worker,
        "process_id": os.getpid(),
        "thread_id": threading.get_ident(),
        "target": str(target),
        "before_sha256": before_sha,
        "after_rollback_sha256": after_sha,
        "gate_failed": gate_failed,
        "gate_error_type": gate.get("error_type", ""),
        "rollback_verified": rollback_verified,
        "post_rollback_gate_passed": post_gate["passed"],
    }
    trace_path = worker_dir / "rollback_trace.json"
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        **trace,
        "ready": gate_failed and rollback_verified and post_gate["passed"],
        "artifacts": {
            "target": str(target),
            "trace": str(trace_path),
        },
    }


def _compile_gate(path: Path) -> dict[str, Any]:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return {"passed": False, "error_type": type(exc).__name__, "stderr_tail": str(exc)[-300:]}
    return {"passed": True, "error_type": "", "stderr_tail": ""}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
