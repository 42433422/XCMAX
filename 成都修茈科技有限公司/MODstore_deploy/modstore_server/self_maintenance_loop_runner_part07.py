# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations


from modstore_server.self_maintenance_loop_runner_part07_part01 import (
    _facade as _facade,
    _validate_structured_review_protocol as _validate_structured_review_protocol,
    _validate_structured_qa_protocol as _validate_structured_qa_protocol,
    _structured_report_from_step as _structured_report_from_step,
    _structured_protocol_ok as _structured_protocol_ok,
    _structured_report_gate as _structured_report_gate,
    _allowed_auto_merge_globs as _allowed_auto_merge_globs,
    _auto_merge_scope_globs as _auto_merge_scope_globs,
    _auto_merge_forbidden_globs as _auto_merge_forbidden_globs,
    _auto_merge_max_files as _auto_merge_max_files,
    _auto_merge_max_lines as _auto_merge_max_lines,
    _step_reports as _step_reports,
    _has_high_risk_report as _has_high_risk_report,
    _missing_report_only_evidence as _missing_report_only_evidence,
    _run_cmd as _run_cmd,
    _cleanup_merge_workspace as _cleanup_merge_workspace,
    _para_repository_candidates as _para_repository_candidates,
    _remote_branch_head as _remote_branch_head,
    _validate_remediation_branch_delivery as _validate_remediation_branch_delivery,
    _changed_files_for_branch as _changed_files_for_branch,
    _diff_numstat_for_branch as _diff_numstat_for_branch,
    _kb_json_kind_for_repo_path as _kb_json_kind_for_repo_path,
    _validate_kb_json_changes_for_auto_merge as _validate_kb_json_changes_for_auto_merge,
)
