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
import fnmatch
import re
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import httpx
from apscheduler.triggers.cron import CronTrigger

from .duty_roster import SIX_LINE_DEPARTMENTS, all_planned_employee_ids
from .duty_employee_registry import duty_employee_records
from .employee_executor import execute_employee_task
from .models import EmployeeExecutionMetric, IncidentEvent, get_session_factory
from .self_evolution_knowledge import (
    build_self_evolution_context,
    collect_proactive_signals,
    evolution_metrics_gate,
    record_loop_evolution_knowledge,
    render_self_evolution_context,
    validate_kb_payload,
)

logger = logging.getLogger(__name__)


DEFAULT_RUNTIME_DIR = str(Path.home() / ".xcmax" / "modstore-daily")
DEFAULT_LEDGER_NAME = "self_maintenance_loop_runs.jsonl"
DEFAULT_MEMORY_NAME = "self_maintenance_loop_memory.json"
DEFAULT_GOVERNANCE_AUDIT_NAME = "self_maintenance_governance_actions.jsonl"
DEFAULT_CLEAN_BASELINE_NAME = "self_maintenance_clean_baseline.json"
DEFAULT_PARA_AUTH_CACHE_NAME = "para_guest_auth_cache.json"
DEFAULT_MERGE_WORKSPACE_ROOT = "self_maintenance_merge_workspaces"
DEFAULT_STATUS_FILE = (
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/"
    "self_maintenance_loop_status.py"
)
DEFAULT_AUTO_MERGE_GLOBS = [DEFAULT_STATUS_FILE]
DEFAULT_AUTO_MERGE_SCOPE_GLOBS = [
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_*.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_evolution_knowledge.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_evolution_kb_redisvl.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/incident_model_router.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/incident_team_orchestrator.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/adaptive_release_controller.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_merge_audit_sampler.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/autonomous_risk_gate.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/human_uncertainty_queue.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/kb_self_maintenance.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/node_coordinator.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/predictive_maintenance.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/release_recovery_orchestrator.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/unified_autonomy_orchestrator.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_approve_policy.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/ops_staged_auto_approve.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/digest_vibe_prep.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_signal_collector.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/models_project_context.py",
    "FHD/XCAGI/kb/fixes/*.json",
    "FHD/XCAGI/kb/fixes/*.md",
    "FHD/XCAGI/kb/patterns/*.json",
    "FHD/XCAGI/kb/patterns/*.md",
    "FHD/XCAGI/kb/metrics/*.jsonl",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_self_*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_self_evolution_knowledge*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_policy*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_ops_staged_auto_approve*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_digest_vibe_prep.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_project_context*.py",
]
DEFAULT_AUTO_MERGE_FORBIDDEN_GLOBS = [
    "*.env",
    "*.env.*",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*secret*",
    "**/*credential*",
    "**/*token*",
    ".github/workflows/*",
    "**/migrations/**",
    "**/alembic/**",
    "**/models.py",
    "**/models/**",
    "**/api/app_factory.py",
    "**/Dockerfile*",
    "**/docker-compose*.yml",
    "**/requirements*.txt",
    "**/pyproject.toml",
    "**/package-lock.json",
]
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
    tmp.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return baseline


def _clean_baseline_context() -> str:
    return json.dumps(load_clean_baseline(), ensure_ascii=False, sort_keys=True)[:4000]


def _append_ledger(record: Dict[str, Any]) -> None:
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
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        logger.exception("failed to read self-maintenance ledger")
        return []
    return rows[-limit:]


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
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        logger.exception("failed to read self-maintenance governance audit")
        return []
    return rows[-limit:]


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


def _governance_audit_summary(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    items = rows if isinstance(rows, list) else _read_governance_audit(10)
    success_count = sum(1 for item in items if isinstance(item, dict) and item.get("ok") is not False)
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
        "health": "bad" if consecutive_failures >= 2 else ("warn" if failure_count else "ok"),
    }


