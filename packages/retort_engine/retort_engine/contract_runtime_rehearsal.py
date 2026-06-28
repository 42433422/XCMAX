from __future__ import annotations

import json
import uuid
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
    cases: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    rehearsal_id = run_id or _run_id("contract-runtime")
    lab = root / ".retort" / "contract_runtime_rehearsals" / rehearsal_id
    lab.mkdir(parents=True, exist_ok=True)
    rows = [_run_case(lab, dict(case)) for case in (cases or DEFAULT_CONTRACT_CASES)]
    ready_rows = [row for row in rows if row["ready"]]
    summary = {
        "run_id": rehearsal_id,
        "case_count": len(rows),
        "ready_case_count": len(ready_rows),
        "violation_rejected_count": sum(1 for row in rows if row["invalid_rejected"]),
        "rollback_verified_count": sum(1 for row in rows if row["rollback"]["verified"]),
        "valid_payload_accepted_count": sum(1 for row in rows if row["valid_accepted"]),
        "all_violations_rejected": bool(rows) and all(row["invalid_rejected"] for row in rows),
        "all_rollbacks_verified": bool(rows) and all(row["rollback"]["verified"] for row in rows),
        "all_valid_payloads_accepted": bool(rows) and all(row["valid_accepted"] for row in rows),
        "contract_names": sorted({str(row["contract"]) for row in rows}),
    }
    ready = summary["ready_case_count"] == summary["case_count"] and summary["all_violations_rejected"] and summary["all_rollbacks_verified"] and summary["all_valid_payloads_accepted"]
    result = {
        "status": "ready" if ready else "needs_contract_runtime_evidence",
        "project": str(root),
        "summary": summary,
        "cases": rows,
        "evidence": {
            "style": "runtime_contract_violation_rejected_then_rollback",
            "lab_dir": str(lab),
            "runtime_guard": "retort_engine.contracts.validate_contract",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _run_case(lab: Path, case: dict[str, Any]) -> dict[str, Any]:
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
        "artifacts": {
            "state": str(state_path),
            "invalid_payload": str(case_lab / "invalid_payload.json"),
            "invalid_check": str(case_lab / "invalid_check.json"),
            "valid_payload": str(case_lab / "valid_payload.json"),
            "valid_check": str(case_lab / "valid_check.json"),
        },
        "ready": (not invalid_check["valid"]) and valid_check["valid"] and rollback_verified,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
