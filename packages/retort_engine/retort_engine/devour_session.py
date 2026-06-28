from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def build_devour_session(
    *,
    source: str,
    external_path: Path | None,
    pre_assessment: dict[str, Any],
    external_assessment: dict[str, Any],
    own_assessment: dict[str, Any],
    tasks: list[dict[str, str]],
    execution: dict[str, Any],
    branch_state: dict[str, Any],
    absorption_state: dict[str, Any],
    llm_review: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": _devour_session_status(execution, own_assessment),
        "source": source,
        "stage_order": ["pre_dual_review", "overlap_comparison", "absorption_execution", "improvement_proof", "final_self_review"],
        "pre_dual_review": {
            "status": "ready",
            "context_policy": "isolated_before_absorption",
            "panels": [
                _assessment_panel("own_before", "主项目吞噬前深评", pre_assessment, source=str(pre_assessment.get("project") or "")),
                _assessment_panel("external", "外部项目深评", external_assessment, source=source),
            ],
        },
        "overlap_comparison": _overlap_comparison(source, external_path, tasks),
        "absorption_execution": {
            "status": str(execution.get("status") or "not_run"),
            "summary": str(execution.get("summary") or ""),
            "changed_files": [str(item) for item in execution.get("changed_files") or []],
            "gates": [item for item in execution.get("gates") or [] if isinstance(item, dict)],
            "branch": branch_state,
            "tasks": tasks,
        },
        "improvement_proof": _improvement_proof(pre_assessment, own_assessment, execution, absorption_state),
        "final_self_review": _final_self_review(own_assessment, llm_review),
    }


def assessment_score(assessment: dict[str, Any]) -> float | None:
    scores = assessment.get("scores") if isinstance(assessment, dict) else []
    if not isinstance(scores, list):
        return None
    preferred = ("calibrated_overall", "product_level", "retort_product_maturity")
    for dimension in preferred:
        for score in scores:
            if isinstance(score, dict) and score.get("dimension") == dimension:
                try:
                    return round(float(score.get("value")), 1)
                except (TypeError, ValueError):
                    return None
    return None


def assessment_file_count(assessment: dict[str, Any]) -> int:
    evidence = assessment.get("evidence") if isinstance(assessment, dict) else []
    if not isinstance(evidence, list):
        return 0
    for item in evidence:
        match = re.match(r"source_files=(\d+)", str(item))
        if match:
            return int(match.group(1))
    return 0


def assessment_score_status(assessment: dict[str, Any]) -> str:
    metadata = assessment.get("metadata") if isinstance(assessment.get("metadata"), dict) else {}
    source = str(metadata.get("score_source") or "")
    if assessment_score(assessment) is not None and source == "paibi_llm":
        return "paibi_llm_completed"
    if assessment_score(assessment) is not None:
        return "score_available"
    if source == "paibi_llm_pending":
        return "paibi_llm_pending"
    if source in {"paibi_llm_blocked", "paibi_llm_required_but_disabled"}:
        return "paibi_llm_blocked"
    if source == "paibi_llm_unavailable":
        return "paibi_llm_unavailable"
    if source == "external_evidence_only":
        return "external_evidence_collected_needs_llm"
    if source == "unavailable_external_project":
        return "external_project_unavailable"
    return "paibi_llm_required_not_scored"


def _devour_session_status(execution: dict[str, Any], own_assessment: dict[str, Any]) -> str:
    if assessment_score(own_assessment) is not None:
        return "final_deep_review_scored"
    status = assessment_score_status(own_assessment)
    if status == "paibi_llm_pending" and execution.get("status") in {"applied", "noop"}:
        return "absorbed_awaiting_final_llm_score"
    if status in {"paibi_llm_blocked", "paibi_llm_unavailable"}:
        return "final_deep_review_blocked"
    if execution.get("status") in {"applied", "noop"}:
        return "absorbed_awaiting_final_llm_score"
    if execution.get("status") in {"failed", "timeout"}:
        return "absorption_execution_failed"
    return "pre_review_ready"