def _governance_audit_gate() -> Dict[str, Any]:
    summary = _governance_audit_summary()
    health = str(summary.get("health") or "").strip()
    ok = health != "bad"
    return {
        "ok": ok,
        "blocking": not ok,
        "action": "allow" if ok else "hold_for_governance_review",
        "reason": "governance_audit_healthy" if ok else "governance_audit_consecutive_failures",
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
    if action not in {"auto_merged_low_risk", "auto_continue"} and status != "completed_merged":
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
    if isinstance(open_items_raw, list):
        for item in open_items_raw:
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and int(item.get("retry_count") or 1) >= max_retries
            ):
                item["escalated"] = True
                logger.warning(
                    "open_item run_id=%s exceeded max_retries=%d, escalating",
                    item.get("run_id"),
                    max_retries,
                )
        memory["open_items"] = [
            item
            for item in open_items_raw
            if not (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and int(item.get("retry_count") or 1) >= max_retries
            )
        ]
    last_decision = memory.get("last_policy_decision")
    if isinstance(last_decision, dict) and str(last_decision.get("reason") or "") in {
        "review_or_qa_reported_risk",
        "employee_step_failed",
        "loop_not_completed",
    }:
        return None
    open_items = memory.get("open_items")
    recent_runs = memory.get("recent_runs")
    if not isinstance(open_items, list) or not isinstance(recent_runs, list):
        return None

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
        if not isinstance(item, dict) or item.get("kind") != "human_strategy_approval":
            continue
        reason = str(item.get("reason") or "")
        if reason not in {
            "changed_files_match_forbidden_globs",
            "changed_files_outside_dynamic_low_risk_scope",
            "changed_files_outside_low_risk_globs",
            "missing_report_only_evidence",
        }:
            continue
        branch = str(item.get("branch") or "").strip()
        para_task_id = str(item.get("task_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if branch and para_task_id:
            return {
                "branch": branch,
                "failed_run_id": run_id,
                "failed_steps": ["qa"],
                "para_task_id": para_task_id,
                "reason": "resume_human_strategy_candidate",
            }
    return None


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
    """自维护 loop 的执行身份。

    默认 0 = 平台身份：认知走平台密钥旁路（chat_dispatch_via_platform_only），
    成本记平台、不计任何真实用户的 llm_calls 配额。避免把平台自治工作错误闸控到
    owner 个人钱包（曾导致 ``403 配额不足: llm_calls`` 死亡螺旋）。
    运维可用 ``MODSTORE_SELF_MAINTENANCE_USER_ID`` 覆盖为某个真实用户。
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
                    "created_at": _iso(row.created_at)
                    if isinstance(row.created_at, datetime)
                    else str(row.created_at or ""),
                    "event_type": row.event_type,
                    "fingerprint": row.fingerprint,
                    "id": int(row.id),
                    "source": row.source,
                    "summary": str(payload.get("summary") or "")[:500],
                }
            )
        return {"count": int(count), "events": incidents, "lookback_hours": lookback_hours}
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
        "signal_count": signal_count,
    }


def _last_started_at() -> Optional[datetime]:
    for row in reversed(_read_ledger()):
        if row.get("phase") == "start":
            return _parse_iso(row.get("started_at") or row.get("created_at"))
    return None


def reconcile_stale_self_maintenance_runs() -> Dict[str, Any]:
    rows = _read_ledger(limit=300)
    started: Dict[str, Dict[str, Any]] = {}
    terminal: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        phase = str(row.get("phase") or "")
        if phase == "start":
            started[run_id] = row
        elif phase in {"complete", "skip"}:
            terminal[run_id] = row

    stale_minutes = _env_int("MODSTORE_SELF_MAINTENANCE_STALE_RUN_MINUTES", 90)
    cutoff = _utc_now() - timedelta(minutes=stale_minutes)
    reconciled: List[str] = []
    for run_id, start in started.items():
        if run_id in terminal:
            continue
        started_at = _parse_iso(start.get("started_at") or start.get("created_at"))
        if started_at is None or started_at > cutoff:
            continue
        final = {
            "completed_at": _iso(_utc_now()),
            "error": "run did not write a terminal record before stale timeout",
            "phase": "complete",
            "policy_decision": {
                "action": "stop",
                "reason": "stale_interrupted_run",
                "stale_minutes": stale_minutes,
            },
            "run_id": run_id,
            "started_at": _iso(started_at),
            "status": "abandoned_stale",
            "triggered_by": start.get("triggered_by"),
        }
        _append_ledger(final)
        reconciled.append(run_id)
    return {"reconciled": reconciled, "stale_minutes": stale_minutes}


def should_run_self_maintenance_loop(force: bool = False) -> Dict[str, Any]:
    if not _env_bool("MODSTORE_SELF_MAINTENANCE_ENABLED", True):
        return {"should_run": False, "reason": "disabled"}

    evaluation = evaluate_self_maintenance_need()
    metrics_gate = evolution_metrics_gate()
    if not force and metrics_gate.get("pause"):
        return {
            **evaluation,
            "evolution_metrics_gate": metrics_gate,
            "reason": "evolution_metrics_pause",
            "should_run": False,
        }
    threshold = _env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1)
    cooldown_minutes = _env_int("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360)
    last_started = _last_started_at()

    if not force and last_started is not None and cooldown_minutes > 0:
        next_allowed = last_started + timedelta(minutes=cooldown_minutes)
        if _utc_now() < next_allowed:
            return {
                **evaluation,
                "cooldown_minutes": cooldown_minutes,
                "next_allowed_at": _iso(next_allowed),
                "reason": "cooldown",
                "should_run": False,
                "threshold": threshold,
            }

    if not force and int(evaluation["signal_count"]) < threshold:
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
        "reason": "force" if force else "threshold_met",
        "should_run": True,
        "threshold": threshold,
    }


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
    return True


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
        "task_id": para_result.get("task_id")
        or para_result.get("id")
        or response.get("taskId"),
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
    text = _extract_report_excerpt(result).lower()
    transient_terms = (
        "connection refused",
        "econnrefused",
        "para api 调用失败",
        "para_api_failed_outboxed",
        "para_api_rejected_outboxed",
        "未在线",
        "disconnected",
        "timeout waiting for para",
    )
    return any(term in text for term in transient_terms)


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


def _base_para_input(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "branch": os.environ.get("MODSTORE_PARA_BRANCH"),
        "device_id": os.environ.get("MODSTORE_PARA_DEVICE_ID"),
        "repo_url": os.environ.get("MODSTORE_PARA_REPO_URL"),
        "suppress_lifecycle_events": True,
        "wait_for_para": True,
        "wait_timeout_sec": _env_int("MODSTORE_PARA_WAIT_TIMEOUT_SEC", 900),
    }
    if extra:
        data.update(extra)
    return data


def _code_task_text(run_id: str, evaluation: Dict[str, Any], memory: Dict[str, Any]) -> str:
    gaps = ", ".join(evaluation.get("gaps") or []) or "none"
    evolution_context = render_self_evolution_context(
        build_self_evolution_context(run_id=run_id, evaluation=evaluation, memory=memory)
    )
    return (
        "Run a real MODstore self-maintenance improvement task. "
        "Use the previous loop memory and current evidence gaps to fix the highest-value "
        "executable gap in the self-maintenance loop. "
        "Before reasoning from scratch, check SELF_EVOLUTION_CONTEXT. "
        "If a fix_knowledge_hit matches the current symptom and its diff still applies safely, "
        "reuse that historical fix first instead of inventing a new approach. "
        "If there is no bug gap, choose one proactive task from performance, coverage, or tech_debt signals. "
        "When you fix a bug, write the symptom/root_cause/fix_diff triad under FHD/XCAGI/kb/fixes; "
        "when review/QA approves a reusable change, write the pattern under FHD/XCAGI/kb/patterns. "
        "Do not create marker-only/status-only changes as proof of completion. "
        "Prefer changes that make scheduler gating, loop memory, report-only review/QA, "
        "or policy decisions more directly executable. "
        f"If and only if there is no safe actionable source change, update `{DEFAULT_STATUS_FILE}` "
        f"with LOOP_RUN_ID={run_id!r}, LOOP_KIND='scheduled_self_maintenance', "
        "BRIDGE='para_main_device', UPDATED_AT to the current UTC time, and a clear "
        "NO_ACTION_REASON explaining why no source change was safe. "
        "Do not edit runtime-only, ignored, .devfleet, or .trae files. "
        f"Current evidence gaps: {gaps}. "
        f"Previous loop memory JSON: {_memory_context(memory)}. "
        f"SELF_EVOLUTION_CONTEXT JSON: {evolution_context}"
    )


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
        "If the target branch is missing in the report-only workspace, fetch it from origin/repo_url "
        "and compare `origin/<base>...origin/<target>` or the local equivalent. "
        "If fetch/branch resolution fails, report that exact failure as target_branch_unavailable. "
        "Return concrete findings, risks, and missing evidence. "
        "At the end, output exactly one JSON object after the marker "
        f"{STRUCTURED_REVIEW_MARKER}: with schema "
        "{\"max_severity\":\"none|low|medium|high|critical\","
        "\"blocking_findings\":[],\"risk_class\":\"low|medium|high\","
        "\"target_branch_available\":true,\"tested_commands\":[]}. "
        f"Previous loop memory JSON: {_memory_context(memory)}"
    )


def _qa_task_text(run_id: str, branch: Optional[str], memory: Dict[str, Any]) -> str:
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    return (
        "MODSTORE_REPORT_ONLY=1. Report-only QA task. "
        "Do not change files, do not commit, and do not push. "
        f"Verify the executable evidence for self-maintenance loop run {run_id}. "
        f"Target branch to verify: `{branch or ''}`. "
        f"Base branch: `{base_branch}`. Repo URL: `{repo_url}`. "
        "Do not inspect your own report-only task branch as the target branch. "
        "If the target branch is missing in the report-only workspace, fetch it from origin/repo_url "
        "and compare `origin/<base>...origin/<target>` or the local equivalent. "
        "If fetch/branch resolution fails, report that exact failure as target_branch_unavailable. "
        "Evaluate the target branch, tests, changed files, and previous loop memory as merge-readiness evidence. "
        "Use CLEAN_BASELINE_JSON to separate existing allowed failures from new failures; "
        "FAIL only for new failures, missing target branch, blocking findings, or unsafe evidence. "
        "Do not fail only because the final terminal ledger record for this in-flight run does not exist yet; "
        "that record is written after QA returns. "
        "Return PASS only when the target branch is executable and no new review/QA risk remains; "
        "return FAIL for real missing executable evidence, unsafe scope, new failed tests, or unresolved review findings. "
        "At the end, output exactly one JSON object after the marker "
        f"{STRUCTURED_QA_MARKER}: with schema "
        "{\"verdict\":\"PASS|FAIL\",\"blocking_findings\":[],"
        "\"tested_commands\":[{\"command\":\"...\",\"exit_code\":0,\"status\":\"passed|failed\"}],"
        "\"target_branch_available\":true,"
        "\"test_delta\":{\"baseline_id\":\"...\",\"new_failures\":[],\"new_errors\":[]},"
        "\"changed_files_scope\":\"low|medium|high\","
        "\"risk_class\":\"low|medium|high\"}. "
        f"CLEAN_BASELINE_JSON: {_clean_baseline_context()}. "
        f"Previous loop memory JSON: {_memory_context(memory)}"
    )


def _json_after_marker(text: str, marker: str) -> Optional[Dict[str, Any]]:
    idx = (text or "").find(marker)
    if idx < 0:
        return None
    tail = text[idx + len(marker) :]
    tail = tail.lstrip(" \t\r\n:=`")
    if tail.startswith("json"):
        tail = tail[4:].lstrip(" \t\r\n")
    try:
        obj, _ = json.JSONDecoder().raw_decode(tail)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _structured_report_from_step(step: Dict[str, Any], marker: str) -> Optional[Dict[str, Any]]:
    report = str(step.get("report_excerpt") or "")
    parsed = _json_after_marker(report, marker)
    if parsed is not None:
        return parsed
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
                return obj
            if marker == STRUCTURED_REVIEW_MARKER and "max_severity" in obj:
                return obj
    return None


def _structured_report_gate(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    review_steps = [step for step in steps if step.get("step") == "review"]
    qa_steps = [step for step in steps if step.get("step") == "qa"]
    if review_steps:
        review_json = _structured_report_from_step(review_steps[-1], STRUCTURED_REVIEW_MARKER)
        if not review_json:
            return {"ok": False, "reason": "missing_structured_review_result"}
        severity = str(review_json.get("max_severity") or "high").lower()
        blocking = review_json.get("blocking_findings")
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
            }
    else:
        review_json = None

    if qa_steps:
        qa_json = _structured_report_from_step(qa_steps[-1], STRUCTURED_QA_MARKER)
        if not qa_json:
            return {"ok": False, "reason": "missing_structured_qa_result", "review": review_json}
        verdict = str(qa_json.get("verdict") or "").upper()
        if verdict != "PASS":
            return {"ok": False, "reason": "structured_qa_verdict_not_pass", "qa": qa_json}
        if qa_json.get("target_branch_available") is not True:
            return {"ok": False, "reason": "structured_qa_target_branch_unavailable", "qa": qa_json}
        blocking = qa_json.get("blocking_findings")
        if isinstance(blocking, list) and blocking:
            return {"ok": False, "reason": "structured_qa_blocking_findings", "qa": qa_json}
        test_delta = qa_json.get("test_delta") if isinstance(qa_json.get("test_delta"), dict) else {}
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
    return _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS",
        DEFAULT_AUTO_MERGE_SCOPE_GLOBS,
    )


def _auto_merge_forbidden_globs() -> List[str]:
    return _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS",
        DEFAULT_AUTO_MERGE_FORBIDDEN_GLOBS,
    )


def _auto_merge_max_files() -> int:
    return _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_FILES", 12)


def _auto_merge_max_lines() -> int:
    return _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_LINES", 600)


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


def _changed_files_for_branch(
    *, repo_url: str, base_branch: str, branch: str, workspace: Path
) -> List[str]:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    _run_cmd(["git", "clone", "--no-tags", repo_url, str(workspace)], timeout=300)
    _run_cmd(["git", "fetch", "origin", base_branch, branch], cwd=workspace, timeout=180)
    _run_cmd(["git", "checkout", "-B", base_branch, f"origin/{base_branch}"], cwd=workspace)
    diff = _run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            f"origin/{base_branch}...origin/{branch}",
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
                ["git", "-c", "core.quotePath=false", "show", f"origin/{branch}:{normalized}"],
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


def _normalize_repo_path(file_name: str) -> str:
    return (file_name or "").replace("\\", "/").strip().strip('"').strip("'")


def _diff_stats_changed_files_consistency(
    files: List[str],
    diff_stats: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(diff_stats, dict) or diff_stats.get("source") != "git_diff_numstat":
        return {"ok": True, "reason": "diff_stats_consistency_not_enforced_for_legacy_input"}
    expected = {_normalize_repo_path(file_name) for file_name in files if file_name}
    stats_changed = diff_stats.get("changed_files")
    if not isinstance(stats_changed, list):
        file_stats = diff_stats.get("files") if isinstance(diff_stats.get("files"), dict) else {}
        binary_files = diff_stats.get("binary_files") if isinstance(diff_stats.get("binary_files"), list) else []
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
    normalized = _normalize_repo_path(file_name)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in globs)


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
    return max(0, min(_env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V2", 90), 100))


def _historical_auto_merge_success_rate(memory: Optional[Dict[str, Any]]) -> Optional[float]:
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
        text = json.dumps(run, ensure_ascii=False).lower()
        if "auto_merged_low_risk" in text or "completed_merged" in text:
            considered += 1
            if any(term in text for term in ("rollback", "revert", "regression", "回滚", "退回")):
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
    if any(part in lower for part in ("models.py", "/models/", "migration", "alembic", "payment", "auth", "security")):
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
        {"file": file_name, "score": _file_type_risk(file_name)}
        for file_name in normalized_files
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


def _semantic_review_qa_analysis(steps: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not isinstance(steps, list):
        return {"available": False, "penalty": 8, "reason": "no_structured_llm_reports"}
    penalty = 0
    reports: Dict[str, Any] = {}
    review_steps = [step for step in steps if isinstance(step, dict) and step.get("step") == "review"]
    qa_steps = [step for step in steps if isinstance(step, dict) and step.get("step") == "qa"]
    if review_steps:
        review_json = _structured_report_from_step(review_steps[-1], STRUCTURED_REVIEW_MARKER)
        if isinstance(review_json, dict):
            reports["review"] = review_json
            severity = str(review_json.get("max_severity") or "medium").lower()
            penalty += {"none": 0, "low": 2, "medium": 8, "high": 30, "critical": 50}.get(severity, 15)
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
    text = (diff_excerpt or "").lower()
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
        "source": "diff_semantic_keyword_scan",
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
    rollback_penalty = 4 if rollback_rate is None else int(round(rollback_rate * 35))
    file_penalty = min(25, int((risk_v1.get("components") or {}).get("file_score") or 0) // 2)
    line_penalty = min(18, int((risk_v1.get("components") or {}).get("line_score") or 0))
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
        return _decision({
            "allowed_globs": allowed,
            "changed_files": normalized_files,
            "ok": False,
            "reason": "no_changed_files",
        })

    try:
        from modstore_server.self_maintenance_policy import (
            is_marker_status_path,
            loop_memory_requires_executable_change,
        )

        if all(is_marker_status_path(file_name) for file_name in normalized_files):
            requirement = loop_memory_requires_executable_change(memory)
            if requirement.get("required"):
                return _decision({
                    "allowed_globs": allowed,
                    "changed_files": normalized_files,
                    "ok": False,
                    "reason": "marker_only_diff_requires_executable_change",
                    "self_maintenance_requirement": requirement,
                })
    except Exception as exc:
        return _decision({
            "allowed_globs": allowed,
            "changed_files": normalized_files,
            "error": str(exc),
            "ok": False,
            "reason": "self_maintenance_policy_check_failed",
        })

    consistency = _diff_stats_changed_files_consistency(normalized_files, diff_stats)
    if not consistency.get("ok"):
        return _decision({
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "ok": False,
            "reason": "changed_files_diff_stats_mismatch",
        })

    absolute_forbidden_globs = _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_ABSOLUTE_FORBIDDEN_GLOBS",
        [
            "*.env",
            "*.env.*",
            "**/*.db",
            "**/*.sqlite",
            "**/*.sqlite3",
            "**/*secret*",
            "**/*credential*",
            "**/*token*",
        ],
    )
    absolute_forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _file_matches_any_glob(file_name, absolute_forbidden_globs)
    ]
    if absolute_forbidden_hits:
        return _decision({
            "absolute_forbidden_globs": absolute_forbidden_globs,
            "absolute_forbidden_hits": absolute_forbidden_hits,
            "changed_files": normalized_files,
            "ok": False,
            "reason": "changed_files_match_absolute_forbidden_globs",
        })

    binary_files = diff_stats.get("binary_files") if isinstance(diff_stats, dict) else []
    if binary_files:
        return _decision({
            "binary_files": binary_files,
            "changed_files": normalized_files,
            "ok": False,
            "reason": "binary_files_not_auto_mergeable",
        })

    if _env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", True) and safety_score_v3.get("ok"):
        return _decision({
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "line_changes": int((diff_stats or {}).get("line_changes") or 0),
            "ok": True,
            "reason": "risk_score_v3_any_code_policy_passed",
        })

    forbidden_globs = _auto_merge_forbidden_globs()
    forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _file_matches_any_glob(file_name, forbidden_globs)
    ]
    if forbidden_hits:
        return _decision({
            "changed_files": normalized_files,
            "forbidden_globs": forbidden_globs,
            "forbidden_hits": forbidden_hits,
            "ok": False,
            "reason": "changed_files_match_forbidden_globs",
        })

    max_files = _auto_merge_max_files()
    if len(normalized_files) > max_files:
        return _decision({
            "changed_files": normalized_files,
            "max_files": max_files,
            "ok": False,
            "reason": "too_many_changed_files_for_dynamic_auto_merge",
        })

    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    max_lines = _auto_merge_max_lines()
    if line_changes > max_lines:
        return _decision({
            "changed_files": normalized_files,
            "line_changes": line_changes,
            "max_lines": max_lines,
            "ok": False,
            "reason": "too_many_changed_lines_for_dynamic_auto_merge",
        })

    if _env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True):
        if int(safety_score_v2.get("score") or 0) < int(
            safety_score_v2.get("min_allowed") or 90
        ):
            return _decision({
                "changed_files": normalized_files,
                "ok": False,
                "reason": "auto_merge_safety_score_v2_too_low",
            })
        return _decision({
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "line_changes": line_changes,
            "ok": True,
            "reason": "risk_score_v2_policy_passed",
        })

    if int(risk_score.get("score") or 100) > int(risk_score.get("max_allowed") or 0):
        return _decision({
            "changed_files": normalized_files,
            "ok": False,
            "reason": "auto_merge_risk_score_too_high",
        })

    if _files_match_allowed_globs(normalized_files, allowed):
        return _decision({
            "allowed_globs": allowed,
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "line_changes": diff_stats.get("line_changes"),
            "ok": True,
            "reason": "legacy_low_risk_glob_policy_passed",
        })

    if not _env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True):
        return _decision({
            "allowed_globs": allowed,
            "changed_files": normalized_files,
            "ok": False,
            "reason": "changed_files_outside_low_risk_globs",
        })

    scope_globs = _auto_merge_scope_globs()
    out_of_scope = [
        file_name
        for file_name in normalized_files
        if not _file_matches_any_glob(file_name, scope_globs)
    ]
    if out_of_scope:
        return _decision({
            "changed_files": normalized_files,
            "ok": False,
            "out_of_scope": out_of_scope,
            "reason": "changed_files_outside_dynamic_low_risk_scope",
            "scope_globs": scope_globs,
        })

    return _decision({
        "changed_files": normalized_files,
        "diff_stats_consistency": consistency,
        "dynamic_scope_globs": scope_globs,
        "forbidden_globs": forbidden_globs,
        "line_changes": line_changes,
        "max_files": max_files,
        "max_lines": max_lines,
        "ok": True,
        "reason": "dynamic_low_risk_policy_passed",
    })


def _guest_auth_headers(api_base: str) -> Dict[str, str]:
    env_token = (
        os.environ.get("MODSTORE_PARA_AUTH_TOKEN")
        or os.environ.get("DEVFLEET_AUTH_TOKEN")
        or ""
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


def _read_para_guest_auth_file(api_base: str, *, min_ttl_seconds: int = _PARA_GUEST_AUTH_FILE_SAFETY_SECONDS) -> Optional[str]:
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
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    if not db_file.exists():
        return None
    try:
        with sqlite3.connect(str(db_file), timeout=2.0) as conn:
            row = conn.execute(
                """
                select id, email
                from users
                where email = 'guest@devfleet.local'
                   or (email like 'guest_%@devfleet.local')
                order by case when email = 'guest@devfleet.local' then 0 else 1 end
                limit 1
                """
            ).fetchone()
    except Exception:
        logger.warning("failed to read Para guest user from sqlite for local auth mint", exc_info=True)
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
    signature = _base64url_bytes(hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256).digest())
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
                bootstrap_output = _run_cmd(["launchctl", "bootstrap", domain, str(plist)], timeout=30)
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
                        return {**last_status, "reason": "online_after_stale_current_task_clear"}
                if online and current_task:
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": False,
                        "stale_clear": stale_clear,
                        "status": target.get("status"),
                    }
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
            return {
                **last_status,
                "error": last_error,
                "kickstart": kickstart_result,
                "online": False,
                "reason": "device_online_wait_timeout",
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
    if not repo_url.startswith("file://"):
        return {"ok": False, "reason": "repo_url_not_file_url", "repo_url": repo_url}
    if not base_branch:
        return {"ok": False, "reason": "missing_base_branch"}
    if not api_base:
        return {"ok": False, "reason": "missing_api_base"}

    workspace = _runtime_dir() / DEFAULT_MERGE_WORKSPACE_ROOT / run_id
    files = _changed_files_for_branch(
        repo_url=repo_url,
        base_branch=base_branch,
        branch=branch,
        workspace=workspace,
    )
    diff_stats = _diff_numstat_for_branch(base_branch=base_branch, branch=branch, workspace=workspace)
    diff_excerpt = _run_cmd(
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
    )[:20000]
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
    _run_cmd(["git", "push", "origin", f"HEAD:{base_branch}"], cwd=workspace, timeout=180)
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


def _decide_post_loop_policy(
    *,
    branch: Optional[str],
    gate: Dict[str, Any],
    para_task_id: Optional[str],
    run_id: str,
    status: str,
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    def _await_human(reason: str, **extra: Any) -> Dict[str, Any]:
        decision = {
            "action": "await_human_strategy_approval",
            "reason": reason,
            **extra,
        }
        try:
            from modstore_server.human_uncertainty_queue import enqueue_uncertain_item

            decision["uncertainty_queue"] = enqueue_uncertain_item(
                context={
                    "branch": branch,
                    "active_gates": extra.get("active_gates"),
                    "evolution_gate": extra.get("evolution_gate"),
                    "gate": gate,
                    "governance_gate": extra.get("governance_gate"),
                    "para_task_id": para_task_id,
                    "roster_gate": extra.get("roster_gate"),
                    "run_id": run_id,
                    "status": status,
                },
                decision=decision,
                reason=reason,
            )
        except Exception as exc:
            decision["uncertainty_queue"] = {"queued": False, "error": str(exc)[:300]}
        return decision

    if status != "completed":
        return {"action": "stop", "reason": "loop_not_completed"}
    if any(not bool(step.get("ok")) for step in steps):
        return {"action": "stop", "reason": "employee_step_failed"}
    structured_gate = _structured_report_gate(steps)
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
        return _await_human(
            structured_gate.get("reason") or "structured_report_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
            structured_gate=structured_gate,
        )
    if report_only_missing:
        return _await_human(
            "missing_report_only_evidence",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not roster_gate.get("ok"):
        return _await_human(
            roster_gate.get("reason") or "roster_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not governance_gate.get("ok"):
        return _await_human(
            governance_gate.get("reason") or "governance_gate_failed",
            active_gates=active_gates,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if bool(evolution_gate.get("pause")):
        return _await_human(
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
        return _await_human(
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
        return {
            "action": "auto_merged_low_risk",
            "active_gates": active_gates,
            "evolution_gate": evolution_gate,
            "gate": gate,
            "governance_gate": governance_gate,
            "merge_result": merge_result,
            "reason": "low_risk_policy_passed",
            "roster_gate": roster_gate,
        }
    return _await_human(
        merge_result.get("reason") or "auto_merge_not_allowed",
        gate=gate,
        active_gates=active_gates,
        evolution_gate=evolution_gate,
        governance_gate=governance_gate,
        merge_result=merge_result,
        roster_gate=roster_gate,
    )


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
        for idx, item in enumerate(open_items):
            if (
                isinstance(item, dict)
                and item.get("kind") == "failed_steps"
                and item.get("run_id") == run_id
            ):
                existing_idx = idx
                break
        if existing_idx is not None:
            existing = open_items[existing_idx]
            existing["retry_count"] = int(existing.get("retry_count") or 1) + 1
            existing["last_attempted_at"] = _iso(_utc_now())
            existing["steps"] = failed_steps
        else:
            open_items.append(
                {
                    "created_at": _iso(_utc_now()),
                    "kind": "failed_steps",
                    "retry_count": 1,
                    "run_id": run_id,
                    "steps": failed_steps,
                }
            )
    if decision.get("action") == "await_human_strategy_approval":
        open_items.append(
                {
                    "branch": final.get("branch"),
                    "active_gates": decision.get("active_gates"),
                    "created_at": _iso(_utc_now()),
                    "evolution_gate": decision.get("evolution_gate"),
                    "kind": "human_strategy_approval",
                    "governance_gate": decision.get("governance_gate"),
                    "reason": decision.get("reason"),
                    "roster_gate": decision.get("roster_gate"),
                    "run_id": final.get("run_id"),
                    "task_id": final.get("para_task_id"),
                }
        )
    memory["open_items"] = open_items
    resolution_record = _close_items_resolved_by_final(memory, final)
    knowledge_record = record_loop_evolution_knowledge(final, gate)

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
        }
    )

    memory.update(
        {
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


def run_self_maintenance_loop(
    *, triggered_by: str = "manual", force: bool = False, reason: Optional[str] = None
) -> Dict[str, Any]:
    """Run the real employee maintenance chain when gates allow it."""

    reconcile_stale_self_maintenance_runs()
    run_id = str(uuid.uuid4())
    started_at = _utc_now()
    gate = should_run_self_maintenance_loop(force=force)
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
        _append_ledger(record)
        return record

    user_id = _self_maintenance_actor_user_id()
    loop_memory = _load_loop_memory()
    resume_candidate = _resume_review_qa_candidate(loop_memory)
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
    }
    if resume_candidate:
        start_record["resume_candidate"] = resume_candidate
    _append_ledger(start_record)

    steps: List[Dict[str, Any]] = []
    para_task_id: Optional[str] = (
        str(resume_candidate.get("para_task_id")) if resume_candidate else None
    )
    code_branch: Optional[str] = str(resume_candidate.get("branch")) if resume_candidate else None

    plan = []
    if not resume_candidate:
        plan.append(("vibe-coding-maintainer", "code", _code_task_text(run_id, gate, loop_memory), {}))
    resume_failed_steps = set(resume_candidate.get("failed_steps") or []) if resume_candidate else set()
    should_run_review = not resume_candidate or "review" in resume_failed_steps
    should_run_qa = not resume_candidate or bool({"review", "qa"} & resume_failed_steps)
    if should_run_review:
        plan.append(
            (
            "change-request-auditor",
            "review",
            "",
            {
                "allow_medium_risk": True,
                "report_only": True,
                "wait_timeout_sec": _env_int(
                    "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                ),
            },
        ))
    if should_run_qa:
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
        ))

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

            input_data = _base_para_input(extra)
            result = _execute_employee_task_with_retries(
                employee_id,
                task_text,
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
            if para_meta.get("task_id") and para_task_id is None:
                para_task_id = str(para_meta["task_id"])
            if step_name == "code" and para_meta.get("branch"):
                code_branch = str(para_meta["branch"])

            step_record = {
                "employee_id": employee_id,
                "ok": ok,
                "para": para_meta,
                "phase": "step",
                "report_excerpt": report_excerpt,
                "retry_attempts": result.get("self_maintenance_retry_attempts"),
                "run_id": run_id,
                "step": step_name,
                "timestamp": _iso(_utc_now()),
            }
            steps.append(step_record)
            _append_ledger(step_record)

            if not ok:
                final = {
                    "branch": code_branch,
                    "completed_at": _iso(_utc_now()),
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
        elif policy_decision.get("action") == "await_human_strategy_approval":
            final_status = "completed_waiting_human_strategy"

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


def cron_trigger_for_self_maintenance() -> CronTrigger:
    hour = _env_int("MODSTORE_SELF_MAINTENANCE_HOUR", 3)
    minute = _env_int("MODSTORE_SELF_MAINTENANCE_MINUTE", 0)
    timezone_name = os.environ.get("MODSTORE_SELF_MAINTENANCE_TZ", "Asia/Shanghai")
    return CronTrigger(hour=hour, minute=minute, timezone=timezone_name)


def get_self_maintenance_runtime_status(limit: int = 80) -> Dict[str, Any]:
    """Return the runtime-consumed self-maintenance loop state.

    This is the read side for the loop. It intentionally consumes the same
    ledger, memory and gate functions used by the scheduler instead of relying
    on a marker file committed by an employee branch.
    """

    bounded_limit = max(1, min(int(limit or 80), 300))
    rows = _read_ledger(limit=bounded_limit)
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
        at = str(row.get("created_at") or row.get("completed_at") or row.get("started_at") or "").strip()
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
            for key in ("steps", "nodes", "result", "employee_results", "reports", "items"):
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
            "status": str(row.get("status") or row.get("action") or row.get("reason") or "").strip(),
            "created_at": str(row.get("created_at") or row.get("completed_at") or row.get("started_at") or "").strip(),
            "para_task_id": str(row.get("para_task_id") or "").strip(),
            "branch": str(row.get("branch") or row.get("target_branch") or "").strip(),
            "qa_verdict": str(qa.get("verdict") or "").strip() if qa else "",
            "qa_blocking_findings": qa.get("blocking_findings") if qa else [],
            "qa_tested_commands": qa.get("tested_commands") if qa else [],
            "qa_target_branch_available": qa.get("target_branch_available") if qa else None,
            "qa_risk_class": str(qa.get("risk_class") or "").strip() if qa else "",
            "review_verdict": str(review.get("verdict") or "").strip() if review else "",
            "review_max_severity": str(review.get("max_severity") or "").strip() if review else "",
            "review_findings": review.get("findings") if review else [],
            "reason": str(row.get("reason") or "").strip(),
        }

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
            dept_ids = [emp_id for emp_id in _department_employee_ids(dept) if emp_id in planned_ids]
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
            value.get("governance_gate")
            if isinstance(value.get("governance_gate"), dict)
            else {}
        )
        active_gates = (
            value.get("active_gates")
            if isinstance(value.get("active_gates"), dict)
            else {}
        )
        evolution_gate = (
            value.get("evolution_gate")
            if isinstance(value.get("evolution_gate"), dict)
            else {}
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
                value.get("para_task_id")
                or final.get("para_task_id")
                or ""
            ).strip(),
        }

    merge_decision = _merge_decision_summary(memory.get("last_policy_decision"))
    try:
        kb_context = build_self_evolution_context(
            run_id="runtime_status",
            evaluation=gate if isinstance(gate, dict) else {},
            memory=memory if isinstance(memory, dict) else {},
        )
        kb_search = kb_context.get("kb_search") if isinstance(kb_context.get("kb_search"), dict) else {}
        fix_hits = kb_context.get("fix_knowledge_hits") if isinstance(kb_context.get("fix_knowledge_hits"), list) else []
        pattern_hits = kb_context.get("pattern_hits") if isinstance(kb_context.get("pattern_hits"), list) else []
        kb_summary = {
            "kb_root": kb_context.get("kb_root"),
            "engine": kb_search.get("engine"),
            "fix_hit_count": kb_search.get("fix_hit_count", len(fix_hits)),
            "pattern_hit_count": kb_search.get("pattern_hit_count", len(pattern_hits)),
            "redisvl_status": kb_search.get("redisvl_status"),
            "top_fix_hits": [
                {
                    "symptom": str(item.get("symptom") or item.get("summary") or item.get("id") or "")[:180],
                    "root_cause": str(item.get("root_cause") or "")[:180],
                    "fix_diff": str(item.get("fix_diff") or "")[:2000],
                    "executable_template": item.get("executable_template")
                    if isinstance(item.get("executable_template"), dict)
                    else {},
                    "required_tests": (
                        item.get("executable_template", {}).get("required_tests")
                        if isinstance(item.get("executable_template"), dict)
                        and isinstance(item.get("executable_template", {}).get("required_tests"), list)
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
                    "pattern": str(item.get("pattern") or item.get("summary") or item.get("id") or "")[:180],
                    "summary": str(item.get("summary") or "")[:180],
                    "applicability": str(item.get("applicability") or item.get("applicability_check") or "")[:1000],
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
            "fix_hit_count": 0,
            "pattern_hit_count": 0,
            "redisvl_status": {"ready": False, "error": str(exc)[:300]},
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
    metric_windows = metrics_gate.get("windows") if isinstance(metrics_gate.get("windows"), list) else []
    evolution_metrics_summary = {
        "pause": bool(metrics_gate.get("pause")),
        "reason": metrics_gate.get("reason"),
        "history_count": metrics_gate.get("history_count"),
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
        roster_alignment.get("gate")
        if isinstance(roster_alignment.get("gate"), dict)
        else {}
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
            roster_alignment.get("gate")
            if isinstance(roster_alignment.get("gate"), dict)
            else {}
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
            detail = "Loop 参与者命中编制基线但未完成 duty registry 上岗登记，必须先在编制图谱补登记。"
            primary_surface = "duty_roster_graph"
            primary_view = "loop"
            primary_action = "register_duty_employees"
            next_actions = ["register_duty_employees", "refresh_self_maintenance_status"]
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
            next_actions = ["inspect_governance_audit", "review_failed_governance_actions"]
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
                {"surface": "self_evolution_loop", "role": "runtime_overview", "view": "loop"},
                {"surface": "duty_roster_graph", "role": "governance_surface", "view": primary_view},
                {"surface": "employee_space", "role": "execution_surface", "employee_id": target_ids[0] if target_ids else ""},
            ],
            "employee_space": {
                "role": "execution_surface",
                "title": title if primary_surface == "employee_space" else "员工空间只展示执行现场",
                "detail": detail if primary_surface == "employee_space" else "补登记、隔离、数据源修复统一在编制图谱处理，避免工位页绕过上岗门禁。",
                "cta": "看执行现场" if primary_surface == "employee_space" else "去编制图谱处理",
            },
            "duty_roster_graph": {
                "role": "governance_surface",
                "title": title,
                "detail": detail,
                "cta": "执行治理动作" if primary_surface == "duty_roster_graph" else "查看编制准入",
            },
        }

    ui_bridge = _ui_bridge_summary()
    generated_at = datetime.now(timezone.utc).isoformat()
    latest_event_at = (
        rows[-1].get("created_at")
        or rows[-1].get("updated_at")
        or rows[-1].get("at")
        if rows
        else None
    )
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
        "surfaces": ["employee_space", "duty_roster_graph", "self_evolution_loop_runtime"],
        "identity_dependencies": ["participants", "roster_alignment", "ui_bridge"],
        "gate_dependencies": [
            "active_gates",
            "governance_gate",
            "roster_alignment.gate",
            "merge_decision",
            "evolution_metrics_summary",
        ],
        "truth_dependencies": ["source", "evidence", "governance_audit", "run_timelines"],
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
        "active_gates.items": bool(active_gates.get("items")) if isinstance(active_gates, dict) else False,
        "governance_audit.summary": bool(governance_audit_summary),
        "governance_gate.summary": bool(governance_gate_current.get("summary"))
        if isinstance(governance_gate_current, dict)
        else False,
        "roster_alignment.gate": bool(roster_alignment.get("gate"))
        if isinstance(roster_alignment, dict)
        else False,
        "ui_bridge.employee_space": bool(ui_bridge.get("employee_space"))
        if isinstance(ui_bridge, dict)
        else False,
        "ui_bridge.duty_roster_graph": bool(ui_bridge.get("duty_roster_graph"))
        if isinstance(ui_bridge, dict)
        else False,
        "ui_bridge.governance_action": bool(ui_bridge.get("governance_action"))
        if isinstance(ui_bridge, dict)
        else False,
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
            {
                str(item.get("surface"))
                for item in contract_surface_incidents
                if item.get("surface")
            }
        ),
        "actions": sorted(
            {
                str(item.get("action"))
                for item in contract_surface_incidents
                if item.get("action")
            }
        ),
        "by_severity": {
            severity: sum(
                1
                for item in contract_surface_incidents
                if item.get("severity") == severity
            )
            for severity in sorted(
                {
                    str(item.get("severity") or "unknown")
                    for item in contract_surface_incidents
                }
            )
        },
        "requires_admin_count": sum(
            1 for item in contract_surface_incidents if item.get("requires_admin")
        ),
        "executable_count": sum(
            1 for item in contract_surface_incidents if item.get("executable")
        ),
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
        else contract_primary_incident.get("detail")
        if isinstance(contract_primary_incident, dict)
        else "All runtime contract surfaces are ready."
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
        "executable_available": contract_surface_incident_summary.get("executable_available", False),
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
            "employee_id": ui_bridge.get("primary_employee_id")
            if isinstance(ui_bridge, dict)
            else None,
            "target_employee_ids": (
                ui_bridge.get("target_employee_ids")
                if isinstance(ui_bridge, dict)
                and isinstance(ui_bridge.get("target_employee_ids"), list)
                else []
            ),
            "label": (
                "Open governance surface"
                if contract_surface_incident_summary.get("primary_target_surface") == "duty_roster_graph"
                else "Open employee surface"
                if contract_surface_incident_summary.get("primary_target_surface") == "employee_space"
                else "Open full loop"
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
            "auto_merge_low_risk": _env_bool(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True
            ),
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
            "threshold": _env_int("MODSTORE_SELF_MAINTENANCE_THRESHOLD", 1),
            "cooldown_minutes": _env_int("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", 360),
        },
    }


__all__ = [
    "cron_trigger_for_self_maintenance",
    "evaluate_self_maintenance_need",
    "get_self_maintenance_runtime_status",
    "ledger_path",
    "loop_memory_path",
    "reconcile_stale_self_maintenance_runs",
    "run_self_maintenance_loop",
    "should_run_self_maintenance_loop",
]
