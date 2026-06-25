"""Manual audit sampling for autonomous auto-merge decisions.

Each autonomy phase must earn trust with evidence.  This sampler draws up to
100 auto-merge records per phase from the self-maintenance ledger, writes a
human review queue, and summarizes labeled false-positive rates when reviewers
append verdicts.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PHASES = ("phase_a", "phase_b", "phase_c", "phase_d")
DEFAULT_SAMPLE_SIZE = 100


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _ledger_path() -> Path:
    raw = (os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / "self_maintenance_loop_runs.jsonl"


def _audit_dir() -> Path:
    raw = (os.environ.get("MODSTORE_AUTO_MERGE_AUDIT_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _runtime_dir() / "auto_merge_audits"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _read_jsonl(path: Path, *, max_rows: int = 20000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
    except OSError:
        return []
    return rows[-max_rows:]


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _stable_id(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _policy_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("policy_decision")
    return value if isinstance(value, dict) else {}


def _merge_result(row: Dict[str, Any]) -> Dict[str, Any]:
    decision = _policy_decision(row)
    value = decision.get("merge_result")
    return value if isinstance(value, dict) else {}


def _changed_files(row: Dict[str, Any]) -> List[str]:
    result = _merge_result(row)
    files = result.get("changed_files")
    if isinstance(files, list):
        return [str(item) for item in files if str(item)]
    return []


def _is_auto_merge(row: Dict[str, Any]) -> bool:
    decision = _policy_decision(row)
    action = str(decision.get("action") or "")
    reason = str(decision.get("reason") or "")
    result = _merge_result(row)
    return bool(
        action == "auto_merged_low_risk"
        or action.startswith("auto_merged")
        or "auto_merge" in reason
        or result.get("reason") == "merged_low_risk_branch"
    )


def _phase_from_row(row: Dict[str, Any]) -> str:
    result = _merge_result(row)
    reason = str(result.get("reason") or _policy_decision(row).get("reason") or "").lower()
    files = "\n".join(_changed_files(row)).lower()
    if (
        result.get("safety_score_v3")
        or "v3" in reason
        or any(
            token in files
            for token in (
                "adaptive_release_controller",
                "autonomous_risk_gate",
                "auto_merge_audit_sampler",
                "human_uncertainty_queue",
                "kb_self_maintenance",
                "unified_autonomy_orchestrator",
            )
        )
    ):
        return "phase_d"
    if any(
        token in files
        for token in (
            "incident_team_orchestrator",
            "node_coordinator",
            "predictive_maintenance",
            "release_recovery_orchestrator",
            "incident_model_router",
        )
    ):
        return "phase_c"
    if (
        result.get("safety_score_v2")
        or "v2" in reason
        or any(
            token in files
            for token in (
                "employee_task_market",
                "employee_runtime_policy",
                "employee_health_scan",
                "employee_autonomy_service",
            )
        )
    ):
        return "phase_b"
    return "phase_a"


def _queue_path() -> Path:
    return _audit_dir() / "manual_review_queue.jsonl"


def _existing_queue_ids() -> set[str]:
    rows = _read_jsonl(_queue_path(), max_rows=50000)
    return {str(row.get("sample_id") or "") for row in rows if str(row.get("sample_id") or "")}


def _review_results_path() -> Path:
    raw = (os.environ.get("MODSTORE_AUTO_MERGE_AUDIT_RESULTS") or "").strip()
    return Path(raw).expanduser() if raw else _audit_dir() / "manual_review_results.jsonl"


def _load_review_results() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _read_jsonl(_review_results_path(), max_rows=50000):
        sample_id = str(row.get("sample_id") or "").strip()
        if sample_id:
            out[sample_id] = row
    return out


def _sample_rows(
    rows: Sequence[Dict[str, Any]], sample_size: int, seed: str
) -> List[Dict[str, Any]]:
    if len(rows) <= sample_size:
        return list(rows)
    rng = random.Random(seed)
    return rng.sample(list(rows), sample_size)


def _sample_item(row: Dict[str, Any], phase: str, run_id: str) -> Dict[str, Any]:
    result = _merge_result(row)
    decision = _policy_decision(row)
    sample_id = _stable_id(
        phase,
        row.get("run_id"),
        row.get("branch"),
        result.get("merge_commit_sha"),
        result.get("changed_files"),
    )
    return {
        "audit_questions": [
            "Was the auto-merge decision correct?",
            "Did the change stay inside the intended autonomy boundary?",
            "Did review/QA evidence support the merge?",
            "Would a human reviewer have blocked this change?",
        ],
        "branch": row.get("branch"),
        "changed_files": result.get("changed_files") or [],
        "decision_reason": decision.get("reason"),
        "merge_commit_sha": result.get("merge_commit_sha"),
        "phase": phase,
        "policy_scores": {
            "risk_score": result.get("risk_score"),
            "safety_score_v2": result.get("safety_score_v2"),
            "safety_score_v3": result.get("safety_score_v3"),
        },
        "review_status": "pending",
        "run_id": row.get("run_id"),
        "sample_id": sample_id,
        "sample_run_id": run_id,
        "schema_version": 1,
        "task_id": row.get("para_task_id") or row.get("task_id"),
        "ts": time.time(),
    }


def _metrics_for_phase(
    phase: str, items: Sequence[Dict[str, Any]], review_results: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    labeled = []
    false_positive = 0
    needs_policy_change = 0
    for item in items:
        result = review_results.get(str(item.get("sample_id") or ""))
        if not result:
            continue
        labeled.append(result)
        verdict = str(result.get("verdict") or "").strip().lower()
        if verdict in {"false_positive", "incorrect", "bad_merge", "fail", "reject"}:
            false_positive += 1
        if bool(result.get("needs_policy_change")):
            needs_policy_change += 1
    labeled_count = len(labeled)
    false_positive_rate = None if labeled_count == 0 else false_positive / labeled_count
    recommended_boundary = "hold"
    if labeled_count >= 30 and false_positive_rate is not None and false_positive_rate < 0.01:
        recommended_boundary = "expand"
    elif labeled_count >= 30 and false_positive_rate is not None and false_positive_rate >= 0.03:
        recommended_boundary = "contract"
    return {
        "false_positive_count": false_positive,
        "false_positive_rate": false_positive_rate,
        "labeled_count": labeled_count,
        "needs_policy_change_count": needs_policy_change,
        "pending_count": max(0, len(items) - labeled_count),
        "phase": phase,
        "recommended_trust_boundary": recommended_boundary,
        "sample_count": len(items),
    }


def run_auto_merge_audit_sampling_once(
    *,
    phases: Optional[Iterable[str]] = None,
    sample_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Create per-phase human audit samples and a management summary."""

    requested_phases = [
        str(item).strip().lower() for item in (phases or PHASES) if str(item).strip()
    ]
    requested_phases = [item for item in requested_phases if item in PHASES]
    if not requested_phases:
        requested_phases = list(PHASES)
    size = max(
        1, sample_size or _env_int("MODSTORE_AUTO_MERGE_AUDIT_SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE)
    )
    size = min(size, 100)
    rows = [row for row in _read_jsonl(_ledger_path()) if _is_auto_merge(row)]
    by_phase: Dict[str, List[Dict[str, Any]]] = {phase: [] for phase in requested_phases}
    for row in rows:
        phase = _phase_from_row(row)
        if phase in by_phase:
            by_phase[phase].append(row)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"audit-{stamp}-{_stable_id(stamp, len(rows))[:8]}"
    existing_ids = _existing_queue_ids()
    review_results = _load_review_results()
    summary: Dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ledger_path": str(_ledger_path()),
        "ok": True,
        "phase_metrics": {},
        "review_results_path": str(_review_results_path()),
        "run_id": run_id,
        "sample_size_per_phase": size,
        "schema_version": 1,
        "source": "phase_d_auto_merge_audit_sampler",
        "total_auto_merge_candidates": len(rows),
    }
    queue_rows: List[Dict[str, Any]] = []
    audit_dir = _audit_dir()
    for phase, candidates in by_phase.items():
        sample = _sample_rows(candidates, size, seed=f"{run_id}:{phase}")
        items = [_sample_item(row, phase, run_id) for row in sample]
        phase_path = audit_dir / f"{run_id}-{phase}.json"
        _write_json(
            phase_path,
            {
                "candidate_count": len(candidates),
                "items": items,
                "phase": phase,
                "run_id": run_id,
                "sample_count": len(items),
                "schema_version": 1,
            },
        )
        for item in items:
            if str(item.get("sample_id") or "") not in existing_ids:
                queue_rows.append(item)
        metrics = _metrics_for_phase(phase, items, review_results)
        metrics["candidate_count"] = len(candidates)
        metrics["sample_path"] = str(phase_path)
        summary["phase_metrics"][phase] = metrics
    _append_jsonl(_queue_path(), queue_rows)
    summary["new_queue_items"] = len(queue_rows)
    summary["queue_path"] = str(_queue_path())
    latest_path = audit_dir / "latest_summary.json"
    run_path = audit_dir / f"{run_id}-summary.json"
    _write_json(run_path, summary)
    _write_json(latest_path, summary)
    summary["summary_path"] = str(run_path)
    summary["latest_summary_path"] = str(latest_path)
    return summary


__all__ = ["PHASES", "run_auto_merge_audit_sampling_once"]
