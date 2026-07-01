from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.devour_session import assessment_score, assessment_score_status


def run_proof_path(root: Path, run_id: str) -> Path:
    return root / ".retort" / "run_proofs" / f"{run_id}.json"


def build_absorption_run_proof(
    *,
    root: Path,
    source: str,
    external_path: Path | None,
    pre_assessment: dict[str, Any],
    external_assessment: dict[str, Any],
    own_assessment: dict[str, Any],
    tasks: list[dict[str, Any]],
    execution: dict[str, Any],
    branch_state: dict[str, Any],
    absorption_state: dict[str, Any],
    llm_review: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(execution.get("run_id") or "")
    metadata = own_assessment.get("metadata") if isinstance(own_assessment.get("metadata"), dict) else {}
    audit = metadata.get("capability_absorption_audit") if isinstance(metadata.get("capability_absorption_audit"), dict) else {}
    changed_files = [str(item) for item in execution.get("changed_files") or []]
    gates = [item for item in execution.get("gates") or [] if isinstance(item, dict)]
    code_graph_path = str(execution.get("code_graph_proof_path") or audit.get("latest_code_graph_proof_path") or "")
    code_graph = _read_json(Path(code_graph_path)) if code_graph_path else {}
    before_score = assessment_score(pre_assessment)
    after_score = assessment_score(own_assessment)
    proof = absorption_state.get("closed_loop_proof") if isinstance(absorption_state.get("closed_loop_proof"), dict) else {}
    flags = proof.get("flags") if isinstance(proof.get("flags"), dict) else {}
    final_llm = _final_llm_verdict(own_assessment, llm_review)
    core_change = _core_change_binding(changed_files, audit)
    test_increment = _test_increment_binding(audit)
    code_graph_binding = {
        "path": code_graph_path,
        "exists": bool(code_graph_path and Path(code_graph_path).is_file()),
        "run_id": str(code_graph.get("run_id") or run_id),
        "node_count": int(code_graph.get("node_count") or execution.get("code_graph_node_count") or 0),
        "edge_count": int(code_graph.get("edge_count") or execution.get("code_graph_edge_count") or 0),
        "changed_file_count": int(code_graph.get("changed_file_count") or 0),
    }
    return {
        "schema": "retort.absorption_run_proof.v1",
        "run_id": run_id,
        "status": _run_proof_status(execution, final_llm, core_change, test_increment, code_graph_binding),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "source": source,
        "external_path": "" if external_path is None else str(external_path),
        "score_binding": {
            "before_score": before_score,
            "external_score": assessment_score(external_assessment),
            "after_score": after_score,
            "score_delta": round(after_score - before_score, 1) if before_score is not None and after_score is not None else None,
            "before_status": assessment_score_status(pre_assessment),
            "external_status": assessment_score_status(external_assessment),
            "after_status": assessment_score_status(own_assessment),
        },
        "core_change_binding": core_change,
        "code_graph_binding": code_graph_binding,
        "test_increment_binding": test_increment,
        "llm_final_verdict": final_llm,
        "execution_binding": {
            "status": str(execution.get("status") or ""),
            "gates_passed": bool(execution.get("gates_passed")),
            "gate_passed_count": sum(1 for gate in gates if gate.get("ok")),
            "gate_count": len(gates),
            "changed_file_count": len(changed_files),
            "employee_results_path": str(execution.get("employee_results_path") or ""),
            "review_report_path": str(execution.get("review_report_path") or ""),
            "commit": str(execution.get("commit") or ""),
            "merge_commit": str(execution.get("merge_commit") or ""),
            "rollback_rehearsal": bool(execution.get("rollback_rehearsal")),
        },
        "branch_binding": branch_state,
        "closed_loop_binding": {
            "verified": bool(proof.get("verified")),
            "flags": flags,
            "missing": [str(item) for item in proof.get("missing") or []],
        },
        "task_binding": {
            "task_count": len(tasks),
            "task_ids": [str(task.get("task_id") or "") for task in tasks],
            "dimensions": sorted({str(task.get("dimension") or "") for task in tasks if task.get("dimension")}),
        },
    }


def write_absorption_run_proof(root: Path, proof: dict[str, Any]) -> Path:
    run_id = str(proof.get("run_id") or "run")
    path = run_proof_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    proof["path"] = str(path)
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def summarize_run_proof_for_session(proof: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(proof.get("run_id") or ""),
        "status": str(proof.get("status") or ""),
        "path": str(proof.get("path") or ""),
        "score_binding": proof.get("score_binding") if isinstance(proof.get("score_binding"), dict) else {},
        "core_change_binding": proof.get("core_change_binding") if isinstance(proof.get("core_change_binding"), dict) else {},
        "code_graph_binding": proof.get("code_graph_binding") if isinstance(proof.get("code_graph_binding"), dict) else {},
        "test_increment_binding": proof.get("test_increment_binding") if isinstance(proof.get("test_increment_binding"), dict) else {},
        "llm_final_verdict": proof.get("llm_final_verdict") if isinstance(proof.get("llm_final_verdict"), dict) else {},
    }


def _core_change_binding(changed_files: list[str], audit: dict[str, Any]) -> dict[str, Any]:
    behavior_source_files = [str(item) for item in audit.get("behavior_source_files") or []]
    behavior_test_files = [str(item) for item in audit.get("behavior_test_files") or []]
    generated_evidence_files = [str(item) for item in audit.get("generated_evidence_files") or []]
    core_files = behavior_source_files + behavior_test_files
    changed_count = len(changed_files)
    core_count = len(core_files)
    return {
        "changed_files": changed_files,
        "changed_file_count": changed_count,
        "core_behavior_files": core_files,
        "core_behavior_file_count": core_count,
        "core_behavior_change_ratio": round(core_count / changed_count, 3) if changed_count else 0.0,
        "behavior_source_files": behavior_source_files,
        "behavior_test_files": behavior_test_files,
        "generated_evidence_files": generated_evidence_files,
        "latest_changed_source_line_count": int(audit.get("latest_changed_source_line_count") or 0),
        "latest_changed_test_line_count": int(audit.get("latest_changed_test_line_count") or 0),
        "reason": str(audit.get("reason") or ""),
        "risk_level": str(audit.get("risk_level") or ""),
        "blockers": [str(item) for item in audit.get("blockers") or []],
    }


def _test_increment_binding(audit: dict[str, Any]) -> dict[str, Any]:
    behavior_test_files = [str(item) for item in audit.get("behavior_test_files") or []]
    line_count = int(audit.get("latest_changed_test_line_count") or 0)
    ratio = audit.get("latest_test_to_source_ratio")
    if ratio is None:
        ratio = audit.get("test_to_source_ratio")
    return {
        "test_files": behavior_test_files,
        "test_file_count": len(behavior_test_files),
        "test_line_count": line_count,
        "latest_test_to_source_ratio": ratio,
        "latest_test_to_source_ratio_status": str(audit.get("latest_test_to_source_ratio_status") or audit.get("test_to_source_ratio_status") or ""),
        "target": float(audit.get("latest_test_to_source_ratio_target") or 0.4),
    }


def _final_llm_verdict(own_assessment: dict[str, Any], llm_review: dict[str, Any]) -> dict[str, Any]:
    metadata = own_assessment.get("metadata") if isinstance(own_assessment.get("metadata"), dict) else {}
    dispatch = llm_review.get("dispatch") if isinstance(llm_review.get("dispatch"), dict) else {}
    scores = [item for item in own_assessment.get("scores") or [] if isinstance(item, dict)]
    return {
        "status": assessment_score_status(own_assessment),
        "score": assessment_score(own_assessment),
        "score_source": str(metadata.get("score_source") or "paibi_llm_pending"),
        "decision": str(metadata.get("llm_decision") or ""),
        "llm_task_id": str(metadata.get("llm_task_id") or dispatch.get("task_id") or ""),
        "llm_dispatch_status": str(dispatch.get("status") or llm_review.get("status") or ""),
        "scores": scores,
        "score_gate": metadata.get("llm_score_gate") if isinstance(metadata.get("llm_score_gate"), dict) else {},
        "record_policy": "只有排比 LLM 返回结构化分数时，最终评分才保留。",
    }


def _run_proof_status(execution: dict[str, Any], final_llm: dict[str, Any], core_change: dict[str, Any], test_increment: dict[str, Any], code_graph: dict[str, Any]) -> str:
    if execution.get("status") not in {"applied", "noop"}:
        return "execution_not_applied"
    if final_llm.get("status") == "paibi_llm_completed":
        return "bound_scored"
    if not code_graph.get("exists"):
        return "bound_missing_code_graph"
    if not core_change.get("core_behavior_file_count"):
        return "bound_missing_core_change"
    if not test_increment.get("test_file_count"):
        return "bound_missing_test_increment"
    if final_llm.get("status") == "paibi_llm_pending":
        return "bound_awaiting_llm"
    return "bound_needs_final_llm"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
