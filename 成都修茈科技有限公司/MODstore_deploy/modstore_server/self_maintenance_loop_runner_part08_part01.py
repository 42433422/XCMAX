# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part08_part01_part01 import (
    _early_kb_validation_for_branch as _early_kb_validation_for_branch,
    _early_kb_validation_in_workspace as _early_kb_validation_in_workspace,
    _find_pr_number_for_branch as _find_pr_number_for_branch,
    _gh_pr_comment as _gh_pr_comment,
    _gh_pr_add_label as _gh_pr_add_label,
    _existing_kb_schema_retry_item as _existing_kb_schema_retry_item,
    _reject_and_retry_kb_schema_failure as _reject_and_retry_kb_schema_failure,
    _normalize_repo_path as _normalize_repo_path,
)
from modstore_server.self_maintenance_loop_runner_part08_part01_part02 import (
    _diff_stats_changed_files_consistency as _diff_stats_changed_files_consistency,
    _file_matches_any_glob as _file_matches_any_glob,
    _files_match_allowed_globs as _files_match_allowed_globs,
    _auto_merge_max_risk_score as _auto_merge_max_risk_score,
    _auto_merge_min_safety_score_v2 as _auto_merge_min_safety_score_v2,
    _historical_auto_merge_success_rate as _historical_auto_merge_success_rate,
    _historical_rollback_rate as _historical_rollback_rate,
    _file_type_risk as _file_type_risk,
    _auto_merge_risk_score_v1 as _auto_merge_risk_score_v1,
    _semantic_review_qa_analysis as _semantic_review_qa_analysis,
)
