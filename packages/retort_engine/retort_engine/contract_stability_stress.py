from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from retort_engine.contract_runtime_rehearsal import build_contract_runtime_rehearsal


def build_contract_stability_stress(
    project: str | Path,
    *,
    rounds: int = 2,
    concurrent_workers: int = 120,
    output: str | Path = "",
) -> dict[str, Any]:
    """Run repeated high-concurrency contract rejection and rollback rehearsals."""
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    normalized_rounds = max(2, rounds)
    normalized_workers = max(101, concurrent_workers)
    runs = [
        build_contract_runtime_rehearsal(
            root,
            run_id=f"contract-stability-round-{index:02d}",
            concurrent_workers=normalized_workers,
        )
        for index in range(1, normalized_rounds + 1)
    ]
    run_summaries = [run.get("summary") if isinstance(run.get("summary"), dict) else {} for run in runs]
    total_faults = sum(int(summary.get("concurrency_fault_injection_count") or 0) for summary in run_summaries)
    total_rejected = sum(int(summary.get("concurrent_violation_rejected_count") or 0) for summary in run_summaries)
    total_rollbacks = sum(int(summary.get("concurrent_rollback_verified_count") or 0) for summary in run_summaries)
    summary = {
        "round_count": len(runs),
        "ready_round_count": sum(1 for run in runs if run.get("status") == "ready"),
        "concurrent_worker_count": normalized_workers,
        "concurrency_floor": 100,
        "concurrency_floor_exceeded": normalized_workers > 100,
        "total_fault_injection_count": total_faults,
        "total_concurrent_violation_rejected_count": total_rejected,
        "total_concurrent_rollback_verified_count": total_rollbacks,
        "state_leak_count": total_faults - min(total_rejected, total_rollbacks),
        "all_rounds_rejected_violations": all(summary.get("all_concurrent_violations_rejected") is True for summary in run_summaries),
        "all_rounds_verified_rollbacks": all(summary.get("all_concurrent_rollbacks_verified") is True for summary in run_summaries),
        "all_rounds_valid_payloads_accepted": all(summary.get("all_valid_payloads_accepted") is True for summary in run_summaries),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["round_count"] >= 2
        and summary["ready_round_count"] == summary["round_count"]
        and summary["concurrency_floor_exceeded"]
        and summary["state_leak_count"] == 0
        and summary["all_rounds_rejected_violations"]
        and summary["all_rounds_verified_rollbacks"]
        and summary["all_rounds_valid_payloads_accepted"]
    )
    result = {
        "status": "ready" if ready else "needs_contract_stability_evidence",
        "project": str(root),
        "summary": summary,
        "runs": [
            {
                "index": index,
                "status": run.get("status", ""),
                "summary": run.get("summary", {}),
                "evidence": run.get("evidence", {}),
            }
            for index, run in enumerate(runs, start=1)
        ],
        "evidence": {
            "style": "repeated_120_worker_contract_fault_injection",
            "runtime_guard": "retort_engine.contracts.validate_contract",
            "fault_model": "threaded_invalid_payload_workers_with_per_worker_state_rollback",
            "acceptance": ">100 concurrent workers across repeated rounds with zero state leaks",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result
