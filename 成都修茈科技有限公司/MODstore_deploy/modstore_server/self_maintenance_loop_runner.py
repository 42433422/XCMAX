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
from .self_maintenance_jsonl import read_jsonl_tail
from .self_maintenance_merge_policy import (
    DEFAULT_FORBIDDEN_GLOBS as DEFAULT_AUTO_MERGE_FORBIDDEN_GLOBS,
)
from .self_maintenance_merge_policy import DEFAULT_SCOPE_GLOBS as DEFAULT_AUTO_MERGE_SCOPE_GLOBS
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning("invalid integer env %s=%r; using %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_flag_enabled(name: str) -> bool:
    """Master switches that default OFF when unset (dry-run 等显式危险开关)。"""
    return _env_bool(name, False)


def _auto_dispatch_deploy_enabled() -> bool:
    """staging 自动部署主开关：未设置时默认开启；显式 0/false/off 关闭。"""
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY")
    if raw is None or not str(raw).strip():
        return True
    return _env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY", True)


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return list(default)
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    return values or list(default)


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or DEFAULT_RUNTIME_DIR)


def ledger_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER")
    return Path(raw) if raw else _runtime_dir() / DEFAULT_LEDGER_NAME


def loop_memory_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY")
    return Path(raw) if raw else _runtime_dir() / DEFAULT_MEMORY_NAME


def governance_audit_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT")
    return Path(raw) if raw else _runtime_dir() / DEFAULT_GOVERNANCE_AUDIT_NAME


def clean_baseline_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE")
    if raw:
        return Path(raw)
    kb_root = os.environ.get("XCMAX_SELF_EVOLUTION_KB_ROOT") or os.environ.get("XCMAX_KB_ROOT")
    if kb_root:
        return Path(kb_root).expanduser() / "metrics" / DEFAULT_CLEAN_BASELINE_NAME
    return _runtime_dir() / DEFAULT_CLEAN_BASELINE_NAME


def _default_clean_baseline() -> Dict[str, Any]:
    return {
        "baseline_id": "initial-current-known-failures-2026-06-18",
        "created_at": "2026-06-18T23:37:10+00:00",
        "notes": (
            "Initial clean baseline from the first real report-only QA pass. "
            "QA must fail only for new failures beyond this baseline and should refresh "
            "allowed_failure_nodeids when a clean full-test collection is available."
        ),
        "openapi": {
            "allowed_error_count": 0,
            "allowed_info_count": 49,
            "allowed_warn_count": 1819,
            "allowed_patterns": [
                "routes=1076 ops=1028",
                "warn=1819",
                "info=49",
            ],
        },
        "pytest": {
            "allowed_error_count": 32,
            "allowed_failure_count": 80,
            "allowed_error_nodeids": [],
            "allowed_failure_nodeids": [],
            "allowed_failure_patterns": [
                "PermissionError",
                "sidebar_menu_manager.py",
                "outside this workspace",
            ],
            "source_run_id": "84c3aaf5-d3ff-420f-a31b-4680451cebbd",
        },
        "ruff": {
            "allowed_error_count": 63,
            "allowed_patterns": [
                "ruff check app",
                "63 errors",
            ],
        },
        "schema_version": 1,
    }


def load_clean_baseline() -> Dict[str, Any]:
    path = clean_baseline_path()
    if not path.exists():
        return _default_clean_baseline()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _default_clean_baseline()
    except Exception:
        logger.exception("failed to read clean baseline")
        return _default_clean_baseline()


def ensure_clean_baseline() -> Dict[str, Any]:
    path = clean_baseline_path()
    if path.exists():
        return load_clean_baseline()
    baseline = _default_clean_baseline()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return baseline


def _clean_baseline_context() -> str:
    return json.dumps(load_clean_baseline(), ensure_ascii=False, sort_keys=True)[:4000]


def _append_ledger(record: Dict[str, Any]) -> None:
    record = dict(record)
    run_id = str(record.get("run_id") or "").strip()
    if run_id:
        record.setdefault("correlation_id", run_id)
    record.setdefault("ledger_schema_version", 2)
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_ledger(limit: int = 100) -> List[Dict[str, Any]]:
    path = ledger_path()
    return read_jsonl_tail(path, limit=limit)


def _ledger_row_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    """Return a normalized timestamp for one append-only ledger row.

    Step records use ``timestamp`` while start/terminal records use one of the
    ``*_at`` fields.  Keeping that compatibility here prevents an otherwise
    valid step from becoming timeless when it is projected into runtime
    evidence.
    """

    for key in (
        "timestamp",
        "created_at",
        "completed_at",
        "updated_at",
        "started_at",
        "verified_at",
        "deployed_at",
        "at",
    ):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _select_recent_milestone_rows(
    rows: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    window_days: int = DEFAULT_EVIDENCE_WINDOW_DAYS,
    run_limit: int = DEFAULT_EVIDENCE_RUN_LIMIT,
    row_limit: int = DEFAULT_EVIDENCE_ROW_LIMIT,
) -> List[Dict[str, Any]]:
    """Select coherent, time-bounded work evidence immune to heartbeat churn.

    The live feed remains intentionally small, but proof of a recent completed
    work cycle must not disappear merely because the scheduler emitted many
    idle heartbeats or policy skips.  Rows without a parseable timestamp are
    excluded, and evidence expires after ``window_days`` so an old success can
    never prove current autonomy forever.
    """

    current = (now or _utc_now()).astimezone(timezone.utc)
    bounded_days = max(1, min(int(window_days or DEFAULT_EVIDENCE_WINDOW_DAYS), 90))
    bounded_runs = max(1, min(int(run_limit or DEFAULT_EVIDENCE_RUN_LIMIT), 64))
    bounded_rows = max(1, min(int(row_limit or DEFAULT_EVIDENCE_ROW_LIMIT), 512))
    cutoff = current - timedelta(days=bounded_days)
    future_tolerance = current + timedelta(minutes=5)
    excluded_phases = {"heartbeat", "skip", "kb_salvage"}

    eligible: List[Tuple[Dict[str, Any], datetime]] = []
    latest_by_run: Dict[str, datetime] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        phase = str(row.get("phase") or "").strip().lower()
        if phase in excluded_phases:
            continue
        if not phase and not row.get("event") and not row.get("event_type"):
            continue
        observed_at = _ledger_row_timestamp(row)
        if observed_at is None or observed_at < cutoff or observed_at > future_tolerance:
            continue
        eligible.append((row, observed_at))
        run_id = str(row.get("run_id") or "").strip()
        if run_id and observed_at > latest_by_run.get(run_id, cutoff):
            latest_by_run[run_id] = observed_at

    selected_run_ids = {
        run_id
        for run_id, _ in sorted(latest_by_run.items(), key=lambda item: item[1])[-bounded_runs:]
    }

    return retain_completed_merge_runs(
        eligible,
        latest_by_run=latest_by_run,
        recent_run_ids=selected_run_ids,
        cutoff=cutoff,
        row_limit=bounded_rows,
    )


def loop_lease_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEASE_FILE")
    return Path(raw) if raw else _runtime_dir() / DEFAULT_LOOP_LEASE_NAME


