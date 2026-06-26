"""Phase-D autonomous merge risk gate.

The Phase-B gate was scope based: structured QA plus a dynamic low-risk
whitelist.  Phase-D keeps hard safety blocks, but lets any code path be
considered when the v3 score is high enough.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def min_safety_score_v3() -> int:
    return max(
        0, min(_env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V3", 95), 100)
    )


def _line_changes(diff_stats: Dict[str, Any]) -> int:
    try:
        return int((diff_stats or {}).get("line_changes") or 0)
    except (TypeError, ValueError):
        return 0


def _file_risk(file_name: str) -> int:
    lower = str(file_name or "").lower()
    if any(token in lower for token in (".env", "secret", "credential", "token")):
        return 100
    if any(token in lower for token in ("payment", "billing", "auth", "permission", "security")):
        return 35
    if any(token in lower for token in ("migration", "alembic", "models.py", "/models/")):
        return 32
    if any(
        token in lower
        for token in ("dockerfile", "docker-compose", ".github/workflows", "pyproject.toml")
    ):
        return 28
    if any(token in lower for token in ("/api/", "route", "scheduler", "workflow", "employee")):
        return 22
    if lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return 16
    if lower.endswith((".md", ".txt", ".json", ".yaml", ".yml")):
        return 8
    return 14


def _historical_rollback_rate(memory: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(memory, dict):
        return None
    rows = memory.get("recent_runs")
    if not isinstance(rows, list):
        return None
    considered = 0
    rolled_back = 0
    for row in rows[-80:]:
        if not isinstance(row, dict):
            continue
        text = json.dumps(row, ensure_ascii=False).lower()
        if "auto_merged" not in text and "completed_merged" not in text:
            continue
        considered += 1
        if any(token in text for token in ("rollback", "revert", "regression", "回滚", "退回")):
            rolled_back += 1
    if considered <= 0:
        return None
    return rolled_back / considered


def _historical_ci_pass_rate(memory: Optional[Dict[str, Any]]) -> Optional[float]:
    env = os.environ.get("MODSTORE_AUTONOMOUS_CI_PASS_RATE")
    if env is not None and str(env).strip():
        try:
            return max(0.0, min(float(str(env).strip()), 1.0))
        except ValueError:
            pass
    if not isinstance(memory, dict):
        return None
    rows = memory.get("recent_runs")
    if not isinstance(rows, list):
        return None
    considered = 0
    passed = 0
    for row in rows[-80:]:
        if not isinstance(row, dict):
            continue
        text = json.dumps(row, ensure_ascii=False).lower()
        if not any(token in text for token in ("ci", "qa", "pytest", "lint", "test")):
            continue
        considered += 1
        failed = any(
            token in text
            for token in (
                "ci_failed",
                "qa failure",
                "pytest failed",
                "test failed",
                "result: fail",
                '"verdict": "fail"',
                '"verdict":"fail"',
            )
        )
        if not failed:
            passed += 1
    if considered <= 0:
        return None
    return passed / considered


def _security_scan(diff_excerpt: str, files: Sequence[str]) -> Dict[str, Any]:
    text = (diff_excerpt or "").lower()
    paths = "\n".join(str(item or "").lower() for item in files)
    high_patterns = {
        "hardcoded_secret": r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{12,}",
        "destructive_shell": r"(?i)(rm\s+-rf|DROP\s+TABLE|DELETE\s+FROM)",
        "unsafe_subprocess": r"(?i)(shell\s*=\s*True|os\.system\()",
    }
    high_hits = [name for name, pattern in high_patterns.items() if re.search(pattern, text)]
    path_hits = [
        token
        for token in ("secret", "credential", ".env", ".pem", ".key", "token")
        if token in paths
    ]
    medium_hits = [
        token
        for token in ("auth", "permission", "payment", "migration", "docker", "workflow")
        if token in text or token in paths
    ]
    return {
        "hard_block": bool(high_hits or path_hits),
        "high_hits": sorted(set(high_hits + path_hits)),
        "medium_hits": sorted(set(medium_hits)),
        "penalty": min(80, len(high_hits) * 35 + len(path_hits) * 30 + len(medium_hits) * 4),
        "source": "phase_d_security_scan",
    }


def _semantic_penalty_from_v2(
    safety_score_v2: Optional[Dict[str, Any]],
) -> Tuple[int, Dict[str, Any]]:
    if not isinstance(safety_score_v2, dict):
        return 18, {"available": False, "reason": "missing_v2_semantic_signal"}
    semantic = safety_score_v2.get("semantic_llm_analysis")
    if not isinstance(semantic, dict):
        return 14, {"available": False, "reason": "missing_structured_llm_analysis"}
    reports = semantic.get("reports") if isinstance(semantic.get("reports"), dict) else {}
    if not reports:
        return 18, {"available": False, "reason": "empty_structured_llm_reports"}
    penalty = int(semantic.get("penalty") or 0)
    scaled = min(45, max(0, penalty // 2))
    return scaled, {
        "available": True,
        "penalty_from_v2": penalty,
        "reports": reports,
        "source": "structured_review_qa_llm_reports",
    }


def assess_any_code_auto_merge_v3(
    *,
    diff_excerpt: str = "",
    diff_stats: Optional[Dict[str, Any]] = None,
    files: Sequence[str],
    kb_validation: Optional[Dict[str, Any]] = None,
    memory: Optional[Dict[str, Any]] = None,
    risk_score_v1: Optional[Dict[str, Any]] = None,
    safety_score_v2: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a Phase-D score for arbitrary-code auto merge.

    The score intentionally uses only durable signals that the loop already
    produces: structured review/QA, historical rollback rate, CI/QA pass rate,
    deterministic security scan, file criticality and diff size.
    """

    del risk_score_v1, steps
    normalized_files = [str(item or "").strip() for item in files if str(item or "").strip()]
    line_changes = _line_changes(diff_stats or {})
    file_scores = [{"file": item, "score": _file_risk(item)} for item in normalized_files]
    max_file_risk = max([int(item["score"]) for item in file_scores] or [0])
    file_penalty = min(28, max_file_risk // 3)
    line_penalty = min(28, line_changes // 35)
    semantic_penalty, semantic = _semantic_penalty_from_v2(safety_score_v2)
    security = _security_scan(diff_excerpt, normalized_files)
    rollback_rate = _historical_rollback_rate(memory)
    rollback_penalty = 8 if rollback_rate is None else min(30, int(round(rollback_rate * 70)))
    ci_pass_rate = _historical_ci_pass_rate(memory)
    ci_penalty = 8 if ci_pass_rate is None else min(30, int(round((1.0 - ci_pass_rate) * 80)))
    kb_penalty = 0
    hard_blockers: List[str] = []
    if isinstance(kb_validation, dict) and not kb_validation.get("ok", True):
        kb_penalty = 50
        hard_blockers.append("kb_validation_failed")
    if security.get("hard_block"):
        hard_blockers.append("security_scan_hard_block")
    if not normalized_files:
        hard_blockers.append("no_changed_files")
    if line_changes <= 0:
        hard_blockers.append("missing_diff_stats")

    total_penalty = (
        file_penalty
        + line_penalty
        + semantic_penalty
        + int(security.get("penalty") or 0)
        + rollback_penalty
        + ci_penalty
        + kb_penalty
    )
    score = max(0, min(100, 100 - total_penalty))
    min_allowed = min_safety_score_v3()
    ok = score >= min_allowed and not hard_blockers
    missing_signals = []
    if rollback_rate is None:
        missing_signals.append("historical_rollback_rate")
    if ci_pass_rate is None:
        missing_signals.append("ci_pass_rate")
    if not semantic.get("available"):
        missing_signals.append("structured_llm_semantic")
    uncertainty_score = max(
        0, min(100, (100 - score) + len(missing_signals) * 6 + len(hard_blockers) * 20)
    )
    return {
        "ci_pass_rate": ci_pass_rate,
        "components": {
            "ci_penalty": ci_penalty,
            "file_penalty": file_penalty,
            "kb_penalty": kb_penalty,
            "line_penalty": line_penalty,
            "rollback_penalty": rollback_penalty,
            "security_penalty": security.get("penalty"),
            "semantic_penalty": semantic_penalty,
        },
        "file_scores": file_scores,
        "hard_blockers": hard_blockers,
        "historical_rollback_rate": rollback_rate,
        "line_changes": line_changes,
        "min_allowed": min_allowed,
        "missing_signals": missing_signals,
        "ok": ok,
        "reason": (
            "risk_score_v3_policy_passed" if ok else "risk_score_v3_below_threshold_or_blocked"
        ),
        "schema_version": 3,
        "score": score,
        "security_scan": security,
        "semantic_llm_analysis": semantic,
        "source": "risk_score_v3_llm_history_ci_security",
        "uncertainty_score": uncertainty_score,
    }


__all__ = ["assess_any_code_auto_merge_v3", "min_safety_score_v3"]