def _assessment_panel(role: str, title: str, assessment: dict[str, Any], *, source: str) -> dict[str, Any]:
    metadata = assessment.get("metadata") if isinstance(assessment.get("metadata"), dict) else {}
    scores = [item for item in assessment.get("scores") or [] if isinstance(item, dict)]
    return {
        "role": role,
        "title": title,
        "source": source,
        "project": str(assessment.get("project") or source),
        "score": assessment_score(assessment),
        "score_status": assessment_score_status(assessment),
        "score_source": str(metadata.get("score_source") or metadata.get("score_authority") or "unknown"),
        "score_count": len(scores),
        "file_count": assessment_file_count(assessment),
        "evidence_highlights": _evidence_highlights(assessment),
        "feature_highlights": _feature_highlights(metadata),
        "llm_task_id": str(metadata.get("llm_task_id") or ((assessment.get("llm_review") or {}).get("dispatch") or {}).get("task_id") or ""),
    }


def _evidence_highlights(assessment: dict[str, Any], *, limit: int = 8) -> list[str]:
    evidence = [str(item) for item in assessment.get("evidence") or []]
    priority_prefixes = (
        "source_files=",
        "test_functions=",
        "git_tracking_state=",
        "lint=",
        "test=",
        "closed_loop_verified=",
        "closed_loop_missing=",
        "capability_absorption_local_score_removed=",
        "capability_absorption_risk_level=",
        "capability_absorption_blockers=",
        "behavior_source_file_count=",
        "behavior_test_file_count=",
        "test_to_source_ratio=",
        "employee_execution_mode=",
    )
    picked: list[str] = []
    for prefix in priority_prefixes:
        picked.extend(item for item in evidence if item.startswith(prefix) and item not in picked)
    picked.extend(item for item in evidence if item not in picked)
    return picked[:limit]


def _feature_highlights(metadata: dict[str, Any], *, limit: int = 6) -> list[str]:
    features = metadata.get("features") if isinstance(metadata.get("features"), dict) else {}
    return [str(key) for key, value in features.items() if value][:limit]


def _overlap_comparison(source: str, external_path: Path | None, tasks: list[dict[str, str]]) -> dict[str, Any]:
    profile = external_project_profile(external_path)
    signals = [
        label
        for key, label in (
            ("review_pipeline", "审查流水线"),
            ("file_grouping", "文件/差异分组"),
            ("benchmarking", "质量基准"),
            ("plugin_surface", "CLI/插件入口"),
        )
        if profile.get(key)
    ]
    dimensions = sorted({str(task.get("dimension") or "") for task in tasks if task.get("dimension")})
    return {
        "status": "depth_overlap_found" if tasks else "no_overlap_depth_found",
        "source": source,
        "depth_policy": "只吸收与 Retort 当前吸收、评估、证据闭环重合的深度，不扩主线广度。",
        "external_depth_signals": signals,
        "overlap_dimensions": dimensions,
        "absorb_targets": [
            {
                "title": str(task.get("title") or ""),
                "dimension": str(task.get("dimension") or ""),
                "priority": str(task.get("priority") or ""),
                "why": str(task.get("why") or ""),
            }
            for task in tasks
        ],
        "deferred_breadth": ["非重合方向暂不进入 Retort 主线", "可上架为未来 AI 员工或市场候选"],
    }


