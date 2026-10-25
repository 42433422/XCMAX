"""Compute risk and safety scores from supplied diff, history and review evidence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, review, workspace


def _auto_merge_max_risk_score() -> int:
    return max(
        0,
        min(
            config._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", 40),
            100,
        ),
    )


def _auto_merge_min_safety_score_v2() -> int:
    return max(
        0,
        min(
            config._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V2", 90),
            100,
        ),
    )


def _historical_auto_merge_success_rate(
    memory: Optional[Dict[str, Any]],
) -> Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    successes = 0
    for run in recent_runs[-30:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "")
        reason = str(decision.get("reason") or "")
        if action == "auto_merged_low_risk" or "auto_merge" in reason or "low_risk" in reason:
            considered += 1
            status = str(run.get("status") or "")
            if action == "auto_merged_low_risk" or status == "completed_merged":
                successes += 1
    if considered <= 0:
        return None
    return successes / considered


def _historical_rollback_rate(
    memory: Optional[Dict[str, Any]],
) -> Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    rollbacks = 0
    for run in recent_runs[-50:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        decision = decision if isinstance(decision, dict) else {}
        if (
            str(decision.get("action") or "") != "auto_merged_low_risk"
            and str(run.get("status") or "") != "completed_merged"
        ):
            continue
        considered += 1
        merge_result = decision.get("merge_result")
        merge_result = merge_result if isinstance(merge_result, dict) else {}
        rollback_records = [
            run.get("rollback"),
            decision.get("rollback"),
            merge_result.get("rollback"),
        ]
        explicit_statuses = {
            str(run.get("status") or "").lower(),
            str(run.get("rollback_status") or "").lower(),
            str(decision.get("action") or "").lower(),
            str(decision.get("outcome") or "").lower(),
            str(merge_result.get("outcome") or "").lower(),
        }
        rolled_back = bool(
            explicit_statuses
            & {
                "auto_rollback",
                "completed_rolled_back",
                "rollback_completed",
                "rollback_executed",
                "rolled_back",
            }
        )
        if not rolled_back:
            for record in rollback_records:
                if not isinstance(record, dict):
                    continue
                status = str(record.get("status") or record.get("outcome") or "").lower()
                if record.get("executed") is True or status in {
                    "completed",
                    "executed",
                    "rolled_back",
                    "success",
                }:
                    rolled_back = True
                    break
        if rolled_back:
            rollbacks += 1
    if considered <= 0:
        return None
    return rollbacks / considered


def _file_type_risk(file_name: str) -> int:
    lower = file_name.lower()
    if workspace._kb_json_kind_for_repo_path(file_name):
        return 8
    if lower.endswith((".md", ".txt", ".json")):
        return 10
    if "/tests/" in lower or lower.startswith("tests/"):
        return 12
    if any((part in lower for part in ("/scripts/dev/", "self_maintenance", "self_evolution"))):
        return 18
    if any((part in lower for part in ("/api/", "routes", "scheduler", "workflow", "employee"))):
        return 32
    if any(
        (
            part in lower
            for part in (
                "models.py",
                "/models/",
                "migration",
                "alembic",
                "payment",
                "auth",
                "security",
            )
        )
    ):
        return 55
    if lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return 25
    return 20


def _auto_merge_risk_score_v1(
    files: List[str],
    diff_stats: Dict[str, Any],
    *,
    memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic Phase-A risk score for 100% auto-merge decisions.

    The score is intentionally transparent: file type risk, changed lines,
    sensitive keywords and historical same-loop merge success rate.
    """
    normalized_files = [
        workspace._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    per_file_scores = [
        {"file": file_name, "score": _file_type_risk(file_name)} for file_name in normalized_files
    ]
    file_score = max(
        [score for item in per_file_scores if isinstance((score := item.get("score")), int)] or [0]
    )
    line_score = min(25, line_changes // 20)
    keyword_terms = (
        "auth",
        "credential",
        "delete",
        "docker",
        "drop",
        "migration",
        "payment",
        "permission",
        "secret",
        "security",
        "token",
    )
    keyword_hits = sorted(
        {
            term
            for term in keyword_terms
            if any((term in file_name.lower() for file_name in normalized_files))
        }
    )
    keyword_score = min(25, len(keyword_hits) * 8)
    success_rate = _historical_auto_merge_success_rate(memory)
    history_score = 8 if success_rate is None else int(round((1.0 - success_rate) * 20))
    raw_score = file_score + line_score + keyword_score + history_score
    score = max(0, min(100, raw_score))
    if score <= 39:
        risk_class = "low"
    elif score <= 69:
        risk_class = "medium"
    else:
        risk_class = "high"
    return {
        "components": {
            "file_score": file_score,
            "history_score": history_score,
            "keyword_score": keyword_score,
            "line_score": line_score,
        },
        "file_scores": per_file_scores,
        "historical_auto_merge_success_rate": success_rate,
        "keyword_hits": keyword_hits,
        "line_changes": line_changes,
        "max_allowed": _auto_merge_max_risk_score(),
        "risk_class": risk_class,
        "schema_version": 1,
        "score": score,
    }


def _semantic_review_qa_analysis(
    steps: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if not isinstance(steps, list):
        return {"available": False, "penalty": 8, "reason": "no_structured_llm_reports"}
    penalty = 0
    reports: Dict[str, Any] = {}
    review_steps = [
        step for step in steps if isinstance(step, dict) and step.get("step") == "review"
    ]
    qa_steps = [step for step in steps if isinstance(step, dict) and step.get("step") == "qa"]
    if review_steps:
        review_json = review._structured_report_from_step(
            review_steps[-1], config.STRUCTURED_REVIEW_MARKER
        )
        if isinstance(review_json, dict):
            reports["review"] = review_json
            severity = str(review_json.get("max_severity") or "medium").lower()
            penalty += {
                "none": 0,
                "low": 2,
                "medium": 8,
                "high": 30,
                "critical": 50,
            }.get(severity, 15)
            if review_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    if qa_steps:
        qa_json = review._structured_report_from_step(qa_steps[-1], config.STRUCTURED_QA_MARKER)
        if isinstance(qa_json, dict):
            reports["qa"] = qa_json
            verdict = str(qa_json.get("verdict") or "").upper()
            penalty += 0 if verdict == "PASS" else 50
            risk_class = str(qa_json.get("risk_class") or "medium").lower()
            penalty += {"low": 0, "medium": 8, "high": 30}.get(risk_class, 12)
            if qa_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    return {
        "available": bool(reports),
        "penalty": min(80, penalty),
        "reports": reports,
        "source": "structured_review_qa_llm_reports",
    }


def _diff_semantic_penalty(diff_excerpt: str) -> Dict[str, Any]:
    raw_diff = diff_excerpt or ""
    saw_unified_diff = False
    current_path = ""
    added_source_lines: List[str] = []
    excluded_added_line_prefixes = ("fhd/xcagi/kb/", "docs/")
    for line in raw_diff.splitlines():
        if line.startswith("diff --git "):
            saw_unified_diff = True
            continue
        if line.startswith("+++ "):
            path = line[4:].strip().strip('"')
            current_path = path[2:] if path.startswith("b/") else path
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        normalized_path = current_path.lower()
        if any((normalized_path.startswith(prefix) for prefix in excluded_added_line_prefixes)):
            continue
        path_parts = [part for part in normalized_path.split("/") if part]
        file_name = path_parts[-1] if path_parts else ""
        if "tests" in path_parts or file_name.startswith(("test_", "spec_")):
            continue
        added_source_lines.append(line[1:])
    scanned_text = "\n".join(added_source_lines) if saw_unified_diff else raw_diff
    text = scanned_text.lower()
    high_terms = [
        "drop table",
        "delete from",
        "rm -rf",
        "subprocess",
        "shell=true",
        "jwt_secret",
        "api_key",
        "password",
        "token",
    ]
    medium_terms = ["migration", "permission", "auth", "payment", "docker", "workflow"]
    high_hits = [term for term in high_terms if term in text]
    medium_hits = [term for term in medium_terms if term in text]
    return {
        "high_hits": high_hits,
        "medium_hits": medium_hits,
        "penalty": min(50, len(high_hits) * 16 + len(medium_hits) * 5),
        "source": (
            "diff_added_source_keyword_scan" if saw_unified_diff else "diff_semantic_keyword_scan"
        ),
    }


def _auto_merge_safety_score_v2(
    files: List[str],
    diff_stats: Dict[str, Any],
    *,
    diff_excerpt: str = "",
    memory: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    risk_v1 = _auto_merge_risk_score_v1(files, diff_stats, memory=memory)
    semantic = _semantic_review_qa_analysis(steps)
    diff_semantic = _diff_semantic_penalty(diff_excerpt)
    rollback_rate = _historical_rollback_rate(memory)
    rollback_penalty = 2 if rollback_rate is None else int(round(rollback_rate * 35))
    file_penalty = min(25, int((risk_v1.get("components") or {}).get("file_score") or 0) // 4)
    line_score = int((risk_v1.get("components") or {}).get("line_score") or 0)
    line_penalty = min(18, (line_score + 1) // 2)
    keyword_penalty = min(18, int((risk_v1.get("components") or {}).get("keyword_score") or 0))
    total_penalty = (
        file_penalty
        + line_penalty
        + keyword_penalty
        + int(semantic.get("penalty") or 0)
        + int(diff_semantic.get("penalty") or 0)
        + rollback_penalty
    )
    score = max(0, min(100, 100 - total_penalty))
    if score >= 90:
        risk_class = "low"
    elif score >= 70:
        risk_class = "medium"
    else:
        risk_class = "high"
    return {
        "components": {
            "diff_semantic_penalty": diff_semantic.get("penalty"),
            "file_penalty": file_penalty,
            "keyword_penalty": keyword_penalty,
            "line_penalty": line_penalty,
            "rollback_penalty": rollback_penalty,
            "semantic_llm_penalty": semantic.get("penalty"),
        },
        "diff_semantic_analysis": diff_semantic,
        "historical_rollback_rate": rollback_rate,
        "min_allowed": _auto_merge_min_safety_score_v2(),
        "risk_class": risk_class,
        "schema_version": 2,
        "score": score,
        "semantic_llm_analysis": semantic,
        "source": "risk_score_v2_structured_llm_plus_history",
    }


def _auto_merge_safety_score_v3(
    files: List[str],
    diff_stats: Dict[str, Any],
    *,
    diff_excerpt: str = "",
    kb_validation: Optional[Dict[str, Any]] = None,
    memory: Optional[Dict[str, Any]] = None,
    risk_score_v1: Optional[Dict[str, Any]] = None,
    safety_score_v2: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    try:
        from modstore_server.autonomous_risk_gate import assess_any_code_auto_merge_v3

        return assess_any_code_auto_merge_v3(
            diff_excerpt=diff_excerpt,
            diff_stats=diff_stats,
            files=files,
            kb_validation=kb_validation,
            memory=memory,
            risk_score_v1=risk_score_v1,
            safety_score_v2=safety_score_v2,
            steps=steps,
        )
    except RECOVERABLE_ERRORS as exc:
        return {
            "error": str(exc)[:500],
            "min_allowed": config._env_int(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V3", 95
            ),
            "ok": False,
            "reason": "risk_score_v3_unavailable",
            "schema_version": 3,
            "score": 0,
            "source": "risk_score_v3_error",
        }
