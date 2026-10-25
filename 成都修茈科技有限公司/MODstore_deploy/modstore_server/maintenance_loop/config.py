"""Shared time, environment and policy constants; no runtime orchestration."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger("modstore_server.self_maintenance_loop_runner")

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

DEFAULT_STATUS_FILE = "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_loop_status.py"

DEFAULT_AUTO_MERGE_GLOBS = [DEFAULT_STATUS_FILE]

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

_REVIEW_DIMENSION_KEYS = ("security", "business_logic", "performance")

_REVIEW_DIMENSION_STATUSES = frozenset({"pass", "fail", "n/a"})

_REVIEW_SEVERITIES = frozenset({"none", "low", "medium", "high", "critical"})

_REVIEW_RISK_CLASSES = frozenset({"low", "medium", "high"})

KB_SCHEMA_RETRY_MAX = 2

KB_SCHEMA_FAILED_LABEL = "kb-schema-failed"

KB_SCHEMA_FAILED_STATUS = "kb_schema_failed"

NEEDS_HUMAN_LABEL = "needs-human"

LOOP_EVICT_MAX_ITEMS = 100

LOOP_EVICT_STUCK_AGE_SECONDS = 24 * 3600

LOOP_EVICT_STUCK_RETRY_THRESHOLD = 3

LOOP_EVICT_AGE_OUT_SECONDS = 7 * 24 * 3600


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
