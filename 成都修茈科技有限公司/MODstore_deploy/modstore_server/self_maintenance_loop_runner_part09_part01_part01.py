# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _diff_semantic_penalty(diff_excerpt: str) -> _facade().Dict[str, _facade().Any]:
    raw_diff = diff_excerpt or ""
    saw_unified_diff = False
    current_path = ""
    added_source_lines: _facade().List[str] = []
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
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    risk_v1 = _facade()._auto_merge_risk_score_v1(files, diff_stats, memory=memory)
    semantic = _facade()._semantic_review_qa_analysis(steps)
    diff_semantic = _facade()._diff_semantic_penalty(diff_excerpt)
    rollback_rate = _facade()._historical_rollback_rate(memory)
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
        "min_allowed": _facade()._auto_merge_min_safety_score_v2(),
        "risk_class": risk_class,
        "schema_version": 2,
        "score": score,
        "semantic_llm_analysis": semantic,
        "source": "risk_score_v2_structured_llm_plus_history",
    }


def _auto_merge_safety_score_v3(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    kb_validation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    risk_score_v1: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    safety_score_v2: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
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
            "min_allowed": _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V3", 95
            ),
            "ok": False,
            "reason": "risk_score_v3_unavailable",
            "schema_version": 3,
            "score": 0,
            "source": "risk_score_v3_error",
        }


def _assess_branch_auto_merge_policy(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    kb_validation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    allowed = _facade()._allowed_auto_merge_globs()
    normalized_files = [
        _facade()._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    risk_score = _facade()._auto_merge_risk_score_v1(normalized_files, diff_stats, memory=memory)
    safety_score_v2 = _facade()._auto_merge_safety_score_v2(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        memory=memory,
        steps=steps,
    )
    safety_score_v3 = _facade()._auto_merge_safety_score_v3(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=memory,
        risk_score_v1=risk_score,
        safety_score_v2=safety_score_v2,
        steps=steps,
    )

    def _decision(
        payload: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        return {
            **payload,
            "risk_score": risk_score,
            "safety_score_v2": safety_score_v2,
            "safety_score_v3": safety_score_v3,
        }

    if not normalized_files:
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "no_changed_files",
            }
        )
    try:
        from modstore_server.self_maintenance_policy import (
            assess_loop_memory_executable_change_block,
            para_merge_review_max_diff_chars,
        )

        executable_block = assess_loop_memory_executable_change_block(memory, normalized_files)
        if executable_block is not None:
            decision_payload: _facade().Dict[str, _facade().Any] = {
                "changed_files": normalized_files,
                "ok": False,
                **executable_block,
            }
            if "kb_paths" not in executable_block:
                decision_payload["allowed_globs"] = allowed
            return _decision(decision_payload)
        retort_block = _facade().retort_remediation.assess_retort_scope_diff_contract(
            memory, normalized_files, diff_stats, diff_excerpt=diff_excerpt
        )
        if retort_block is not None:
            return _decision({"changed_files": normalized_files, "ok": False, **retort_block})
    except RECOVERABLE_ERRORS as exc:
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "error": str(exc),
                "ok": False,
                "reason": "self_maintenance_policy_check_failed",
            }
        )
    max_review_chars = para_merge_review_max_diff_chars()
    diff_chars = int((diff_stats or {}).get("git_diff_chars") or 0)
    if diff_chars <= 0 and diff_excerpt:
        diff_chars = len(diff_excerpt)
    if diff_chars > max_review_chars:
        return _decision(
            {
                "changed_files": normalized_files,
                "git_diff_chars": diff_chars,
                "max_diff_chars": max_review_chars,
                "ok": False,
                "reason": "diff_too_large_for_para_merge_review",
            }
        )
    consistency = _facade()._diff_stats_changed_files_consistency(normalized_files, diff_stats)
    if not consistency.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "ok": False,
                "reason": "changed_files_diff_stats_mismatch",
            }
        )
    absolute_forbidden_globs = _facade()._shared_auto_merge_absolute_forbidden_globs()
    absolute_forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _facade()._file_matches_any_glob(file_name, absolute_forbidden_globs)
    ]
    if absolute_forbidden_hits:
        return _decision(
            {
                "absolute_forbidden_globs": absolute_forbidden_globs,
                "absolute_forbidden_hits": absolute_forbidden_hits,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "changed_files_match_absolute_forbidden_globs",
            }
        )
    binary_files = diff_stats.get("binary_files") if isinstance(diff_stats, dict) else []
    if binary_files:
        return _decision(
            {
                "binary_files": binary_files,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "binary_files_not_auto_mergeable",
            }
        )
    if _facade()._env_bool(
        "MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", True
    ) and safety_score_v3.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": int((diff_stats or {}).get("line_changes") or 0),
                "ok": True,
                "reason": "risk_score_v3_any_code_policy_passed",
            }
        )
    forbidden_globs = _facade()._auto_merge_forbidden_globs()
    forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _facade()._file_matches_any_glob(file_name, forbidden_globs)
    ]
    if forbidden_hits:
        return _decision(
            {
                "changed_files": normalized_files,
                "forbidden_globs": forbidden_globs,
                "forbidden_hits": forbidden_hits,
                "ok": False,
                "reason": "changed_files_match_forbidden_globs",
            }
        )
    max_files = _facade()._auto_merge_max_files()
    if len(normalized_files) > max_files:
        return _decision(
            {
                "changed_files": normalized_files,
                "max_files": max_files,
                "ok": False,
                "reason": "too_many_changed_files_for_dynamic_auto_merge",
            }
        )
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    max_lines = _facade()._auto_merge_max_lines()
    if line_changes > max_lines:
        return _decision(
            {
                "changed_files": normalized_files,
                "line_changes": line_changes,
                "max_lines": max_lines,
                "ok": False,
                "reason": "too_many_changed_lines_for_dynamic_auto_merge",
            }
        )
    if _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True):
        if int(safety_score_v2.get("score") or 0) < int(safety_score_v2.get("min_allowed") or 90):
            return _decision(
                {
                    "changed_files": normalized_files,
                    "ok": False,
                    "reason": "auto_merge_safety_score_v2_too_low",
                }
            )
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": line_changes,
                "ok": True,
                "reason": "risk_score_v2_policy_passed",
            }
        )
    if int(risk_score.get("score") or 100) > int(risk_score.get("max_allowed") or 0):
        return _decision(
            {
                "changed_files": normalized_files,
                "ok": False,
                "reason": "auto_merge_risk_score_too_high",
            }
        )
    if _facade()._files_match_allowed_globs(normalized_files, allowed):
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": diff_stats.get("line_changes"),
                "ok": True,
                "reason": "legacy_low_risk_glob_policy_passed",
            }
        )
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True):
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "changed_files_outside_low_risk_globs",
            }
        )
    scope_globs = _facade()._auto_merge_scope_globs()
    out_of_scope = [
        file_name
        for file_name in normalized_files
        if not _facade()._file_matches_any_glob(file_name, scope_globs)
    ]
    if out_of_scope:
        return _decision(
            {
                "changed_files": normalized_files,
                "ok": False,
                "out_of_scope": out_of_scope,
                "reason": "changed_files_outside_dynamic_low_risk_scope",
                "scope_globs": scope_globs,
            }
        )
    return _decision(
        {
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "dynamic_scope_globs": scope_globs,
            "forbidden_globs": forbidden_globs,
            "line_changes": line_changes,
            "max_files": max_files,
            "max_lines": max_lines,
            "ok": True,
            "reason": "dynamic_low_risk_policy_passed",
        }
    )
