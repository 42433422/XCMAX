"""Enforce allowed scope and forbidden changes before merge execution."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modstore_server import self_maintenance_merge_policy
from modstore_server import self_maintenance_retort_remediation as retort_remediation
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, risk, workspace


def _allowed_auto_merge_globs() -> List[str]:
    return config._env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_GLOBS", config.DEFAULT_AUTO_MERGE_GLOBS
    )


def _auto_merge_scope_globs() -> List[str]:
    return self_maintenance_merge_policy.scope_globs()


def _auto_merge_forbidden_globs() -> List[str]:
    return self_maintenance_merge_policy.forbidden_globs()


def _auto_merge_max_files() -> int:
    return self_maintenance_merge_policy.max_files()


def _auto_merge_max_lines() -> int:
    return self_maintenance_merge_policy.max_lines()


def _assess_branch_auto_merge_policy(
    files: List[str],
    diff_stats: Dict[str, Any],
    *,
    diff_excerpt: str = "",
    kb_validation: Optional[Dict[str, Any]] = None,
    memory: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    allowed = _allowed_auto_merge_globs()
    normalized_files = [
        workspace._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    risk_score = risk._auto_merge_risk_score_v1(
        normalized_files, diff_stats, memory=memory
    )
    safety_score_v2 = risk._auto_merge_safety_score_v2(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        memory=memory,
        steps=steps,
    )
    safety_score_v3 = risk._auto_merge_safety_score_v3(
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
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
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

        executable_block = assess_loop_memory_executable_change_block(
            memory, normalized_files
        )
        if executable_block is not None:
            decision_payload: Dict[str, Any] = {
                "changed_files": normalized_files,
                "ok": False,
                **executable_block,
            }
            if "kb_paths" not in executable_block:
                decision_payload["allowed_globs"] = allowed
            return _decision(decision_payload)
        retort_block = retort_remediation.assess_retort_scope_diff_contract(
            memory, normalized_files, diff_stats, diff_excerpt=diff_excerpt
        )
        if retort_block is not None:
            return _decision(
                {"changed_files": normalized_files, "ok": False, **retort_block}
            )
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
    consistency = workspace._diff_stats_changed_files_consistency(
        normalized_files, diff_stats
    )
    if not consistency.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "ok": False,
                "reason": "changed_files_diff_stats_mismatch",
            }
        )
    absolute_forbidden_globs = self_maintenance_merge_policy.absolute_forbidden_globs()
    absolute_forbidden_hits = [
        file_name
        for file_name in normalized_files
        if workspace._file_matches_any_glob(file_name, absolute_forbidden_globs)
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
    binary_files = (
        diff_stats.get("binary_files") if isinstance(diff_stats, dict) else []
    )
    if binary_files:
        return _decision(
            {
                "binary_files": binary_files,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "binary_files_not_auto_mergeable",
            }
        )
    if config._env_bool(
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
    forbidden_globs = _auto_merge_forbidden_globs()
    forbidden_hits = [
        file_name
        for file_name in normalized_files
        if workspace._file_matches_any_glob(file_name, forbidden_globs)
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
    max_files = _auto_merge_max_files()
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
    max_lines = _auto_merge_max_lines()
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
    if config._env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True):
        if int(safety_score_v2.get("score") or 0) < int(
            safety_score_v2.get("min_allowed") or 90
        ):
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
    if workspace._files_match_allowed_globs(normalized_files, allowed):
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
    if not config._env_bool(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True
    ):
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "changed_files_outside_low_risk_globs",
            }
        )
    scope_globs = _auto_merge_scope_globs()
    out_of_scope = [
        file_name
        for file_name in normalized_files
        if not workspace._file_matches_any_glob(file_name, scope_globs)
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
