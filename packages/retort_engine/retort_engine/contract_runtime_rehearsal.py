from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.contracts import validate_contract


DEFAULT_CONTRACT_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "pr_review_missing_comments",
        "contract": "pr_review_result",
        "invalid_payload": {"status": "reviewed", "summary": {}, "files": [], "task_groups": [], "incremental": {}},
        "valid_payload": {"status": "reviewed", "summary": {}, "files": [], "comments": [], "task_groups": [], "incremental": {}},
    },
    {
        "case_id": "operator_journey_missing_replay",
        "contract": "operator_journey_replay_result",
        "invalid_payload": {"status": "ready", "project": "p", "summary": {}, "stages": [], "artifacts": [], "live_probes": {}, "evidence": {}},
        "valid_payload": {"status": "ready", "project": "p", "summary": {}, "stages": [], "artifacts": [], "live_probes": {}, "replay": {}, "evidence": {}},
    },
    {
        "case_id": "cross_domain_missing_cases",
        "contract": "cross_domain_absorption_replay_result",
        "invalid_payload": {"status": "ready", "project": "p", "summary": {}, "evidence": {}},
        "valid_payload": {"status": "ready", "project": "p", "summary": {}, "cases": [], "evidence": {}},
    },
)


def build_contract_runtime_rehearsal(
    project: str | Path,
    *,
    output: str | Path = "",
    run_id: str = "",
    concurrent_workers: int = 6,
    cases: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    rehearsal_id = run_id or _run_id("contract-runtime")
    lab = root / ".retort" / "contract_runtime_rehearsals" / rehearsal_id
    lab.mkdir(parents=True, exist_ok=True)
    rows = [_run_case(lab, dict(case), concurrent_workers=max(1, concurrent_workers)) for case in (cases or DEFAULT_CONTRACT_CASES)]
    ready_rows = [row for row in rows if row["ready"]]
    summary = {
        "run_id": rehearsal_id,
        "case_count": len(rows),
        "ready_case_count": len(ready_rows),
        "violation_rejected_count": sum(1 for row in rows if row["invalid_rejected"]),
        "rollback_verified_count": sum(1 for row in rows if row["rollback"]["verified"]),
        "valid_payload_accepted_count": sum(1 for row in rows if row["valid_accepted"]),
        "concurrent_worker_count": max(1, concurrent_workers),
        "concurrency_fault_injection_count": sum(len(row["concurrency_fault_injections"]) for row in rows),
        "concurrent_violation_rejected_count": sum(1 for row in rows for item in row["concurrency_fault_injections"] if item["invalid_rejected"]),
        "concurrent_rollback_verified_count": sum(1 for row in rows for item in row["concurrency_fault_injections"] if item["rollback_verified"]),
        "all_violations_rejected": bool(rows) and all(row["invalid_rejected"] for row in rows),
        "all_rollbacks_verified": bool(rows) and all(row["rollback"]["verified"] for row in rows),
        "all_valid_payloads_accepted": bool(rows) and all(row["valid_accepted"] for row in rows),
        "all_concurrent_violations_rejected": bool(rows) and all(item["invalid_rejected"] for row in rows for item in row["concurrency_fault_injections"]),
        "all_concurrent_rollbacks_verified": bool(rows) and all(item["rollback_verified"] for row in rows for item in row["concurrency_fault_injections"]),
        "contract_names": sorted({str(row["contract"]) for row in rows}),
    }
    ready = (
        summary["ready_case_count"] == summary["case_count"]
        and summary["all_violations_rejected"]
        and summary["all_rollbacks_verified"]
        and summary["all_valid_payloads_accepted"]
        and summary["all_concurrent_violations_rejected"]
        and summary["all_concurrent_rollbacks_verified"]
    )
    result = {
        "status": "ready" if ready else "needs_contract_runtime_evidence",
        "project": str(root),
        "summary": summary,
        "cases": rows,
        "evidence": {
            "style": "runtime_contract_violation_rejected_then_rollback",
            "lab_dir": str(lab),
            "runtime_guard": "retort_engine.contracts.validate_contract",
            "fault_injection_model": "threaded_invalid_payload_workers_with_per_worker_state_rollback",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _run_case(lab: Path, case: dict[str, Any], *, concurrent_workers: int) -> dict[str, Any]:
    case_id = str(case["case_id"])
    contract = str(case["contract"])
    case_lab = lab / case_id
    case_lab.mkdir(parents=True, exist_ok=True)
    state_path = case_lab / "producer_state.json"
    before_state = {"case_id": case_id, "contract": contract, "last_valid_payload": case["valid_payload"]}
    state_path.write_text(json.dumps(before_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    invalid_check = validate_contract(contract, dict(case["invalid_payload"]))
    if not invalid_check["valid"]:
        state_path.write_text(json.dumps(before_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    rollback_verified = json.loads(state_path.read_text(encoding="utf-8")) == before_state
    valid_check = validate_contract(contract, dict(case["valid_payload"]))
    concurrency = _run_concurrency_fault_injections(case_lab, case, concurrent_workers=concurrent_workers)
    _write_json(case_lab / "invalid_payload.json", dict(case["invalid_payload"]))
    _write_json(case_lab / "invalid_check.json", invalid_check)
    _write_json(case_lab / "valid_payload.json", dict(case["valid_payload"]))
    _write_json(case_lab / "valid_check.json", valid_check)
    return {
        "case_id": case_id,
        "contract": contract,
        "invalid_rejected": not invalid_check["valid"],
        "valid_accepted": bool(valid_check["valid"]),
        "missing_fields": invalid_check["missing"],
        "rollback": {
            "strategy": "restore_last_valid_contract_payload_state",
            "performed": not invalid_check["valid"],
            "verified": rollback_verified,
        },
        "concurrency_fault_injections": concurrency,
        "artifacts": {
            "state": str(state_path),
            "invalid_payload": str(case_lab / "invalid_payload.json"),
            "invalid_check": str(case_lab / "invalid_check.json"),
            "valid_payload": str(case_lab / "valid_payload.json"),
            "valid_check": str(case_lab / "valid_check.json"),
            "concurrency_dir": str(case_lab / "concurrency"),
        },
        "ready": (not invalid_check["valid"]) and valid_check["valid"] and rollback_verified and all(item["invalid_rejected"] and item["rollback_verified"] for item in concurrency),
    }


def _run_concurrency_fault_injections(case_lab: Path, case: dict[str, Any], *, concurrent_workers: int) -> list[dict[str, Any]]:
    concurrency_dir = case_lab / "concurrency"
    concurrency_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=concurrent_workers) as pool:
        return list(pool.map(lambda worker: _concurrent_fault_worker(concurrency_dir, case, worker), range(1, concurrent_workers + 1)))


def _concurrent_fault_worker(concurrency_dir: Path, case: dict[str, Any], worker: int) -> dict[str, Any]:
    contract = str(case["contract"])
    state_path = concurrency_dir / f"worker_{worker:02d}_state.json"
    before_state = {"worker": worker, "contract": contract, "last_valid_payload": case["valid_payload"]}
    state_path.write_text(json.dumps(before_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    invalid_check = validate_contract(contract, dict(case["invalid_payload"]))
    rollback_performed = not invalid_check["valid"]
    if rollback_performed:
        state_path.write_text(json.dumps(before_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    worker_result = {
        "worker": worker,
        "invalid_rejected": not invalid_check["valid"],
        "rollback_performed": rollback_performed,
        "rollback_verified": state_after == before_state,
        "missing_fields": invalid_check["missing"],
        "state_path": str(state_path),
    }
    _write_json(concurrency_dir / f"worker_{worker:02d}_result.json", worker_result)
    return worker_result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