@contextmanager
def _exclusive_loop_lease():
    """Hold one OS-backed lease for the complete maintenance transaction."""

    path = loop_lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError):
            acquired = False
        if acquired:
            fh.seek(0)
            fh.truncate()
            fh.write(
                json.dumps(
                    {
                        "acquired_at": _iso(_utc_now()),
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            fh.flush()
        yield acquired
    finally:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        fh.close()


def _load_loop_memory() -> Dict[str, Any]:
    path = loop_memory_path()
    if not path.exists():
        return {
            "closed_items": [],
            "open_items": [],
            "recent_runs": [],
            "run_count": 0,
            "updated_at": None,
        }
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("failed to read self-maintenance memory")
        return {}


def _read_governance_audit(limit: int = 10) -> List[Dict[str, Any]]:
    path = governance_audit_path()
    return read_jsonl_tail(path, limit=limit)


def _append_governance_audit(record: Dict[str, Any]) -> Path:
    path = governance_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def record_governance_audit_review(
    *,
    note: str = "",
    admin_user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    recent = _read_governance_audit(10)
    summary = _governance_audit_summary(recent)
    record = {
        "action": "review_governance_audit",
        "admin_user_id": admin_user_id,
        "created_at": _iso(_utc_now()),
        "note": str(note or "")[:1000],
        "ok": True,
        "previous_summary": summary,
        "source": "self_maintenance_loop_api",
        "status": "reviewed",
    }
    path = _append_governance_audit(record)
    next_recent = _read_governance_audit(10)
    return {
        "ok": True,
        "audit_path": str(path),
        "record": record,
        "summary": _governance_audit_summary(next_recent),
    }


def _governance_audit_summary(
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    items = rows if isinstance(rows, list) else _read_governance_audit(10)
    success_count = sum(
        1 for item in items if isinstance(item, dict) and item.get("ok") is not False
    )
    failure_count = sum(1 for item in items if isinstance(item, dict) and item.get("ok") is False)
    consecutive_failures = 0
    for item in reversed(items):
        if isinstance(item, dict) and item.get("ok") is False:
            consecutive_failures += 1
        else:
            break
    return {
        "recent_count": len(items),
        "success_count": success_count,
        "failure_count": failure_count,
        "consecutive_failures": consecutive_failures,
        "health": ("bad" if consecutive_failures >= 2 else ("warn" if failure_count else "ok")),
    }


def _governance_audit_gate() -> Dict[str, Any]:
    summary = _governance_audit_summary()
    health = str(summary.get("health") or "").strip()
    ok = health != "bad"
    return {
        "ok": ok,
        "blocking": not ok,
        "action": "allow" if ok else "hold_for_governance_review",
        "reason": ("governance_audit_healthy" if ok else "governance_audit_consecutive_failures"),
        "summary": summary,
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }


def _policy_active_gates_snapshot(
    *,
    evolution_metrics: Optional[Dict[str, Any]] = None,
    gate: Dict[str, Any],
    governance_gate: Dict[str, Any],
    report_only_missing: bool = False,
    roster_gate: Dict[str, Any],
    structured_gate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    evo = evolution_metrics if isinstance(evolution_metrics, dict) else {}
    structured = structured_gate if isinstance(structured_gate, dict) else {"ok": True}
    items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if gate.get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": gate.get("reason") or gate.get("trigger_reason") or "",
            "detail": f"missing={gate.get('missing_count', 0)} threshold={gate.get('threshold', '')}",
        },
        {
            "key": "structured",
            "label": "Structured QA/Review",
            "status": "allow" if structured.get("ok") is not False else "blocked",
            "ok": structured.get("ok") is not False,
            "blocking": structured.get("ok") is False,
            "reason": structured.get("reason") or "",
            "detail": "QA/review JSON gate",
        },
        {
            "key": "report_only",
            "label": "Report-only Evidence",
            "status": "blocked" if report_only_missing else "allow",
            "ok": not report_only_missing,
            "blocking": bool(report_only_missing),
            "reason": "missing_report_only_evidence" if report_only_missing else "",
            "detail": "Para report-only evidence gate",
        },
        {
            "key": "roster",
            "label": "Roster Gate",
            "status": roster_gate.get("action") or "unknown",
            "ok": roster_gate.get("ok") is not False,
            "blocking": bool(roster_gate.get("blocking")),
            "reason": roster_gate.get("reason") or "",
            "detail": roster_gate.get("policy") or "",
        },
        {
            "key": "governance",
            "label": "Governance Gate",
            "status": governance_gate.get("action") or "unknown",
            "ok": governance_gate.get("ok") is not False,
            "blocking": bool(governance_gate.get("blocking")),
            "reason": governance_gate.get("reason") or "",
            "detail": governance_gate.get("policy") or "",
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if evo.get("pause") else "allow",
            "ok": not bool(evo.get("pause")),
            "blocking": bool(evo.get("pause")),
            "reason": evo.get("reason") or "",
            "detail": f"history={evo.get('history_count', 0)}",
        },
    ]
    blocking_items = [item for item in items if item.get("blocking")]
    return {
        "ok": not blocking_items,
        "blocking_count": len(blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in blocking_items],
        "items": items,
    }


def _write_loop_memory(memory: Dict[str, Any]) -> None:
    path = loop_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(memory, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def _memory_context(memory: Dict[str, Any]) -> str:
    recent_runs = memory.get("recent_runs") if isinstance(memory, dict) else []
    open_items = memory.get("open_items") if isinstance(memory, dict) else []
    closed_items = memory.get("closed_items") if isinstance(memory, dict) else []
    last_decision = memory.get("last_policy_decision") if isinstance(memory, dict) else None
    payload = {
        "closed_items": closed_items[-8:] if isinstance(closed_items, list) else [],
        "last_policy_decision": last_decision,
        "open_items": open_items[-8:] if isinstance(open_items, list) else [],
        "recent_runs": recent_runs[-5:] if isinstance(recent_runs, list) else [],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:6000]


def _coerce_str_set(values: Optional[List[str]]) -> set:
    return {str(value).strip() for value in (values or []) if str(value).strip()}


def _open_item_steps(item: Dict[str, Any]) -> List[str]:
    steps = item.get("steps")
    if not isinstance(steps, list):
        return []
    return [str(step) for step in steps if str(step)]


def _failed_open_item_identity(item: Dict[str, Any]) -> str:
    """Stable identity for max-retry open items; run_id alone is not unique enough."""

    return "|".join(
        [
            str(item.get("kind") or ""),
            str(item.get("run_id") or ""),
            str(item.get("branch") or ""),
            str(item.get("para_task_id") or item.get("task_id") or ""),
            ",".join(_open_item_steps(item)),
            str(item.get("created_at") or ""),
        ]
    )


def _open_item_matches_resolution(
    item: Dict[str, Any],
    *,
    branches: set,
    reasons: set,
    run_ids: set,
    task_ids: set,
) -> bool:
    if run_ids and str(item.get("run_id") or "") in run_ids:
        return True
    if branches and str(item.get("branch") or "") in branches:
        return True
    if reasons and str(item.get("reason") or "") in reasons:
        return True
    if task_ids:
        item_task_ids = {
            str(item.get("task_id") or ""),
            str(item.get("para_task_id") or ""),
        }
        if task_ids & {value for value in item_task_ids if value}:
            return True
    return False


def _close_open_items_in_memory(
    memory: Dict[str, Any],
    *,
    actor: str,
    branches: Optional[List[str]] = None,
    reasons: Optional[List[str]] = None,
    resolution_reason: str,
    run_ids: Optional[List[str]] = None,
    task_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []

    branch_set = _coerce_str_set(branches)
    reason_set = _coerce_str_set(reasons)
    run_id_set = _coerce_str_set(run_ids)
    task_id_set = _coerce_str_set(task_ids)
    kept: List[Dict[str, Any]] = []
    closed: List[Dict[str, Any]] = []
    closed_at = _iso(_utc_now())
    for item in open_items:
        if not isinstance(item, dict):
            continue
        if _open_item_matches_resolution(
            item,
            branches=branch_set,
            reasons=reason_set,
            run_ids=run_id_set,
            task_ids=task_id_set,
        ):
            closed.append(
                {
                    "actor": actor,
                    "closed_at": closed_at,
                    "original_item": item,
                    "resolution_reason": resolution_reason,
                }
            )
        else:
            kept.append(item)

    memory["open_items"] = kept[-50:]
    memory["closed_items"] = (closed_items + closed)[-200:]
    memory["updated_at"] = closed_at
    return {"closed_count": len(closed), "closed_items": closed}


def close_loop_memory_items(
    *,
    actor: str = "self_maintenance",
    branches: Optional[List[str]] = None,
    reasons: Optional[List[str]] = None,
    resolution_reason: str,
    run_ids: Optional[List[str]] = None,
    task_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Close resolved loop-memory risks without deleting audit history."""

    memory = _load_loop_memory()
    result = _close_open_items_in_memory(
        memory,
        actor=actor,
        branches=branches,
        reasons=reasons,
        resolution_reason=resolution_reason,
        run_ids=run_ids,
        task_ids=task_ids,
    )
    _write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }


def _close_items_resolved_by_final(memory: Dict[str, Any], final: Dict[str, Any]) -> Dict[str, Any]:
    decision = final.get("policy_decision")
    if not isinstance(decision, dict):
        decision = {}
    action = str(decision.get("action") or "")
    status = str(final.get("status") or "")
    if (
        action
        not in {
            "auto_merged_low_risk",
            "auto_continue",
        }
        and status != "completed_merged"
    ):
        return {"closed_count": 0, "closed_items": []}

    run_ids: List[str] = []
    task_ids: List[str] = []
    branches: List[str] = []
    resume_candidate = final.get("resume_candidate")
    if isinstance(resume_candidate, dict):
        failed_run_id = str(resume_candidate.get("failed_run_id") or "").strip()
        if failed_run_id:
            run_ids.append(failed_run_id)
        para_task_id = str(resume_candidate.get("para_task_id") or "").strip()
        if para_task_id:
            task_ids.append(para_task_id)
        branch = str(resume_candidate.get("branch") or "").strip()
        if branch:
            branches.append(branch)

    run_id = str(final.get("run_id") or "").strip()
    if run_id:
        run_ids.append(run_id)
    para_task_id = str(final.get("para_task_id") or "").strip()
    if para_task_id:
        task_ids.append(para_task_id)
    branch = str(final.get("branch") or "").strip()
    if branch:
        branches.append(branch)

    return _close_open_items_in_memory(
        memory,
        actor="self_maintenance_loop",
        branches=branches,
        resolution_reason=str(decision.get("reason") or status or "resolved_by_successful_loop"),
        run_ids=run_ids,
        task_ids=task_ids,
    )


def _resume_review_qa_candidate(memory: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_RESUME_REVIEW_QA", True):
        return None
    if not isinstance(memory, dict):
        return None
    max_retries = int(os.environ.get("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES") or "3")
    open_items_raw = memory.get("open_items")
    enqueue_success_keys: set[str] = set()
    if isinstance(open_items_raw, list):
        # First pass: collect items exceeding max retries, but only mark escalated after successful enqueue for non-code items
        over_retry_items = []
        for item in open_items_raw:
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and int(item.get("retry_count") or 1) >= max_retries
            ):
                over_retry_items.append(item)

        # Enqueue non-code escalated items to human uncertainty queue first, only mark escalated on success
        if over_retry_items:
            try:
                from modstore_server.human_uncertainty_queue import enqueue_uncertain_item

                for item in over_retry_items:
                    steps = _open_item_steps(item)
                    item_identity = _failed_open_item_identity(item)
                    if "code" in steps:
                        # Code failures are handled separately, keep in open_items for code fix retries
                        logger.warning(
                            "open_item identity=%s exceeded max_retries=%d, steps include code, will retry code remediation",
                            item_identity,
                            max_retries,
                        )
                        continue
                    # Non-code items: try to enqueue to human queue
                    logger.warning(
                        "open_item identity=%s exceeded max_retries=%d, escalating to human review",
                        item_identity,
                        max_retries,
                    )
                    try:
                        result = enqueue_uncertain_item(
                            context={
                                "run_id": item.get("run_id"),
                                "failed_steps": steps,
                                "retry_count": item.get("retry_count"),
                                "branch": item.get("branch"),
                                "para_task_id": item.get("para_task_id"),
                            },
                            decision={
                                "action": "await_human_strategy_approval",
                                "reason": "max_retries_exceeded",
                            },
                            reason=f"self-maintenance step {steps} failed {item.get('retry_count')} times, exceeded max retries",
                        )
                        if result.get("queued") or result.get("reason") == "duplicate":
                            item["escalated"] = True
                            enqueue_success_keys.add(item_identity)
                            logger.info(
                                "successfully enqueued escalated item identity=%s to human queue",
                                item_identity,
                            )
                        else:
                            logger.warning(
                                "failed to enqueue escalated item identity=%s to human queue, will retry next loop",
                                item_identity,
                            )
                    except Exception as exc:
                        logger.warning(
                            "failed to enqueue escalated item identity=%s to human queue: %s, will retry next loop",
                            item_identity,
                            exc,
                        )
            except Exception as exc:
                logger.warning("failed to import human uncertainty queue: %s", exc)

        # Remove only successfully enqueued non-code escalated items from open_items; keep others for retry/visibility
        if enqueue_success_keys:
            memory["open_items"] = [
                item
                for item in open_items_raw
                if not (
                    isinstance(item, dict)
                    and item.get("kind") == "failed_steps"
                    and int(item.get("retry_count") or 1) >= max_retries
                    and "code" not in _open_item_steps(item)
                    and _failed_open_item_identity(item) in enqueue_success_keys
                )
            ]
        else:
            memory["open_items"] = open_items_raw
    # Escalated non-code failures are removed from open_items above; do not stop
    # the whole loop when other branches still have executable remediation holds.

    # KB schema retry: if there's a non-escalated kb_schema_retry open_item,
    # return None to trigger a fresh code step. The employee will see the
    # previous KB schema errors in loop memory (via _memory_context) and
    # should produce a corrected branch. Escalated items (retry_count >=
    # KB_SCHEMA_RETRY_MAX) are skipped so the loop waits for human review.
    if isinstance(open_items_raw, list):
        for item in reversed(open_items_raw):
            if not isinstance(item, dict):
                continue
            if item.get("kind") != "kb_schema_retry":
                continue
            if item.get("escalated"):
                continue
            logger.info(
                "kb_schema_retry: resuming fresh code step for run_id=%s retry_count=%d",
                item.get("run_id"),
                int(item.get("retry_count") or 0),
            )
            return None

    last_decision = memory.get("last_policy_decision")
    last_reason = str(last_decision.get("reason") or "") if isinstance(last_decision, dict) else ""
    if last_reason == "review_or_qa_reported_risk":
        # Real risk remains blocked; removing approval must never turn it into a bypass.
        return None
    if last_reason in {"employee_step_failed", "loop_not_completed"}:
        # Allow resumption for incomplete loops or step failures (e.g., code step can retry)
        pass
    open_items = memory.get("open_items")
    recent_runs = memory.get("recent_runs")
    if not isinstance(open_items, list) or not isinstance(recent_runs, list):
        return None

    # First check for code step failures that need retry (before review/qa)
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") != "failed_steps":
            continue
        steps = item.get("steps")
        if not isinstance(steps, list) or "code" not in steps:
            continue
        retry_count = int(item.get("retry_count") or 1)
        if retry_count >= max_retries:
            continue  # Already handled escalation above
        # Code failures without branch/task_id need fresh run (return None to start from code step)
        if not item.get("branch") and not item.get("para_task_id"):
            return None
        # Code failures with existing branch/task_id can resume if we have context
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("para_task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if branch and para_task_id:
            return {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(steps),
                "para_task_id": para_task_id,
                "reason": "resume_failed_code_step",
            }

    # Code-level remediation takes priority over review/QA-only retries. Walk
    # newest-first so a stale branch/failure pair cannot starve a later hold
    # that already contains the current independent-review findings.
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",  # legacy ledger compatibility
        }:
            continue
        reason = _normalize_automated_remediation_reason(memory, item)
        resume_plan = _automated_remediation_resume_plan(reason)
        if resume_plan is None:
            continue
        failed_steps, continue_existing_code_task = resume_plan
        if "code" not in failed_steps:
            continue
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        if not branch or not para_task_id:
            continue
        candidate: Dict[str, Any] = {
            "branch": branch,
            "failed_run_id": str(item.get("run_id") or "").strip(),
            "failed_steps": list(failed_steps),
            "para_task_id": para_task_id,
            "reason": "resume_automated_remediation_candidate",
        }
        if reason.startswith("para_merge_"):
            candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
            candidate["remediation_reason"] = reason
        elif reason == RETORT_SCOPE_REASON:
            candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
            candidate["remediation_reason"] = reason
        if continue_existing_code_task:
            if reason.startswith("para_merge_"):
                if para_merge_resume_pins_rejected_branch(item):
                    candidate["continue_existing_code_task"] = True
            elif not item.get("resume_from_clean_baseline"):
                candidate["continue_existing_code_task"] = True
        return candidate

    # Para merge AI review vetoes are not in the generic code-resume plan, so a
    # stale failed_steps review/qa hold must not starve the newest veto remediation.
    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",  # legacy ledger compatibility
        }:
            continue
        candidate = resume_candidate_from_para_ai_review_item(memory, item)
        if candidate is not None:
            return candidate

    # Then check for review/qa failures
    review_failed_run_ids = set()
    for item in open_items:
        if not isinstance(item, dict) or item.get("kind") != "failed_steps":
            continue
        steps = item.get("steps")
        if not isinstance(steps, list):
            continue
        if any(str(step) in {"review", "qa"} for step in steps):
            run_id = str(item.get("run_id") or "")
            if run_id:
                review_failed_run_ids.add((run_id, tuple(str(step) for step in steps)))

    for run in reversed(recent_runs):
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or "")
        matched_steps = None
        for candidate_run_id, candidate_steps in review_failed_run_ids:
            if run_id == candidate_run_id:
                matched_steps = candidate_steps
                break
        if matched_steps is None:
            continue
        branch = str(run.get("branch") or "").strip()
        para_task_id = str(run.get("para_task_id") or "").strip()
        if branch and para_task_id:
            return {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(matched_steps),
                "para_task_id": para_task_id,
                "reason": "resume_failed_review_or_qa",
            }

    for item in reversed(open_items):
        if not isinstance(item, dict) or item.get("kind") not in {
            "automated_remediation",
            "human_strategy_approval",  # legacy ledger compatibility
        }:
            continue
        reason = _normalize_automated_remediation_reason(memory, item)
        candidate = resume_candidate_from_para_ai_review_item(memory, item)
        if candidate is not None:
            return candidate
        if reason in {
            "auto_merge_safety_score_v2_too_low",
            "auto_merge_safety_score_v3_too_low",
            "risk_score_v3_below_threshold_or_blocked",
        }:
            branch = str(item.get("branch") or "").strip()
            para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
            run_id = str(item.get("run_id") or "").strip()
            if branch and para_task_id:
                return {
                    "branch": branch,
                    "continue_existing_code_task": True,
                    "failed_run_id": run_id,
                    "failed_steps": ["code"],
                    "para_task_id": para_task_id,
                    "reason": "resume_safety_score_remediation",
                }
            continue
        resume_plan = _automated_remediation_resume_plan(reason)
        if resume_plan is None:
            continue
        failed_steps, continue_existing_code_task = resume_plan
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("task_id") or item.get("para_task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if branch and para_task_id:
            candidate: Dict[str, Any] = {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": list(failed_steps),
                "para_task_id": para_task_id,
                "reason": "resume_automated_remediation_candidate",
            }
            if reason.startswith("para_merge_"):
                candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
                candidate["remediation_reason"] = reason
            elif reason == RETORT_SCOPE_REASON:
                candidate["remediation_feedback"] = str(item.get("detail") or "")[:4000]
                candidate["remediation_reason"] = reason
            if continue_existing_code_task:
                if reason.startswith("para_merge_"):
                    if para_merge_resume_pins_rejected_branch(item):
                        candidate["continue_existing_code_task"] = True
                elif not item.get("resume_from_clean_baseline"):
                    candidate["continue_existing_code_task"] = True
            return candidate
    return None


def _resume_steps(resume_candidate: Optional[Dict[str, Any]]) -> set[str]:
    """Return the failed step and every downstream step that must be rerun."""

    if not resume_candidate:
        return {"code", "review", "qa"}
    failed = {str(item) for item in (resume_candidate.get("failed_steps") or [])}
    if "code" in failed:
        return {"code", "review", "qa"}
    if "review" in failed:
        return {"review", "qa"}
    if "qa" in failed:
        return {"qa"}
    return set()


def _resume_dispatch_context(
    resume_candidate: Optional[Dict[str, Any]], steps_to_run: set[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Choose the Para task id and base branch for a resumed loop.

    Code retries must use a fresh Para task. A score remediation still keeps
    the prior candidate branch as its base so the production fix survives.
    A merge-review rejection starts from the configured clean base and treats
    the rejected branch as reference only; otherwise each rejection compounds
    the previous diff until the reviewer can never accept it. Review/QA-only
    retries keep the original task and branch for evidence.
    """

    if not resume_candidate:
        return None, None
    para_task_id = str(resume_candidate.get("para_task_id") or "").strip() or None
    code_branch = str(resume_candidate.get("branch") or "").strip() or None
    if "code" not in steps_to_run:
        return para_task_id, code_branch
    if resume_candidate.get("continue_existing_code_task"):
        return None, code_branch
    return None, None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _file_url_to_path(repo_url: str) -> Optional[Path]:
    if not repo_url.startswith("file://"):
        return None
    parsed = urlparse(repo_url)
    return Path(unquote(parsed.path))


def _self_maintenance_actor_user_id() -> int:
    """自维护 loop 的 LLM 执行身份（默认平台身份 ``user_id=0``）。

    ``services.llm.chat_dispatch_via_session`` 仅在 ``uid > 0`` 时调
    ``quota_middleware.require_llm_credit`` 走某真实用户的个人 ``llm_calls`` 月配额闸；
    传 ``0`` 即跳过该配额、改用 ``llm_key_resolver.resolve_api_key`` 的平台密钥
    （``user_id=0`` 无 BYOK 凭证行，自然回落 ``platform_api_key``）。指标表 ``user_id``
    仍由 ``employee_executor._resolve_metric_user_id`` 回落到真实 ``users.id``，监控不丢。

    历史 bug：本函数旧实现（``_first_user_id``）取「库里第一个真实用户」作执行身份，
    使平台自治工作全部记到 owner 个人配额上；其额度耗尽后整条 loop 持续报
    ``403: 配额不足: llm_calls``（生产实测 99.6% 失败的根因）。

    运维如需按某真实用户 BYOK/配额计费，可设 ``MODSTORE_SELF_MAINTENANCE_USER_ID=<uid>``。
    """
    env_uid = os.environ.get("MODSTORE_SELF_MAINTENANCE_USER_ID", "").strip()
    if env_uid:
        try:
            return int(env_uid)
        except ValueError:
            logger.warning("MODSTORE_SELF_MAINTENANCE_USER_ID not an int: %s", env_uid)
    return 0


def _recent_employee_failure_count(lookback_hours: int) -> int:
    since = _utc_now() - timedelta(hours=lookback_hours)
    db = get_session_factory()()
    try:
        return (
            db.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.created_at >= since)
            .filter(EmployeeExecutionMetric.status != "success")
            .count()
        )
    except Exception:
        logger.exception("failed to count recent employee failures")
        return 1
    finally:
        db.close()


def _recent_incident_signals(lookback_hours: int, *, limit: int = 8) -> Dict[str, Any]:
    """Return fresh incident signals that should wake the maintenance loop.

    The 03:00 cron remains as a batch safety net, but Phase A treats new
    quality/error/security incidents as a real-time signal for employee
    delegation.
    """

    since = _utc_now() - timedelta(hours=lookback_hours)
    event_types = {
        "ci.failed",
        "incident.unknown",
        "on_error",
        "on_quality_fail",
        "security.alert",
    }
    db = get_session_factory()()
    try:
        query = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.created_at >= since)
            .filter(IncidentEvent.event_type.in_(sorted(event_types)))
            .order_by(IncidentEvent.created_at.desc())
        )
        rows = query.limit(max(1, int(limit))).all()
        count = query.count()
        incidents: List[Dict[str, Any]] = []
        for row in rows:
            payload: Dict[str, Any] = {}
            try:
                loaded = json.loads(row.payload_json or "{}")
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {}
            incidents.append(
                {
                    "created_at": (
                        _iso(row.created_at)
                        if isinstance(row.created_at, datetime)
                        else str(row.created_at or "")
                    ),
                    "event_type": row.event_type,
                    "fingerprint": row.fingerprint,
                    "id": int(row.id),
                    "source": row.source,
                    "summary": str(payload.get("summary") or "")[:500],
                }
            )
        return {
            "count": int(count),
            "events": incidents,
            "lookback_hours": lookback_hours,
        }
    except Exception:
        logger.exception("failed to read recent incident signals")
        return {"count": 1, "events": [], "error": "incident_signal_query_failed"}
    finally:
        db.close()


def evaluate_self_maintenance_need() -> Dict[str, Any]:
    """Return deterministic signals used by the threshold gate."""

    gaps: List[str] = []
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    device_id = os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    runtime_provenance = collect_runtime_provenance(target_branch=branch or "main")

    if not api_base:
        gaps.append("missing MODSTORE_PARA_API_BASE")
    if not device_id:
        gaps.append("missing MODSTORE_PARA_DEVICE_ID")
    if not repo_url:
        gaps.append("missing MODSTORE_PARA_REPO_URL")
    elif "/Desktop/" in repo_url and not _env_bool(
        "MODSTORE_SELF_MAINTENANCE_ALLOW_DESKTOP_REPO", False
    ):
        gaps.append("repo url still points into Desktop")
    if not branch:
        gaps.append("missing MODSTORE_PARA_BRANCH")
    if _env_bool(
        "MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True
    ) and not runtime_provenance.get("ok"):
        reasons = ",".join(str(item) for item in runtime_provenance.get("reasons") or [])
        gaps.append(f"runtime provenance blocked: {reasons or 'unknown'}")

    repo_path = _file_url_to_path(repo_url)
    if repo_path is not None and not repo_path.exists():
        gaps.append(f"repo url path does not exist: {repo_path}")

    lookback_hours = _env_int("MODSTORE_SELF_MAINTENANCE_LOOKBACK_HOURS", 24)
    failure_count = _recent_employee_failure_count(lookback_hours)
    incident_signals = _recent_incident_signals(lookback_hours)
    incident_count = int(incident_signals.get("count") or 0)
    proactive_signals = collect_proactive_signals()
    proactive_task_count = (
        len(proactive_signals.get("candidates") or [])
        if _env_bool("MODSTORE_SELF_EVOLUTION_PROACTIVE_ENABLED", True)
        else 0
    )
    signal_count = len(gaps) + failure_count + incident_count + proactive_task_count

    return {
        "api_base": api_base,
        "branch": branch,
        "device_id": device_id,
        "failure_count": failure_count,
        "gaps": gaps,
        "incident_count": incident_count,
        "incident_signals": incident_signals,
        "lookback_hours": lookback_hours,
        "proactive_signals": proactive_signals,
        "proactive_task_count": proactive_task_count,
        "repo_url": repo_url,
        "runtime_provenance": runtime_provenance,
        "signal_count": signal_count,
    }


def _last_started_at() -> Optional[datetime]:
    for row in reversed(_read_ledger()):
        if row.get("phase") == "start":
            return _parse_iso(row.get("started_at") or row.get("created_at"))
    return None


def reconcile_stale_self_maintenance_runs(
    *, exclusive_lease_reacquired: bool = False
) -> Dict[str, Any]:
    """Close interrupted runs without misreporting them as completed work.

    When the caller has just acquired the process-wide loop lease, any older
    start row without a terminal row is necessarily orphaned: an actually
    running transaction would still own the same OS lock.  Reconcile that case
    immediately instead of leaving the management console in ``running`` for
    the full stale timeout after a deploy or process restart.  Callers that do
    not hold the lease retain the conservative age-based behavior.
    """

    rows = _read_ledger(limit=300)
    started: Dict[str, Dict[str, Any]] = {}
    terminal: Dict[str, Dict[str, Any]] = {}
    steps_by_run: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[run_id] = row
        elif phase in {"complete", "skip"}:
            terminal[run_id] = row
        elif phase in {"step", "step_retry"}:
            steps_by_run.setdefault(run_id, []).append(row)

    # 默认 180 分钟：3 step × 30 分钟 + 内层重试 + dispatch 延迟的余量。
    # 旧默认 90 分钟刚好卡在 (wait_timeout_sec=1800 × 3) 边界，加任何 dispatch
    # 延迟就超时 → abandoned_stale。提到 180 给足余量。
    stale_minutes = _env_int("MODSTORE_SELF_MAINTENANCE_STALE_RUN_MINUTES", 180)
    cutoff = _utc_now() - timedelta(minutes=stale_minutes)
    reconciled: List[str] = []
    for run_id, start in started.items():
        if run_id in terminal:
            continue
        started_at = _parse_iso(start.get("started_at") or start.get("created_at"))
        if started_at is None:
            continue
        if not exclusive_lease_reacquired and started_at > cutoff:
            continue

        interrupted = bool(exclusive_lease_reacquired)
        terminal_status = "abandoned_interrupted" if interrupted else "abandoned_stale"
        terminal_reason = (
            "interrupted_run_after_lease_reacquired" if interrupted else "stale_interrupted_run"
        )
        terminal_error = (
            "previous process lost the exclusive loop lease before writing a terminal record"
            if interrupted
            else "run did not write a terminal record before stale timeout"
        )

        # 找该 run 最后一个 step 终态；如果只有 step_retry 没有 phase=step，
        # 说明某个 step 的内层重试还没收敛就超时了——补一条 step 终态记录，
        # 让下游查询能看到完整 step 链路。
        run_steps = steps_by_run.get(run_id) or []
        last_step_phase = str(run_steps[-1].get("phase") or "") if run_steps else ""
        if last_step_phase == "step_retry":
            last_step = run_steps[-1]
            step_terminal = {
                "employee_id": last_step.get("employee_id"),
                "error": (
                    "step interrupted before the process released its loop lease"
                    if interrupted
                    else "step abandoned during inner retry before stale timeout"
                ),
                "ok": False,
                "phase": "step",
                "run_id": run_id,
                "status": terminal_status,
                "step": last_step.get("step"),
                "timestamp": _iso(_utc_now()),
            }
            _append_ledger(step_terminal)

        final = {
            "completed_at": _iso(_utc_now()),
            "error": terminal_error,
            "phase": "complete",
            "policy_decision": {
                "action": "stop",
                "reason": terminal_reason,
                "exclusive_lease_reacquired": interrupted,
                "recovery_required": interrupted,
                "stale_minutes": stale_minutes,
            },
            "recovery_required": interrupted,
            "run_id": run_id,
            "started_at": _iso(started_at),
            "status": terminal_status,
            "triggered_by": start.get("triggered_by"),
        }
        _append_ledger(final)
        reconciled.append(run_id)
    return {
        "exclusive_lease_reacquired": bool(exclusive_lease_reacquired),
        "reconciled": reconciled,
        "stale_minutes": stale_minutes,
    }


def should_run_self_maintenance_loop(
    force: bool = False, triggered_by: str = "manual"
) -> Dict[str, Any]:
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_ENABLED", True):
        return {"should_run": False, "reason": "disabled"}

    evaluation = evaluate_self_maintenance_need()
    runtime_provenance = evaluation.get("runtime_provenance")
    if (
        _env_bool("MODSTORE_SELF_MAINTENANCE_REQUIRE_CLEAN_RUNTIME", True)
        and isinstance(runtime_provenance, dict)
        and not runtime_provenance.get("ok")
    ):
        return {
            **evaluation,
            "force_requested": force,
            "reason": "runtime_provenance_blocked",
            "should_run": False,
            "triggered_by": triggered_by,
        }
    metrics_gate = evolution_metrics_gate()
    if not force and metrics_gate.get("pause"):
        return {
            **evaluation,
            "evolution_metrics_gate": metrics_gate,
            "reason": "evolution_metrics_pause",
            "should_run": False,
        }
    threshold = _env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1)
    from modstore_server.autonomy_scheduler import self_maintenance_cooldown_minutes

    cooldown_minutes = self_maintenance_cooldown_minutes(triggered_by)
    last_started = _last_started_at()
    pending_recovery = pending_run_recovery(_read_ledger(limit=300), triggered_by)
    recovery_kind = str((pending_recovery or {}).get("kind") or "")
    recovery_detail = (pending_recovery or {}).get("detail")
    interrupted_recovery = recovery_detail if recovery_kind == "interrupted_recovery" else None
    transient_failure_recovery = (
        recovery_detail if recovery_kind == "transient_failure_recovery" else None
    )

    if not force and pending_recovery is None and last_started is not None and cooldown_minutes > 0:
        next_allowed = last_started + timedelta(minutes=cooldown_minutes)
        if _utc_now() < next_allowed:
            return {
                **evaluation,
                "cooldown_minutes": cooldown_minutes,
                "next_allowed_at": _iso(next_allowed),
                "reason": "cooldown",
                "should_run": False,
                "threshold": threshold,
                "triggered_by": triggered_by,
            }

    if not force and pending_recovery is None and int(evaluation["signal_count"]) < threshold:
        return {
            **evaluation,
            "cooldown_minutes": cooldown_minutes,
            "reason": "below_threshold",
            "should_run": False,
            "threshold": threshold,
        }

    return {
        **evaluation,
        "cooldown_minutes": cooldown_minutes,
        "interrupted_recovery": interrupted_recovery,
        "transient_failure_recovery": transient_failure_recovery,
        "reason": (
            "force"
            if force
            else (
                "interrupted_recovery"
                if interrupted_recovery is not None
                else (
                    "transient_failure_recovery"
                    if transient_failure_recovery is not None
                    else "threshold_met"
                )
            )
        ),
        "should_run": True,
        "threshold": threshold,
    }


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


def _employee_result_ok(result: Dict[str, Any]) -> bool:
    if not result or result.get("handler_failed"):
        return False
    report_text = _extract_report_excerpt(result).lower()
    if "blocked by risk middleware" in report_text:
        return False
    if any(
        marker in report_text
        for marker in (
            "[e2e-agent] codex cli 失败",
            "[e2e-agent] cursor agent 失败",
            "codex cli timeout after",
            "report-only 执行器失败",
        )
    ):
        return False
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if str(inner.get("status", "")).lower() in {"failed", "error"}:
        return False
    if not bool(inner.get("ok", True)):
        return False
    outputs = inner.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("ok") is False:
                return False
    # Nested delivery_validation with non-zero exit codes is hard failure evidence
    # even when the outer Para envelope claims ok=True.
    dv_gate = _delivery_validation_gate(result)
    if dv_gate.get("found") and not dv_gate.get("ok"):
        return False
    return True


def _delivery_validation_command_failed(command: Any) -> bool:
    return isinstance(command, dict) and command.get("exit_code") not in (0, None)


def _delivery_validation_gate(result: Any) -> Dict[str, Any]:
    """Evaluate nested delivery_validation for closed-loop completion evidence.

    Returns a stable dict used by validate/writeback completion checks:
      found / ok / reason / delivery_validation
    """
    dv = _find_delivery_validation(result)
    if not isinstance(dv, dict):
        return {
            "delivery_validation": None,
            "found": False,
            "ok": True,
            "reason": "delivery_validation_absent",
        }
    cmds = dv.get("commands")
    if not isinstance(cmds, list) or not cmds:
        return {
            "delivery_validation": dv,
            "found": True,
            "ok": True,
            "reason": "delivery_validation_no_commands",
        }
    failed_cmds = [c for c in cmds if _delivery_validation_command_failed(c)]
    if failed_cmds:
        return {
            "delivery_validation": dv,
            "failed_commands": failed_cmds[:3],
            "found": True,
            "ok": False,
            "reason": "delivery_validation_failed",
        }
    return {
        "delivery_validation": dv,
        "found": True,
        "ok": True,
        "reason": "delivery_validation_passed",
    }


def _find_delivery_validation(obj: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    """递归查找 result 里的 delivery_validation dict（Para 远端返回）。

    delivery_validation 不在本地代码产出，由 Para 平台返回时嵌在
    result.result.outputs[].response / para_result 等任意层级，故需递归。

    Determinism contract:
    - Prefer canonical Para nests (``para_result`` / ``response`` / ``outputs`` / …)
      before other keys.
    - Remaining dict keys are visited in sorted order (not insertion order).
    - Lists keep the first 12 items; depth is capped at 6.
    - When multiple DVs exist, prefer the one with a ``commands`` list (and among
      those, the one with non-zero exit_code evidence).
    """
    candidates: List[Tuple[Tuple[int, int, int, int], Dict[str, Any]]] = []
    _collect_delivery_validation_candidates(obj, depth=depth, out=candidates)
    if not candidates:
        return None
    # Higher score wins; tie-break by discovery rank (earlier preferred path).
    best = max(candidates, key=lambda item: (item[0][0], item[0][1], item[0][2], -item[0][3]))
    return best[1]


def _collect_delivery_validation_candidates(
    obj: Any,
    *,
    depth: int,
    out: List[Tuple[Tuple[int, int, int, int], Dict[str, Any]]],
    rank: int = 0,
) -> int:
    """Collect scored delivery_validation candidates; returns next discovery rank."""
    if depth > 6 or not isinstance(obj, (dict, list)):
        return rank
    if isinstance(obj, dict):
        dv = obj.get("delivery_validation")
        if isinstance(dv, dict):
            cmds = dv.get("commands") if isinstance(dv.get("commands"), list) else []
            failed = sum(1 for c in cmds if _delivery_validation_command_failed(c))
            # score: has_commands, failed_count, commands_len, -rank
            out.append(((1 if cmds else 0, failed, len(cmds), rank), dv))
            rank += 1
        preferred_present = [
            key
            for key in _DELIVERY_VALIDATION_PREFERRED_KEYS
            if key in obj and key != "delivery_validation"
        ]
        remaining = sorted(
            key
            for key in obj.keys()
            if key not in _DELIVERY_VALIDATION_PREFERRED_KEYS and key != "delivery_validation"
        )
        for key in preferred_present + remaining:
            rank = _collect_delivery_validation_candidates(
                obj.get(key), depth=depth + 1, out=out, rank=rank
            )
        return rank
    for item in obj[:12]:
        rank = _collect_delivery_validation_candidates(item, depth=depth + 1, out=out, rank=rank)
    return rank


def _extract_failure_reason(
    result: Dict[str, Any], para_meta: Optional[Dict[str, Any]] = None
) -> str:
    """Extract a human-readable failure reason from an employee execution result.

    Used to enrich ledger records so failures stop being silent (ok=False with
    no explanation). Order: explicit error fields > status markers > report text.
    """
    if not result:
        return "empty_result"

    # 优先挖 result.result.outputs 里 ok=False 的具体 handler 错误（最精确），
    # 再退回到顶层 handler_failed 标记 / para 错误 / report 文本标记。
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    inner_outputs_failure = ""
    if isinstance(inner, dict):
        outputs = inner.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, dict) and item.get("ok") is False:
                    handler = str(item.get("handler") or item.get("name") or "")
                    err = item.get("error") or item.get("message") or item.get("stderr")
                    detail = item.get("detail") or item.get("reason")
                    parts = [f"handler={handler}"] if handler else []
                    if err:
                        parts.append(f"error={str(err)[:200]}")
                    if detail:
                        parts.append(f"detail={str(detail)[:120]}")
                    inner_outputs_failure = (
                        "output_failed: " + " ".join(parts) if parts else "output ok=False"
                    )
                    break

    # path_guard 失败：vibe-coding-maintainer 等 scope_globs 限定导致 changed_files 越权。
    # 这种情况下 outputs 里 handler item.ok 可能是 True，但 path_guard.ok=False 仍把
    # handler_ok 置 False（见 employee_executor._handlers_execution_ok 之后的 path_guard 分支）。
    path_guard_failure = ""
    if isinstance(inner, dict):
        pg = inner.get("path_guard")
        if isinstance(pg, dict) and pg.get("checked") and not pg.get("ok"):
            violations = pg.get("violations") or []
            vstr = "; ".join(
                f"{v.get('path', '')}({v.get('reason', '')})"
                for v in violations[:5]
                if isinstance(v, dict)
            )
            path_guard_failure = (
                f"path_guard_violation: {vstr}"[:300] if vstr else "path_guard_violation"
            )

    # handler_failed 顶层标记
    if result.get("handler_failed"):
        msg = result.get("handler_failed_message") or result.get("error")
        if msg:
            return f"handler_failed: {str(msg)[:300]}"
        if path_guard_failure:
            return path_guard_failure
        if inner_outputs_failure:
            return inner_outputs_failure
        return "handler_failed"

    # 显式 path_guard / outputs 失败但没顶层 handler_failed 标记
    if path_guard_failure:
        return path_guard_failure
    if inner_outputs_failure:
        return inner_outputs_failure

    # delivery_validation 失败：员工交付了代码（change_delivery.ok=true）但验证命令
    # （测试/lint）失败。这是 code step 最常见的静默失败来源——_employee_result_ok
    # 判 False 但其他分支都提不到原因。delivery_validation 由 Para 远端返回，嵌在
    # result 任意层级，用 deterministic `_delivery_validation_gate` 定位。
    dv_gate = _delivery_validation_gate(result)
    if dv_gate.get("found") and not dv_gate.get("ok"):
        failed_cmds = dv_gate.get("failed_commands") or []
        parts: List[str] = []
        for c in failed_cmds[:3]:
            if not isinstance(c, dict):
                continue
            ec = c.get("exit_code")
            cmd = str(c.get("command") or "")[:80]
            tail = str(c.get("output_tail") or c.get("output") or "")[:120]
            seg = f"exit={ec}"
            if cmd:
                seg += f" cmd={cmd}"
            if tail:
                seg += f" tail={tail}"
            parts.append(seg)
        if parts:
            return "delivery_validation_failed: " + " | ".join(parts)[:300]
        return "delivery_validation_failed"

    # para 层错误（走 Para bridge 时）
    if isinstance(para_meta, dict):
        para_err = para_meta.get("error")
        if para_err:
            return f"para_error: {str(para_err)[:300]}"
        para_status = str(para_meta.get("para_status") or "").lower()
        if para_status and para_status not in {"completed", "ok", "success", ""}:
            return f"para_status={para_status}"

    if isinstance(inner, dict):
        status = str(inner.get("status") or "").lower()
        if status in {"failed", "error"}:
            return f"inner_status={status}: {str(inner.get('error') or inner.get('message') or '')[:200]}"

    # 从 report_excerpt 里找已知失败标记
    report = _extract_report_excerpt(result).lower()
    markers = (
        ("blocked by risk middleware", "blocked_by_risk_middleware"),
        ("codex cli 失败", "codex_cli_failed"),
        ("cursor agent 失败", "cursor_agent_failed"),
        ("codex cli timeout after", "codex_cli_timeout"),
        ("report-only 执行器失败", "report_only_executor_failed"),
        ("无法完成", "agent_gave_up"),
        ("无法完成修复", "agent_gave_up_fix"),
        ("需要更多轮次或人工介入", "agent_needs_human"),
        ("达到最大工具调用轮次", "agent_max_rounds_reached"),
    )
    for marker, label in markers:
        if marker in report:
            return label

    return "ok_false_unknown_reason"


def _extract_para_meta(result: Dict[str, Any]) -> Dict[str, Any]:
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    outputs = inner.get("outputs") if isinstance(inner, dict) else None
    output = None
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("handler") == "para_delegate":
                output = item
                break
    if output is None and isinstance(inner, dict):
        output = inner

    response = output.get("response") if isinstance(output, dict) else None
    para_result = output.get("para_result") if isinstance(output, dict) else None
    if not isinstance(response, dict):
        response = {}
    if not isinstance(para_result, dict):
        para_result = {}

    subtasks = para_result.get("subtasks")
    first_subtask = subtasks[0] if isinstance(subtasks, list) and subtasks else {}

    return {
        "branch": first_subtask.get("branch") or first_subtask.get("branchName"),
        "completed_at": para_result.get("completed_at"),
        "error": output.get("error") if isinstance(output, dict) else None,
        "para_status": para_result.get("status"),
        "subtask_id": first_subtask.get("id") or response.get("subtaskId"),
        "task_id": para_result.get("task_id") or para_result.get("id") or response.get("taskId"),
    }


def _collect_text_fields(value: Any, out: List[str], depth: int = 0) -> None:
    if depth > 6 or len(out) >= 24:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return
    if isinstance(value, list):
        for item in value[:12]:
            _collect_text_fields(item, out, depth + 1)
        return
    if isinstance(value, dict):
        preferred = {
            "content",
            "detail",
            "error",
            "message",
            "output",
            "report",
            "stderr",
            "stdout",
            "summary",
        }
        for key in preferred:
            if key in value:
                _collect_text_fields(value.get(key), out, depth + 1)
        for key, item in list(value.items())[:24]:
            if key not in preferred:
                _collect_text_fields(item, out, depth + 1)


def _extract_report_excerpt(result: Dict[str, Any], limit: int = 4000) -> str:
    texts: List[str] = []
    _collect_text_fields(result, texts)
    seen = set()
    compact: List[str] = []
    for text in texts:
        normalized = " ".join(text.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        compact.append(normalized)
        if sum(len(x) for x in compact) >= limit:
            break
    return "\n".join(compact)[:limit]


def _is_transient_employee_dispatch_failure(result: Dict[str, Any]) -> bool:
    # Accepted wait-timeout is not a transient network blip: the Para task was
    # already created. Redispatching would duplicate work (see kb fix
    # 20260723T062851Z-fix-accepted-para-timeout-duplicate-code-retry).
    if _is_accepted_para_wait_timeout(result):
        return False
    return is_transient_dispatch_failure(result)


def _coerce_truthy_flag(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _para_item_is_accepted_wait_timeout(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    handler = str(item.get("handler") or "").strip()
    if handler and handler != "para_delegate":
        return False
    if not _coerce_truthy_flag(item.get("accepted")):
        return False
    status = str(item.get("status") or "").strip().lower()
    if status == "para_task_timeout":
        return True
    # Some wrappers put the wait outcome under para_result / snapshot.status.
    for nest_key in ("para_result", "snapshot", "response"):
        nested = item.get(nest_key)
        if isinstance(nested, dict):
            nested_status = str(nested.get("status") or "").strip().lower()
            if nested_status == "para_task_timeout":
                return True
    return False


def _is_accepted_para_wait_timeout(result: Dict[str, Any]) -> bool:
    """Detect an accepted Para task whose synchronous wait expired.

    Shapes covered (all mean: task accepted, do NOT start code_fix redispatch):
    - ``result.outputs[]`` para_delegate item with accepted + para_task_timeout
    - flat handler dict at top-level / ``result``
    - accepted flag as bool/1/\"true\"; timeout status on item or nested para_result
    """
    if not isinstance(result, dict):
        return False
    if _para_item_is_accepted_wait_timeout(result):
        return True
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if _para_item_is_accepted_wait_timeout(inner):
        return True
    outputs = inner.get("outputs") if isinstance(inner, dict) else None
    if not isinstance(outputs, list):
        return False
    return any(_para_item_is_accepted_wait_timeout(item) for item in outputs)


def _loop_platform_bench_override() -> Optional[tuple]:
    """后台自维护/进化 loop 默认走平台派发：LLM 成本记平台密钥、不查/扣用户 ``llm_calls`` 配额。

    与 digest 产线一致——后台自治 loop 不该按「用户调用」计量。``_first_user_id()`` 返回的是
    第一个真实用户，挂到其月度配额上几小时就 ``403 配额不足: llm_calls``（生产实测疯跑 99.6%
    失败、进化引擎误把配额失败当 prompt 问题狂改的根因）。返回平台 bench (provider, model) 作为
    ``bench_llm_override`` → cognition ``use_platform_dispatch=True`` → 不经 require_llm_credit；
    ``user_id`` 仍透传给 RAG/指标。关闭（回退按用户配额）：``MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM=0``。
    """
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_PLATFORM_LLM", True):
        return None
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        rp, rm = resolve_platform_bench_llm()
        if rp and rm:
            return (rp, rm)
    except Exception:  # noqa: BLE001
        return None
    return None


def _execute_employee_task_with_retries(
    employee_id: str,
    task_text: str,
    input_data: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    retries = max(0, _env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRIES", 2))
    delay_sec = max(1, _env_int("MODSTORE_SELF_MAINTENANCE_STEP_RETRY_DELAY_SEC", 10))
    attempts = retries + 1
    bench_override = _loop_platform_bench_override()
    result: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        device_wait = _wait_for_para_device_online()
        if not device_wait.get("online"):
            logger.warning(
                "self-maintenance para device not online before dispatch employee=%s attempt=%s/%s detail=%s",
                employee_id,
                attempt,
                attempts,
                device_wait,
            )
        result = execute_employee_task(
            employee_id,
            task_text,
            input_data,
            user_id=user_id,
            bench_llm_override=bench_override,
        )
        if _employee_result_ok(result):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        if attempt >= attempts or not _is_transient_employee_dispatch_failure(result):
            result["self_maintenance_retry_attempts"] = attempt
            return result
        logger.warning(
            "self-maintenance employee step transient dispatch failure; retrying employee=%s attempt=%s/%s",
            employee_id,
            attempt,
            attempts,
        )
        time.sleep(delay_sec)
    result["self_maintenance_retry_attempts"] = attempts
    return result


def _run_step_with_inner_retries(
    *,
    employee_id: str,
    step_name: str,
    task_text: str,
    extra: Dict[str, Any],
    user_id: int,
    run_id: str,
) -> Tuple[Dict[str, Any], bool, str, Dict[str, Any], str, int, int]:
    """Run code fix retries or report protocol/infrastructure retries.

    Returns the final employee result plus retry counters. Intermediate attempts
    are recorded as ``phase=step_retry`` without polluting the final step list.
    """
    if step_name == "code":
        inner_max = max(1, _env_int("MODSTORE_SELF_MAINTENANCE_CODE_FIX_RETRIES", 2) + 1)
        retry_kind = "code_fix"
    else:
        # Default 2 extra rounds: protocol follow-rate target ≥90% (was ~46% with 1 retry).
        inner_max = max(1, _env_int("MODSTORE_SELF_MAINTENANCE_MARKER_RETRIES", 2) + 1)
        retry_kind = "marker"
    marker = STRUCTURED_REVIEW_MARKER if step_name == "review" else STRUCTURED_QA_MARKER

    last_task_text = task_text
    result: Dict[str, Any] = {}
    ok = False
    failure_reason = ""
    para_meta: Dict[str, Any] = {}
    report_excerpt = ""
    code_fix_retry_rounds = 0
    marker_retry_rounds = 0

    for attempt in range(1, inner_max + 1):
        input_data = _base_para_input(extra)
        result = _execute_employee_task_with_retries(
            employee_id,
            last_task_text,
            input_data,
            user_id=user_id,
        )
        ok = _employee_result_ok(result)
        para_meta = _extract_para_meta(result)
        report_excerpt = _extract_report_excerpt(result)
        para_report_excerpt = _fetch_para_task_report_excerpt(
            para_meta.get("task_id"),
            para_meta.get("subtask_id"),
        )
        if para_report_excerpt:
            report_excerpt = (report_excerpt + "\n" + para_report_excerpt)[-10000:]
        failure_reason = "" if ok else _extract_failure_reason(result, para_meta)

        is_final = attempt >= inner_max

        # 决定是否需要内层重试
        should_retry = False
        if not ok and not is_final:
            # code step: dispatch/code 失败 → 反馈原因让员工修代码再交付
            # review/qa step: dispatch 失败不重试内层（_execute_employee_task_with_retries
            #                 已重试过瞬态失败），让外层走 _decide_post_loop_policy
            # Para 已受理但同步等待超时并非代码缺陷；让外层记忆负责后续有界重试，
            # 避免同一轮立即创建重复 Para 任务。
            if retry_kind == "code_fix" and not _is_accepted_para_wait_timeout(result):
                should_retry = True
        elif ok and retry_kind == "marker" and not is_final:
            # dispatch 成功但 marker/协议不合规 → 打回重跑（攻克遵循率缺口）
            protocol_ok, protocol_reason = _structured_protocol_ok(step_name, report_excerpt)
            if not protocol_ok:
                failure_reason = protocol_reason or "structured_protocol_invalid"
                should_retry = True
            elif step_name == "qa":
                qa_json = _structured_report_from_step(
                    {"report_excerpt": report_excerpt},
                    STRUCTURED_QA_MARKER,
                )
                if _qa_executor_infrastructure_unavailable(qa_json):
                    failure_reason = "structured_qa_executor_unavailable"
                    should_retry = True

        if not is_final and should_retry:
            trace_record = {
                "employee_id": employee_id,
                "error": failure_reason,
                "inner_attempt": attempt,
                "ok": ok,
                "para": para_meta,
                "phase": "step_retry",
                "report_excerpt": report_excerpt,
                "retry_attempts": result.get("self_maintenance_retry_attempts"),
                "run_id": run_id,
                "status": "success" if ok else "failed",
                "step": step_name,
                "timestamp": _iso(_utc_now()),
            }
            _append_ledger(trace_record)

        if not should_retry:
            break

        if retry_kind == "code_fix":
            last_task_text = (
                task_text
                + f"\n\n=== PREVIOUS ATTEMPT FAILED (inner round {attempt}/{inner_max - 1}) ===\n"
                + f"failure_reason: {failure_reason}\n"
                + "MANDATORY: Address the failure reason above. Re-run the failing "
                + "command locally, fix until it passes, then deliver again. Do not "
                + "report completion unless the previously failing command now exits 0."
            )
            code_fix_retry_rounds = attempt
        elif failure_reason == "structured_qa_executor_unavailable":
            last_task_text = qa_executor_retry_prompt(task_text, attempt, inner_max)
            marker_retry_rounds = attempt
        else:  # marker / protocol
            last_task_text = (
                task_text
                + f"\n\n=== PREVIOUS REPORT PROTOCOL REJECTED (inner round {attempt}/{inner_max - 1}) ===\n"
                + f"required_marker: {marker}\n"
                + f"protocol_error: {failure_reason or 'missing_or_invalid_structured_json'}\n"
                + "Re-emit exactly one JSON object after the marker. "
                + "For review, dimensions.security / business_logic / performance are mandatory "
                + "with status pass|fail|n/a and findings lists. "
                + "Do not summarize — output the full protocol JSON."
            )
            marker_retry_rounds = attempt

    return (
        result,
        ok,
        failure_reason,
        para_meta,
        report_excerpt,
        code_fix_retry_rounds,
        marker_retry_rounds,
    )


def _fetch_para_task_report_excerpt(
    task_id: Optional[str], subtask_id: Optional[str], limit: int = 8000
) -> str:
    if not task_id:
        return ""
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    if not api_base:
        return ""
    try:
        headers = _guest_auth_headers(api_base)
        with httpx.Client(timeout=20.0, trust_env=False, verify=False) as client:
            resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
            resp.raise_for_status()
            task = (resp.json() or {}).get("task") or {}
    except Exception:
        logger.exception("failed to fetch Para task report logs task_id=%s", task_id)
        return ""

    chunks: List[str] = []
    for subtask in task.get("subTasks") or task.get("subtasks") or []:
        if subtask_id and str(subtask.get("id")) != str(subtask_id):
            continue
        for log in subtask.get("logs") or []:
            content = str(log.get("content") or "").strip()
            if content:
                chunks.append(content)
    return "\n".join(chunks)[-limit:]


def _fetch_para_task_state(api_base: str, task_id: str) -> Dict[str, Any]:
    headers = _guest_auth_headers(api_base)
    with httpx.Client(timeout=20.0, trust_env=False, verify=False) as client:
        resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        task = (resp.json() or {}).get("task") or {}
    return task if isinstance(task, dict) else {}


def _reconcile_requested_merge_feedback(
    memory: Dict[str, Any],
    *,
    api_base: Optional[str] = None,
    task_fetcher: Optional[Any] = None,
) -> Dict[str, Any]:
    """Settle requested merges from Para without confusing request with success.

    ``completed_merge_requested`` remains open until Para reports a real merged
    SHA. Any terminal merge failure becomes an automated remediation item with
    the exact findings. The next code employee starts from the configured clean
    base and uses the rejected branch only as evidence, preventing retries from
    accumulating an ever-larger inherited diff.
    """

    base = (api_base or os.environ.get("MODSTORE_PARA_API_BASE") or "").strip()
    recent_runs = memory.get("recent_runs")
    open_items = memory.get("open_items")
    if not base or not isinstance(recent_runs, list):
        return {"changed": False, "merged": 0, "remediation_added": 0}
    if not isinstance(open_items, list):
        open_items = []
        memory["open_items"] = open_items

    fetcher = task_fetcher or _fetch_para_task_state
    changed = False
    merged = 0
    remediation_added = 0
    checked_task_ids: set[str] = set()
    for run in reversed(recent_runs):
        if not isinstance(run, dict):
            continue
        if str(run.get("status") or "") != "completed_merge_requested":
            continue
        task_id = str(run.get("para_task_id") or "").strip()
        if not task_id or task_id in checked_task_ids:
            continue
        checked_task_ids.add(task_id)
        try:
            task = fetcher(base, task_id)
        except Exception:
            logger.exception("failed to reconcile requested Para merge task_id=%s", task_id)
            continue
        task_status = str(task.get("status") or "").strip().lower()
        branch = str(run.get("branch") or "").strip()
        if task_status == "merged" and str(task.get("merge_commit_sha") or "").strip():
            merge_sha = str(task.get("merge_commit_sha") or "").strip()
            existing_receipt = run.get("merge_reconciliation")
            receipt = {
                "merge_commit_sha": merge_sha,
                "reconciled_at": _iso(_utc_now()),
                "status": "merged",
                "task_id": task_id,
            }
            if not (
                isinstance(existing_receipt, dict)
                and existing_receipt.get("status") == "merged"
                and existing_receipt.get("task_id") == task_id
                and existing_receipt.get("merge_commit_sha") == merge_sha
            ):
                run["merge_reconciliation"] = receipt
                changed = True
            closed = _close_open_items_in_memory(
                memory,
                actor="para_merge_reconciler",
                branches=[branch],
                resolution_reason="para_reported_real_merge_sha",
                task_ids=[task_id],
            )
            if closed.get("closed_count"):
                changed = True
            merged += 1
            continue
        terminal_failure_statuses = {
            "cancelled",
            "dispatch_error",
            "dispatch_failed",
            "failed",
            "merge_conflict",
        }
        if task_status not in terminal_failure_statuses:
            continue
        conflict = task.get("merge_conflict")
        if not isinstance(conflict, dict):
            conflict = {}
        source = str(conflict.get("source") or "").strip()
        detail = str(
            conflict.get("detail")
            or task.get("fail_reason")
            or task.get("error")
            or f"Para merge task ended with status={task_status}"
        ).strip()[:4000]
        reason, item_kind, open_items, changed = reconcile_para_merge_failure_state(
            memory, changed, detail, source, task_id, task_status
        )
        existing_receipt = run.get("merge_reconciliation")
        receipt = {
            "detail": detail,
            "reconciled_at": _iso(_utc_now()),
            "source": source,
            "status": task_status,
            "task_id": task_id,
        }
        if not (
            isinstance(existing_receipt, dict)
            and existing_receipt.get("status") == task_status
            and existing_receipt.get("task_id") == task_id
            and existing_receipt.get("source") == source
            and existing_receipt.get("detail") == detail
        ):
            run["merge_reconciliation"] = receipt
            changed = True
        already_open = any(
            isinstance(item, dict)
            and str(item.get("task_id") or item.get("para_task_id") or "") == task_id
            and item.get("reason") == reason
            and item.get("kind") == item_kind
            for item in open_items
        )
        if not already_open:
            rejected_branch = str(conflict.get("branch_name") or branch).strip()
            resume_from_clean_baseline = resume_from_clean_baseline_for_para_merge(reason, detail)
            veto_meta = (
                classify_para_merge_review_detail(detail) if source == "ai-review-veto" else {}
            )
            open_item: Dict[str, Any] = {
                "branch": rejected_branch,
                "created_at": _iso(_utc_now()),
                "detail": detail,
                "kind": item_kind,
                "para_task_id": task_id,
                "reason": reason,
                "rejected_branch": rejected_branch,
                "resume_from_clean_baseline": resume_from_clean_baseline,
                "review_feedback": detail if source == "ai-review-veto" else "",
                "run_id": str(run.get("run_id") or "").strip(),
                "source": source,
                "task_status": task_status,
                "task_id": task_id,
            }
            if source == "ai-review-veto":
                open_item["review_actionable_findings"] = veto_meta.get("actionable_code_findings")
                open_item["review_veto_branch_hint"] = veto_meta.get("branch_hint") or ""
                open_item["review_veto_code"] = veto_meta.get("veto_code") or ""
                if veto_meta.get("review_diff_chars") is not None:
                    open_item["review_diff_chars"] = veto_meta["review_diff_chars"]
            open_items.append(open_item)
            changed = True
            remediation_added += 1

    if changed:
        memory["open_items"] = (memory.get("open_items") or [])[-50:]
        memory["updated_at"] = _iso(_utc_now())
    return {
        "changed": changed,
        "merged": merged,
        "remediation_added": remediation_added,
    }


def _base_para_input(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "branch": os.environ.get("MODSTORE_PARA_BRANCH"),
        "device_id": os.environ.get("MODSTORE_PARA_DEVICE_ID"),
        "repo_url": os.environ.get("MODSTORE_PARA_REPO_URL"),
        "suppress_lifecycle_events": True,
        "wait_for_para": True,
        "wait_timeout_sec": _env_int("MODSTORE_PARA_WAIT_TIMEOUT_SEC", 1800),
        # vibe-coding-maintainer 的 agent handler 在 Para 未启用 fallback 时需要
        # project_root 才能分析文件；para_delegate 模式会忽略此字段。
        # 默认指向生产仓库根目录，可用 MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT 覆盖。
        "project_root": (os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT") or "/root/XCMAX"),
    }
    if extra:
        data.update(extra)
    return data


def _python_supports_focused_tests(candidate: Path) -> bool:
    """Return whether a Python executable has the loop's test dependencies."""

    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return False
    try:
        probe = subprocess.run(
            [str(candidate), "-c", "import apscheduler, pytest"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _focused_test_command() -> str:
    """Resolve one executable QA command from the running MODstore environment.

    The scheduler may itself run from the lighter FHD venv, which intentionally
    does not install pytest.  Prefer the MODstore venv used for repository tests
    and expose explicit overrides for production or isolated runners.
    """

    command_override = os.environ.get("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", "").strip()
    if command_override:
        return command_override

    test_python_override = os.environ.get("MODSTORE_SELF_MAINTENANCE_TEST_PYTHON", "").strip()
    deploy_root = Path(
        os.environ.get("MODSTORE_DEPLOY_ROOT") or Path(__file__).resolve().parent.parent
    )
    runtime_root = os.environ.get("MODSTORE_RUNTIME_ROOT", "").strip()
    candidates = [
        Path(test_python_override).expanduser() if test_python_override else None,
        deploy_root / ".venv" / "bin" / "python",
        (
            Path(runtime_root).expanduser() / "MODstore_deploy" / ".venv" / "bin" / "python"
            if runtime_root
            else None
        ),
        Path(sys.executable),
    ]
    test_python = next(
        (
            candidate
            for candidate in candidates
            if candidate and _python_supports_focused_tests(candidate)
        ),
        Path(sys.executable),
    )
    test_path = (
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py"
    )
    return f"{shlex.quote(str(test_python))} -m pytest {shlex.quote(test_path)} -q"


def _code_task_text(
    run_id: str,
    evaluation: Dict[str, Any],
    memory: Dict[str, Any],
    resume_candidate: Optional[Dict[str, Any]] = None,
) -> str:
    gaps = ", ".join(evaluation.get("gaps") or []) or "none"
    focused_test_command = _focused_test_command()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main"
    black_command, isort_command = _diff_quality_commands(
        base_ref=f"origin/{base_branch}",
        target_ref="WORKTREE",
    )
    evolution_context_dict = build_self_evolution_context(
        run_id=run_id, evaluation=evaluation, memory=memory
    )
    evolution_context = render_self_evolution_context(evolution_context_dict)
    # 强制复用历史 fix：把 fix_knowledge_hits 的关键内容以可读格式提取出来，
    # 让 LLM 不需要解析 JSON 就能直接看到 symptom/root_cause/fix_diff。
    fix_hits = evolution_context_dict.get("fix_knowledge_hits") or []
    fix_digest_parts = []
    for idx, hit in enumerate(fix_hits[:3], 1):
        symptom = str(hit.get("symptom") or "")[:200]
        root_cause = str(hit.get("root_cause") or "")[:200]
        fix_diff = str(hit.get("fix_diff") or "")[:1500]
        if not symptom and not fix_diff:
            continue
        fix_digest_parts.append(
            f"[HISTORICAL FIX #{idx}]\n"
            f"  symptom: {symptom}\n"
            f"  root_cause: {root_cause}\n"
            f"  fix_diff (first 1500 chars):\n{fix_diff}"
        )
    fix_digest = (
        "\n\n".join(fix_digest_parts) if fix_digest_parts else "(no historical fixes matched)"
    )
    last_decision = memory.get("last_policy_decision") if isinstance(memory, dict) else None
    selected_remediation: Optional[Dict[str, Any]] = None
    if (
        isinstance(resume_candidate, dict)
        and resume_candidate.get("reason") == "resume_safety_score_remediation"
    ):
        selected_remediation = resume_candidate
        open_items = memory.get("open_items") if isinstance(memory, dict) else None
        if isinstance(open_items, list):
            selected_branch = str(resume_candidate.get("branch") or "")
            selected_run_id = str(resume_candidate.get("failed_run_id") or "")
            selected_task_id = str(resume_candidate.get("para_task_id") or "")
            for item in reversed(open_items):
                if not isinstance(item, dict):
                    continue
                item_task_id = str(item.get("task_id") or item.get("para_task_id") or "")
                if (
                    (selected_branch and str(item.get("branch") or "") == selected_branch)
                    or (selected_run_id and str(item.get("run_id") or "") == selected_run_id)
                    or (selected_task_id and item_task_id == selected_task_id)
                ):
                    selected_remediation = {**item, **resume_candidate}
                    break
    elif isinstance(last_decision, dict) and str(last_decision.get("reason") or "") in {
        "auto_merge_safety_score_v2_too_low",
        "auto_merge_safety_score_v3_too_low",
        "risk_score_v3_below_threshold_or_blocked",
    }:
        selected_remediation = last_decision
    external_review_remediation = external_review_remediation_prompt(resume_candidate)
    external_merge_remediation = external_merge_remediation_prompt(resume_candidate)
    retort_scope_remediation = retort_remediation.retort_scope_remediation_prompt(resume_candidate)
    structured_report_remediation = structured_report_remediation_prompt(memory, resume_candidate)
    score_remediation = ""
    if isinstance(selected_remediation, dict):
        merge_result = (
            selected_remediation.get("merge_result")
            if isinstance(selected_remediation.get("merge_result"), dict)
            else {}
        )
        v2 = (
            merge_result.get("safety_score_v2")
            if isinstance(merge_result.get("safety_score_v2"), dict)
            else {}
        )
        v3 = (
            merge_result.get("safety_score_v3")
            if isinstance(merge_result.get("safety_score_v3"), dict)
            else {}
        )
        review = (
            (v2.get("semantic_llm_analysis") or {}).get("reports", {}).get("review", {})
            if isinstance(v2.get("semantic_llm_analysis"), dict)
            else {}
        )
        remediation_evidence = {
            "branch": selected_remediation.get("branch"),
            "failed_run_id": selected_remediation.get("failed_run_id")
            or selected_remediation.get("run_id"),
            "reason": selected_remediation.get("reason"),
            "review_max_severity": review.get("max_severity"),
            "review_tested_commands": review.get("tested_commands"),
            "safety_score_v2": v2.get("score"),
            "safety_score_v2_min": v2.get("min_allowed"),
            "safety_score_v3": v3.get("score"),
            "safety_score_v3_min": v3.get("min_allowed"),
        }
        score_remediation = (
            "\n\n=== EXISTING BRANCH SCORE REMEDIATION ===\n"
            "Your workspace is already checked out on a newly created isolated remediation work branch "
            f"whose immutable base is `{str(selected_remediation.get('branch') or '').strip()}`. "
            "Do not checkout, switch to, reset, commit, or push directly to that immutable base branch. "
            "Make the follow-up on the current checked-out work branch only; do not replace its production fix with an "
            "unrelated change. The previous independent review/score did not authorize merge. "
            "Address its missing evidence on this candidate, especially any promised focused "
            "regression test that is absent. A test-only follow-up commit is valid here because "
            "the existing candidate already contains the production fix. Run that focused test "
            "and the mandatory loop policy suite, then commit the current work branch and push HEAD to that same "
            "work-branch name. Report `git branch --show-current` and `git rev-parse HEAD` as delivery evidence. "
            "Do not lower, bypass, or game either safety threshold. Evidence: "
            f"{json.dumps(remediation_evidence, ensure_ascii=False, sort_keys=True)}"
        )
    return (
        "Run a real MODstore self-maintenance improvement task. === SELF_MAINTENANCE_CANONICAL_MERGE_BASE:main === "
        "Use the previous loop memory and current evidence gaps to fix the highest-value "
        "executable gap in the self-maintenance loop. "
        "MANDATORY: Before reasoning from scratch, you MUST check the HISTORICAL FIXES below. "
        "If a historical fix's symptom matches the current gap and its fix_diff still applies safely, "
        "you MUST reuse that fix first (apply the diff or its approach) instead of inventing a new solution. "
        "Only when no historical fix applies may you reason from scratch. "
        "If there is no bug gap, choose one proactive task from performance, coverage, or tech_debt signals. "
        "When you fix a bug, write the symptom/root_cause/fix_diff triad under FHD/XCAGI/kb/fixes; "
        "every changed fix JSON MUST conform to the EXACT schema below (all fields required, no extras that break validation):\n"
        "```json\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "kind": "fix",\n'
        '  "created_at": "2026-07-20T12:00:00+00:00",\n'
        '  "symptom": "<non-empty string: observed symptom>",\n'
        '  "root_cause": "<non-empty string: root cause>",\n'
        '  "fix_diff": "<non-empty string: diff or description>",\n'
        '  "metadata": {"component": "...", "files": ["..."]},\n'
        '  "executable_template": {\n'
        '    "applicability_check": "<non-empty string>",\n'
        '    "patch_strategy": "<non-empty string>",\n'
        '    "rollback_plan": "<non-empty string>",\n'
        '    "required_tests": ["test_a.py", "test_b.py"]\n'
        "  }\n"
        "}\n"
        "```\n"
        "CRITICAL: executable_template MUST be an object (the executable_template object "
        "must not be a string, null, or omitted) with non-empty string fields "
        "applicability_check/patch_strategy/rollback_plan AND a "
        "string-list required_tests. Common failure: writing fix_diff as a description but "
        "forgetting executable_template, or setting executable_template to a string. "
        "MANDATORY PRE-PUSH VALIDATION: Before committing/pushing any KB JSON file, you MUST "
        'run `python -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; '
        "import json; validate_kb_payload('fixes', json.load(open('FHD/XCAGI/kb/fixes/<file>.json')))\"` "
        "(or 'patterns' for pattern files) and require it to return without raising. If validation "
        "raises ValueError, FIX the JSON before pushing — the loop will reject KB-schema-invalid "
        "branches with a `kb-schema-failed` PR label and retry up to 2 times before escalating to "
        "human review. Validate each changed KB JSON with "
        "self_evolution_knowledge.validate_kb_payload before reporting completion. "
        "when review/QA approves a reusable change, write the pattern under FHD/XCAGI/kb/patterns. "
        "Do not create marker-only/status-only changes as proof of completion. "
        "Prefer changes that make scheduler gating, loop memory, report-only review/QA, "
        "or policy decisions more directly executable. "
        "\n\n=== OUTPUT QUALITY REQUIREMENTS ===\n"
        "- State one evidence-backed symptom and root cause before changing code.\n"
        "- Make the smallest production change that fixes that root cause and add focused regression tests; "
        "do not submit marker-only, comment-only, formatting-only, or test-only work as the fix.\n"
        "- DIFF PROTOCOL: When describing patches in the report or KB fix_diff, emit a complete "
        "unified diff that `git apply` / `git apply --check` can consume "
        "(must include `diff --git`, `---/+++`, and `@@` hunks). "
        "Forbidden: summary-only answers, bullet paraphrases of changes, or partial hunks without file headers.\n"
        "- Prefer committing real file edits in the worktree (git add/commit/push) over pasting diffs; "
        "if you paste a patch, it must still be git-applyable.\n"
        "- Keep production scope and changed lines minimal enough for a legitimate safety_score_v2 target of at least 90; "
        "never hide, omit, or misclassify risky files or behavior to influence the score.\n"
        "- Leave review and QA to the independent report-only employees; do not self-approve or fabricate their evidence.\n"
        "- Report every verification command with its real exit code and concise passing output.\n"
        f"Before reporting completion, execute `{focused_test_command}` in the target branch "
        "and require exit code 0. "
        f"Also run `{black_command}` and `{isort_command}` from "
        "`成都修茈科技有限公司/MODstore_deploy`; these commands deterministically "
        "check every changed Python file in the target diff without importing "
        "unrelated historical formatting debt. Also run "
        "`python scripts/dev/source_governance.py --top 10` from the repository root; "
        "all three are mandatory merge-readiness gates and must exit 0. "
        f"If and only if there is no safe actionable source change, update `{DEFAULT_STATUS_FILE}` "
        f"with LOOP_RUN_ID={run_id!r}, LOOP_KIND='scheduled_self_maintenance', "
        "BRIDGE='para_main_device', UPDATED_AT to the current UTC time, and a clear "
        "NO_ACTION_REASON explaining why no source change was safe. "
        "Do not edit runtime-only, ignored, .devfleet, or .trae files. "
        "MANDATORY SELF-VERIFICATION: Before reporting completion, you MUST run the "
        "relevant tests/lint/type-check commands for the files you changed and paste "
        "the passing output (exit code 0) in your report. If any command fails, fix "
        "your changes and retry — do NOT report completion with failing tests. The "
        "loop will reject your delivery if delivery_validation shows exit_code != 0, "
        "and you will be given the failure_reason to fix; save everyone a round by "
        "self-verifying first. "
        f"Current evidence gaps: {gaps}. "
        f"Previous loop memory JSON: {_memory_context(memory)}. "
        f"{score_remediation}"
        f"{external_review_remediation}"
        f"{external_merge_remediation}"
        f"{retort_scope_remediation}"
        f"{structured_report_remediation}"
        f"\n\n=== HISTORICAL FIXES (MUST READ FIRST) ===\n{fix_digest}\n"
        f"\n=== SELF_EVOLUTION_CONTEXT JSON ===\n{evolution_context}"
    )


def _evaluate_retort_clarification_before_review(
    *,
    run_id: str,
    branch: Optional[str],
    para_task_id: str,
    memory: Dict[str, Any],
) -> Dict[str, Any]:
    """Force self-maintenance review through Retort clarification gate.

    Returns ``{"blocked": True, "reason": ...}`` when human clarification is still
    required; otherwise ``{"blocked": False, ...}``. Failures in the gate itself
    are non-blocking so review can continue with evidence of the gate error.
    """

    enabled = os.environ.get(
        "MODSTORE_SELF_MAINTENANCE_RETORT_CLARIFICATION", "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"blocked": False, "reason": "disabled"}

    try:
        from modstore_server.retort_clarification_gate import (
            evaluate_retort_clarification_gate,
            gate_enabled,
        )
    except Exception as exc:  # noqa: BLE001
        return {"blocked": False, "reason": f"gate_import_failed:{type(exc).__name__}"}

    if not gate_enabled():
        return {"blocked": False, "reason": "gate_disabled"}

    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    target = str(branch or "").strip()
    change_evidence = retort_change_evidence.resolve_retort_change_evidence(
        run_id=run_id,
        branch=target,
        repo_url=repo_url,
        base_branch=base_branch,
        memory=memory,
        workspace_root=_runtime_dir() / DEFAULT_MERGE_WORKSPACE_ROOT,
        changed_files_for_branch=lambda workspace: _changed_files_for_branch(
            repo_url=repo_url,
            base_branch=base_branch,
            branch=target,
            workspace=workspace,
        ),
        cleanup_workspace=_cleanup_merge_workspace,
    )
    changed_files = list(change_evidence.get("changed_files") or [])
    if change_evidence.get("skip_reason"):
        reason = str(change_evidence["skip_reason"])
        logger.warning(
            "retort clarification skipped run_id=%s reason=%s source=%s",
            run_id,
            reason,
            change_evidence.get("source"),
        )
        return {
            "blocked": False,
            "reason": reason,
            "changed_file_count": 0,
            "change_evidence": change_evidence,
            "para_task_id": para_task_id,
        }

    intent_bits = [
        f"self-maintenance review run {run_id}",
        f"branch {target}" if target else "",
        str((memory or {}).get("last_goal") or "").strip(),
        str((memory or {}).get("summary") or "").strip(),
    ]
    strategy_intent = " | ".join(bit for bit in intent_bits if bit)[:4000]
    try:
        gate = evaluate_retort_clarification_gate(
            strategy_intent=strategy_intent,
            changed_files=changed_files,
            proposal_id=f"self-maintenance:{run_id}",
            run_id=str(run_id or ""),
            package_id="change-request-auditor",
            auto_open=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"blocked": False, "reason": f"gate_eval_failed:{type(exc).__name__}"}

    blockers = list(gate.get("blockers") or [])
    pending = "retort_clarification_pending" in blockers
    expired = "retort_clarification_expired" in blockers
    cancelled = "retort_clarification_cancelled" in blockers
    if pending or expired or cancelled:
        reason = (
            "retort_clarification_pending"
            if pending
            else ("retort_clarification_expired" if expired else "retort_clarification_cancelled")
        )
        return {
            "blocked": True,
            "reason": reason,
            "blockers": blockers,
            "clarification": gate.get("clarification"),
            "change_evidence": change_evidence,
            "changed_file_count": len(changed_files),
            "para_task_id": para_task_id,
        }
    return {
        "blocked": False,
        "reason": "aligned_or_not_needed",
        "blockers": blockers,
        "clarification": gate.get("clarification"),
        "change_evidence": change_evidence,
        "changed_file_count": len(changed_files),
        "aligned": bool(gate.get("aligned")),
    }


def _review_task_text(run_id: str, branch: Optional[str], memory: Dict[str, Any]) -> str:
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    return (
        "MODSTORE_REPORT_ONLY=1. Report-only review task. "
        "Do not change files, do not commit, and do not push. "
        f"Review the self-maintenance loop run {run_id}. "
        f"Target branch to inspect: `{branch or ''}`. "
        f"Base branch: `{base_branch}`. Repo URL: `{repo_url}`. "
        "Do not inspect your own report-only task branch as the target branch. "
        "The report-only workspace bootstrap has already fetched `origin/<base>` and "
        "`origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, "
        "checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. "
        "Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. "
        "Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. "
        "\n\n=== MANDATORY REVIEW DIMENSIONS (all three required) ===\n"
        "1) security — injection, secrets, unsafe deserialization, authz bypass, shell=True, etc.\n"
        "2) business_logic — wrong control flow, broken invariants, missing error handling, "
        "incorrect state transitions, API contract breakage, silent data loss, feature regressions.\n"
        "3) performance — obvious slow queries (SELECT * / missing LIMIT on hot paths), N+1 "
        "(ORM query inside loops), unbounded while/for loops, sync sleep on request path, "
        "unbounded list/buffer growth.\n"
        "For each dimension set status to pass|fail|n/a and list concrete findings "
        "(empty list only when status is pass or n/a). "
        "Any dimension status=fail MUST also appear in blocking_findings and raise max_severity "
        "to at least medium (high/critical when warranted).\n"
        "Return concrete findings, risks, and missing evidence. "
        "PROTOCOL STRICT: At the end, output exactly one JSON object after the marker "
        f"{STRUCTURED_REVIEW_MARKER}: with schema "
        '{"max_severity":"none|low|medium|high|critical",'
        '"blocking_findings":[],"risk_class":"low|medium|high",'
        '"target_branch_available":true,"tested_commands":[],'
        '"dimensions":{'
        '"security":{"status":"pass|fail|n/a","findings":[]},'
        '"business_logic":{"status":"pass|fail|n/a","findings":[]},'
        '"performance":{"status":"pass|fail|n/a","findings":[]}'
        "}}. "
        "If you omit dimensions or use wrong enums, the loop will REJECT and re-run you. "
        f"Previous loop memory JSON: {_memory_context(memory)}"
    )


def _qa_task_text(run_id: str, branch: Optional[str], memory: Dict[str, Any]) -> str:
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    focused_test_command = _focused_test_command()
    base_ref = f"origin/{base_branch or 'main'}"
    target_ref = f"origin/{str(branch or '').strip()}" if branch else "HEAD"
    black_command, isort_command = _diff_quality_commands(
        base_ref=base_ref,
        target_ref=target_ref,
    )
    return (
        "MODSTORE_REPORT_ONLY=1. Report-only QA task. "
        "Do not change files, do not commit, and do not push. "
        f"Verify the executable evidence for self-maintenance loop run {run_id}. "
        f"Target branch to verify: `{branch or ''}`. "
        f"Base branch: `{base_branch}`. Repo URL: `{repo_url}`. "
        "Do not inspect your own report-only task branch as the target branch. "
        "The report-only workspace bootstrap has already fetched `origin/<base>` and "
        "`origin/<target>`. Use those pre-fetched refs read-only. Do not run git fetch, clone, "
        "checkout, or any command that writes `.git`; the executor sandbox intentionally blocks it. "
        "Verify both refs with `git cat-file -e` and compare `origin/<base>...origin/<target>`. "
        "Only report target_branch_unavailable when a pre-fetched ref cannot be resolved. "
        "Evaluate the target branch, tests, changed files, and previous loop memory as merge-readiness evidence. "
        f"You MUST execute the focused verification command `{focused_test_command}` and include its "
        "exact command, real exit code, and status in tested_commands. If that command's absolute Python "
        "path does not exist on this worker, also run a platform-equivalent local `python -m pytest` command "
        "against the same focused test file, and include both attempts in tested_commands. The equivalent "
        "command is valid evidence only when it executes the same pytest target successfully; a syntax-only "
        "check or a different test target is not a substitute. Materialize the COMPLETE target ref into a "
        "temporary directory (for example `git archive origin/<target> | tar -x`) before running the equivalent "
        "command; do not archive only `成都修茈科技有限公司/MODstore_deploy`, because focused policy tests read "
        "the sibling `FHD/` autonomy-guard SSOT. Run pytest from that complete target tree. If the complete-tree "
        "equivalent command cannot finish, times out, or exits nonzero, return FAIL even when the failure looks "
        "environmental; never report PASS with no successful focused tested_commands entry. Do not fail solely "
        "because the scheduler's absolute Python path is unavailable when the complete-tree equivalent focused "
        "command passes. "
        "From the target branch archive, you MUST also run "
        f"`{black_command}` and `{isort_command}` from "
        "`成都修茈科技有限公司/MODstore_deploy`; these commands deterministically "
        "check every changed Python file in the target diff. Also run "
        "`python scripts/dev/source_governance.py --top 10` from the repository root. "
        "Record their exact commands, real exit codes, and statuses in quality_checks. "
        "Use CLEAN_BASELINE_JSON to separate existing allowed failures from new failures; "
        "FAIL only for new failures, missing target branch, blocking findings, or unsafe evidence. "
        "Do not fail only because the final terminal ledger record for this in-flight run does not exist yet; "
        "that record is written after QA returns. "
        "Return PASS only when the target branch is executable and no new review/QA risk remains; "
        "return FAIL for real missing executable evidence, unsafe scope, new failed tests, or unresolved review findings. "
        "At the end, output exactly one JSON object after the marker "
        f"{STRUCTURED_QA_MARKER}: with schema "
        '{"verdict":"PASS|FAIL","blocking_findings":[],'
        '"tested_commands":[{"command":"...","exit_code":0,"status":"passed|failed"}],'
        '"quality_checks":{'
        '"black":{"command":"...","exit_code":0,"status":"passed|failed"},'
        '"isort":{"command":"...","exit_code":0,"status":"passed|failed"},'
        '"source_governance":{"command":"...","exit_code":0,"status":"passed|failed"}},'
        '"target_branch_available":true,'
        '"test_delta":{"baseline_id":"...","new_failures":[],"new_errors":[]},'
        '"changed_files_scope":"low|medium|high",'
        '"risk_class":"low|medium|high"}. '
        f"CLEAN_BASELINE_JSON: {_clean_baseline_context()}. "
        f"Previous loop memory JSON: {_memory_context(memory)}"
    )


def _json_after_marker(text: str, marker: str) -> Optional[Dict[str, Any]]:
    report = text or ""
    positions: List[int] = []
    start = 0
    while True:
        idx = report.find(marker, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(marker)
    for idx in reversed(positions):
        tail = report[idx + len(marker) :]
        tail = tail.lstrip(" \t\r\n:=`")
        if tail.startswith("json"):
            tail = tail[4:].lstrip(" \t\r\n")
        try:
            obj, _ = json.JSONDecoder().raw_decode(tail)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


_REVIEW_DIMENSION_KEYS = ("security", "business_logic", "performance")
_REVIEW_DIMENSION_STATUSES = frozenset({"pass", "fail", "n/a"})
_REVIEW_SEVERITIES = frozenset({"none", "low", "medium", "high", "critical"})
_REVIEW_RISK_CLASSES = frozenset({"low", "medium", "high"})


def _validate_structured_review_protocol(
    obj: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Strict protocol for review employee output. Incomplete → reject/rerun."""
    if not isinstance(obj, dict):
        return False, "missing_structured_review_object"
    severity = str(obj.get("max_severity") or "").strip().lower()
    if severity not in _REVIEW_SEVERITIES:
        return False, "invalid_max_severity"
    if str(obj.get("risk_class") or "").strip().lower() not in _REVIEW_RISK_CLASSES:
        return False, "invalid_risk_class"
    if not isinstance(obj.get("blocking_findings"), list):
        return False, "blocking_findings_not_list"
    if not isinstance(obj.get("tested_commands"), list):
        return False, "tested_commands_not_list"
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return False, "target_branch_available_not_bool"
    dimensions = obj.get("dimensions")
    if not isinstance(dimensions, dict):
        return False, "missing_dimensions"
    for key in _REVIEW_DIMENSION_KEYS:
        dim = dimensions.get(key)
        if not isinstance(dim, dict):
            return False, f"missing_dimension_{key}"
        status = str(dim.get("status") or "").strip().lower()
        if status not in _REVIEW_DIMENSION_STATUSES:
            return False, f"invalid_dimension_status_{key}"
        if not isinstance(dim.get("findings"), list):
            return False, f"dimension_findings_not_list_{key}"
        if status == "fail" and not dim.get("findings"):
            return False, f"dimension_fail_without_findings_{key}"
    fail_dims = [
        key
        for key in _REVIEW_DIMENSION_KEYS
        if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
    ]
    if fail_dims and severity in {"none", "low"}:
        return False, "dimension_fail_severity_too_low"
    if fail_dims and not obj.get("blocking_findings"):
        return False, "dimension_fail_without_blocking_findings"
    return True, ""


def _validate_structured_qa_protocol(obj: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "missing_structured_qa_result"
    if str(obj.get("verdict") or "").strip().upper() not in {"PASS", "FAIL"}:
        return False, "invalid_qa_verdict"
    if not isinstance(obj.get("blocking_findings"), list):
        return False, "qa_blocking_findings_not_list"
    if not isinstance(obj.get("tested_commands"), list):
        return False, "qa_tested_commands_not_list"
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return False, "qa_target_branch_available_not_bool"
    return True, ""


def _structured_report_from_step(step: Dict[str, Any], marker: str) -> Optional[Dict[str, Any]]:
    report = str(step.get("report_excerpt") or "")
    parsed = _json_after_marker(report, marker)
    candidates: List[Dict[str, Any]] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
    for line in report.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if marker == STRUCTURED_QA_MARKER and "verdict" in obj:
                candidates.append(obj)
            if marker == STRUCTURED_REVIEW_MARKER and "max_severity" in obj:
                candidates.append(obj)
    for obj in candidates:
        if marker == STRUCTURED_REVIEW_MARKER:
            ok, _reason = _validate_structured_review_protocol(obj)
            if ok:
                return obj
        elif marker == STRUCTURED_QA_MARKER:
            ok, _reason = _validate_structured_qa_protocol(obj)
            if ok:
                return obj
        else:
            return obj
    # Backward-compatible parse for ledger display: return first candidate even if
    # protocol-incomplete (gate/retry paths call validators explicitly).
    return candidates[0] if candidates else None


def _structured_protocol_ok(step_name: str, report_excerpt: str) -> Tuple[bool, str]:
    if step_name == "review":
        obj = _json_after_marker(report_excerpt, STRUCTURED_REVIEW_MARKER)
        if obj is None:
            # fall back to line scan via step helper without protocol filter
            loose = None
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"max_severity"' in line:
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        loose = candidate
                        break
            obj = loose
        return _validate_structured_review_protocol(obj)
    if step_name == "qa":
        obj = _json_after_marker(report_excerpt, STRUCTURED_QA_MARKER)
        if obj is None:
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"verdict"' in line:
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        obj = candidate
                        break
        return _validate_structured_qa_protocol(obj)
    return True, ""


def _structured_report_gate(steps: List[Dict[str, Any]], branch=None) -> Dict[str, Any]:
    review_steps = [step for step in steps if step.get("step") == "review"]
    qa_steps = [step for step in steps if step.get("step") == "qa"]
    if review_steps:
        review_json = _structured_report_from_step(review_steps[-1], STRUCTURED_REVIEW_MARKER)
        protocol_ok, protocol_reason = _validate_structured_review_protocol(review_json)
        if not protocol_ok:
            return {
                "ok": False,
                "reason": protocol_reason or "missing_structured_review_result",
                "review": review_json,
            }
        severity = str(review_json.get("max_severity") or "high").lower()
        blocking = review_json.get("blocking_findings")
        dimensions = (
            review_json.get("dimensions") if isinstance(review_json.get("dimensions"), dict) else {}
        )
        failed_dims = [
            key
            for key in _REVIEW_DIMENSION_KEYS
            if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
        ]
        if severity not in {"none", "low", "medium"}:
            return {
                "ok": False,
                "reason": "structured_review_high_severity",
                "review": review_json,
            }
        if isinstance(blocking, list) and blocking:
            return {
                "ok": False,
                "reason": "structured_review_blocking_findings",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
        if failed_dims:
            return {
                "ok": False,
                "reason": "structured_review_dimension_fail",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
    else:
        review_json = None

    if qa_steps:
        qa_json = _structured_report_from_step(qa_steps[-1], STRUCTURED_QA_MARKER)
        qa_ok, qa_reason = _validate_structured_qa_protocol(qa_json)
        if not qa_ok:
            return {
                "ok": False,
                "reason": qa_reason or "missing_structured_qa_result",
                "review": review_json,
                "qa": qa_json,
            }
        if qa_json.get("target_branch_available") is not True:
            return {
                "ok": False,
                "reason": "structured_qa_target_branch_unavailable",
                "qa": qa_json,
            }
        verdict = str(qa_json.get("verdict") or "").upper()
        if verdict != "PASS":
            return {
                "ok": False,
                "reason": _qa_verdict_failure_reason(qa_json),
                "qa": qa_json,
            }
        blocking = qa_json.get("blocking_findings")
        if isinstance(blocking, list) and blocking:
            return {
                "ok": False,
                "reason": "structured_qa_blocking_findings",
                "qa": qa_json,
            }
        tested_commands = qa_json.get("tested_commands")
        focused_command = _focused_test_command()
        if not isinstance(tested_commands, list) or not any(
            isinstance(item, dict)
            and _matches_focused_test_command(item.get("command"), focused_command)
            and int(item.get("exit_code") if item.get("exit_code") is not None else -1) == 0
            and str(item.get("status") or "").lower().startswith("passed")
            for item in tested_commands
        ):
            return {
                "ok": False,
                "reason": "structured_qa_focused_command_not_passed",
                "focused_command": focused_command,
                "qa": qa_json,
            }
        quality_failure = _quality_check_failure(qa_json, target_branch=branch)
        if quality_failure:
            return {
                "ok": False,
                "reason": quality_failure,
                "qa": qa_json,
            }
        test_delta = (
            qa_json.get("test_delta") if isinstance(qa_json.get("test_delta"), dict) else {}
        )
        for key in ("new_failures", "new_errors"):
            values = test_delta.get(key)
            if isinstance(values, list) and values:
                return {
                    "ok": False,
                    "reason": f"structured_qa_{key}",
                    "qa": qa_json,
                }
    else:
        qa_json = None

    return {
        "ok": True,
        "qa": qa_json,
        "reason": "structured_reports_passed",
        "review": review_json,
    }


def _allowed_auto_merge_globs() -> List[str]:
    return _env_list("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_GLOBS", DEFAULT_AUTO_MERGE_GLOBS)


def _auto_merge_scope_globs() -> List[str]:
    return _shared_auto_merge_scope_globs()


def _auto_merge_forbidden_globs() -> List[str]:
    return _shared_auto_merge_forbidden_globs()


def _auto_merge_max_files() -> int:
    return _shared_auto_merge_max_files()


def _auto_merge_max_lines() -> int:
    return _shared_auto_merge_max_lines()


def _step_reports(steps: List[Dict[str, Any]]) -> str:
    return "\n".join(str(step.get("report_excerpt") or "") for step in steps)


def _has_high_risk_report(steps: List[Dict[str, Any]]) -> bool:
    text = _step_reports(steps).lower()
    if any(term.lower() in text for term in HIGH_RISK_TERMS):
        return True
    return bool(HIGH_RISK_REPORT_RE.search(_step_reports(steps)))


def _missing_report_only_evidence(steps: List[Dict[str, Any]]) -> bool:
    markers = (
        "report-only task completed",
        "result:",
        "verdict",
        "审查结论",
        "具体发现",
        "evidence:",
    )
    for step in steps:
        if step.get("step") not in {"review", "qa"}:
            continue
        text = str(step.get("report_excerpt") or "").lower()
        if not any(marker in text for marker in markers):
            return True
    return False


def _run_cmd(args: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{output}")
    return output


def _cleanup_merge_workspace(workspace: Path) -> bool:
    """Remove one ephemeral merge workspace without widening the delete scope."""

    root = (_runtime_dir() / DEFAULT_MERGE_WORKSPACE_ROOT).resolve()
    candidate = workspace.resolve()
    if candidate == root or root not in candidate.parents:
        logger.error("refusing to clean merge workspace outside root: %s", candidate)
        return False
    try:
        shutil.rmtree(candidate)
    except FileNotFoundError:
        return True
    except OSError:
        logger.exception("failed to clean merge workspace: %s", candidate)
        return False
    return True


def _para_repository_candidates(repo_url: str) -> List[str]:
    """Return authenticated Para transport first, then the public origin.

    Production Para branches are created by devices that do not share the
    scheduler's interactive HTTPS credentials.  ``MODSTORE_PARA_BARE_REPO``
    is therefore the durable transport contract and may be either a local
    bare path or an SSH URL.  The public origin remains a fail-soft fallback.
    """

    repositories: List[str] = []
    for candidate in (
        os.environ.get("MODSTORE_PARA_BARE_REPO", "").strip(),
        str(repo_url or "").strip(),
    ):
        if candidate and candidate not in repositories:
            repositories.append(candidate)
    return repositories


def _remote_branch_head(repo_url: str, branch: str) -> Optional[str]:
    """Resolve a Para branch head without mutating a workspace."""
    if not repo_url or not branch:
        return None
    for repository in _para_repository_candidates(repo_url):
        try:
            proc = subprocess.run(
                ["git", "ls-remote", "--heads", repository, f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        line = next(
            (item.strip() for item in (proc.stdout or "").splitlines() if item.strip()),
            "",
        )
        sha = line.split(None, 1)[0] if line else ""
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            return sha.lower()
    return None


def _validate_remediation_branch_delivery(
    *, base_branch: str, delivered_branch: str
) -> Dict[str, Any]:
    """Require a resumed code employee to advance its isolated work branch."""
    if not base_branch:
        return {"ok": True, "reason": "not_score_remediation"}
    if not delivered_branch:
        return {"ok": False, "reason": "missing_delivered_branch"}
    if delivered_branch == base_branch:
        return {
            "ok": False,
            "reason": "remediation_wrote_to_immutable_base_branch",
            "base_branch": base_branch,
            "delivered_branch": delivered_branch,
        }
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_head = _remote_branch_head(repo_url, base_branch)
    delivered_head = _remote_branch_head(repo_url, delivered_branch)
    if not delivered_head:
        return {
            "ok": False,
            "reason": "delivered_branch_head_unavailable",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
        }
    if base_head and delivered_head == base_head:
        return {
            "ok": False,
            "reason": "remediation_branch_not_advanced",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
            "delivered_head": delivered_head,
        }
    return {
        "ok": True,
        "reason": "remediation_branch_advanced",
        "base_branch": base_branch,
        "base_head": base_head,
        "delivered_branch": delivered_branch,
        "delivered_head": delivered_head,
    }


def _changed_files_for_branch(
    *, repo_url: str, base_branch: str, branch: str, workspace: Path
) -> List[str]:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists() and not _cleanup_merge_workspace(workspace):
        raise RuntimeError(f"stale merge workspace cleanup failed: {workspace}")
    clone_errors: List[str] = []
    cloned_from = ""
    for repository in _para_repository_candidates(repo_url):
        if workspace.exists() and not _cleanup_merge_workspace(workspace):
            raise RuntimeError(f"failed clone workspace cleanup: {workspace}")
        try:
            # This workspace is used only for ref diffs and targeted ``git
            # show`` calls.  Avoid materializing the multi-GB working tree;
            # partial-clone support lazily fetches only a KB blob when schema
            # validation actually needs it.
            _run_cmd(
                [
                    "git",
                    "clone",
                    "--no-tags",
                    "--filter=blob:none",
                    "--no-checkout",
                    repository,
                    str(workspace),
                ],
                timeout=300,
            )
        except Exception as exc:
            clone_errors.append(f"{type(exc).__name__}:{str(exc)[:300]}")
            continue
        cloned_from = repository
        break
    if not cloned_from:
        raise RuntimeError(
            "unable to clone Para repository through configured transports: "
            + "; ".join(clone_errors)
        )
    # Para 创建的分支可能只存在于 Para 本地工作区，尚未 push 到 origin。
    # 先 fetch base_branch（一定在远程），再 best-effort fetch branch。
    _run_cmd(["git", "fetch", "origin", base_branch], cwd=workspace, timeout=180)
    _fetch_branch = subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    branch_ref = f"origin/{branch}" if _fetch_branch.returncode == 0 else None
    # Fallback: Para e2e-agent 会把分支 push 到本地 bareRepo
    # （默认 /Users/a4243342/XCMAX-runtime/devfleet-bare.git，与 e2e-agent.mjs DEVFLEET_BARE_REPO 一致）。
    # 如果 origin 没有，从 bareRepo fetch，并创建本地 origin 引用让后续 diff 命令统一用 origin/{branch}。
    if not branch_ref:
        bare_repo = os.environ.get(
            "MODSTORE_PARA_BARE_REPO", "/Users/a4243342/XCMAX-runtime/devfleet-bare.git"
        ).strip()
        if bare_repo:
            _sp_run = subprocess.run(
                ["git", "fetch", bare_repo, branch],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if _sp_run.returncode == 0:
                # 把 FETCH_HEAD 创建为 origin/{branch} 引用，让后续 diff/numstat 统一用 origin/{branch}。
                _run_cmd(
                    [
                        "git",
                        "update-ref",
                        f"refs/remotes/origin/{branch}",
                        "FETCH_HEAD",
                    ],
                    cwd=workspace,
                )
                branch_ref = f"origin/{branch}"
                logger.info(
                    "auto_merge: fetched branch %s from Para bareRepo %s",
                    branch,
                    bare_repo,
                )
    if not branch_ref:
        logger.warning(
            "auto_merge: branch %s not on remote or bareRepo — Para may not have pushed it",
            branch,
        )
        return []
    diff = _run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            f"origin/{base_branch}...{branch_ref}",
        ],
        cwd=workspace,
    )
    return [line.strip() for line in diff.splitlines() if line.strip()]


def _diff_numstat_for_branch(*, base_branch: str, branch: str, workspace: Path) -> Dict[str, Any]:
    diff = _run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--numstat",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
    )
    total_additions = 0
    total_deletions = 0
    binary_files: List[str] = []
    per_file: Dict[str, Dict[str, int]] = {}
    for raw_line in diff.splitlines():
        parts = raw_line.split("\t", 2)
        if len(parts) != 3:
            continue
        added_raw, deleted_raw, file_name = parts
        file_name = file_name.strip()
        if added_raw == "-" or deleted_raw == "-":
            binary_files.append(file_name)
            continue
        try:
            additions = int(added_raw)
            deletions = int(deleted_raw)
        except ValueError:
            binary_files.append(file_name)
            continue
        total_additions += additions
        total_deletions += deletions
        per_file[file_name] = {"additions": additions, "deletions": deletions}
    return {
        "additions": total_additions,
        "binary_files": binary_files,
        "changed_files": sorted(set(per_file) | set(binary_files)),
        "deletions": total_deletions,
        "files": per_file,
        "line_changes": total_additions + total_deletions,
        "source": "git_diff_numstat",
    }


def _kb_json_kind_for_repo_path(file_name: str) -> Optional[str]:
    normalized = _normalize_repo_path(file_name)
    if normalized.startswith("FHD/XCAGI/kb/fixes/") and normalized.endswith(".json"):
        return "fixes"
    if normalized.startswith("FHD/XCAGI/kb/patterns/") and normalized.endswith(".json"):
        return "patterns"
    return None


def _validate_kb_json_changes_for_auto_merge(
    *,
    branch: str,
    files: List[str],
    workspace: Path,
) -> Dict[str, Any]:
    checked: List[str] = []
    errors: List[Dict[str, str]] = []
    for file_name in files:
        kind = _kb_json_kind_for_repo_path(file_name)
        if not kind:
            continue
        normalized = _normalize_repo_path(file_name)
        checked.append(normalized)
        try:
            raw = _run_cmd(
                [
                    "git",
                    "-c",
                    "core.quotePath=false",
                    "show",
                    f"origin/{branch}:{normalized}",
                ],
                cwd=workspace,
                timeout=60,
            )
            payload = json.loads(raw)
            validate_kb_payload(kind, payload)
        except Exception as exc:
            errors.append({"error": str(exc)[:500], "file": normalized, "kind": kind})
    if errors:
        return {
            "checked": checked,
            "errors": errors,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    return {
        "checked": checked,
        "ok": True,
        "reason": "kb_json_schema_valid" if checked else "no_kb_json_changes",
    }


KB_SCHEMA_RETRY_MAX = 2
KB_SCHEMA_FAILED_LABEL = "kb-schema-failed"
KB_SCHEMA_FAILED_STATUS = "kb_schema_failed"
NEEDS_HUMAN_LABEL = "needs-human"


def _early_kb_validation_for_branch(
    *,
    run_id: str,
    branch: str,
) -> Dict[str, Any]:
    """Early KB JSON schema validation for a code-step branch.

    Clones the repo (best-effort), fetches the branch, gets the changed-files
    list, and runs ``_validate_kb_json_changes_for_auto_merge`` against any KB
    JSON files in the diff. Returns a dict with::

        {
          "ok": bool,                           # True if validation passed (or no KB files / clone failed)
          "reason": str,                        # "kb_json_schema_validation_failed" on failure
          "kb_validation": {...},               # raw _validate_kb_json_changes_for_auto_merge result
          "files": [...],                       # changed-files list (empty if clone failed)
          "workspace": str,                     # workspace path used (for cleanup/debug)
          "clone_error": str | None,            # set if clone/fetch failed (ok=True, non-blocking)
        }

    Design: clone failures are non-blocking (return ok=True with clone_error set)
    so the loop falls back to the existing auto_merge-stage validation. Only
    actual KB schema validation failures return ok=False.
    """
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    if not repo_url or not base_branch or not branch:
        return {
            "ok": True,
            "reason": "early_kb_validation_skipped_missing_env",
            "kb_validation": None,
            "files": [],
            "workspace": "",
            "clone_error": None,
        }
    workspace = _runtime_dir() / DEFAULT_MERGE_WORKSPACE_ROOT / f"{run_id}-kb-early"
    try:
        return _early_kb_validation_in_workspace(
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            workspace=workspace,
        )
    finally:
        _cleanup_merge_workspace(workspace)


def _early_kb_validation_in_workspace(
    *,
    base_branch: str,
    branch: str,
    repo_url: str,
    run_id: str,
    workspace: Path,
) -> Dict[str, Any]:
    try:
        files = _changed_files_for_branch(
            repo_url=repo_url,
            base_branch=base_branch,
            branch=branch,
            workspace=workspace,
        )
    except Exception as exc:
        # Clone/fetch failure is non-blocking: fall back to auto_merge-stage check.
        logger.warning(
            "early_kb_validation: clone/fetch failed for branch=%s run_id=%s: %s",
            branch,
            run_id,
            exc,
        )
        return {
            "ok": True,
            "reason": "early_kb_validation_clone_failed",
            "kb_validation": None,
            "files": [],
            "workspace": str(workspace),
            "clone_error": str(exc)[:500],
        }
    if not files:
        return {
            "ok": True,
            "reason": "early_kb_validation_no_changed_files",
            "kb_validation": None,
            "files": [],
            "workspace": str(workspace),
            "clone_error": None,
        }
    # Short-circuit: if no KB JSON files in the diff, skip validation entirely.
    kb_files = [f for f in files if _kb_json_kind_for_repo_path(f)]
    if not kb_files:
        return {
            "ok": True,
            "reason": "early_kb_validation_no_kb_json_changes",
            "kb_validation": None,
            "files": files,
            "workspace": str(workspace),
            "clone_error": None,
        }
    kb_validation = _validate_kb_json_changes_for_auto_merge(
        branch=branch,
        files=files,
        workspace=workspace,
    )
    return {
        "ok": bool(kb_validation.get("ok")),
        "reason": str(kb_validation.get("reason") or ""),
        "kb_validation": kb_validation,
        "files": files,
        "workspace": str(workspace),
        "clone_error": None,
    }


def _find_pr_number_for_branch(branch: str) -> Optional[int]:
    """Find the open PR number for a branch via `gh pr list --head`.

    Returns None if gh is unavailable, not authenticated, or no open PR exists.
    Never raises — PR commenting/labeling is best-effort.
    """
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = [
        "gh",
        "pr",
        "list",
        "--head",
        branch,
        "--state",
        "open",
        "--json",
        "number",
        "--jq",
        ".[0].number",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        logger.warning("kb_schema_retry: gh pr list failed for branch=%s: %s", branch, exc)
        return None
    if proc.returncode != 0:
        logger.warning(
            "kb_schema_retry: gh pr list rc=%s for branch=%s stderr=%s",
            proc.returncode,
            branch,
            (proc.stderr or "")[:200],
        )
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _gh_pr_comment(pr_number: int, body: str) -> bool:
    """Best-effort PR comment via `gh pr comment`. Returns True on success."""
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = [
        "gh",
        "pr",
        "comment",
        str(pr_number),
        "--body",
        body,
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:
        logger.warning("kb_schema_retry: gh pr comment failed pr=%s: %s", pr_number, exc)
        return False
    if proc.returncode != 0:
        logger.warning(
            "kb_schema_retry: gh pr comment rc=%s pr=%s stderr=%s",
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _gh_pr_add_label(pr_number: int, label: str) -> bool:
    """Best-effort PR label add via `gh pr edit --add-label`. Returns True on success."""
    repo = os.environ.get("GITHUB_REPO", "").strip()
    cmd: List[str] = [
        "gh",
        "pr",
        "edit",
        str(pr_number),
        "--add-label",
        label,
    ]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:
        logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s failed pr=%s: %s",
            label,
            pr_number,
            exc,
        )
        return False
    if proc.returncode != 0:
        # Most common failure: label doesn't exist in repo yet. Log but don't block.
        logger.warning(
            "kb_schema_retry: gh pr edit --add-label %s rc=%s pr=%s stderr=%s",
            label,
            proc.returncode,
            pr_number,
            (proc.stderr or "")[:200],
        )
        return False
    return True


def _existing_kb_schema_retry_item(
    open_items: List[Dict[str, Any]],
    *,
    branch: str,
    para_task_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Find the most recent non-escalated kb_schema_retry open_item.

    Matching priority (first match wins, scanning most-recent first):
      1. Exact branch match
      2. Exact para_task_id match
      3. Any non-escalated kb_schema_retry item within the last 24h
         (so retry_count escalates even if the employee pushes a new branch
         on each retry — common when the LLM doesn't reuse branches)
    """
    now = _utc_now()
    fallback_within_24h: Optional[Dict[str, Any]] = None
    for item in reversed(open_items):
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "kb_schema_retry":
            continue
        if item.get("escalated"):
            continue
        item_branch = str(item.get("branch") or "").strip()
        item_task_id = str(item.get("para_task_id") or "").strip()
        if branch and item_branch == branch:
            return item
        if para_task_id and item_task_id == para_task_id:
            return item
        # Fallback: track recent retries across different branches so the
        # employee cannot reset retry_count by creating a new branch each time.
        created_dt = _parse_iso(item.get("created_at") or item.get("last_attempted_at"))
        if created_dt and (now - created_dt).total_seconds() <= 24 * 3600:
            if fallback_within_24h is None:
                fallback_within_24h = item
    return fallback_within_24h


def _reject_and_retry_kb_schema_failure(
    *,
    run_id: str,
    branch: str,
    para_task_id: Optional[str],
    kb_validation: Dict[str, Any],
    steps: List[Dict[str, Any]],
    gate: Dict[str, Any],
    triggered_by: str = "scheduled_self_maintenance",
    started_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Reject KB-schema-invalid branch and retry code step (or escalate to human).

    Called immediately after code step completes when KB JSON schema validation fails.
    Actions (best-effort, never raises):
      1. Comment on the PR (find by branch via `gh pr list --head`)
      2. Add ``kb-schema-failed`` label to the PR
      3. Write/refresh a ``kb_schema_retry`` open_item in loop memory (retry_count++)
      4. If retry_count >= KB_SCHEMA_RETRY_MAX: add ``needs-human`` label, mark escalated
      5. Return a final state dict with policy_decision.action=hold_for_automated_remediation

    Next LOOP iteration sees the ``kb_schema_retry`` open_item and re-runs the code step
    (see ``_resume_review_qa_candidate``). After KB_SCHEMA_RETRY_MAX retries without
    resolution, the item is marked escalated so the loop stops retrying and waits for
    human review.
    """
    errors = kb_validation.get("errors") if isinstance(kb_validation, dict) else None
    if not isinstance(errors, list) or not errors:
        errors = [{"error": "unknown kb schema validation failure", "file": "", "kind": ""}]
    error_bullets = "\n".join(
        f"- file: `{e.get('file') or '?'}` kind: `{e.get('kind') or '?'}` error: {(e.get('error') or '')[:300]}"
        for e in errors[:8]
    )
    checked_files = kb_validation.get("checked") if isinstance(kb_validation, dict) else []
    checked_str = ", ".join(str(f) for f in checked_files) if checked_files else "(none)"

    # Load loop memory to compute retry_count
    memory = _load_loop_memory()
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    existing = _existing_kb_schema_retry_item(open_items, branch=branch, para_task_id=para_task_id)
    if existing is not None:
        retry_count = int(existing.get("retry_count") or 0) + 1
    else:
        retry_count = 1
    escalated = retry_count >= KB_SCHEMA_RETRY_MAX

    # 1. Find PR by branch
    pr_number = _find_pr_number_for_branch(branch)

    # 2. Comment on PR with error details
    comment_body = (
        f"## KB JSON schema validation failed (attempt {retry_count}/{KB_SCHEMA_RETRY_MAX})\n\n"
        f"The KB JSON file(s) in this branch failed schema validation. "
        f"Please fix the schema errors below and re-push.\n\n"
        f"**Checked files:** {checked_str}\n\n"
        f"**Errors:**\n{error_bullets}\n\n"
        f"**Required schema for fix KB** (`FHD/XCAGI/kb/fixes/*.json`):\n"
        "```json\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "kind": "fix",\n'
        '  "created_at": "<ISO-8601>",\n'
        '  "symptom": "<non-empty string>",\n'
        '  "root_cause": "<non-empty string>",\n'
        '  "fix_diff": "<non-empty string>",\n'
        '  "metadata": {},\n'
        '  "executable_template": {\n'
        '    "applicability_check": "<non-empty string>",\n'
        '    "patch_strategy": "<non-empty string>",\n'
        '    "rollback_plan": "<non-empty string>",\n'
        '    "required_tests": ["test_a.py"]\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "Validate before push:\n"
        "```\n"
        'python -c "from modstore_server.self_evolution_knowledge import validate_kb_payload; '
        "import json; validate_kb_payload('fixes', json.load(open('<file>')))\"\n"
        "```\n"
    )
    if escalated:
        comment_body += (
            f"\n\n**Escalated to human review** after {retry_count} retry attempts. "
            f"Manual fix required. The `needs-human` label has been applied."
        )
    if pr_number is not None:
        _gh_pr_comment(pr_number, comment_body)
        _gh_pr_add_label(pr_number, KB_SCHEMA_FAILED_LABEL)
        if escalated:
            _gh_pr_add_label(pr_number, NEEDS_HUMAN_LABEL)
    else:
        logger.warning(
            "kb_schema_retry: no open PR found for branch=%s; skipping PR comment/label",
            branch,
        )

    # 3. Write/refresh kb_schema_retry open_item
    now = _utc_now()
    if existing is not None:
        existing["retry_count"] = retry_count
        existing["last_attempted_at"] = _iso(now)
        existing["kb_validation_errors"] = errors[:10]
        existing["run_id"] = run_id
        existing["escalated"] = escalated
        if para_task_id:
            existing["para_task_id"] = para_task_id
    else:
        new_item: Dict[str, Any] = {
            "branch": branch,
            "created_at": _iso(now),
            "escalated": escalated,
            "kind": "kb_schema_retry",
            "kb_validation_errors": errors[:10],
            "last_attempted_at": _iso(now),
            "para_task_id": para_task_id,
            "retry_count": retry_count,
            "run_id": run_id,
            "steps": ["code"],
        }
        open_items.append(new_item)
    memory["open_items"] = open_items
    memory["updated_at"] = _iso(now)
    _write_loop_memory(memory)

    # 4. Governance audit record
    audit_record = {
        "action": "kb_schema_retry",
        "actor": "auto",
        "branch": branch,
        "escalated": escalated,
        "created_at": _iso(now),
        "kb_validation_errors": errors[:10],
        "ok": False,
        "pr_number": pr_number,
        "reason": "kb_json_schema_validation_failed",
        "retry_count": retry_count,
        "run_id": run_id,
        "source": "self_maintenance_loop_runner",
        "status": "escalated" if escalated else "retrying",
    }
    try:
        _append_governance_audit(audit_record)
    except Exception:
        logger.exception("kb_schema_retry: failed to write governance audit")

    # 5. Build final state — status must be distinct from generic ``failed`` so
    # observers / dashboards can tell KB writeback schema rejection apart from
    # dispatch or test failures.
    final_status = "completed_waiting_human_strategy" if escalated else KB_SCHEMA_FAILED_STATUS
    policy_decision = {
        "action": "hold_for_automated_remediation",
        "active_gates": {
            "kb_schema_gate": {
                "ok": False,
                "blocking": True,
                "label": KB_SCHEMA_FAILED_LABEL,
                "reason": "kb_json_schema_validation_failed",
                "retry_count": retry_count,
                "escalated": escalated,
                "status": final_status,
            }
        },
        "governance_gate": audit_record,
        "kb_validation": kb_validation,
        "reason": "kb_json_schema_validation_failed",
        "retry_count": retry_count,
        "escalated": escalated,
        "status": final_status,
    }
    final = {
        "branch": branch,
        "completed_at": _iso(now),
        "error": "kb_json_schema_validation_failed",
        "failed_step": "code",
        "failure_kind": KB_SCHEMA_FAILED_STATUS,
        "kb_schema_failed": True,
        "kb_schema_retry": True,
        "para_task_id": para_task_id,
        "phase": "complete",
        "policy_decision": policy_decision,
        "run_id": run_id,
        "started_at": _iso(started_at) if started_at else _iso(now),
        "status": final_status,
        "steps": steps,
        "triggered_by": triggered_by,
    }
    _append_ledger(final)
    return final


def _normalize_repo_path(file_name: str) -> str:
    return _shared_normalize_repo_path(file_name)


def _diff_stats_changed_files_consistency(
    files: List[str],
    diff_stats: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(diff_stats, dict) or diff_stats.get("source") != "git_diff_numstat":
        return {
            "ok": True,
            "reason": "diff_stats_consistency_not_enforced_for_legacy_input",
        }
    expected = {_normalize_repo_path(file_name) for file_name in files if file_name}
    stats_changed = diff_stats.get("changed_files")
    if not isinstance(stats_changed, list):
        file_stats = diff_stats.get("files") if isinstance(diff_stats.get("files"), dict) else {}
        binary_files = (
            diff_stats.get("binary_files")
            if isinstance(diff_stats.get("binary_files"), list)
            else []
        )
        stats_changed = list(file_stats.keys()) + binary_files
    actual = {_normalize_repo_path(str(file_name)) for file_name in stats_changed if str(file_name)}
    missing_from_numstat = sorted(expected - actual)
    extra_in_numstat = sorted(actual - expected)
    if missing_from_numstat or extra_in_numstat:
        return {
            "expected_name_only_files": sorted(expected),
            "extra_in_numstat": extra_in_numstat,
            "missing_from_numstat": missing_from_numstat,
            "numstat_files": sorted(actual),
            "ok": False,
            "reason": "changed_files_diff_stats_mismatch",
        }
    return {
        "checked_files": sorted(expected),
        "ok": True,
        "reason": "changed_files_diff_stats_match",
    }


def _file_matches_any_glob(file_name: str, globs: List[str]) -> bool:
    return _shared_file_matches_any_glob(file_name, globs)


def _files_match_allowed_globs(files: List[str], globs: List[str]) -> bool:
    if not files:
        return False
    for file_name in files:
        if not _file_matches_any_glob(file_name, globs):
            return False
    return True


def _auto_merge_max_risk_score() -> int:
    return max(0, min(_env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", 40), 100))


def _auto_merge_min_safety_score_v2() -> int:
    return max(
        0,
        min(
            _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V2", 90),
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


def _historical_rollback_rate(memory: Optional[Dict[str, Any]]) -> Optional[float]:
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
    if _kb_json_kind_for_repo_path(file_name):
        return 8
    if lower.endswith((".md", ".txt", ".json")):
        return 10
    if "/tests/" in lower or lower.startswith("tests/"):
        return 12
    if any(part in lower for part in ("/scripts/dev/", "self_maintenance", "self_evolution")):
        return 18
    if any(part in lower for part in ("/api/", "routes", "scheduler", "workflow", "employee")):
        return 32
    if any(
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

    normalized_files = [_normalize_repo_path(file_name) for file_name in files if file_name]
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    per_file_scores = [
        {"file": file_name, "score": _file_type_risk(file_name)} for file_name in normalized_files
    ]
    file_score = max([int(item["score"]) for item in per_file_scores] or [0])
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
            if any(term in file_name.lower() for file_name in normalized_files)
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
        review_json = _structured_report_from_step(review_steps[-1], STRUCTURED_REVIEW_MARKER)
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
        qa_json = _structured_report_from_step(qa_steps[-1], STRUCTURED_QA_MARKER)
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
    # A unified diff contains unchanged context and often a generated KB record.
    # Scanning both made a safe replacement such as ``python3`` -> ``sys.executable``
    # look dangerous merely because an unchanged context line called
    # ``subprocess.run`` and the KB explained that call. Score only added source
    # lines. Keep the old plain-text behavior for callers that provide a summary
    # rather than a unified diff.
    saw_unified_diff = False
    current_path = ""
    added_source_lines: List[str] = []
    excluded_added_line_prefixes = (
        "fhd/xcagi/kb/",
        "docs/",
    )
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
        if any(normalized_path.startswith(prefix) for prefix in excluded_added_line_prefixes):
            continue
        # Tests may legitimately name/mock a risky production API in order to
        # prove a narrow fix. Treating that test evidence as newly introduced
        # production behavior made adding the promised regression test lower
        # the score by 16 points. Production additions remain scanned.
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
    # Unknown history is uncertainty, not evidence of a rollback. Keep a small
    # conservative penalty while still allowing a genuinely narrow first run
    # with independent review/QA evidence to reach the documented >= 90 gate.
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
    except Exception as exc:
        return {
            "error": str(exc)[:500],
            "min_allowed": _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V3", 95),
            "ok": False,
            "reason": "risk_score_v3_unavailable",
            "schema_version": 3,
            "score": 0,
            "source": "risk_score_v3_error",
        }


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
    normalized_files = [_normalize_repo_path(file_name) for file_name in files if file_name]
    risk_score = _auto_merge_risk_score_v1(normalized_files, diff_stats, memory=memory)
    safety_score_v2 = _auto_merge_safety_score_v2(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        memory=memory,
        steps=steps,
    )
    safety_score_v3 = _auto_merge_safety_score_v3(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=memory,
        risk_score_v1=risk_score,
        safety_score_v2=safety_score_v2,
        steps=steps,
    )

    def _decision(payload: Dict[str, Any]) -> Dict[str, Any]:
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
            decision_payload: Dict[str, Any] = {
                "changed_files": normalized_files,
                "ok": False,
                **executable_block,
            }
            if "kb_paths" not in executable_block:
                decision_payload["allowed_globs"] = allowed
            return _decision(decision_payload)

        retort_block = retort_remediation.assess_retort_scope_diff_contract(
            memory,
            normalized_files,
            diff_stats,
            diff_excerpt=diff_excerpt,
        )
        if retort_block is not None:
            return _decision(
                {
                    "changed_files": normalized_files,
                    "ok": False,
                    **retort_block,
                }
            )
    except Exception as exc:
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

    consistency = _diff_stats_changed_files_consistency(normalized_files, diff_stats)
    if not consistency.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "ok": False,
                "reason": "changed_files_diff_stats_mismatch",
            }
        )

    absolute_forbidden_globs = _shared_auto_merge_absolute_forbidden_globs()
    absolute_forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _file_matches_any_glob(file_name, absolute_forbidden_globs)
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

    if _env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", True) and safety_score_v3.get("ok"):
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
        if _file_matches_any_glob(file_name, forbidden_globs)
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

    if _env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True):
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

    if _files_match_allowed_globs(normalized_files, allowed):
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

    if not _env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True):
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
        if not _file_matches_any_glob(file_name, scope_globs)
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


def _guest_auth_headers(api_base: str) -> Dict[str, str]:
    env_token = (
        os.environ.get("MODSTORE_PARA_AUTH_TOKEN") or os.environ.get("DEVFLEET_AUTH_TOKEN") or ""
    ).strip()
    if env_token:
        return {"Authorization": f"Bearer {env_token}"}

    cache_key = api_base.rstrip("/")
    cached = _PARA_GUEST_AUTH_CACHE.get(cache_key)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at:
            return {"Authorization": f"Bearer {token}"}
        _PARA_GUEST_AUTH_CACHE.pop(cache_key, None)

    file_token = _read_para_guest_auth_file(cache_key)
    if file_token:
        return {"Authorization": f"Bearer {file_token}"}

    local_token = _mint_local_para_guest_auth_token(cache_key)
    if local_token:
        return {"Authorization": f"Bearer {local_token}"}

    with httpx.Client(timeout=20.0, trust_env=False, verify=False) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(f"{api_base.rstrip('/')}/api/auth/guest")
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
        if resp is None:
            raise RuntimeError("Para guest auth request was not attempted")
        resp.raise_for_status()
        token = str((resp.json() or {}).get("token") or "").strip()
        if not token:
            raise RuntimeError("Para guest auth response missing token")
    expires_at = time.time() + _PARA_GUEST_AUTH_TTL_SECONDS
    _PARA_GUEST_AUTH_CACHE[cache_key] = (
        token,
        expires_at,
    )
    _write_para_guest_auth_file(cache_key, token, expires_at)
    return {"Authorization": f"Bearer {token}"}


def para_auth_cache_path() -> Path:
    override = os.environ.get("MODSTORE_PARA_AUTH_CACHE")
    if override:
        return Path(override)
    return _runtime_dir() / DEFAULT_PARA_AUTH_CACHE_NAME


def _read_para_guest_auth_file(
    api_base: str, *, min_ttl_seconds: int = _PARA_GUEST_AUTH_FILE_SAFETY_SECONDS
) -> Optional[str]:
    path = para_auth_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("failed to read Para guest auth cache file", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    cache_key = api_base.rstrip("/")
    if str(data.get("api_base") or "").rstrip("/") != cache_key:
        return None
    token = str(data.get("token") or "").strip()
    try:
        expires_at = float(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if not token or time.time() + min_ttl_seconds >= expires_at:
        return None
    _PARA_GUEST_AUTH_CACHE[cache_key] = (token, expires_at)
    return token


def _write_para_guest_auth_file(api_base: str, token: str, expires_at: float) -> None:
    path = para_auth_cache_path()
    payload = {
        "api_base": api_base.rstrip("/"),
        "created_at": _utc_now().isoformat(),
        "expires_at": expires_at,
        "expires_at_iso": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "token": token,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        logger.warning("failed to write Para guest auth cache file", exc_info=True)


def _base64url_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _mint_local_para_guest_auth_token(api_base: str) -> Optional[str]:
    if not _env_bool("MODSTORE_PARA_AUTH_LOCAL_MINT", True):
        return None
    db_file = _para_db_file()
    # _para_db_file() 在没有本地 Para DB（如 CVM 远程触发场景）时返回 None，
    # 不能调 .exists()，否则 NoneType.exists() 会抛 AttributeError。
    if db_file is None or not db_file.exists():
        return None
    try:
        with sqlite3.connect(str(db_file), timeout=2.0) as conn:
            # fmt: off
            row = conn.execute("""
                select id, email
                from users
                where email = 'guest@devfleet.local'
                   or (email like 'guest_%@devfleet.local')
                order by case when email = 'guest@devfleet.local' then 0 else 1 end
                limit 1
                """).fetchone()
            # fmt: on
    except Exception:
        logger.warning(
            "failed to read Para guest user from sqlite for local auth mint",
            exc_info=True,
        )
        return None
    if not row:
        return None
    user_id, email = str(row[0] or "").strip(), str(row[1] or "").strip()
    if not user_id or not email:
        return None
    now = int(time.time())
    expires_at = now + 7 * 24 * 60 * 60
    secret = (
        os.environ.get("MODSTORE_PARA_JWT_SECRET")
        or os.environ.get("JWT_SECRET")
        or "devfleet-dev-secret-change-me"
    )
    header = _base64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _base64url_json(
        {
            "email": email,
            "exp": expires_at,
            "iat": now,
            "id": user_id,
            "sub": user_id,
        }
    )
    unsigned = f"{header}.{payload}"
    signature = _base64url_bytes(
        hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256).digest()
    )
    token = f"{unsigned}.{signature}"
    cache_key = api_base.rstrip("/")
    _PARA_GUEST_AUTH_CACHE[cache_key] = (token, float(expires_at))
    _write_para_guest_auth_file(cache_key, token, float(expires_at))
    return token


def _kickstart_para_agent() -> Dict[str, Any]:
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_KICKSTART_PARA_AGENT", True):
        return {"attempted": False, "reason": "disabled"}
    import sys

    if sys.platform != "darwin":
        return {
            "attempted": False,
            "reason": f"platform {sys.platform} not supported (launchctl is macOS only)",
        }
    label = os.environ.get(
        "MODSTORE_PARA_AGENT_LAUNCHD_LABEL",
        "com.xcmax.para-main-agent.watchdog",
    )
    target = f"gui/{os.getuid()}/{label}"
    domain = f"gui/{os.getuid()}"
    plist = Path(
        os.environ.get("MODSTORE_PARA_AGENT_LAUNCHD_PLIST")
        or str(Path.home() / "Library/LaunchAgents" / f"{label}.plist")
    )
    try:
        output = _run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
        return {"attempted": True, "ok": True, "output": output, "target": target}
    except Exception as first_exc:
        bootstrap_result: Dict[str, Any] = {"attempted": False}
        if plist.exists():
            try:
                bootstrap_output = _run_cmd(
                    ["launchctl", "bootstrap", domain, str(plist)], timeout=30
                )
                bootstrap_result = {
                    "attempted": True,
                    "ok": True,
                    "output": bootstrap_output,
                    "plist": str(plist),
                }
            except Exception as bootstrap_exc:
                bootstrap_text = str(bootstrap_exc)
                bootstrap_result = {
                    "attempted": True,
                    "error": bootstrap_text,
                    "ok": "already bootstrapped" in bootstrap_text.lower(),
                    "plist": str(plist),
                }
        try:
            output = _run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "ok": True,
                "output": output,
                "target": target,
            }
        except Exception as second_exc:
            logger.warning(
                "failed to bootstrap/kickstart Para agent target=%s first=%s second=%s",
                target,
                first_exc,
                second_exc,
            )
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "error": str(second_exc),
                "first_error": str(first_exc),
                "ok": False,
                "target": target,
            }


def _para_db_file() -> Optional[Path]:
    raw = os.environ.get("MODSTORE_PARA_DB_FILE") or os.environ.get("DEVFLEET_DB_FILE")
    if not raw:
        candidate = Path.home() / "XCMAX-runtime/para-api/devfleet/api/data/devfleet.db"
        return candidate if candidate.exists() else None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _clear_stale_para_current_task(*, device_id: str, current_task: str) -> Dict[str, Any]:
    db_file = _para_db_file()
    if db_file is None:
        return {"cleared": False, "reason": "para_db_file_missing"}
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "update tool_statuses set current_task=NULL, status='idle' "
                "where device_id=? and tool_name='codex' and current_task=?",
                (device_id, current_task),
            )
            if cur.rowcount <= 0:
                cur = conn.execute(
                    "update tool_statuses set current_task=NULL, status='idle' "
                    "where device_id=? and tool_name='codex' and status='idle' "
                    "and current_task is not null and current_task <> ''",
                    (device_id,),
                )
            conn.commit()
        return {"cleared": cur.rowcount > 0, "db_file": str(db_file)}
    except Exception as exc:
        logger.exception("failed to clear stale para current_task")
        return {"cleared": False, "error": str(exc), "db_file": str(db_file)}


def _reconcile_orphan_para_running_tasks(*, device_id: str) -> Dict[str, Any]:
    db_file = _para_db_file()
    if db_file is None:
        return {"reconciled": False, "reason": "para_db_file_missing"}
    ttl_sec = max(30, _env_int("MODSTORE_PARA_ORPHAN_RUNNING_TASK_TTL_SEC", 300))
    now = _utc_now()
    cutoff = now - timedelta(seconds=ttl_sec)
    now_text = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cutoff_text = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                """
                select id, task_id
                from sub_tasks
                where device_id=?
                  and tool_name='codex'
                  and status='running'
                  and coalesce(updated_at, created_at, '') < ?
                """,
                (device_id, cutoff_text),
            ).fetchall()
            task_ids = sorted({str(row[1]) for row in rows if row and row[1]})
            if rows:
                conn.executemany(
                    """
                    update sub_tasks
                    set status='failed',
                        completed_at=?,
                        updated_at=?,
                        last_error=coalesce(last_error, 'orphan running task reclaimed because codex tool is idle')
                    where id=?
                    """,
                    [(now_text, now_text, str(row[0])) for row in rows],
                )
                for task_id in task_ids:
                    remaining = conn.execute(
                        "select count(*) from sub_tasks where task_id=? and status='running'",
                        (task_id,),
                    ).fetchone()
                    if int((remaining or [0])[0] or 0) <= 0:
                        conn.execute(
                            "update tasks set status='failed', completed_at=? where id=? and status='running'",
                            (now_text, task_id),
                        )
            conn.commit()
        return {
            "db_file": str(db_file),
            "reconciled": bool(rows),
            "subtask_count": len(rows),
            "task_ids": task_ids,
            "ttl_sec": ttl_sec,
        }
    except Exception as exc:
        logger.exception("failed to reconcile orphan Para running tasks")
        return {"reconciled": False, "error": str(exc), "db_file": str(db_file)}


def _wait_for_para_device_online() -> Dict[str, Any]:
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    device_id = os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    if not api_base or not device_id:
        return {"online": False, "reason": "missing_para_api_base_or_device_id"}

    timeout_sec = max(0, _env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", 60))
    poll_sec = max(1, _env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_POLL_SEC", 5))
    deadline = time.monotonic() + timeout_sec
    last_status: Dict[str, Any] = {}
    last_error = ""
    headers: Optional[Dict[str, str]] = None
    kickstart_result: Optional[Dict[str, Any]] = None

    while True:
        try:
            if headers is None:
                headers = _guest_auth_headers(api_base)
            with httpx.Client(timeout=15.0, trust_env=False, verify=False) as client:
                resp = client.get(f"{api_base.rstrip('/')}/api/devices", headers=headers)
                if resp.status_code in {401, 403}:
                    headers = None
                    _PARA_GUEST_AUTH_CACHE.pop(api_base.rstrip("/"), None)
                    raise RuntimeError(f"device status auth failed: {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json() or {}
            devices = payload.get("devices") if isinstance(payload, dict) else payload
            if not isinstance(devices, list):
                devices = []
            target = None
            for item in devices:
                if isinstance(item, dict) and str(item.get("id") or "") == device_id:
                    target = item
                    break
            if target is None:
                last_status = {"reason": "device_not_found", "device_id": device_id}
            else:
                status = str(target.get("status") or "").lower()
                online = bool(target.get("online")) or status == "online"
                codex_tool = {}
                tools = target.get("tools")
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict) and str(tool.get("toolName") or "") == "codex":
                            codex_tool = tool
                            break
                tool_status = str(codex_tool.get("status") or "").lower()
                current_task = str(codex_tool.get("currentTask") or "").strip()
                stale_clear: Optional[Dict[str, Any]] = None
                if online and current_task and tool_status in {"", "idle"}:
                    stale_clear = _clear_stale_para_current_task(
                        device_id=device_id,
                        current_task=current_task,
                    )
                    if stale_clear.get("cleared"):
                        last_status = {
                            "codex_tool": codex_tool,
                            "device_id": device_id,
                            "name": target.get("name"),
                            "online": online,
                            "stale_clear": stale_clear,
                            "status": target.get("status"),
                        }
                        return {
                            **last_status,
                            "reason": "online_after_stale_current_task_clear",
                        }
                if online and current_task:
                    # Device is online but busy. Do not rewrite online→False (that made
                    # force-loops burn the full wait window then look "offline").
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": True,
                        "busy": True,
                        "stale_clear": stale_clear,
                        "status": target.get("status"),
                    }
                    if _env_bool("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE", False):
                        return {**last_status, "reason": "online_busy_allowed"}
                    # Keep polling until idle or timeout; kickstart once in case agent wedged.
                    if kickstart_result is None:
                        kickstart_result = _kickstart_para_agent()
                        headers = None
                else:
                    orphan_reconcile: Optional[Dict[str, Any]] = None
                    if online and not current_task and tool_status in {"", "idle"}:
                        orphan_reconcile = _reconcile_orphan_para_running_tasks(
                            device_id=device_id,
                        )
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": online,
                        "orphan_reconcile": orphan_reconcile,
                        "status": target.get("status"),
                    }
                    if online:
                        return {**last_status, "reason": "online"}
                    if kickstart_result is None:
                        kickstart_result = _kickstart_para_agent()
                        headers = None
        except Exception as exc:
            last_error = str(exc)
            if kickstart_result is None:
                kickstart_result = _kickstart_para_agent()
                headers = None

        if time.monotonic() >= deadline:
            was_online = bool(last_status.get("online")) or bool(last_status.get("busy"))
            return {
                **last_status,
                "error": last_error,
                "kickstart": kickstart_result,
                "online": was_online,
                "reason": (
                    "device_busy_wait_timeout"
                    if last_status.get("busy")
                    else "device_online_wait_timeout"
                ),
                "timeout_sec": timeout_sec,
            }
        time.sleep(poll_sec)


def _mark_para_task_merged(*, api_base: str, task_id: str, merge_sha: str) -> Dict[str, Any]:
    headers = _guest_auth_headers(api_base)
    with httpx.Client(timeout=30.0, trust_env=False, verify=False) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/merge",
            headers=headers,
            json={"merge_commit_sha": merge_sha},
        )
        resp.raise_for_status()
        return resp.json()


def _request_para_task_merge(*, api_base: str, task_id: str) -> Dict[str, Any]:
    """Queue the already-pushed Para workspace only after loop gates pass.

    The CVM cannot reach GitHub directly, while the Para worker on the Mac can.
    Keeping this request here makes review, QA and ``autonomy_guard`` the sole
    authorization path; the device agent only prepares and pushes the branch.
    """

    workspace_root = (
        os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace"
    ).strip()
    workspace_path = str(Path(workspace_root).expanduser() / task_id)
    headers = _guest_auth_headers(api_base)
    with httpx.Client(timeout=30.0, trust_env=False, verify=False) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/request-merge",
            headers=headers,
            json={"workspace_path": workspace_path, "auto_merge": True},
        )
        resp.raise_for_status()
        payload = resp.json()
    return {
        "ok": True,
        "para_response": payload,
        "reason": "merge_requested_after_loop_risk_gate",
        "workspace_path": workspace_path,
    }


def _loop_steps_roster_gate(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    participant_ids: set[str] = set()

    def _collect(value: Any) -> None:
        if isinstance(value, dict):
            for key in (
                "employee_id",
                "employeeId",
                "emp_id",
                "empId",
                "actor",
                "assignee",
                "worker_id",
                "role_employee_id",
            ):
                text = str(value.get(key) or "").strip()
                if text:
                    participant_ids.add(text)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    _collect(child)
        elif isinstance(value, list):
            for item in value:
                _collect(item)

    _collect(steps)
    try:
        planned_ids = set(all_planned_employee_ids())
    except Exception as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_roster_load_error",
        }
    try:
        deployed_ids = set(duty_employee_records().keys())
    except Exception as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_employee_registry_load_error",
        }
    in_roster_ids = sorted(emp_id for emp_id in participant_ids if emp_id in planned_ids)
    out_of_roster_ids = sorted(emp_id for emp_id in participant_ids if emp_id not in planned_ids)
    not_deployed_ids = sorted(emp_id for emp_id in in_roster_ids if emp_id not in deployed_ids)
    if out_of_roster_ids:
        return {
            "action": "isolate",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "ok": False,
            "out_of_roster_ids": out_of_roster_ids,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "out_of_roster_participants_detected",
        }
    if not_deployed_ids:
        return {
            "action": "hold",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "not_deployed_ids": not_deployed_ids,
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "in_roster_but_not_registered_duty_employee",
        }
    if not participant_ids:
        return {
            "action": "wait",
            "blocking": True,
            "in_roster_ids": [],
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": 0,
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "no_loop_participants_detected",
        }
    return {
        "action": "allow",
        "blocking": False,
        "in_roster_ids": in_roster_ids,
        "ok": True,
        "out_of_roster_ids": [],
        "participant_count": len(participant_ids),
        "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
        "reason": "all_participants_are_in_duty_roster",
    }


def _auto_merge_low_risk_branch(
    *,
    run_id: str,
    task_id: Optional[str],
    branch: Optional[str],
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not task_id or not branch:
        return {"ok": False, "reason": "missing_task_or_branch"}

    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    # Security guard: by default only local file:// repos allow auto-merge.
    # Trusted remote repos use the Para worker, but the request is emitted only
    # after review, QA and the autonomy SSOT have all passed.
    allow_remote = _env_bool("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", False)
    if not repo_url.startswith("file://") and not (
        allow_remote and repo_url.startswith(("http://", "https://"))
    ):
        return {"ok": False, "reason": "repo_url_not_file_url", "repo_url": repo_url}
    if not base_branch:
        return {"ok": False, "reason": "missing_base_branch"}
    if not api_base:
        return {"ok": False, "reason": "missing_api_base"}

    if repo_url.startswith(("http://", "https://")):
        report_gate = _structured_report_gate(steps or [], branch)
        if not report_gate.get("ok"):
            return {
                "ok": False,
                "reason": report_gate.get("reason") or "structured_reports_not_passed",
                "structured_report_gate": report_gate,
            }

        branch_head_sha = _remote_branch_head(repo_url, branch)
        base_head_sha = _remote_branch_head(repo_url, base_branch)
        if base_head_sha and branch_head_sha == base_head_sha:
            return {
                "ok": False,
                "reason": "remote_branch_not_advanced",
                "branch": branch,
                "branch_head_sha": branch_head_sha,
            }

        # Production CVM deployments intentionally do not require direct GitHub
        # reachability.  When ls-remote is unavailable, defer the remote-head
        # check to the authenticated Para merge worker.  That worker creates or
        # reuses the PR by the exact reviewed branch name and fails closed if
        # the branch is absent; review/QA and the autonomy guard still run here
        # before the merge request is emitted.
        head_verification = (
            "verified_on_cvm" if branch_head_sha else "delegated_to_para_merge_worker"
        )

        from modstore_server.autonomy_guard_delegate import evaluate_risk

        decision = evaluate_risk(
            "self_maintenance_l1_merge",
            action_id=f"loop:{run_id}:self_maintenance_l1_merge",
            source="self_maintenance_loop.remote_merge_request",
        )
        if not decision.allowed:
            return {
                "ok": False,
                "reason": "autonomy_guard_blocked",
                "risk_decision": decision.to_dict(),
            }
        try:
            request_result = _request_para_task_merge(api_base=api_base, task_id=task_id)
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc)[:500],
                "reason": "para_merge_request_failed",
                "risk_decision": decision.to_dict(),
            }
        merge_request_record = {
            "base_branch": base_branch,
            "base_head_sha": base_head_sha or "",
            "branch": branch,
            "branch_head_sha": branch_head_sha or "",
            "created_at": _iso(_utc_now()),
            "event": "merge_requested",
            "head_verification": head_verification,
            "ok": True,
            "para_task_id": task_id,
            "phase": "merge",
            "run_id": run_id,
            "status": "pending",
        }
        _append_ledger(merge_request_record)
        _append_governance_audit(
            {
                **merge_request_record,
                "kind": "merge_requested",
            }
        )
        return {
            "ok": True,
            "base_head_sha": base_head_sha or "",
            "branch_head_sha": branch_head_sha or "",
            "head_verification": head_verification,
            "merge_requested": True,
            "para_request": request_result,
            "reason": "merge_requested_after_loop_risk_gate",
            "risk_decision": decision.to_dict(),
            "structured_report_gate": report_gate,
        }

    workspace = _runtime_dir() / DEFAULT_MERGE_WORKSPACE_ROOT / run_id
    try:
        return _auto_merge_local_repo(
            api_base=api_base,
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            steps=steps,
            task_id=task_id,
            workspace=workspace,
        )
    finally:
        _cleanup_merge_workspace(workspace)


def _auto_merge_local_repo(
    *,
    api_base: str,
    base_branch: str,
    branch: str,
    repo_url: str,
    run_id: str,
    steps: Optional[List[Dict[str, Any]]],
    task_id: str,
    workspace: Path,
) -> Dict[str, Any]:
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    decision = evaluate_risk(
        "self_maintenance_l1_merge",
        action_id=f"loop:{run_id}:self_maintenance_l1_merge",
        source="self_maintenance_loop.auto_merge",
    )
    if not decision.allowed:
        return {
            "ok": False,
            "reason": "autonomy_guard_blocked",
            "risk_decision": decision.to_dict(),
        }

    files = _changed_files_for_branch(
        repo_url=repo_url,
        base_branch=base_branch,
        branch=branch,
        workspace=workspace,
    )
    if not files:
        # 分支不在远程或无变更 → 不能 auto_merge，降级为 await_human。
        return {
            "ok": False,
            "reason": "branch_not_on_remote_or_empty",
            "branch": branch,
            "changed_files": [],
        }
    diff_stats = _diff_numstat_for_branch(
        base_branch=base_branch, branch=branch, workspace=workspace
    )
    diff_excerpt = _run_cmd_excerpt(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--find-renames",
            "--unified=3",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
        timeout=180,
        max_chars=20000,
    )
    kb_validation = _validate_kb_json_changes_for_auto_merge(
        branch=branch,
        files=files,
        workspace=workspace,
    )
    if not kb_validation.get("ok"):
        return {
            "changed_files": files,
            "kb_validation": kb_validation,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    policy = _assess_branch_auto_merge_policy(
        files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=_load_loop_memory(),
        steps=steps,
    )
    if not policy.get("ok"):
        return policy

    _run_cmd(["git", "merge", "--no-ff", "--no-edit", f"origin/{branch}"], cwd=workspace)
    merge_sha = _run_cmd(["git", "rev-parse", "HEAD"], cwd=workspace)
    # Push 到 origin 可能因认证/权限失败（如 GitHub https 需 token）。
    # 失败时降级为 await_human，不让整个 auto_merge 崩溃。
    _push_proc = subprocess.run(
        ["git", "push", "origin", f"HEAD:{base_branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if _push_proc.returncode != 0:
        return {
            "ok": False,
            "reason": "push_to_origin_failed",
            "merge_sha": merge_sha,
            "push_stderr": (_push_proc.stderr or "")[:500],
            "branch": branch,
        }
    para_update = _mark_para_task_merged(api_base=api_base, task_id=task_id, merge_sha=merge_sha)
    return {
        **policy,
        "diff_excerpt": diff_excerpt,
        "kb_validation": kb_validation,
        "merge_commit_sha": merge_sha,
        "ok": True,
        "para_update": para_update,
        "reason": "merged_low_risk_branch",
        "workspace": str(workspace),
    }


def _auto_dispatch_deploy_envs() -> List[str]:
    """Return ordered deploy envs when auto-dispatch master switch is on.

    默认仅 staging；production 必须显式写在 ENVS 中才会出现。
    staging always precedes production when both are requested.
    """
    if not _auto_dispatch_deploy_enabled():
        return []
    raw = str(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_ENVS", "") or ""
    ).strip()
    if not raw:
        return ["staging"]
    requested: List[str] = []
    for part in raw.split(","):
        env = part.strip().lower()
        if env in {"staging", "production"} and env not in requested:
            requested.append(env)
    return [env for env in ("staging", "production") if env in requested]


def _dispatch_fhd_deploy_action(
    *,
    environment: str,
    action: str,
    action_id: str,
) -> Dict[str, Any]:
    """Dispatch ``fhd-deploy.yml`` via ``gh workflow run`` (or dry-run skip)."""
    gh_command = (
        "gh workflow run fhd-deploy.yml "
        f"-f environment={environment} "
        f"-f action={action} "
        f"-f action_id={action_id}"
    )
    # gh workflow run needs a git repo cwd to resolve the remote; the runtime
    # copy under XCMAX-runtime/ is not a git repo, so use MODSTORE_GIT_REPO_ROOT.
    deploy_cwd = os.environ.get("MODSTORE_GIT_REPO_ROOT") or None
    if _env_flag_enabled("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"):
        return {
            "ok": True,
            "reason": "dry_run_skipped",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": "",
            "gh_exit_code": 0,
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    try:
        proc = subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "fhd-deploy.yml",
                "-f",
                f"environment={environment}",
                "-f",
                f"action={action}",
                "-f",
                f"action_id={action_id}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=deploy_cwd,
        )
        ok = proc.returncode == 0
        output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
        return {
            "ok": ok,
            "reason": "dispatched" if ok else "gh_non_zero_exit",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": output,
            "gh_exit_code": int(proc.returncode),
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    except Exception as exc:  # noqa: BLE001 — surface to ledger
        return {
            "ok": False,
            "reason": f"dispatch_threw:{exc}",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": str(exc),
            "gh_exit_code": -1,
            "action_id": action_id,
        }


def _dispatch_deploy_for_merge(
    *,
    run_id: str,
    branch: str,
    environments: List[str],
) -> List[Dict[str, Any]]:
    """Apply-latest per env after low-risk merge; freeze and stop on first failure."""
    results: List[Dict[str, Any]] = []
    for environment in environments:
        action_id = f"loop:{run_id}:deploy:{environment}"
        result = _dispatch_fhd_deploy_action(
            environment=environment,
            action="apply-latest",
            action_id=action_id,
        )
        record = {
            "event": "deploy_dispatch",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "apply-latest",
            "ok": bool(result.get("ok")),
            "reason": result.get("reason"),
            "action_id": action_id,
            "gh_command": result.get("gh_command"),
            "gh_exit_code": result.get("gh_exit_code"),
        }
        try:
            _append_ledger(record)
        except Exception:  # noqa: BLE001
            logger.exception("failed to append deploy_dispatch ledger")
        try:
            _append_governance_audit({**record, "kind": "deploy_dispatch"})
        except Exception:  # noqa: BLE001
            logger.exception("failed to append deploy_dispatch governance audit")
        results.append(result)
        if result.get("ok"):
            continue
        freeze_id = f"loop:{run_id}:freeze:{environment}"
        freeze_result = _dispatch_fhd_deploy_action(
            environment=environment,
            action="freeze-manifest",
            action_id=freeze_id,
        )
        freeze_record = {
            "event": "deploy_freeze",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "freeze-manifest",
            "ok": bool(freeze_result.get("ok")),
            "reason": freeze_result.get("reason"),
            "action_id": freeze_id,
            "triggered_by": action_id,
        }
        try:
            _append_ledger(freeze_record)
        except Exception:  # noqa: BLE001
            logger.exception("failed to append deploy_freeze ledger")
        try:
            _append_governance_audit({**freeze_record, "kind": "deploy_freeze"})
        except Exception:  # noqa: BLE001
            logger.exception("failed to append deploy_freeze governance audit")
        # 显式 callback 通知（非仅流程内嵌）：deploy 失败 + freeze 结果回写 ingest
        try:
            _emit_deploy_callback(
                phase="dispatch_failed",
                payload={
                    **record,
                    "freeze_ok": bool(freeze_result.get("ok")),
                    "freeze_action_id": freeze_id,
                },
                action_id=action_id,
            )
            _emit_deploy_callback(
                phase="freeze_manifest",
                payload=freeze_record,
                action_id=freeze_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to emit deploy_callback after freeze")
        break
    return results


def _emit_deploy_callback(
    *,
    phase: str,
    payload: Dict[str, Any],
    action_id: Optional[str] = None,
) -> None:
    """Fail-open 调用 FHD autonomy deploy_callback（或等价 ingest HTTP）。"""
    try:
        autonomy_scripts = Path(__file__).resolve().parents[3] / "FHD" / "scripts" / "autonomy"
        candidates = [
            autonomy_scripts,
            Path(os.environ.get("XCAGI_FHD_RUNTIME_ROOT", "")) / "scripts" / "autonomy",
            Path(__file__).resolve().parents[2] / "FHD" / "scripts" / "autonomy",
        ]
        for candidate in candidates:
            if candidate and (candidate / "autonomy_callback.py").is_file():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                from autonomy_callback import deploy_callback  # type: ignore[import-not-found]

                deploy_callback(phase, payload, source="self_maintenance", action_id=action_id)
                return
    except Exception:  # noqa: BLE001
        logger.debug("deploy_callback import path failed", exc_info=True)

    base_url = (os.environ.get("FHD_API_BASE_URL") or "").strip()
    token = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    if not base_url or not token:
        return
    body: Dict[str, Any] = {
        "action": f"deploy:{phase}",
        "payload": {**payload, "callback_event": f"deploy:{phase}"},
        "source": "self_maintenance",
    }
    if action_id:
        body["action_id"] = action_id
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{base_url.rstrip('/')}/api/ops/autonomy/actions/ingest",
                headers={
                    "X-Autonomy-Token": token,
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except Exception:  # noqa: BLE001
        logger.debug("deploy_callback HTTP fallback failed", exc_info=True)


def _record_verified_deploy_employee_metric(record: Dict[str, Any]) -> bool:
    """Credit the release officer only for an exact verified production deploy.

    Dispatch acceptance, staging success and uncorrelated health checks are not
    employee evidence.  The deterministic task marker makes callback retries
    idempotent.
    """

    if not (
        str(record.get("event") or "") == "post_deploy_verified"
        and str(record.get("environment") or "").strip().lower() == "production"
        and record.get("ok") is True
        and record.get("identity_verified") is True
        and str(record.get("status") or "").strip().lower() == "verified"
    ):
        return False
    run_id = str(record.get("run_id") or "").strip()
    merge_sha = str(record.get("merge_sha") or "").strip().lower()
    workflow_run_id = str(record.get("workflow_run_id") or "").strip()
    if not run_id or not re.fullmatch(r"[0-9a-f]{40,64}", merge_sha) or not workflow_run_id:
        return False
    marker = f"[deploy-receipt:{run_id}:{merge_sha[:12]}:{workflow_run_id}]"[:128]
    try:
        sf = get_session_factory()
        with sf() as session:
            exists = (
                session.query(EmployeeExecutionMetric.id)
                .filter(
                    EmployeeExecutionMetric.employee_id == "deploy-release-officer",
                    EmployeeExecutionMetric.task == marker,
                    EmployeeExecutionMetric.status == "success",
                )
                .first()
            )
            if exists:
                return False
            user = (
                session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
                or session.query(User).order_by(User.id.asc()).first()
            )
            if user is None:
                logger.warning("deploy receipt metric skipped: no user row")
                return False
            session.add(
                EmployeeExecutionMetric(
                    user_id=int(user.id),
                    employee_id="deploy-release-officer",
                    task=marker,
                    status="success",
                    duration_ms=0.0,
                    llm_tokens=0,
                    error="",
                    failure_kind="",
                )
            )
            session.commit()
        return True
    except Exception:
        logger.exception("failed to record verified deploy release employee metric")
        return False


def _append_deploy_receipt_event(record: Dict[str, Any]) -> None:
    """Write the same deployment receipt to loop and governance ledgers."""

    _append_ledger(record)
    _append_governance_audit(
        {
            **record,
            "kind": str(record.get("event") or "deployment_receipt"),
        }
    )
    _record_verified_deploy_employee_metric(record)


def _run_deploy_receipts_after_merge(
    *,
    run_id: str,
    merge_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run staging receipts only after a concrete pushed merge.

    This path is inert by default. It uses a new switch so a legacy dispatch
    flag cannot silently activate it. Production requires its own explicit
    switch and remains gated on a verified staging receipt.
    """

    if not _env_bool("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", False):
        return {"enabled": False, "reason": "deploy_receipts_disabled"}
    if bool(merge_result.get("merge_requested")):
        return {"enabled": True, "ok": False, "reason": "merge_not_completed"}
    merge_sha = str(merge_result.get("merge_commit_sha") or "").strip()
    if not merge_sha:
        return {"enabled": True, "ok": False, "reason": "merge_sha_missing"}

    repo_root_text = str(os.environ.get("MODSTORE_GIT_REPO_ROOT") or "").strip()
    deploy_ref = str(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_DEPLOY_REF")
        or os.environ.get("MODSTORE_PARA_BRANCH")
        or ""
    ).strip()
    try:
        from modstore_server.self_maintenance_deploy_receipts import (
            GhActionsDeploymentGateway,
            run_staged_deployment_chain,
        )

        gateway = GhActionsDeploymentGateway.from_environment(
            repo_root=Path(repo_root_text).expanduser(),
            ref=deploy_ref,
        )
        result = run_staged_deployment_chain(
            gateway=gateway,
            record_event=_append_deploy_receipt_event,
            run_id=run_id,
            merge_sha=merge_sha,
            allow_production=_env_bool(
                "MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED",
                False,
            ),
        )
        return {"enabled": True, **result}
    except Exception as exc:  # noqa: BLE001 - setup must fail closed
        failure = {
            "event": "deploy_verification_failed",
            "phase": "deployment",
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": "staging",
            "status": "failed",
            "ok": False,
            "reason": "deploy_receipt_setup_failed",
            "error_type": type(exc).__name__,
        }
        _append_deploy_receipt_event(failure)
        return {
            "enabled": True,
            "ok": False,
            "reason": "deploy_receipt_setup_failed",
        }


def _decide_post_loop_policy(
    *,
    branch: Optional[str],
    gate: Dict[str, Any],
    para_task_id: Optional[str],
    run_id: str,
    status: str,
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    def _hold_for_remediation(reason: str, **extra: Any) -> Dict[str, Any]:
        return {
            "action": "hold_for_automated_remediation",
            "reason": reason,
            **extra,
        }

    if status != "completed":
        return {"action": "stop", "reason": "loop_not_completed"}
    if any(not bool(step.get("ok")) for step in steps):
        return {"action": "stop", "reason": "employee_step_failed"}
    structured_gate = _structured_report_gate(steps, branch)
    report_only_missing = _missing_report_only_evidence(steps)
    roster_gate = _loop_steps_roster_gate(steps)
    governance_gate = _governance_audit_gate()
    try:
        evolution_gate = evolution_metrics_gate()
    except Exception as exc:
        logger.exception("failed to evaluate evolution metrics gate for policy active gates")
        evolution_gate = {
            "pause": False,
            "reason": "metrics_gate_error",
            "error": str(exc)[:300],
            "history_count": 0,
        }
    active_gates = _policy_active_gates_snapshot(
        evolution_metrics=evolution_gate,
        gate=gate,
        governance_gate=governance_gate,
        report_only_missing=report_only_missing,
        roster_gate=roster_gate,
        structured_gate=structured_gate,
    )
    if not structured_gate.get("ok"):
        return _hold_for_remediation(
            structured_gate.get("reason") or "structured_report_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
            structured_gate=structured_gate,
        )
    if report_only_missing:
        return _hold_for_remediation(
            "missing_report_only_evidence",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not roster_gate.get("ok"):
        return _hold_for_remediation(
            roster_gate.get("reason") or "roster_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not governance_gate.get("ok"):
        return _hold_for_remediation(
            governance_gate.get("reason") or "governance_gate_failed",
            active_gates=active_gates,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if bool(evolution_gate.get("pause")):
        return _hold_for_remediation(
            evolution_gate.get("reason") or "evolution_metrics_pause",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not branch:
        return {
            "action": "auto_continue",
            "active_gates": active_gates,
            "evolution_gate": evolution_gate,
            "governance_gate": governance_gate,
            "reason": "no_code_branch",
            "roster_gate": roster_gate,
        }
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True):
        return _hold_for_remediation(
            "auto_merge_disabled",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )

    merge_result = _auto_merge_low_risk_branch(
        run_id=run_id,
        task_id=para_task_id,
        branch=branch,
        steps=steps,
    )
    if merge_result.get("ok"):
        merge_requested = bool(merge_result.get("merge_requested"))
        deployment_receipt = (
            {"enabled": False, "reason": "merge_not_completed"}
            if merge_requested
            else _run_deploy_receipts_after_merge(
                run_id=run_id,
                merge_result=merge_result,
            )
        )
        return {
            "action": (
                "auto_merge_requested_low_risk" if merge_requested else "auto_merged_low_risk"
            ),
            "active_gates": active_gates,
            "deployment_receipt": deployment_receipt,
            "evolution_gate": evolution_gate,
            "gate": gate,
            "governance_gate": governance_gate,
            "merge_result": merge_result,
            "reason": ("low_risk_merge_requested" if merge_requested else "low_risk_policy_passed"),
            "roster_gate": roster_gate,
        }
    return _hold_for_remediation(
        merge_result.get("reason") or "auto_merge_not_allowed",
        gate=gate,
        active_gates=active_gates,
        evolution_gate=evolution_gate,
        governance_gate=governance_gate,
        merge_result=merge_result,
        roster_gate=roster_gate,
    )


LOOP_EVICT_MAX_ITEMS = 100
LOOP_EVICT_STUCK_AGE_SECONDS = 24 * 3600
LOOP_EVICT_STUCK_RETRY_THRESHOLD = 3
LOOP_EVICT_AGE_OUT_SECONDS = 7 * 24 * 3600


def _evict_loop_memory_items(
    memory: Dict[str, Any],
    *,
    actor: str = "auto",
    note: str = "",
    admin_user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Evict stale open_items so the loop can resume fresh runs.

    Rules (checked in order, first match wins):
      - any item with created_at > 7d  → evict (reason=aged_out_7d)
      - failed_steps item with created_at > 24h AND retry_count >= 3
        → evict (reason=stuck_24h_retry_3)
    Evicted items are appended to memory["evicted_items"] (capped at the last
    LOOP_EVICT_MAX_ITEMS entries) and a ``loop_evicted`` governance audit
    record is written so the action is visible in the governance UI.
    Returns a summary dict; never raises.
    """

    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    evicted_items = memory.get("evicted_items")
    if not isinstance(evicted_items, list):
        evicted_items = []

    now = _utc_now()
    kept: List[Dict[str, Any]] = []
    newly_evicted: List[Dict[str, Any]] = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        created_dt = _parse_iso(item.get("created_at"))
        age_seconds = (now - created_dt).total_seconds() if created_dt else 0.0
        retry_count = int(item.get("retry_count") or 0)
        kind = str(item.get("kind") or "")

        evict_reason = ""
        if age_seconds >= LOOP_EVICT_AGE_OUT_SECONDS:
            evict_reason = "aged_out_7d"
        elif (
            kind == "failed_steps"
            and age_seconds >= LOOP_EVICT_STUCK_AGE_SECONDS
            and retry_count >= LOOP_EVICT_STUCK_RETRY_THRESHOLD
        ):
            evict_reason = "stuck_24h_retry_3"

        if evict_reason:
            evicted_entry: Dict[str, Any] = {
                "actor": actor,
                "evicted_at": _iso(now),
                "evict_reason": evict_reason,
                "original_item": item,
            }
            if note:
                evicted_entry["note"] = str(note)[:1000]
            if admin_user_id is not None:
                evicted_entry["admin_user_id"] = admin_user_id
            newly_evicted.append(evicted_entry)
        else:
            kept.append(item)

    memory["open_items"] = kept
    memory["evicted_items"] = (evicted_items + newly_evicted)[-LOOP_EVICT_MAX_ITEMS:]

    if not newly_evicted:
        return {
            "evicted_count": 0,
            "evicted_items": [],
            "reasons": {
                "aged_out_7d": 0,
                "stuck_24h_retry_3": 0,
            },
        }

    reasons = {
        "aged_out_7d": sum(1 for entry in newly_evicted if entry["evict_reason"] == "aged_out_7d"),
        "stuck_24h_retry_3": sum(
            1 for entry in newly_evicted if entry["evict_reason"] == "stuck_24h_retry_3"
        ),
    }
    summary_record = {
        "action": "loop_evicted",
        "actor": actor,
        "admin_user_id": admin_user_id,
        "created_at": _iso(now),
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "note": str(note or "")[:1000],
        "ok": True,
        "reasons": reasons,
        "source": "self_maintenance_loop_runner",
        "status": "evicted",
    }
    try:
        _append_governance_audit(summary_record)
    except Exception:
        logger.exception("failed to write loop_evicted governance audit")

    return {
        "evicted_count": len(newly_evicted),
        "evicted_items": newly_evicted,
        "reasons": reasons,
    }


def evict_loop_memory_items(
    *,
    actor: str = "manual",
    note: str = "",
    admin_user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Manually evict stale loop-memory open_items (veto channel).

    Exposed via POST /api/xcmax/admin/loop/memory/evict for human override when
    the loop is stuck resuming long-failed runs.
    """

    memory = _load_loop_memory()
    result = _evict_loop_memory_items(
        memory,
        actor=actor,
        note=note,
        admin_user_id=admin_user_id,
    )
    memory["updated_at"] = _iso(_utc_now())
    _write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }


def _update_loop_memory(final: Dict[str, Any], gate: Dict[str, Any]) -> None:
    memory = _load_loop_memory()
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        recent_runs = []
    open_items = memory.get("open_items")
    if not isinstance(open_items, list):
        open_items = []
    closed_items = memory.get("closed_items")
    if not isinstance(closed_items, list):
        closed_items = []
    memory["closed_items"] = closed_items

    decision = final.get("policy_decision") or {}
    steps = final.get("steps") if isinstance(final.get("steps"), list) else []
    failed_steps = [step.get("step") for step in steps if not step.get("ok")]
    if failed_steps:
        run_id = final.get("run_id")
        existing_idx = None
        # First try to match by current run_id (normal case for fresh runs)
        for idx, item in enumerate(open_items):
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and item.get("run_id") == run_id
            ):
                existing_idx = idx
                break
        # If not found, check for resumed run's original failed_run_id
        if existing_idx is None and isinstance(final.get("resume_candidate"), dict):
            failed_run_id = str(
                final.get("resume_candidate", {}).get("failed_run_id") or ""
            ).strip()
            if failed_run_id:
                for idx, item in enumerate(open_items):
                    if (
                        isinstance(item, dict)
                        and item.get("kind") == "failed_steps"
                        and item.get("run_id") == failed_run_id
                    ):
                        existing_idx = idx
                        break
        # If still not found and failing at code step (no branch/task yet), match existing open code failure
        if existing_idx is None and failed_steps == ["code"]:
            for idx, item in reversed(list(enumerate(open_items))):
                if (
                    isinstance(item, dict)
                    and item.get("kind") == "failed_steps"
                    and item.get("steps") == ["code"]
                    and not item.get("branch")
                    and not item.get("task_id")
                    and not item.get("para_task_id")
                ):
                    existing_idx = idx
                    break
        # If still not found and failing with same branch/para_task_id, match existing task failure
        if existing_idx is None:
            branch = str(final.get("branch") or "").strip()
            para_task_id = str(final.get("para_task_id") or "").strip()
            if branch or para_task_id:
                for idx, item in reversed(list(enumerate(open_items))):
                    if not (isinstance(item, dict) and item.get("kind") == "failed_steps"):
                        continue
                    item_branch = str(item.get("branch") or "").strip()
                    item_task_id = str(
                        item.get("para_task_id") or item.get("task_id") or ""
                    ).strip()
                    if (branch and item_branch == branch) or (
                        para_task_id and item_task_id == para_task_id
                    ):
                        existing_idx = idx
                        break
        if existing_idx is not None:
            existing = open_items[existing_idx]
            existing["retry_count"] = int(existing.get("retry_count") or 1) + 1
            existing["last_attempted_at"] = _iso(_utc_now())
            existing["steps"] = failed_steps
            existing["run_id"] = run_id
            # Update branch/task info if present in final record
            if final.get("branch"):
                existing["branch"] = final.get("branch")
            if final.get("para_task_id"):
                existing["para_task_id"] = final.get("para_task_id")
        else:
            new_item = {
                "created_at": _iso(_utc_now()),
                "kind": "failed_steps",
                "retry_count": 1,
                "run_id": run_id,
                "steps": failed_steps,
            }
            if final.get("branch"):
                new_item["branch"] = final.get("branch")
            if final.get("para_task_id"):
                new_item["para_task_id"] = final.get("para_task_id")
            open_items.append(new_item)
    if decision.get("action") == "hold_for_automated_remediation":
        remediation_item = {
            "branch": final.get("branch"),
            "active_gates": decision.get("active_gates"),
            "created_at": _iso(_utc_now()),
            "evolution_gate": decision.get("evolution_gate"),
            "kind": "automated_remediation",
            "governance_gate": decision.get("governance_gate"),
            "reason": decision.get("reason"),
            "roster_gate": decision.get("roster_gate"),
            "run_id": final.get("run_id"),
            "task_id": final.get("para_task_id"),
        }
        if decision.get("detail"):
            remediation_item["detail"] = decision.get("detail")
        structured_gate = decision.get("structured_gate")
        if isinstance(structured_gate, dict):
            remediation_item["structured_gate"] = structured_gate
        if decision.get("resume_from_clean_baseline"):
            remediation_item["resume_from_clean_baseline"] = True
        open_items.append(remediation_item)
    memory["open_items"] = open_items
    close_successful_code_resume(memory, final, _close_open_items_in_memory)
    resolution_record = _close_items_resolved_by_final(memory, final)
    knowledge_record = record_loop_evolution_knowledge(final, gate)
    # KB salvage: record_loop_evolution_knowledge only writes on
    # auto_merged_low_risk, so failed / await_human runs would otherwise lose
    # any KB files the Para employee already produced. Scan the workspace
    # regardless of policy_decision so later runs can reuse the knowledge.
    salvage_summary: Optional[Dict[str, Any]] = None
    try:
        # Para e2e-agent 工作区路径：DEVFLEET_WORKSPACE_ROOT/{para_task_id}
        para_task_id = final.get("para_task_id") or ""
        ws_root = os.environ.get(
            "DEVFLEET_WORKSPACE_ROOT",
            "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace",
        )
        para_workspace = Path(ws_root) / para_task_id if para_task_id else Path(ws_root)
        salvage_summary = salvage_kb_from_workspace(
            para_workspace=para_workspace, run_id=final.get("run_id")
        )
        if salvage_summary and (
            salvage_summary.get("salvaged_fixes") or salvage_summary.get("salvaged_patterns")
        ):
            logger.info(
                "kb salvage run_id=%s salvaged_fixes=%s salvaged_patterns=%s",
                final.get("run_id"),
                salvage_summary.get("salvaged_fixes"),
                salvage_summary.get("salvaged_patterns"),
            )
        _append_ledger(
            {
                "phase": "kb_salvage",
                "run_id": final.get("run_id"),
                "para_task_id": final.get("para_task_id"),
                "salvaged_fixes": (salvage_summary.get("salvaged_fixes") if salvage_summary else 0),
                "salvaged_patterns": (
                    salvage_summary.get("salvaged_patterns") if salvage_summary else 0
                ),
                "skipped": salvage_summary.get("skipped") if salvage_summary else 0,
                "workspace": (salvage_summary.get("workspace") if salvage_summary else None),
                "timestamp": _iso(_utc_now()),
            }
        )
    except Exception:
        logger.exception("kb salvage failed run_id=%s", final.get("run_id"))

    recent_runs.append(
        {
            "action": decision.get("action"),
            "active_gates": decision.get("active_gates"),
            "branch": final.get("branch"),
            "completed_at": final.get("completed_at"),
            "evolution_gate_pause": (
                decision.get("evolution_gate", {}).get("pause")
                if isinstance(decision.get("evolution_gate"), dict)
                else None
            ),
            "evolution_gate_reason": (
                decision.get("evolution_gate", {}).get("reason")
                if isinstance(decision.get("evolution_gate"), dict)
                else None
            ),
            "gate_reason": gate.get("reason"),
            "governance_gate_action": (
                decision.get("governance_gate", {}).get("action")
                if isinstance(decision.get("governance_gate"), dict)
                else None
            ),
            "governance_gate_reason": (
                decision.get("governance_gate", {}).get("reason")
                if isinstance(decision.get("governance_gate"), dict)
                else None
            ),
            "governance_gate_health": (
                decision.get("governance_gate", {}).get("summary", {}).get("health")
                if isinstance(decision.get("governance_gate"), dict)
                and isinstance(decision.get("governance_gate", {}).get("summary"), dict)
                else None
            ),
            "para_task_id": final.get("para_task_id"),
            "roster_gate_action": (
                decision.get("roster_gate", {}).get("action")
                if isinstance(decision.get("roster_gate"), dict)
                else None
            ),
            "roster_gate_reason": (
                decision.get("roster_gate", {}).get("reason")
                if isinstance(decision.get("roster_gate"), dict)
                else None
            ),
            "roster_gate_out_of_roster_ids": (
                decision.get("roster_gate", {}).get("out_of_roster_ids")
                if isinstance(decision.get("roster_gate"), dict)
                and isinstance(decision.get("roster_gate", {}).get("out_of_roster_ids"), list)
                else []
            ),
            "roster_gate_not_deployed_ids": (
                decision.get("roster_gate", {}).get("not_deployed_ids")
                if isinstance(decision.get("roster_gate"), dict)
                and isinstance(decision.get("roster_gate", {}).get("not_deployed_ids"), list)
                else []
            ),
            "run_id": final.get("run_id"),
            "status": final.get("status"),
            "structured_gate": (
                decision.get("structured_gate")
                if isinstance(decision.get("structured_gate"), dict)
                else None
            ),
            "kb_salvage": salvage_summary,
        }
    )

    # Auto-evict stale open_items before persistence so long-failed runs do
    # not get resumed every LOOP iteration (24h + retry_count>=3, or 7d old).
    try:
        evict_summary = _evict_loop_memory_items(memory, actor="auto")
    except Exception:
        evict_summary = {"evicted_count": 0, "error": "evict_failed"}
        logger.exception("loop memory auto-evict failed run_id=%s", final.get("run_id"))

    memory.update(
        {
            "evicted_items": memory.get("evicted_items", [])[-LOOP_EVICT_MAX_ITEMS:],
            "last_evict_summary": evict_summary,
            "last_gate": gate,
            "last_knowledge_record": knowledge_record,
            "last_policy_decision": decision,
            "last_resolution_record": resolution_record,
            "last_run": recent_runs[-1],
            "open_items": memory.get("open_items", [])[-50:],
            "closed_items": memory.get("closed_items", [])[-200:],
            "recent_runs": recent_runs[-20:],
            "run_count": int(memory.get("run_count") or 0) + 1,
            "updated_at": _iso(_utc_now()),
        }
    )
    _write_loop_memory(memory)


def _run_self_maintenance_loop_unlocked(
    *,
    triggered_by: str = "manual",
    force: bool = False,
    reason: Optional[str] = None,
    remediation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the real employee maintenance chain when gates allow it."""

    # This function is reached only after ``run_self_maintenance_loop`` has
    # acquired the cross-process OS lease.  Any prior open row is therefore an
    # interrupted process, not concurrent work.
    reconcile_stale_self_maintenance_runs(exclusive_lease_reacquired=True)
    run_id = str(uuid.uuid4())
    started_at = _utc_now()
    gate = should_run_self_maintenance_loop(force=force, triggered_by=triggered_by)
    ensure_clean_baseline()

    if not gate.get("should_run"):
        record = {
            "created_at": _iso(started_at),
            "force": force,
            "gate": gate,
            "phase": "skip",
            "reason": reason,
            "run_id": run_id,
            "status": f"skipped_{gate.get('reason')}",
            "triggered_by": triggered_by,
        }
        record.update(_remediation_lineage_fields(remediation_context))
        _append_ledger(record)
        return record

    user_id = _self_maintenance_actor_user_id()
    loop_memory = _load_loop_memory()
    merge_reconciliation = _reconcile_requested_merge_feedback(loop_memory)
    retort_scope_reconciliation = _reconcile_retort_scope_remediations(loop_memory)
    absorbed_merge_reconciliation = _reconcile_absorbed_para_merge_remediations(
        loop_memory,
        base_branch=os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main",
    )
    if (
        merge_reconciliation.get("changed")
        or retort_scope_reconciliation.get("changed")
        or absorbed_merge_reconciliation.get("changed")
    ):
        _write_loop_memory(loop_memory)
    resume_candidate = (
        _resume_candidate_from_remediation_context(
            loop_memory,
            remediation_context,
        )
        if remediation_context
        else _resume_review_qa_candidate(loop_memory)
    )
    if remediation_context and resume_candidate is None:
        record = _unavailable_remediation_context_record(
            created_at=_iso(started_at),
            force=force,
            gate=gate,
            remediation_context=remediation_context,
            run_id=run_id,
            triggered_by=triggered_by,
        )
        _append_ledger(record)
        return record
    start_record = {
        "created_at": _iso(started_at),
        "force": force,
        "gate": gate,
        "memory_path": str(loop_memory_path()),
        "phase": "start",
        "reason": reason,
        "run_id": run_id,
        "started_at": _iso(started_at),
        "status": "running",
        "triggered_by": triggered_by,
        "user_id": user_id,
        "runtime_provenance": gate.get("runtime_provenance"),
    }
    start_record.update(_remediation_lineage_fields(remediation_context))
    if any(merge_reconciliation.values()):
        start_record["merge_reconciliation"] = merge_reconciliation
    if retort_scope_reconciliation.get("changed"):
        start_record["retort_scope_reconciliation"] = retort_scope_reconciliation
    if absorbed_merge_reconciliation.get("changed"):
        start_record["absorbed_para_merge_reconciliation"] = absorbed_merge_reconciliation
    if resume_candidate:
        start_record["resume_candidate"] = resume_candidate
    _append_ledger(start_record)

    steps: List[Dict[str, Any]] = []
    plan = []
    steps_to_run = _resume_steps(resume_candidate)
    para_task_id, code_branch = _resume_dispatch_context(resume_candidate, steps_to_run)
    if "code" in steps_to_run:
        # Code remediation always starts a fresh Para task. Appending to a
        # completed task leaves its old base branch/completed_at in force, so a
        # new subtask can both lose the candidate diff and fail to report final
        # completion. Safety-score remediation keeps the candidate as the new
        # task's base branch; ordinary failed code starts from the configured base.
        code_extra: Dict[str, Any] = {
            "allow_medium_risk": True,
            # self-maintenance loop 干活范围是整个 XCMAX 仓库（FHD/XCAGI/kb/fixes、
            # 成都修茈科技有限公司/MODstore_deploy/modstore_server 等），与 vibe-coding-maintainer
            # 默认 scope_globs（限定 vibe-coding/）冲突；loop 是受信任系统调度，显式跳过 path_guard。
            "skip_path_guard": True,
        }
        if resume_candidate and resume_candidate.get("continue_existing_code_task"):
            code_extra["branch"] = code_branch
        plan.append(
            (
                "vibe-coding-maintainer",
                "code",
                _code_task_text(run_id, gate, loop_memory, resume_candidate),
                code_extra,
            )
        )
    if "review" in steps_to_run:
        plan.append(
            (
                "change-request-auditor",
                "review",
                "",
                {
                    "allow_medium_risk": True,
                    "report_only": True,
                    "skip_path_guard": True,
                    "wait_timeout_sec": _env_int(
                        "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                    ),
                },
            )
        )
    if "qa" in steps_to_run:
        plan.append(
            (
                "test-qa-runner",
                "qa",
                "",
                {
                    "allow_medium_risk": True,
                    "report_only": True,
                    "wait_timeout_sec": _env_int(
                        "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                    ),
                },
            )
        )

    try:
        for employee_id, step_name, task_text, extra in plan:
            if step_name == "review":
                task_text = _review_task_text(run_id, code_branch, loop_memory)
            elif step_name == "qa":
                task_text = _qa_task_text(run_id, code_branch, loop_memory)

            if para_task_id and step_name == "code":
                extra = {**extra, "para_task_id": para_task_id}
            elif para_task_id:
                extra = {
                    **extra,
                    "review_base_branch": os.environ.get("MODSTORE_PARA_BRANCH"),
                    "review_repo_url": os.environ.get("MODSTORE_PARA_REPO_URL"),
                    "review_target_branch": code_branch,
                    "review_target_para_task_id": para_task_id,
                }

            remediation_base_branch = (
                str(extra.get("branch") or "").strip() if step_name == "code" else ""
            )

            if step_name == "review":
                retort_gate = _evaluate_retort_clarification_before_review(
                    run_id=run_id,
                    branch=code_branch,
                    para_task_id=str(para_task_id or ""),
                    memory=loop_memory,
                )
                if retort_gate.get("blocked"):
                    scope_only = _retort_scope_only_clarification(retort_gate)
                    step_record = {
                        "employee_id": employee_id,
                        "error": str(retort_gate.get("reason") or "retort_clarification_pending"),
                        "ok": False,
                        "para": {},
                        "phase": "step",
                        "report_excerpt": "",
                        "run_id": run_id,
                        "status": ("completed_held_for_remediation" if scope_only else "failed"),
                        "step": step_name,
                        "timestamp": _iso(_utc_now()),
                        "retort_clarification": retort_gate,
                    }
                    steps.append(step_record)
                    _append_ledger(step_record)
                    final = {
                        "branch": code_branch,
                        "completed_at": _iso(_utc_now()),
                        "error": str(retort_gate.get("reason") or "retort_clarification_pending"),
                        "failed_step": step_name,
                        "para_task_id": para_task_id,
                        "phase": "complete",
                        "run_id": run_id,
                        "started_at": _iso(started_at),
                        "status": "failed",
                        "steps": steps,
                        "triggered_by": triggered_by,
                        "retort_clarification": retort_gate,
                    }
                    if resume_candidate:
                        final["resume_candidate"] = resume_candidate
                    if scope_only:
                        final["policy_decision"] = {
                            "action": "hold_for_automated_remediation",
                            "detail": (
                                "Retort requires a smaller clean-base patch before unattended review."
                            ),
                            "reason": RETORT_SCOPE_REASON,
                            "resume_from_clean_baseline": True,
                        }
                    else:
                        final["policy_decision"] = _decide_post_loop_policy(
                            branch=code_branch,
                            gate=gate,
                            para_task_id=para_task_id,
                            run_id=run_id,
                            status="failed",
                            steps=steps,
                        )
                    _append_ledger(final)
                    _update_loop_memory(final, gate)
                    return final

            (
                result,
                ok,
                failure_reason,
                para_meta,
                report_excerpt,
                code_fix_retry_rounds,
                marker_retry_rounds,
            ) = _run_step_with_inner_retries(
                employee_id=employee_id,
                step_name=step_name,
                task_text=task_text,
                extra=extra,
                user_id=user_id,
                run_id=run_id,
            )
            if para_meta.get("task_id") and para_task_id is None:
                para_task_id = str(para_meta["task_id"])
            if step_name == "code" and para_meta.get("branch"):
                code_branch = str(para_meta["branch"])

            branch_delivery_validation: Optional[Dict[str, Any]] = None
            if step_name == "code" and ok and remediation_base_branch:
                branch_delivery_validation = _validate_remediation_branch_delivery(
                    base_branch=remediation_base_branch,
                    delivered_branch=str(code_branch or ""),
                )
                if not branch_delivery_validation.get("ok"):
                    ok = False
                    failure_reason = str(branch_delivery_validation.get("reason") or "")

            step_record = {
                "employee_id": employee_id,
                "error": failure_reason,
                "ok": ok,
                "para": para_meta,
                "phase": "step",
                "report_excerpt": report_excerpt,
                "retry_attempts": result.get("self_maintenance_retry_attempts"),
                "code_fix_retry_rounds": code_fix_retry_rounds,
                "marker_retry_rounds": marker_retry_rounds,
                "run_id": run_id,
                "status": "success" if ok else "failed",
                "step": step_name,
                "timestamp": _iso(_utc_now()),
            }
            if branch_delivery_validation is not None:
                step_record["branch_delivery_validation"] = branch_delivery_validation
            steps.append(step_record)
            _append_ledger(step_record)

            if not ok:
                final = {
                    "branch": code_branch,
                    "completed_at": _iso(_utc_now()),
                    "error": failure_reason,
                    "failed_step": step_name,
                    "para_task_id": para_task_id,
                    "phase": "complete",
                    "run_id": run_id,
                    "started_at": _iso(started_at),
                    "status": "failed",
                    "steps": steps,
                    "triggered_by": triggered_by,
                }
                if resume_candidate:
                    final["resume_candidate"] = resume_candidate
                final["policy_decision"] = _decide_post_loop_policy(
                    branch=code_branch,
                    gate=gate,
                    para_task_id=para_task_id,
                    run_id=run_id,
                    status="failed",
                    steps=steps,
                )
                _append_ledger(final)
                _update_loop_memory(final, gate)
                return final

            # Early KB JSON schema validation: right after code step succeeds,
            # before review/qa. If the employee pushed KB JSON files with schema
            # errors (e.g., missing/wrong executable_template), reject the branch
            # immediately and retry the code step (or escalate to human after
            # KB_SCHEMA_RETRY_MAX attempts). This avoids wasting review/qa cycles
            # on schema-invalid branches and gives the employee fast feedback.
            if step_name == "code" and ok and code_branch:
                try:
                    early_kb = _early_kb_validation_for_branch(run_id=run_id, branch=code_branch)
                except Exception:
                    logger.exception(
                        "early KB validation crashed for branch=%s run_id=%s; skipping",
                        code_branch,
                        run_id,
                    )
                    early_kb = {"ok": True, "reason": "early_kb_validation_crashed"}
                if (
                    isinstance(early_kb, dict)
                    and not early_kb.get("ok")
                    and early_kb.get("reason") == "kb_json_schema_validation_failed"
                    and isinstance(early_kb.get("kb_validation"), dict)
                ):
                    logger.warning(
                        "early KB schema validation failed for branch=%s run_id=%s; rejecting and retrying code step",
                        code_branch,
                        run_id,
                    )
                    return _reject_and_retry_kb_schema_failure(
                        run_id=run_id,
                        branch=code_branch,
                        para_task_id=para_task_id,
                        kb_validation=early_kb["kb_validation"],
                        steps=steps,
                        gate=gate,
                        triggered_by=triggered_by,
                        started_at=started_at,
                    )

        policy_decision = _decide_post_loop_policy(
            branch=code_branch,
            gate=gate,
            para_task_id=para_task_id,
            run_id=run_id,
            status="completed",
            steps=steps,
        )
        final_status = "completed"
        if policy_decision.get("action") == "auto_merged_low_risk":
            final_status = "completed_merged"
        elif policy_decision.get("action") == "auto_merge_requested_low_risk":
            final_status = "completed_merge_requested"
        elif policy_decision.get("action") == "hold_for_automated_remediation":
            final_status = "completed_held_for_remediation"

        final = {
            "branch": code_branch,
            "completed_at": _iso(_utc_now()),
            "para_task_id": para_task_id,
            "phase": "complete",
            "policy_decision": policy_decision,
            "run_id": run_id,
            "started_at": _iso(started_at),
            "status": final_status,
            "steps": steps,
            "triggered_by": triggered_by,
        }
        if resume_candidate:
            final["resume_candidate"] = resume_candidate
        _append_ledger(final)
        _update_loop_memory(final, gate)
        return final
    except Exception as exc:
        logger.exception("self-maintenance loop failed")
        final = {
            "branch": code_branch,
            "completed_at": _iso(_utc_now()),
            "error": str(exc),
            "para_task_id": para_task_id,
            "phase": "complete",
            "run_id": run_id,
            "started_at": _iso(started_at),
            "status": "failed",
            "steps": steps,
            "triggered_by": triggered_by,
        }
        if resume_candidate:
            final["resume_candidate"] = resume_candidate
        final["policy_decision"] = _decide_post_loop_policy(
            branch=code_branch,
            gate=gate,
            para_task_id=para_task_id,
            run_id=run_id,
            status="failed",
            steps=steps,
        )
        _append_ledger(final)
        _update_loop_memory(final, gate)
        return final


@platform_llm_scoped
def run_self_maintenance_loop(
    *,
    triggered_by: str = "manual",
    force: bool = False,
    reason: Optional[str] = None,
    remediation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one maintenance transaction under an OS-backed exclusive lease."""

    with _exclusive_loop_lease() as acquired:
        if acquired:
            return _run_self_maintenance_loop_unlocked(
                triggered_by=triggered_by,
                force=force,
                reason=reason,
                remediation_context=remediation_context,
            )
        run_id = str(uuid.uuid4())
        record = {
            "created_at": _iso(_utc_now()),
            "force": force,
            "phase": "skip",
            "reason": reason,
            "run_id": run_id,
            "status": "skipped_active_lease",
            "triggered_by": triggered_by,
        }
        record.update(_remediation_lineage_fields(remediation_context))
        _append_ledger(record)
        return record


def cron_trigger_for_self_maintenance() -> CronTrigger:
    hour = _env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3)
    minute = _env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0)
    timezone_name = os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai")
    return CronTrigger(hour=hour, minute=minute, timezone=timezone_name)


def record_self_maintenance_heartbeat(
    *, triggered_by: str = "scheduler_heartbeat"
) -> Dict[str, Any]:
    """Append a side-effect-free liveness receipt for the outer loop.

    The full maintenance loop is intentionally daily and may be held by
    cooldown or governance.  A separate heartbeat proves the scheduler is
    still evaluating that gate without pretending code work was performed.
    """

    evaluation = should_run_self_maintenance_loop(
        force=False,
        triggered_by=triggered_by,
    )
    provenance = (
        evaluation.get("runtime_provenance")
        if isinstance(evaluation.get("runtime_provenance"), dict)
        else {}
    )
    metrics_gate = (
        evaluation.get("evolution_metrics_gate")
        if isinstance(evaluation.get("evolution_metrics_gate"), dict)
        else {}
    )
    record = {
        "created_at": _iso(_utc_now()),
        "phase": "heartbeat",
        "run_id": f"heartbeat-{uuid.uuid4().hex[:16]}",
        "status": ("heartbeat_ready" if evaluation.get("should_run") is True else "heartbeat_idle"),
        "triggered_by": str(triggered_by or "scheduler_heartbeat")[:80],
        "gate": {
            "should_run": evaluation.get("should_run") is True,
            "reason": str(evaluation.get("reason") or "")[:160],
            "runtime_provenance_ok": provenance.get("ok") is True,
            "evolution_metrics_paused": metrics_gate.get("pause") is True,
        },
        "read_only": True,
        "side_effects": [],
    }
    _append_ledger(record)
    return record


def get_self_maintenance_runtime_status(limit: int = 80) -> Dict[str, Any]:
    """Return the runtime-consumed self-maintenance loop state.

    This is the read side for the loop. It intentionally consumes the same
    ledger, memory and gate functions used by the scheduler instead of relying
    on a marker file committed by an employee branch.
    """

    bounded_limit = max(1, min(int(limit or 80), 300))
    evidence_scan_limit = max(
        bounded_limit,
        max(
            100,
            min(
                _env_int(
                    "MODSTORE_SELF_MAINTENANCE_EVIDENCE_SCAN_LIMIT",
                    DEFAULT_EVIDENCE_SCAN_LIMIT,
                ),
                20_000,
            ),
        ),
    )
    ledger_rows = _read_ledger(limit=evidence_scan_limit)
    rows = ledger_rows[-bounded_limit:]
    evidence_window_days = max(
        1,
        min(
            _env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_WINDOW_DAYS",
                DEFAULT_EVIDENCE_WINDOW_DAYS,
            ),
            90,
        ),
    )
    evidence_run_limit = max(
        1,
        min(
            _env_int(
                "MODSTORE_SELF_MAINTENANCE_EVIDENCE_RUN_LIMIT",
                DEFAULT_EVIDENCE_RUN_LIMIT,
            ),
            64,
        ),
    )
    milestone_source_rows = _select_recent_milestone_rows(
        ledger_rows,
        window_days=evidence_window_days,
        run_limit=evidence_run_limit,
        row_limit=DEFAULT_EVIDENCE_ROW_LIMIT,
    )
    memory = _load_loop_memory()
    started: Dict[str, Dict[str, Any]] = {}
    terminal: Dict[str, Dict[str, Any]] = {}
    steps_by_run: Dict[str, List[Dict[str, Any]]] = {}

    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[run_id] = row
        elif phase in {"complete", "skip"}:
            terminal[run_id] = row
        elif phase == "step":
            steps_by_run.setdefault(run_id, []).append(row)

    open_run_ids = [run_id for run_id in started if run_id not in terminal]
    latest_complete = None
    latest_skip = None
    for row in reversed(rows):
        phase = str(row.get("phase") or "")
        if latest_complete is None and phase == "complete":
            latest_complete = row
        if latest_skip is None and phase == "skip":
            latest_skip = row
        if latest_complete is not None and latest_skip is not None:
            break

    try:
        gate = should_run_self_maintenance_loop(force=False)
    except Exception as exc:
        logger.exception("failed to evaluate self-maintenance runtime gate")
        gate = {"should_run": False, "reason": "gate_error", "error": str(exc)}

    trigger = cron_trigger_for_self_maintenance()
    open_items = memory.get("open_items") if isinstance(memory.get("open_items"), list) else []
    recent_runs = memory.get("recent_runs") if isinstance(memory.get("recent_runs"), list) else []

    try:
        from modstore_server.duty_roster import all_planned_employee_ids

        planned_employee_ids = set(all_planned_employee_ids())
    except Exception:
        planned_employee_ids = set()

    def _participant_id(value: Any) -> str:
        text = str(value or "").strip()
        if not text or "-" not in text:
            return ""
        if planned_employee_ids and text not in planned_employee_ids:
            return ""
        return text

    def _participant_role(employee_id: str, row: Dict[str, Any]) -> str:
        explicit = str(row.get("role") or row.get("loop_role") or "").strip().lower()
        if explicit:
            return explicit
        step = str(row.get("step") or row.get("stage") or "").strip().lower()
        if step in {"scout", "detect", "detect_signal", "signal"}:
            return "scout"
        if step in {"write", "writer", "fix", "repair", "implement"}:
            return "fix"
        if step in {"review", "reviewer"}:
            return "review"
        if step in {"qa", "verify", "validator", "test"}:
            return "qa"
        by_employee = {
            "workflow-automator": "scout",
            "intake-dispatcher": "scout",
            "task-router-officer": "scout",
            "vibe-coding-maintainer": "fix",
            "code-validator": "review",
            "sandbox-tester": "qa",
            "test-qa-runner": "qa",
            "quality-validator": "qa",
            "self-checker": "verify",
            "host-checker": "ops",
        }
        return by_employee.get(employee_id, "worker")

    def _participant_role_label(role: str) -> str:
        return {
            "scout": "侦察",
            "fix": "修复",
            "review": "评审",
            "qa": "QA",
            "verify": "验证",
            "ops": "运维",
            "worker": "员工",
        }.get(role, role or "员工")

    def _participant_stage(row: Dict[str, Any]) -> str:
        for key in ("step", "stage", "role", "phase", "status"):
            text = str(row.get(key) or "").strip()
            if text:
                return text
        return "loop"

    def _participant_stage_label(stage: str) -> str:
        return {
            "start": "开始",
            "step": "步骤",
            "write": "写代码",
            "writer": "写代码",
            "fix": "修复",
            "review": "评审",
            "qa": "QA",
            "complete": "完成",
            "skip": "跳过",
            "failed": "失败",
            "success": "成功",
        }.get(stage, stage)

    participants_by_id: Dict[str, Dict[str, Any]] = {}

    def _add_participant(employee_id: str, row: Dict[str, Any], source: str) -> None:
        emp_id = _participant_id(employee_id)
        if not emp_id:
            return
        cur = participants_by_id.setdefault(
            emp_id,
            {
                "employee_id": emp_id,
                "role": _participant_role(emp_id, row),
                "role_label": _participant_role_label(_participant_role(emp_id, row)),
                "stages": [],
                "stage_labels": [],
                "sources": [],
                "latest_at": None,
                "run_ids": [],
            },
        )
        stage = _participant_stage(row)
        if stage not in cur["stages"]:
            cur["stages"].append(stage)
        stage_label = _participant_stage_label(stage)
        if stage_label not in cur["stage_labels"]:
            cur["stage_labels"].append(stage_label)
        if source not in cur["sources"]:
            cur["sources"].append(source)
        run_id = str(row.get("run_id") or "").strip()
        if run_id and run_id not in cur["run_ids"]:
            cur["run_ids"].append(run_id)
        observed_at = _ledger_row_timestamp(row)
        at = observed_at.isoformat() if observed_at is not None else ""
        if at and (not cur["latest_at"] or at > str(cur["latest_at"])):
            cur["latest_at"] = at

    def _collect_participants(value: Any, source: str) -> None:
        if isinstance(value, dict):
            for key in (
                "employee_id",
                "employeeId",
                "emp_id",
                "empId",
                "actor",
                "assignee",
                "worker_id",
                "role_employee_id",
            ):
                if key in value:
                    _add_participant(str(value.get(key) or ""), value, source)
            for key in (
                "steps",
                "nodes",
                "result",
                "employee_results",
                "reports",
                "items",
            ):
                if key in value:
                    _collect_participants(value.get(key), source)
        elif isinstance(value, list):
            for item in value:
                _collect_participants(item, source)

    _collect_participants(rows, "ledger")
    _collect_participants(steps_by_run, "open_run_steps")
    _collect_participants(memory.get("last_run"), "memory.last_run")
    _collect_participants(recent_runs, "memory.recent_runs")

    def _timeline_label(row: Dict[str, Any]) -> str:
        phase = str(row.get("phase") or "").strip()
        step = str(row.get("step") or "").strip()
        if phase == "start":
            return "开始"
        if step:
            return _participant_stage_label(step)
        if phase == "complete":
            action = str(row.get("action") or "").strip()
            if action == "auto_merged_low_risk":
                return "自动合并"
            return "完成"
        if phase == "skip":
            return "跳过"
        return phase or "事件"

    def _timeline_item(row: Dict[str, Any]) -> Dict[str, Any]:
        employee_id = _participant_id(
            row.get("employee_id")
            or row.get("employeeId")
            or row.get("emp_id")
            or row.get("actor")
            or row.get("assignee")
        )
        role = _participant_role(employee_id, row) if employee_id else ""
        qa = row.get("qa") if isinstance(row.get("qa"), dict) else None
        review = row.get("review") if isinstance(row.get("review"), dict) else None
        if qa is None and str(row.get("step") or "").strip() == "qa":
            qa = _structured_report_from_step(row, STRUCTURED_QA_MARKER)
        if review is None and str(row.get("step") or "").strip() == "review":
            review = _structured_report_from_step(row, STRUCTURED_REVIEW_MARKER)
        return {
            "run_id": str(row.get("run_id") or "").strip(),
            "phase": str(row.get("phase") or "").strip(),
            "step": str(row.get("step") or "").strip(),
            "label": _timeline_label(row),
            "employee_id": employee_id,
            "role": role,
            "role_label": _participant_role_label(role) if role else "",
            "status": str(
                row.get("status") or row.get("action") or row.get("reason") or ""
            ).strip(),
            "created_at": (
                observed_at.isoformat()
                if (observed_at := _ledger_row_timestamp(row)) is not None
                else ""
            ),
            "para_task_id": str(row.get("para_task_id") or "").strip(),
            "branch": str(row.get("branch") or row.get("target_branch") or "").strip(),
            "qa_verdict": str(qa.get("verdict") or "").strip() if qa else "",
            "qa_blocking_findings": qa.get("blocking_findings") if qa else [],
            "qa_tested_commands": qa.get("tested_commands") if qa else [],
            "qa_target_branch_available": (qa.get("target_branch_available") if qa else None),
            "qa_risk_class": str(qa.get("risk_class") or "").strip() if qa else "",
            "review_verdict": (str(review.get("verdict") or "").strip() if review else ""),
            "review_max_severity": (
                str(review.get("max_severity") or "").strip() if review else ""
            ),
            "review_findings": review.get("findings") if review else [],
            "review_blocking_findings": (review.get("blocking_findings") if review else []),
            "review_dimensions": review.get("dimensions") if review else {},
            "reason": str(row.get("reason") or "").strip(),
            "triggered_by": str(row.get("triggered_by") or "").strip(),
            "force": row.get("force") if isinstance(row.get("force"), bool) else None,
        }

    def _milestone_item(row: Dict[str, Any]) -> Dict[str, Any]:
        item = _timeline_item(row)
        for key in (
            "action",
            "catalog_readback_verified",
            "deployment_state",
            "dry_run",
            "environment",
            "event",
            "event_type",
            "final_status",
            "force",
            "identity_verified",
            "installability_verified",
            "market_catalog_item_id",
            "market_listing_verified",
            "merge_sha",
            "ok",
            "package_id",
            "package_sha256",
            "runtime_contract_verified",
            "source_commit_sha",
            "stored_filename",
            "strategic_council_receipt_id",
            "strategic_council_verified",
            "triggered_by",
            "version",
            "workflow_run_id",
        ):
            if key in row:
                item[key] = row.get(key)
        return item

    milestone_rows = [_milestone_item(row) for row in milestone_source_rows]

    timelines_by_run: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "").strip()
        if not run_id:
            continue
        timelines_by_run.setdefault(run_id, []).append(_timeline_item(row))
    run_timelines = [
        {
            "run_id": run_id,
            "open": run_id in open_run_ids,
            "items": items,
        }
        for run_id, items in timelines_by_run.items()
    ][-12:]

    def _department_employee_ids(dept: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        direct = dept.get("ids")
        if isinstance(direct, list):
            ids.extend(str(item).strip() for item in direct if str(item).strip())
        subzones = dept.get("subzones")
        if isinstance(subzones, dict):
            for subzone in subzones.values():
                if not isinstance(subzone, dict):
                    continue
                sub_ids = subzone.get("ids")
                if isinstance(sub_ids, list):
                    ids.extend(str(item).strip() for item in sub_ids if str(item).strip())
        return list(dict.fromkeys(ids))

    def _department_lookup() -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for dept_key, dept in SIX_LINE_DEPARTMENTS.items():
            if not isinstance(dept, dict):
                continue
            dept_label = str(dept.get("label") or dept_key)
            for emp_id in _department_employee_ids(dept):
                out.setdefault(
                    emp_id,
                    {
                        "department_key": dept_key,
                        "department_label": dept_label,
                    },
                )
        return out

    def _roster_alignment_summary() -> Dict[str, Any]:
        try:
            planned_ids = set(all_planned_employee_ids())
        except Exception as exc:
            logger.exception("failed to load duty roster ids for self-maintenance status")
            planned_ids = set()
            load_error = str(exc)[:300]
        else:
            load_error = ""
        try:
            deployed_ids = set(duty_employee_records().keys())
        except Exception as exc:
            logger.exception("failed to load duty employee registry for self-maintenance status")
            deployed_ids = set()
            deployed_error = str(exc)[:300]
        else:
            deployed_error = ""
        participant_ids = sorted(participants_by_id.keys())
        in_roster_ids = [emp_id for emp_id in participant_ids if emp_id in planned_ids]
        out_of_roster_ids = [emp_id for emp_id in participant_ids if emp_id not in planned_ids]
        in_deployed_ids = [emp_id for emp_id in in_roster_ids if emp_id in deployed_ids]
        not_deployed_ids = [emp_id for emp_id in in_roster_ids if emp_id not in deployed_ids]
        in_roster_set = set(in_roster_ids)
        coverage: List[Dict[str, Any]] = []
        covered_ids: set[str] = set()
        for dept_key, dept in SIX_LINE_DEPARTMENTS.items():
            if not isinstance(dept, dict):
                continue
            dept_ids = [
                emp_id for emp_id in _department_employee_ids(dept) if emp_id in planned_ids
            ]
            hits = [emp_id for emp_id in dept_ids if emp_id in in_roster_set]
            if not hits:
                continue
            covered_ids.update(hits)
            coverage.append(
                {
                    "key": dept_key,
                    "label": str(dept.get("label") or dept_key),
                    "count": len(hits),
                    "total": len(dept_ids),
                    "ids": hits,
                }
            )
        ungrouped_ids = [emp_id for emp_id in in_roster_ids if emp_id not in covered_ids]
        if ungrouped_ids:
            coverage.append(
                {
                    "key": "ungrouped",
                    "label": "未归组",
                    "count": len(ungrouped_ids),
                    "total": len(ungrouped_ids),
                    "ids": ungrouped_ids,
                }
            )
        status = "clean"
        if load_error:
            status = "unknown"
        elif out_of_roster_ids:
            status = "mixed"
        elif not_deployed_ids:
            status = "not_deployed"
        elif not in_roster_ids:
            status = "empty"
        gate_action = "allow"
        gate_reason = "all_participants_are_in_duty_roster"
        gate_blocking = False
        if load_error:
            gate_action = "unknown"
            gate_reason = "duty_roster_load_error"
        elif deployed_error:
            gate_action = "unknown"
            gate_reason = "duty_employee_registry_load_error"
        elif out_of_roster_ids:
            gate_action = "isolate"
            gate_reason = "out_of_roster_participants_detected"
            gate_blocking = True
        elif not_deployed_ids:
            gate_action = "hold"
            gate_reason = "in_roster_but_not_registered_duty_employee"
            gate_blocking = True
        elif not participant_ids:
            gate_action = "wait"
            gate_reason = "no_loop_participants_detected"
        remediation = {
            "action": "none",
            "title": "无需修复",
            "detail": "参与员工已满足编制与上岗登记要求。",
            "target_employee_ids": [],
        }
        if gate_action == "hold":
            remediation = {
                "action": "register_duty_employees",
                "title": "补登记上岗员工",
                "detail": "这些 employee_id 在编制基线内，但未出现在 duty_employee_registry.json；先完成上岗登记后再允许自维护自动放行。",
                "target_employee_ids": not_deployed_ids[:80],
                "registry": "duty_employee_registry.json",
                "suggested_entrypoint": "yuangon_onboard_admin_api",
            }
        elif gate_action == "isolate":
            remediation = {
                "action": "isolate_out_of_roster_participants",
                "title": "隔离非编制参与者",
                "detail": "这些 employee_id 不属于管理端编制基线，不能作为上岗员工进入自维护 loop 自动放行。",
                "target_employee_ids": out_of_roster_ids[:80],
                "policy": "store/catalog employees must stay outside duty loop auto-merge",
            }
        elif gate_action == "wait":
            remediation = {
                "action": "wait_for_participant_evidence",
                "title": "等待参与员工证据",
                "detail": "runtime 尚未暴露 employee_id/actor/assignee；需要 ledger 或 run timeline 回写参与员工。",
                "target_employee_ids": [],
            }
        elif gate_action == "unknown":
            remediation = {
                "action": "repair_roster_data_source",
                "title": "修复编制/上岗数据源",
                "detail": gate_reason,
                "target_employee_ids": [],
            }
        return {
            "status": status,
            "planned_count": len(planned_ids),
            "participant_count": len(participant_ids),
            "in_roster_count": len(in_roster_ids),
            "out_of_roster_count": len(out_of_roster_ids),
            "deployed_count": len(deployed_ids),
            "in_deployed_count": len(in_deployed_ids),
            "not_deployed_count": len(not_deployed_ids),
            "in_roster_ids": in_roster_ids[:80],
            "out_of_roster_ids": out_of_roster_ids[:80],
            "in_deployed_ids": in_deployed_ids[:80],
            "not_deployed_ids": not_deployed_ids[:80],
            "department_coverage": coverage,
            "source": "duty_roster.py:SIX_LINE_DEPARTMENTS",
            "error": load_error or deployed_error,
            "remediation": remediation,
            "gate": {
                "ok": not gate_blocking and not load_error and not deployed_error,
                "blocking": gate_blocking,
                "action": gate_action,
                "reason": gate_reason,
                "policy": "only_registered_duty_roster_participants_can_be_visualized_as_on_duty",
                "out_of_roster_action": "isolate_from_on_duty_views",
                "not_deployed_action": "hold_for_duty_employee_registration",
            },
        }

    roster_alignment = _roster_alignment_summary()
    try:
        planned_ids_for_participants = set(all_planned_employee_ids())
    except Exception:
        planned_ids_for_participants = set()
    try:
        deployed_ids_for_participants = set(duty_employee_records().keys())
    except Exception:
        deployed_ids_for_participants = set()
    departments_by_employee = _department_lookup()
    for emp_id, participant in participants_by_id.items():
        in_roster = emp_id in planned_ids_for_participants
        deployed = emp_id in deployed_ids_for_participants
        dept = departments_by_employee.get(emp_id, {})
        participant["roster_status"] = "in_roster" if in_roster else "out_of_roster"
        participant["roster_label"] = "编制内" if in_roster else "非编制"
        participant["duty_registered"] = deployed
        participant["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
        participant["department_key"] = dept.get("department_key", "")
        participant["department_label"] = dept.get("department_label", "")
    for timeline in run_timelines:
        items = timeline.get("items") if isinstance(timeline, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            emp_id = str(item.get("employee_id") or "").strip()
            if not emp_id:
                continue
            in_roster = emp_id in planned_ids_for_participants
            deployed = emp_id in deployed_ids_for_participants
            dept = departments_by_employee.get(emp_id, {})
            item["roster_status"] = "in_roster" if in_roster else "out_of_roster"
            item["roster_label"] = "编制内" if in_roster else "非编制"
            item["duty_registered"] = deployed
            item["duty_registered_label"] = "已上岗" if deployed else "未登记上岗"
            item["department_key"] = dept.get("department_key", "")
            item["department_label"] = dept.get("department_label", "")

    def _score_summary(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "score": value.get("score"),
            "max_allowed": value.get("max_allowed"),
            "min_allowed": value.get("min_allowed"),
            "reason": value.get("reason"),
            "source": value.get("source"),
            "available": value.get("available"),
            "passed": value.get("passed"),
        }

    def _merge_decision_summary(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        risk_v1 = _score_summary(value.get("risk_score"))
        safety_v2 = _score_summary(value.get("safety_score_v2"))
        safety_v3 = _score_summary(value.get("safety_score_v3"))
        qa = value.get("qa") if isinstance(value.get("qa"), dict) else {}
        review = value.get("review") if isinstance(value.get("review"), dict) else {}
        final = value.get("final") if isinstance(value.get("final"), dict) else {}
        roster_gate = value.get("roster_gate") if isinstance(value.get("roster_gate"), dict) else {}
        governance_gate = (
            value.get("governance_gate") if isinstance(value.get("governance_gate"), dict) else {}
        )
        active_gates = (
            value.get("active_gates") if isinstance(value.get("active_gates"), dict) else {}
        )
        evolution_gate = (
            value.get("evolution_gate") if isinstance(value.get("evolution_gate"), dict) else {}
        )
        return {
            "action": str(value.get("action") or "").strip(),
            "reason": str(value.get("reason") or "").strip(),
            "ok": value.get("ok"),
            "active_gates": active_gates,
            "evolution_gate": evolution_gate,
            "risk_score_v1": risk_v1,
            "safety_score_v2": safety_v2,
            "safety_score_v3": safety_v3,
            "roster_gate": roster_gate,
            "governance_gate": governance_gate,
            "qa_verdict": str(qa.get("verdict") or "").strip(),
            "review_max_severity": str(review.get("max_severity") or "").strip(),
            "branch": str(
                value.get("branch")
                or value.get("target_branch")
                or final.get("branch")
                or final.get("target_branch")
                or ""
            ).strip(),
            "para_task_id": str(
                value.get("para_task_id") or final.get("para_task_id") or ""
            ).strip(),
        }

    merge_decision = _merge_decision_summary(memory.get("last_policy_decision"))
    try:
        kb_context = build_self_evolution_context(
            run_id="runtime_status",
            evaluation=gate if isinstance(gate, dict) else {},
            memory=memory if isinstance(memory, dict) else {},
        )
        kb_search = (
            kb_context.get("kb_search") if isinstance(kb_context.get("kb_search"), dict) else {}
        )
        fix_hits = (
            kb_context.get("fix_knowledge_hits")
            if isinstance(kb_context.get("fix_knowledge_hits"), list)
            else []
        )
        pattern_hits = (
            kb_context.get("pattern_hits")
            if isinstance(kb_context.get("pattern_hits"), list)
            else []
        )
        inventory = (
            kb_context.get("inventory") if isinstance(kb_context.get("inventory"), dict) else {}
        )
        kb_summary = {
            "fix_count": int(inventory.get("fix_count") or 0),
            "pattern_count": int(inventory.get("pattern_count") or 0),
            "total": int(inventory.get("total") or 0),
            "invalid_count": int(inventory.get("invalid_count") or 0),
            "kb_root": kb_context.get("kb_root"),
            "engine": kb_search.get("engine"),
            "fix_hit_count": kb_search.get("fix_hit_count", len(fix_hits)),
            "pattern_hit_count": kb_search.get("pattern_hit_count", len(pattern_hits)),
            "redisvl_status": kb_search.get("redisvl_status"),
            "top_fix_hits": [
                {
                    "symptom": str(
                        item.get("symptom") or item.get("summary") or item.get("id") or ""
                    )[:180],
                    "root_cause": str(item.get("root_cause") or "")[:180],
                    "fix_diff": str(item.get("fix_diff") or "")[:2000],
                    "executable_template": (
                        item.get("executable_template")
                        if isinstance(item.get("executable_template"), dict)
                        else {}
                    ),
                    "required_tests": (
                        item.get("executable_template", {}).get("required_tests")
                        if isinstance(item.get("executable_template"), dict)
                        and isinstance(
                            item.get("executable_template", {}).get("required_tests"),
                            list,
                        )
                        else []
                    ),
                    "rollback_plan": (
                        str(item.get("executable_template", {}).get("rollback_plan") or "")[:1000]
                        if isinstance(item.get("executable_template"), dict)
                        else ""
                    ),
                    "path": item.get("_path"),
                }
                for item in fix_hits[:3]
                if isinstance(item, dict)
            ],
            "top_pattern_hits": [
                {
                    "pattern": str(
                        item.get("pattern") or item.get("summary") or item.get("id") or ""
                    )[:180],
                    "summary": str(item.get("summary") or "")[:180],
                    "applicability": str(
                        item.get("applicability") or item.get("applicability_check") or ""
                    )[:1000],
                    "patch_strategy": str(item.get("patch_strategy") or "")[:1000],
                    "path": item.get("_path"),
                }
                for item in pattern_hits[:3]
                if isinstance(item, dict)
            ],
        }
    except Exception as exc:
        logger.exception("failed to build self-evolution KB runtime summary")
        kb_summary = {
            "error": str(exc)[:500],
            "fix_count": 0,
            "fix_hit_count": 0,
            "invalid_count": 0,
            "pattern_count": 0,
            "pattern_hit_count": 0,
            "redisvl_status": {"ready": False, "error": str(exc)[:300]},
            "total": 0,
        }
    metrics_gate = {}
    try:
        metrics_gate = evolution_metrics_gate()
    except Exception as exc:
        logger.exception("failed to build evolution metrics summary")
        metrics_gate = {
            "pause": False,
            "reason": "metrics_gate_error",
            "error": str(exc)[:500],
            "windows": [],
            "history_count": 0,
        }
    metric_windows = (
        metrics_gate.get("windows") if isinstance(metrics_gate.get("windows"), list) else []
    )
    evolution_metrics_summary = {
        "pause": bool(metrics_gate.get("pause")),
        "reason": metrics_gate.get("reason"),
        "history_count": metrics_gate.get("history_count"),
        "raw_history_count": metrics_gate.get("raw_history_count"),
        "verified_history_count": metrics_gate.get("verified_history_count"),
        "metrics_path": metrics_gate.get("metrics_path"),
        "windows": metric_windows[-2:],
    }

    governance_audit = _read_governance_audit(10)
    governance_audit_summary = _governance_audit_summary(governance_audit)
    governance_gate_current = {
        "ok": governance_audit_summary.get("health") != "bad",
        "blocking": governance_audit_summary.get("health") == "bad",
        "action": (
            "hold_for_governance_review"
            if governance_audit_summary.get("health") == "bad"
            else "allow"
        ),
        "reason": (
            "governance_audit_consecutive_failures"
            if governance_audit_summary.get("health") == "bad"
            else "governance_audit_healthy"
        ),
        "summary": governance_audit_summary,
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }
    roster_gate_current = (
        roster_alignment.get("gate") if isinstance(roster_alignment.get("gate"), dict) else {}
    )
    active_gate_items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if gate.get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": gate.get("reason") or gate.get("trigger_reason") or "",
            "detail": f"missing={gate.get('missing_count', 0)} threshold={gate.get('threshold', '')}",
        },
        {
            "key": "roster",
            "label": "Roster Gate",
            "status": roster_gate_current.get("action") or "unknown",
            "ok": roster_gate_current.get("ok") is not False,
            "blocking": bool(roster_gate_current.get("blocking")),
            "reason": roster_gate_current.get("reason") or "",
            "detail": roster_gate_current.get("policy") or "",
        },
        {
            "key": "governance",
            "label": "Governance Gate",
            "status": governance_gate_current.get("action"),
            "ok": governance_gate_current.get("ok"),
            "blocking": governance_gate_current.get("blocking"),
            "reason": governance_gate_current.get("reason"),
            "detail": governance_gate_current.get("policy"),
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if evolution_metrics_summary.get("pause") else "allow",
            "ok": not bool(evolution_metrics_summary.get("pause")),
            "blocking": bool(evolution_metrics_summary.get("pause")),
            "reason": evolution_metrics_summary.get("reason") or "",
            "detail": f"history={evolution_metrics_summary.get('history_count', 0)}",
        },
    ]
    active_blocking_items = [item for item in active_gate_items if item.get("blocking")]
    active_gates = {
        "ok": not active_blocking_items,
        "blocking_count": len(active_blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in active_blocking_items],
        "items": active_gate_items,
    }

    def _ui_bridge_summary() -> Dict[str, Any]:
        gate_info = (
            roster_alignment.get("gate") if isinstance(roster_alignment.get("gate"), dict) else {}
        )
        remediation_info = (
            roster_alignment.get("remediation")
            if isinstance(roster_alignment.get("remediation"), dict)
            else {}
        )
        gate_action = str(gate_info.get("action") or "").strip()
        gate_reason = str(gate_info.get("reason") or "").strip()
        target_ids = [
            str(emp_id).strip()
            for emp_id in (remediation_info.get("target_employee_ids") or [])
            if str(emp_id).strip()
        ][:80]
        participant_count = len(participants_by_id)
        open_count = len(open_run_ids)
        governance_health = str(governance_audit_summary.get("health") or "").strip()
        governance_consecutive = int(governance_audit_summary.get("consecutive_failures") or 0)

        state = "ready"
        tone = "ok"
        title = "编制与 Loop 已对齐"
        detail = "参与员工满足编制与上岗登记要求，员工空间可作为执行现场展示。"
        primary_surface = "employee_space"
        primary_view = "hub"
        primary_action = "observe_loop_workbench"
        next_actions = ["open_employee_space", "inspect_loop_timeline"]

        if gate_action == "hold":
            state = "requires_duty_registration"
            tone = "bad"
            title = "编制员工未登记上岗"
            detail = (
                "Loop 参与者命中编制基线但未完成 duty registry 上岗登记，必须先在编制图谱补登记。"
            )
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "register_duty_employees"
            next_actions = [
                "register_duty_employees",
                "refresh_self_maintenance_status",
            ]
        elif gate_action == "isolate":
            state = "requires_roster_isolation"
            tone = "bad"
            title = "Loop 混入非编制员工"
            detail = "检测到非编制 employee_id，必须在编制图谱隔离，不能进入上岗员工执行面。"
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "isolate_out_of_roster_participants"
            next_actions = ["inspect_out_of_roster_ids", "isolate_from_on_duty_views"]
        elif gate_action == "unknown":
            state = "roster_source_error"
            tone = "warn"
            title = "编制/上岗数据源异常"
            detail = f"无法确认编制或上岗数据源：{gate_reason or 'unknown'}。"
            primary_surface = "duty_roster_graph"
            primary_view = "department"
            primary_action = "repair_roster_data_source"
            next_actions = ["inspect_roster_source", "repair_duty_registry"]
        elif governance_health == "bad":
            state = "governance_degraded"
            tone = "bad"
            title = "治理动作连续失败"
            detail = f"最近治理动作连续失败 {governance_consecutive} 次；先在完整 Loop 查看治理审计，再恢复自动治理信任。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_governance_audit"
            next_actions = [
                "inspect_governance_audit",
                "review_failed_governance_actions",
            ]
        elif not participant_count:
            state = "waiting_for_loop_participants"
            tone = "warn"
            title = "等待 Loop 派发到员工"
            detail = "runtime 尚未暴露 employee_id/actor/assignee；员工空间暂时只能展示待派发工位。"
            primary_surface = "self_evolution_loop"
            primary_view = "loop"
            primary_action = "inspect_gate_and_evidence"
            next_actions = ["inspect_evidence_gate", "wait_for_participant_evidence"]
        elif open_count:
            state = "running"
            tone = "run"
            title = "上岗员工正在执行 Loop"
            detail = f"{participant_count} 个员工参与，{open_count} 个 run 未闭环；员工空间展示执行现场，编制图谱展示准入。"
            primary_surface = "employee_space"
            primary_view = "hub"
            primary_action = "observe_active_workers"
            next_actions = ["open_employee_space", "inspect_run_timeline"]

        governance_action = {
            "id": primary_action,
            "label": "观察 Loop 状态",
            "status": "informational",
            "surface": primary_surface,
            "view": primary_view,
            "executable": False,
            "target_employee_ids": target_ids,
            "requires_admin": False,
            "allowed_surfaces": [primary_surface],
            "method": "",
            "endpoint_hint": "",
            "refresh_after": ["self_maintenance_status"],
        }
        if gate_action == "hold":
            governance_action.update(
                {
                    "id": "register_duty_employees",
                    "label": "补登记上岗员工",
                    "status": "requires_action",
                    "surface": "duty_roster_graph",
                    "view": "loop",
                    "executable": True,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                    "method": "POST",
                    "endpoint_hint": "/api/admin/yuangon-onboard/run",
                    "refresh_after": ["duty_roster_graph", "self_maintenance_status"],
                }
            )
        elif gate_action == "isolate":
            governance_action.update(
                {
                    "id": "isolate_out_of_roster_participants",
                    "label": "隔离非编制参与者",
                    "status": "enforced",
                    "surface": "duty_roster_graph",
                    "view": "loop",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph", "self_evolution_loop"],
                    "method": "gate",
                    "endpoint_hint": "self_maintenance_roster_gate",
                    "refresh_after": ["self_maintenance_status"],
                }
            )
        elif gate_action == "unknown":
            governance_action.update(
                {
                    "id": "repair_roster_data_source",
                    "label": "修复编制/上岗数据源",
                    "status": "requires_human_review",
                    "surface": "duty_roster_graph",
                    "view": "department",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                }
            )
        elif state == "governance_degraded":
            governance_action.update(
                {
                    "id": "inspect_governance_audit",
                    "label": "复核治理审计",
                    "status": "requires_human_review",
                    "surface": "self_evolution_loop",
                    "view": "loop",
                    "executable": False,
                    "requires_admin": True,
                    "allowed_surfaces": ["duty_roster_graph"],
                    "method": "audit",
                    "endpoint_hint": "governance_audit.summary",
                    "review_endpoint_hint": "/api/ops/self-maintenance/governance-review",
                    "refresh_after": ["self_maintenance_status"],
                }
            )

        return {
            "state": state,
            "tone": tone,
            "title": title,
            "detail": detail,
            "primary_surface": primary_surface,
            "primary_view": primary_view,
            "primary_action": primary_action,
            "primary_employee_id": target_ids[0] if target_ids else "",
            "target_employee_ids": target_ids,
            "gate_action": gate_action,
            "gate_reason": gate_reason,
            "isolation_enforced": gate_action == "isolate",
            "blocked_employee_ids": target_ids if gate_action == "isolate" else [],
            "isolation_reason": gate_reason if gate_action == "isolate" else "",
            "isolation_policy": "out_of_roster_participants_are_never_treated_as_on_duty_workers",
            "governance_action": governance_action,
            "governance_health": governance_audit_summary,
            "next_actions": next_actions,
            "handoff_path": [
                {
                    "surface": "self_evolution_loop",
                    "role": "runtime_overview",
                    "view": "loop",
                },
                {
                    "surface": "duty_roster_graph",
                    "role": "governance_surface",
                    "view": primary_view,
                },
                {
                    "surface": "employee_space",
                    "role": "execution_surface",
                    "employee_id": target_ids[0] if target_ids else "",
                },
            ],
            "employee_space": {
                "role": "execution_surface",
                "title": (
                    title if primary_surface == "employee_space" else "员工空间只展示执行现场"
                ),
                "detail": (
                    detail
                    if primary_surface == "employee_space"
                    else "补登记、隔离、数据源修复统一在编制图谱处理，避免工位页绕过上岗门禁。"
                ),
                "cta": ("看执行现场" if primary_surface == "employee_space" else "去编制图谱处理"),
            },
            "duty_roster_graph": {
                "role": "governance_surface",
                "title": title,
                "detail": detail,
                "cta": (
                    "执行治理动作" if primary_surface == "duty_roster_graph" else "查看编制准入"
                ),
            },
        }

    ui_bridge = _ui_bridge_summary()
    generated_at = datetime.now(timezone.utc).isoformat()
    latest_timestamp = _ledger_row_timestamp(rows[-1]) if rows else None
    latest_event_at = latest_timestamp.isoformat() if latest_timestamp is not None else None
    runtime_source = {
        "name": "self_maintenance_loop_runner",
        "runtime": "MODstore",
        "ledger": str(ledger_path()),
        "memory": str(loop_memory_path()),
        "governance_audit": str(governance_audit_path()),
    }
    runtime_contract = {
        "schema_version": "self_maintenance_runtime.v1",
        "required_top_level": [
            "schema_version",
            "source",
            "generated_at",
            "refreshed_at",
            "evidence",
            "participants",
            "run_timelines",
            "roster_alignment",
            "ui_bridge",
            "active_gates",
            "governance_gate",
            "governance_audit",
            "merge_decision",
        ],
        "surfaces": [
            "employee_space",
            "duty_roster_graph",
            "self_evolution_loop_runtime",
        ],
        "identity_dependencies": ["participants", "roster_alignment", "ui_bridge"],
        "gate_dependencies": [
            "active_gates",
            "governance_gate",
            "roster_alignment.gate",
            "merge_decision",
            "evolution_metrics_summary",
        ],
        "truth_dependencies": [
            "source",
            "evidence",
            "governance_audit",
            "run_timelines",
        ],
        "required_nested": [
            "active_gates.items",
            "governance_audit.summary",
            "governance_gate.summary",
            "roster_alignment.gate",
            "ui_bridge.employee_space",
            "ui_bridge.duty_roster_graph",
            "ui_bridge.governance_action",
        ],
    }
    runtime_top_level_keys = {
        "ok",
        "cron",
        "current_gate",
        "schema_version",
        "contract",
        "contract_validation",
        "source",
        "generated_at",
        "refreshed_at",
        "latest_event_at",
        "evidence",
        "participants",
        "run_timelines",
        "roster_alignment",
        "ui_bridge",
        "active_gates",
        "governance_gate",
        "governance_audit",
        "merge_decision",
        "kb_summary",
        "evolution_metrics_summary",
        "memory",
    }
    contract_missing_fields = [
        field
        for field in runtime_contract["required_top_level"]
        if field not in runtime_top_level_keys
    ]
    contract_nested_presence = {
        "active_gates.items": (
            bool(active_gates.get("items")) if isinstance(active_gates, dict) else False
        ),
        "governance_audit.summary": bool(governance_audit_summary),
        "governance_gate.summary": (
            bool(governance_gate_current.get("summary"))
            if isinstance(governance_gate_current, dict)
            else False
        ),
        "roster_alignment.gate": (
            bool(roster_alignment.get("gate")) if isinstance(roster_alignment, dict) else False
        ),
        "ui_bridge.employee_space": (
            bool(ui_bridge.get("employee_space")) if isinstance(ui_bridge, dict) else False
        ),
        "ui_bridge.duty_roster_graph": (
            bool(ui_bridge.get("duty_roster_graph")) if isinstance(ui_bridge, dict) else False
        ),
        "ui_bridge.governance_action": (
            bool(ui_bridge.get("governance_action")) if isinstance(ui_bridge, dict) else False
        ),
    }
    contract_missing_nested = [
        path
        for path in runtime_contract["required_nested"]
        if not contract_nested_presence.get(path)
    ]
    contract_surface_requirements = {
        "employee_space": [
            "participants",
            "run_timelines",
            "roster_alignment.gate",
            "ui_bridge.employee_space",
            "ui_bridge.governance_action",
        ],
        "duty_roster_graph": [
            "roster_alignment.gate",
            "ui_bridge.duty_roster_graph",
            "ui_bridge.governance_action",
            "governance_gate.summary",
            "governance_audit.summary",
        ],
        "self_evolution_loop_runtime": [
            "active_gates.items",
            "merge_decision",
            "evolution_metrics_summary",
            "governance_gate.summary",
            "governance_audit.summary",
        ],
    }

    def _contract_dependency_present(name: str) -> bool:
        if "." in name:
            return bool(contract_nested_presence.get(name))
        return name in runtime_top_level_keys

    def _contract_surface_remediation(surface: str, missing: List[str]) -> Dict[str, Any]:
        if not missing:
            return {
                "action": "observe",
                "title": "Surface contract ready",
                "detail": "All required runtime dependencies for this surface are present.",
                "severity": "ok",
                "target_surface": surface,
                "target_view": "loop",
                "requires_admin": False,
                "executable": False,
            }
        if surface == "employee_space":
            if "participants" in missing or "run_timelines" in missing:
                return {
                    "action": "wait_for_employee_ledger",
                    "title": "Wait for employee work-order evidence",
                    "detail": "Employee space needs participants and run_timelines before it can prove real loop work.",
                    "severity": "warn",
                    "target_surface": "self_evolution_loop_runtime",
                    "target_view": "loop",
                    "requires_admin": False,
                    "executable": False,
                }
            return {
                "action": "open_duty_roster_graph",
                "title": "Resolve employee governance dependencies",
                "detail": "Employee space is read-only for governance; fix roster/ui_bridge dependencies in duty roster graph.",
                "severity": "bad",
                "target_surface": "duty_roster_graph",
                "target_view": "loop",
                "requires_admin": True,
                "executable": False,
            }
        if surface == "duty_roster_graph":
            if "governance_audit.summary" in missing or "governance_gate.summary" in missing:
                return {
                    "action": "inspect_governance_audit",
                    "title": "Inspect governance audit contract",
                    "detail": "Duty roster graph needs governance gate and audit summaries before it can execute admin decisions.",
                    "severity": "bad",
                    "target_surface": "duty_roster_graph",
                    "target_view": "loop",
                    "requires_admin": True,
                    "executable": True,
                }
            return {
                "action": "repair_roster_contract",
                "title": "Repair roster governance contract",
                "detail": "Duty roster graph needs roster_alignment.gate and ui_bridge governance action dependencies.",
                "severity": "bad",
                "target_surface": "duty_roster_graph",
                "target_view": "loop",
                "requires_admin": True,
                "executable": True,
            }
        return {
            "action": "inspect_runtime_contract",
            "title": "Inspect full loop runtime contract",
            "detail": "Full loop panel needs active gates, merge decision, metrics, and governance summaries.",
            "severity": "bad",
            "target_surface": "self_evolution_loop_runtime",
            "target_view": "loop",
            "requires_admin": False,
            "executable": False,
        }

    contract_surface_readiness = {}
    for surface, requirements in contract_surface_requirements.items():
        missing = [name for name in requirements if not _contract_dependency_present(name)]
        remediation = _contract_surface_remediation(surface, missing)
        contract_surface_readiness[surface] = {
            "ok": not missing,
            "required": requirements,
            "missing": missing,
            "action": remediation["action"],
            "title": remediation["title"],
            "detail": remediation["detail"],
            "severity": remediation["severity"],
            "target_surface": remediation.get("target_surface") or surface,
            "target_view": remediation.get("target_view") or "loop",
            "requires_admin": remediation.get("requires_admin") is True,
            "executable": remediation.get("executable") is True,
        }

    contract_surface_incidents = [
        {
            "id": f"contract:{surface}",
            "source": "contract_validation",
            "schema_version": runtime_contract["schema_version"],
            "created_at": generated_at,
            "surface": surface,
            "severity": readiness.get("severity") or "bad",
            "action": readiness.get("action") or "inspect_runtime_contract",
            "title": readiness.get("title") or "Surface contract blocked",
            "detail": readiness.get("detail") or "Surface runtime dependencies are missing.",
            "target_surface": readiness.get("target_surface") or surface,
            "target_view": readiness.get("target_view") or "loop",
            "requires_admin": readiness.get("requires_admin") is True,
            "executable": readiness.get("executable") is True,
            "missing": readiness.get("missing") or [],
            "required": readiness.get("required") or [],
        }
        for surface, readiness in contract_surface_readiness.items()
        if isinstance(readiness, dict) and not readiness.get("ok")
    ]

    def _contract_incident_priority(item: Dict[str, Any]) -> tuple:
        severity_rank = {"bad": 0, "warn": 1, "ok": 2}
        surface_rank = {
            "duty_roster_graph": 0,
            "self_evolution_loop_runtime": 1,
            "employee_space": 2,
        }
        return (
            severity_rank.get(str(item.get("severity") or "unknown"), 9),
            0 if item.get("executable") else 1,
            0 if item.get("requires_admin") else 1,
            surface_rank.get(str(item.get("surface") or ""), 9),
        )

    contract_primary_incident = (
        sorted(contract_surface_incidents, key=_contract_incident_priority)[0]
        if contract_surface_incidents
        else None
    )
    contract_surface_incident_summary = {
        "status": "blocked" if contract_surface_incidents else "clear",
        "total": len(contract_surface_incidents),
        "surfaces": sorted(
            {str(item.get("surface")) for item in contract_surface_incidents if item.get("surface")}
        ),
        "actions": sorted(
            {str(item.get("action")) for item in contract_surface_incidents if item.get("action")}
        ),
        "by_severity": {
            severity: sum(
                1 for item in contract_surface_incidents if item.get("severity") == severity
            )
            for severity in sorted(
                {str(item.get("severity") or "unknown") for item in contract_surface_incidents}
            )
        },
        "requires_admin_count": sum(
            1 for item in contract_surface_incidents if item.get("requires_admin")
        ),
        "executable_count": sum(1 for item in contract_surface_incidents if item.get("executable")),
        "admin_required": any(
            bool(item.get("requires_admin")) for item in contract_surface_incidents
        ),
        "executable_available": any(
            bool(item.get("executable")) for item in contract_surface_incidents
        ),
        "primary_incident": contract_primary_incident,
        "primary_action": (
            contract_primary_incident.get("action")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
        "primary_surface": (
            contract_primary_incident.get("surface")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
        "primary_target_surface": (
            contract_primary_incident.get("target_surface")
            if isinstance(contract_primary_incident, dict)
            else None
        ),
    }
    contract_global_ok = not contract_missing_fields
    contract_all_surfaces_ok = not contract_surface_incidents
    contract_status_blocked = not contract_global_ok or not contract_all_surfaces_ok
    contract_status_detail = (
        f"Runtime contract top-level required fields are missing: {', '.join(contract_missing_fields[:6])}."
        if contract_missing_fields
        else (
            contract_primary_incident.get("detail")
            if isinstance(contract_primary_incident, dict)
            else "All runtime contract surfaces are ready."
        )
    )
    contract_status = {
        "state": "blocked" if contract_status_blocked else "trusted",
        "tone": "bad" if contract_status_blocked else "ok",
        "label": "Contract blocked" if contract_status_blocked else "Contract trusted",
        "detail": contract_status_detail,
        "global_ok": contract_global_ok,
        "all_surfaces_ok": contract_all_surfaces_ok,
        "primary_action": contract_surface_incident_summary.get("primary_action"),
        "primary_surface": contract_surface_incident_summary.get("primary_surface"),
        "primary_target_surface": contract_surface_incident_summary.get("primary_target_surface"),
        "surface_incident_total": contract_surface_incident_summary.get("total", 0),
        "admin_required": contract_surface_incident_summary.get("admin_required", False),
        "executable_available": contract_surface_incident_summary.get(
            "executable_available", False
        ),
        "primary_route": {
            "surface": contract_surface_incident_summary.get("primary_target_surface")
            or contract_surface_incident_summary.get("primary_surface")
            or "self_evolution_loop_runtime",
            "view": (
                contract_primary_incident.get("target_view")
                if isinstance(contract_primary_incident, dict)
                else "loop"
            ),
            "action": contract_surface_incident_summary.get("primary_action") or "observe",
            "requires_admin": contract_surface_incident_summary.get("admin_required", False),
            "executable": contract_surface_incident_summary.get("executable_available", False),
            "employee_id": (
                ui_bridge.get("primary_employee_id") if isinstance(ui_bridge, dict) else None
            ),
            "target_employee_ids": (
                ui_bridge.get("target_employee_ids")
                if isinstance(ui_bridge, dict)
                and isinstance(ui_bridge.get("target_employee_ids"), list)
                else []
            ),
            "label": (
                "Open governance surface"
                if contract_surface_incident_summary.get("primary_target_surface")
                == "duty_roster_graph"
                else (
                    "Open employee surface"
                    if contract_surface_incident_summary.get("primary_target_surface")
                    == "employee_space"
                    else "Open full loop"
                )
            ),
            "detail": (
                "Admin governance action is available on the target surface."
                if contract_surface_incident_summary.get("executable_available")
                else "Navigate to the target surface for inspection; no direct action is executed here."
            ),
        },
    }

    contract_validation = {
        "ok": contract_global_ok and contract_all_surfaces_ok,
        "global_ok": contract_global_ok,
        "all_surfaces_ok": contract_all_surfaces_ok,
        "schema_version": runtime_contract["schema_version"],
        "required_count": len(runtime_contract["required_top_level"]),
        "missing_fields": contract_missing_fields,
        "required_nested_count": len(runtime_contract["required_nested"]),
        "missing_nested": contract_missing_nested,
        "surface_readiness": contract_surface_readiness,
        "surface_incidents": contract_surface_incidents,
        "surface_incident_summary": contract_surface_incident_summary,
        "contract_status": contract_status,
        "generated_at": generated_at,
        "surfaces": runtime_contract["surfaces"],
        "gate_dependencies": runtime_contract["gate_dependencies"],
        "truth_dependencies": runtime_contract["truth_dependencies"],
    }

    return {
        "ok": True,
        "cron": {
            "hour": _env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3),
            "minute": _env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0),
            "timezone": os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai"),
            "trigger": str(trigger),
        },
        "current_gate": gate,
        "schema_version": runtime_contract["schema_version"],
        "contract": runtime_contract,
        "contract_validation": contract_validation,
        "contract_status": contract_status,
        "source": runtime_source,
        "generated_at": generated_at,
        "refreshed_at": generated_at,
        "latest_event_at": latest_event_at,
        "evidence": {
            "ledger_path": str(ledger_path()),
            "memory_path": str(loop_memory_path()),
            "latest_complete": latest_complete,
            "latest_skip": latest_skip,
            "open_run_ids": open_run_ids,
            "recent_rows": rows[-20:],
            "milestone_rows": milestone_rows,
            "milestone_window": {
                "window_days": evidence_window_days,
                "scan_limit": evidence_scan_limit,
                "run_limit": evidence_run_limit,
                "row_limit": DEFAULT_EVIDENCE_ROW_LIMIT,
                "selected_rows": len(milestone_rows),
                "policy": "recent_meaningful_runs_excluding_heartbeat_skip_and_kb_salvage",
            },
            "steps_by_open_run": {run_id: steps_by_run.get(run_id, []) for run_id in open_run_ids},
        },
        "participants": sorted(
            participants_by_id.values(),
            key=lambda item: str(item.get("latest_at") or ""),
            reverse=True,
        )[:24],
        "run_timelines": run_timelines,
        "roster_alignment": roster_alignment,
        "ui_bridge": ui_bridge,
        "active_gates": active_gates,
        "governance_gate": governance_gate_current,
        "governance_audit": {
            "path": str(governance_audit_path()),
            "summary": governance_audit_summary,
            "recent": governance_audit,
            "last": governance_audit[-1] if governance_audit else None,
        },
        "merge_decision": merge_decision,
        "kb_summary": kb_summary,
        "evolution_metrics_summary": evolution_metrics_summary,
        "memory": {
            "updated_at": memory.get("updated_at"),
            "last_policy_decision": memory.get("last_policy_decision"),
            "last_run": memory.get("last_run"),
            "open_items": open_items[-20:],
            "recent_runs": recent_runs[-20:],
            "run_count": memory.get("run_count"),
        },
        "policy": {
            "auto_merge_low_risk": _env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True),
            "auto_merge_dynamic_low_risk": _env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True
            ),
            "auto_merge_forbidden_globs": _auto_merge_forbidden_globs(),
            "auto_merge_globs": _allowed_auto_merge_globs(),
            "auto_merge_max_files": _auto_merge_max_files(),
            "auto_merge_max_lines": _auto_merge_max_lines(),
            "auto_merge_max_risk_score": _auto_merge_max_risk_score(),
            "auto_merge_min_safety_score_v2": _auto_merge_min_safety_score_v2(),
            "auto_merge_scoring_gate_v2": _env_bool(
                "MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True
            ),
            "auto_merge_scope_globs": _auto_merge_scope_globs(),
            "report_timeout_sec": _env_int("MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800),
            "focused_test_command": _focused_test_command(),
            "threshold": _env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1),
            "cooldown_minutes": _env_int("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360),
            # L4 closure: deploy step after merge（默认开 staging；prod 须显式 ENVS）
            "auto_dispatch_deploy": _auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": _auto_dispatch_deploy_envs(),
            "auto_dispatch_deploy_dry_run": _env_flag_enabled(
                "MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"
            ),
        },
        "l4_closure": {
            "target": "L4",
            "auto_dispatch_deploy": _auto_dispatch_deploy_enabled(),
            "auto_dispatch_deploy_envs": _auto_dispatch_deploy_envs(),
            "half_closed_without_deploy": not _auto_dispatch_deploy_enabled(),
            "open_items_count": len(open_items[-20:]),
        },
    }


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