def _improvement_proof(pre_assessment: dict[str, Any], own_assessment: dict[str, Any], execution: dict[str, Any], absorption_state: dict[str, Any]) -> dict[str, Any]:
    before_score = assessment_score(pre_assessment)
    after_score = assessment_score(own_assessment)
    changed_files = [str(item) for item in execution.get("changed_files") or []]
    gates = [item for item in execution.get("gates") or [] if isinstance(item, dict)]
    proof = absorption_state.get("closed_loop_proof") if isinstance(absorption_state.get("closed_loop_proof"), dict) else {}
    flags = proof.get("flags") if isinstance(proof.get("flags"), dict) else {}
    audit = (own_assessment.get("metadata") or {}).get("capability_absorption_audit") if isinstance(own_assessment.get("metadata"), dict) else {}
    if not isinstance(audit, dict):
        audit = {}
    return {
        "status": _improvement_proof_status(execution, flags),
        "before_score": before_score,
        "after_score": after_score,
        "score_delta": round(after_score - before_score, 1) if before_score is not None and after_score is not None else None,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "gate_passed_count": sum(1 for gate in gates if gate.get("ok")),
        "gate_count": len(gates),
        "closed_loop_flags": flags,
        "missing_closed_loop": [str(item) for item in proof.get("missing") or []],
        "behavior_source_files": [str(item) for item in audit.get("behavior_source_files") or []],
        "behavior_test_files": [str(item) for item in audit.get("behavior_test_files") or []],
        "support_behavior_source_files": [str(item) for item in audit.get("support_behavior_source_files") or []],
        "support_behavior_test_files": [str(item) for item in audit.get("support_behavior_test_files") or []],
        "generated_evidence_files": [str(item) for item in audit.get("generated_evidence_files") or []],
        "generated_only": bool(audit.get("generated_only")),
        "capability_absorption_local_score_removed": bool(audit.get("local_score_removed", True)),
        "capability_absorption_status": audit.get("status"),
        "capability_absorption_risk_level": audit.get("risk_level"),
        "capability_absorption_blockers": [str(item) for item in audit.get("blockers") or []],
        "test_to_source_ratio": audit.get("test_to_source_ratio"),
        "reason": str(audit.get("reason") or ""),
    }


def _improvement_proof_status(execution: dict[str, Any], flags: dict[str, Any]) -> str:
    if execution.get("status") in {"failed", "timeout"}:
        return "failed"
    if flags and all(bool(value) for value in flags.values()):
        return "five_proofs_verified"
    if execution.get("status") in {"applied", "noop"} and bool(execution.get("gates_passed")):
        return "execution_and_gates_verified"
    if execution.get("status") in {"applied", "noop"}:
        return "execution_verified_needs_gates_or_merge"
    return "pending_execution"


def _final_self_review(own_assessment: dict[str, Any], llm_review: dict[str, Any]) -> dict[str, Any]:
    metadata = own_assessment.get("metadata") if isinstance(own_assessment.get("metadata"), dict) else {}
    dispatch = llm_review.get("dispatch") if isinstance(llm_review.get("dispatch"), dict) else {}
    return {
        "status": assessment_score_status(own_assessment),
        "score": assessment_score(own_assessment),
        "score_source": str(metadata.get("score_source") or "paibi_llm_pending"),
        "scores": [item for item in own_assessment.get("scores") or [] if isinstance(item, dict)],
        "llm_task_id": str(metadata.get("llm_task_id") or dispatch.get("task_id") or ""),
        "llm_dispatch_status": str(dispatch.get("status") or llm_review.get("status") or ""),
        "record_policy": "只有排比 LLM 返回结构化分数时，最终评分才保留。",
    }


def external_project_profile(path: Path | None) -> dict[str, bool]:
    if path is None or not path.is_dir():
        return {}
    files = _project_files(path, {".git", "__pycache__", "node_modules"})
    suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".json", ".toml"}
    text = "\n".join(_read(p)[:20000] for p in files[:250] if p.suffix.lower() in suffixes)
    lowered = text.lower()
    return {
        "review_pipeline": any(marker in lowered for marker in ("code review", "review pipeline", "reviewer", "reflection", "localization")),
        "file_grouping": any(marker in lowered for marker in ("file group", "group files", "changed files", "diff hunk", "patch set")),
        "benchmarking": any(marker in lowered for marker in ("benchmark", "precision", "recall", "eval", "evaluation")),
        "plugin_surface": any(marker in lowered for marker in ("plugin", "cli", "github action", "codex")),
    }


def _project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if set(path.relative_to(root).parts) & skip_parts:
            continue
        files.append(path)
    return files


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
