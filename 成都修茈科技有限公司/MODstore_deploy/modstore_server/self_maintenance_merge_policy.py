"""Shared, lightweight policy primitives for self-maintenance merges."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

DEFAULT_SCOPE_GLOBS = [
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_*.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/duty_workforce_learning.py",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_evolution_metrics_job.py",
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
    "成都修茈科技有限公司/MODstore_deploy/tests/test_duty_workforce_learning.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_self_evolution_metrics_job.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_self_evolution_knowledge*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_policy*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_ops_staged_auto_approve*.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_digest_vibe_prep.py",
    "成都修茈科技有限公司/MODstore_deploy/tests/test_project_context*.py",
]
DEFAULT_ABSOLUTE_FORBIDDEN_GLOBS = [
    "*.env",
    "*.env.*",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*secret*",
    "**/*credential*",
    "**/*token*",
]
DEFAULT_FORBIDDEN_GLOBS = [
    *DEFAULT_ABSOLUTE_FORBIDDEN_GLOBS,
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


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return list(default)
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    return values or list(default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def absolute_forbidden_globs() -> list[str]:
    return _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_ABSOLUTE_FORBIDDEN_GLOBS",
        DEFAULT_ABSOLUTE_FORBIDDEN_GLOBS,
    )


def forbidden_globs() -> list[str]:
    return _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS",
        DEFAULT_FORBIDDEN_GLOBS,
    )


def max_files() -> int:
    return _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_FILES", 12)


def max_lines() -> int:
    return _env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_LINES", 600)


def scope_globs() -> list[str]:
    return _env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS",
        DEFAULT_SCOPE_GLOBS,
    )


def normalize_repo_path(file_name: Any) -> str:
    return str(file_name or "").replace("\\", "/").strip().strip('"').strip("'")


def file_matches_any_glob(file_name: Any, globs: list[str]) -> bool:
    normalized = normalize_repo_path(file_name)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in globs)


__all__ = [
    "DEFAULT_ABSOLUTE_FORBIDDEN_GLOBS",
    "DEFAULT_FORBIDDEN_GLOBS",
    "DEFAULT_SCOPE_GLOBS",
    "absolute_forbidden_globs",
    "file_matches_any_glob",
    "forbidden_globs",
    "max_files",
    "max_lines",
    "normalize_repo_path",
    "scope_globs",
]
