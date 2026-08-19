# ruff: noqa: E402, F401
"""Self-maintenance loop runner for MODstore employees.

This module is the outer loop controller. It is intentionally separate from
employee execution: the scheduler decides when a maintenance loop is needed,
then delegates real work to duty employees through the existing Para bridge.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shlex
import shutil
import socket
import ssl
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx
from apscheduler.triggers.cron import CronTrigger

from . import self_maintenance_retort_change_evidence as retort_change_evidence
from . import self_maintenance_retort_remediation as retort_remediation
from .duty_employee_registry import duty_employee_records
from .duty_roster import SIX_LINE_DEPARTMENTS, all_planned_employee_ids
from .employee_executor import execute_employee_task
from .models import EmployeeExecutionMetric, IncidentEvent, User, get_session_factory
from .platform_llm_scope import platform_llm_scoped
from .runtime_provenance import collect_runtime_provenance
from .self_evolution_knowledge import (
    build_self_evolution_context,
    collect_proactive_signals,
    evolution_metrics_gate,
    record_loop_evolution_knowledge,
    render_self_evolution_context,
    salvage_kb_from_workspace,
    validate_kb_payload,
)
from .self_maintenance_merge_policy import (
    absolute_forbidden_globs as _shared_auto_merge_absolute_forbidden_globs,
)
from .self_maintenance_merge_policy import file_matches_any_glob as _shared_file_matches_any_glob
from .self_maintenance_merge_policy import forbidden_globs as _shared_auto_merge_forbidden_globs
from .self_maintenance_merge_policy import max_files as _shared_auto_merge_max_files
from .self_maintenance_merge_policy import max_lines as _shared_auto_merge_max_lines
from .self_maintenance_merge_policy import normalize_repo_path as _shared_normalize_repo_path
from .self_maintenance_merge_policy import scope_globs as _shared_auto_merge_scope_globs
from .self_maintenance_para_merge_remediation import (
    classify_para_merge_review_detail,
    para_merge_resume_pins_rejected_branch,
    reconcile_absorbed_para_merge_remediations,
    reconcile_para_merge_failure_state,
    resume_candidate_from_para_ai_review_item,
    resume_from_clean_baseline_for_para_merge,
)
from .self_maintenance_quality_gate import diff_quality_commands as _diff_quality_commands
from .self_maintenance_quality_gate import (
    matches_focused_test_command as _matches_focused_test_command,
)
from .self_maintenance_quality_gate import (
    qa_executor_infrastructure_unavailable as _qa_executor_infrastructure_unavailable,
)
from .self_maintenance_quality_gate import qa_verdict_failure_reason as _qa_verdict_failure_reason
from .self_maintenance_quality_gate import quality_check_failure as _quality_check_failure
from .self_maintenance_recovery_policy import pending_run_recovery
from .self_maintenance_remediation_lineage import (
    automated_remediation_resume_plan as _automated_remediation_resume_plan,
)
from .self_maintenance_remediation_lineage import (
    normalize_automated_remediation_reason as _normalize_automated_remediation_reason,
)
from .self_maintenance_remediation_lineage import (
    remediation_lineage_fields as _remediation_lineage_fields,
)
from .self_maintenance_remediation_lineage import (
    resume_candidate_from_context as _resume_candidate_from_remediation_context,
)
from .self_maintenance_remediation_lineage import (
    unavailable_context_record as _unavailable_remediation_context_record,
)
from .self_maintenance_remediation_prompts import (
    external_merge_remediation_prompt,
    external_review_remediation_prompt,
    qa_executor_retry_prompt,
    structured_report_remediation_prompt,
)
from .self_maintenance_retry import close_successful_code_resume, is_transient_dispatch_failure
from .self_maintenance_runtime_evidence import retain_completed_merge_runs
from .self_maintenance_subprocess import run_cmd_excerpt as _run_cmd_excerpt


from modstore_server.self_maintenance_loop_runner_part01 import (
    _para_tls_verify as _para_tls_verify,
)

logger = logging.getLogger(__name__)

RETORT_SCOPE_REASON = retort_remediation.RETORT_SCOPE_REASON
_reconcile_retort_scope_remediations = retort_remediation.reconcile_retort_scope_remediations
_reconcile_absorbed_para_merge_remediations = reconcile_absorbed_para_merge_remediations
_retort_scope_only_clarification = retort_remediation.retort_scope_only_clarification

DEFAULT_RUNTIME_DIR = str(Path.home() / ".xcmax" / "modstore-daily")
DEFAULT_LEDGER_NAME = "self_maintenance_loop_runs.jsonl"
DEFAULT_MEMORY_NAME = "self_maintenance_loop_memory.json"
DEFAULT_GOVERNANCE_AUDIT_NAME = "self_maintenance_governance_actions.jsonl"
DEFAULT_CLEAN_BASELINE_NAME = "self_maintenance_clean_baseline.json"
DEFAULT_PARA_AUTH_CACHE_NAME = "para_guest_auth_cache.json"
DEFAULT_MERGE_WORKSPACE_ROOT = "self_maintenance_merge_workspaces"
DEFAULT_LOOP_LEASE_NAME = "self_maintenance_loop.lock"
DEFAULT_EVIDENCE_WINDOW_DAYS = 30
DEFAULT_EVIDENCE_RUN_LIMIT = 24
DEFAULT_EVIDENCE_ROW_LIMIT = 240
DEFAULT_EVIDENCE_SCAN_LIMIT = 5000
DEFAULT_STATUS_FILE = (
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_loop_status.py"
)
DEFAULT_AUTO_MERGE_GLOBS = [DEFAULT_STATUS_FILE]
_PARA_GUEST_AUTH_CACHE: Dict[str, tuple] = {}
_PARA_GUEST_AUTH_TTL_SECONDS = 1800  # 30 分钟
_PARA_GUEST_AUTH_FILE_SAFETY_SECONDS = 60
HIGH_RISK_TERMS = {
    "blocker",
    "blocking:",
    "critical",
    "data loss",
    "destructive",
    "do not approve",
    "keep loop_not_completed",
    "merge conflict",
    "not recommend",
    "not approve",
    "not approved",
    "not completed",
    "do not merge",
    "not ready as completion evidence",
    "not satisfied",
    "blocking qa findings",
    "pytest failed",
    "qa failure",
    "recommendation: do not merge",
    "reject/report qa failure",
    "result: fail",
    "security",
    "secret",
    "高风险",
    "严重",
    "不可批准",
    "不建议",
    "不通过",
    "结论：fail",
    "结论: fail",
    "判定：fail",
    "判定: fail",
    "阻塞",
    "冲突",
}
HIGH_RISK_REPORT_RE = re.compile(
    r"(^|\n)\s*(result\s*:\s*)?fail\b|(^|\n)\s*qa\s*:\s*fail\b",
    re.IGNORECASE,
)
STRUCTURED_QA_MARKER = "SELF_MAINTENANCE_QA_JSON"
STRUCTURED_REVIEW_MARKER = "SELF_MAINTENANCE_REVIEW_JSON"


from modstore_server.self_maintenance_loop_runner_part02 import (
    _utc_now as _utc_now,
    _iso as _iso,
    _env_int as _env_int,
    _env_bool as _env_bool,
    _env_flag_enabled as _env_flag_enabled,
    _auto_dispatch_deploy_enabled as _auto_dispatch_deploy_enabled,
    _env_list as _env_list,
    _runtime_dir as _runtime_dir,
    ledger_path as ledger_path,
    loop_memory_path as loop_memory_path,
    governance_audit_path as governance_audit_path,
    clean_baseline_path as clean_baseline_path,
    _default_clean_baseline as _default_clean_baseline,
    load_clean_baseline as load_clean_baseline,
    ensure_clean_baseline as ensure_clean_baseline,
    _clean_baseline_context as _clean_baseline_context,
    _append_ledger as _append_ledger,
    _read_ledger as _read_ledger,
    _ledger_row_timestamp as _ledger_row_timestamp,
    _select_recent_milestone_rows as _select_recent_milestone_rows,
    loop_lease_path as loop_lease_path,
    _exclusive_loop_lease as _exclusive_loop_lease,
    _load_loop_memory as _load_loop_memory,
    _read_governance_audit as _read_governance_audit,
    _append_governance_audit as _append_governance_audit,
    record_governance_audit_review as record_governance_audit_review,
    _governance_audit_summary as _governance_audit_summary,
    _governance_audit_gate as _governance_audit_gate,
    _policy_active_gates_snapshot as _policy_active_gates_snapshot,
    _write_loop_memory as _write_loop_memory,
    _memory_context as _memory_context,
    _coerce_str_set as _coerce_str_set,
    _open_item_steps as _open_item_steps,
    _failed_open_item_identity as _failed_open_item_identity,
    _open_item_matches_resolution as _open_item_matches_resolution,
    _close_open_items_in_memory as _close_open_items_in_memory,
    close_loop_memory_items as close_loop_memory_items,
)


from modstore_server.self_maintenance_loop_runner_part03 import (
    _close_items_resolved_by_final as _close_items_resolved_by_final,
    _resume_review_qa_candidate as _resume_review_qa_candidate,
    _resume_steps as _resume_steps,
    _resume_dispatch_context as _resume_dispatch_context,
    _parse_iso as _parse_iso,
    _file_url_to_path as _file_url_to_path,
    _self_maintenance_actor_user_id as _self_maintenance_actor_user_id,
    _recent_employee_failure_count as _recent_employee_failure_count,
    _recent_incident_signals as _recent_incident_signals,
    evaluate_self_maintenance_need as evaluate_self_maintenance_need,
    _last_started_at as _last_started_at,
)


from modstore_server.self_maintenance_loop_runner_part04 import (
    reconcile_stale_self_maintenance_runs as reconcile_stale_self_maintenance_runs,
    should_run_self_maintenance_loop as should_run_self_maintenance_loop,
)


# Preferred Para nests for delivery_validation lookup. Order is part of the
# determinism contract: same payload shape always yields the same DV.
_DELIVERY_VALIDATION_PREFERRED_KEYS = (
    "para_result",
    "response",
    "outputs",
    "result",
    "change_delivery",
    "snapshot",
    "subtasks",
    "data",
    "subtask",
)


from modstore_server.self_maintenance_loop_runner_part05 import (
    _employee_result_ok as _employee_result_ok,
    _delivery_validation_command_failed as _delivery_validation_command_failed,
    _delivery_validation_gate as _delivery_validation_gate,
    _find_delivery_validation as _find_delivery_validation,
    _collect_delivery_validation_candidates as _collect_delivery_validation_candidates,
    _extract_failure_reason as _extract_failure_reason,
    _extract_para_meta as _extract_para_meta,
    _collect_text_fields as _collect_text_fields,
    _extract_report_excerpt as _extract_report_excerpt,
    _is_transient_employee_dispatch_failure as _is_transient_employee_dispatch_failure,
    _coerce_truthy_flag as _coerce_truthy_flag,
    _para_item_is_accepted_wait_timeout as _para_item_is_accepted_wait_timeout,
    _is_accepted_para_wait_timeout as _is_accepted_para_wait_timeout,
    _loop_platform_bench_override as _loop_platform_bench_override,
    _execute_employee_task_with_retries as _execute_employee_task_with_retries,
    _run_step_with_inner_retries as _run_step_with_inner_retries,
)


from modstore_server.self_maintenance_loop_runner_part06 import (
    _fetch_para_task_report_excerpt as _fetch_para_task_report_excerpt,
    _fetch_para_task_state as _fetch_para_task_state,
    _reconcile_requested_merge_feedback as _reconcile_requested_merge_feedback,
    _base_para_input as _base_para_input,
    _python_supports_focused_tests as _python_supports_focused_tests,
    _focused_test_command as _focused_test_command,
    _code_task_text as _code_task_text,
    _evaluate_retort_clarification_before_review as _evaluate_retort_clarification_before_review,
    _review_task_text as _review_task_text,
    _qa_task_text as _qa_task_text,
    _json_after_marker as _json_after_marker,
)


_REVIEW_DIMENSION_KEYS = ("security", "business_logic", "performance")
_REVIEW_DIMENSION_STATUSES = frozenset({"pass", "fail", "n/a"})
_REVIEW_SEVERITIES = frozenset({"none", "low", "medium", "high", "critical"})
_REVIEW_RISK_CLASSES = frozenset({"low", "medium", "high"})


from modstore_server.self_maintenance_loop_runner_part07 import (
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


KB_SCHEMA_RETRY_MAX = 2
KB_SCHEMA_FAILED_LABEL = "kb-schema-failed"
KB_SCHEMA_FAILED_STATUS = "kb_schema_failed"
NEEDS_HUMAN_LABEL = "needs-human"


from modstore_server.self_maintenance_loop_runner_part08 import (
    _early_kb_validation_for_branch as _early_kb_validation_for_branch,
    _early_kb_validation_in_workspace as _early_kb_validation_in_workspace,
    _find_pr_number_for_branch as _find_pr_number_for_branch,
    _gh_pr_comment as _gh_pr_comment,
    _gh_pr_add_label as _gh_pr_add_label,
    _existing_kb_schema_retry_item as _existing_kb_schema_retry_item,
    _reject_and_retry_kb_schema_failure as _reject_and_retry_kb_schema_failure,
    _normalize_repo_path as _normalize_repo_path,
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


from modstore_server.self_maintenance_loop_runner_part09 import (
    _diff_semantic_penalty as _diff_semantic_penalty,
    _auto_merge_safety_score_v2 as _auto_merge_safety_score_v2,
    _auto_merge_safety_score_v3 as _auto_merge_safety_score_v3,
    _assess_branch_auto_merge_policy as _assess_branch_auto_merge_policy,
    _guest_auth_headers as _guest_auth_headers,
    para_auth_cache_path as para_auth_cache_path,
    _read_para_guest_auth_file as _read_para_guest_auth_file,
    _write_para_guest_auth_file as _write_para_guest_auth_file,
    _base64url_json as _base64url_json,
    _base64url_bytes as _base64url_bytes,
    _mint_local_para_guest_auth_token as _mint_local_para_guest_auth_token,
    _kickstart_para_agent as _kickstart_para_agent,
    _para_db_file as _para_db_file,
    _clear_stale_para_current_task as _clear_stale_para_current_task,
    _reconcile_orphan_para_running_tasks as _reconcile_orphan_para_running_tasks,
)


from modstore_server.self_maintenance_loop_runner_part10 import (
    _wait_for_para_device_online as _wait_for_para_device_online,
    _mark_para_task_merged as _mark_para_task_merged,
    _request_para_task_merge as _request_para_task_merge,
    _loop_steps_roster_gate as _loop_steps_roster_gate,
    _auto_merge_low_risk_branch as _auto_merge_low_risk_branch,
    _auto_merge_local_repo as _auto_merge_local_repo,
    _auto_dispatch_deploy_envs as _auto_dispatch_deploy_envs,
    _dispatch_fhd_deploy_action as _dispatch_fhd_deploy_action,
    _dispatch_deploy_for_merge as _dispatch_deploy_for_merge,
    _emit_deploy_callback as _emit_deploy_callback,
    _record_verified_deploy_employee_metric as _record_verified_deploy_employee_metric,
    _append_deploy_receipt_event as _append_deploy_receipt_event,
    _run_deploy_receipts_after_merge as _run_deploy_receipts_after_merge,
)


from modstore_server.self_maintenance_loop_runner_part11 import (
    _decide_post_loop_policy as _decide_post_loop_policy,
)


LOOP_EVICT_MAX_ITEMS = 100
LOOP_EVICT_STUCK_AGE_SECONDS = 24 * 3600
LOOP_EVICT_STUCK_RETRY_THRESHOLD = 3
LOOP_EVICT_AGE_OUT_SECONDS = 7 * 24 * 3600


from modstore_server.self_maintenance_loop_runner_part12 import (
    _evict_loop_memory_items as _evict_loop_memory_items,
    evict_loop_memory_items as evict_loop_memory_items,
    _update_loop_memory as _update_loop_memory,
    _run_self_maintenance_loop_unlocked as _run_self_maintenance_loop_unlocked,
    run_self_maintenance_loop as run_self_maintenance_loop,
    cron_trigger_for_self_maintenance as cron_trigger_for_self_maintenance,
    record_self_maintenance_heartbeat as record_self_maintenance_heartbeat,
)


from modstore_server.self_maintenance_loop_runner_part13 import (
    get_self_maintenance_runtime_status as get_self_maintenance_runtime_status,
)


__all__ = [
    "cron_trigger_for_self_maintenance",
    "evaluate_self_maintenance_need",
    "get_self_maintenance_runtime_status",
    "record_self_maintenance_heartbeat",
    "ledger_path",
    "loop_memory_path",
    "reconcile_stale_self_maintenance_runs",
    "run_self_maintenance_loop",
    "should_run_self_maintenance_loop",
]
