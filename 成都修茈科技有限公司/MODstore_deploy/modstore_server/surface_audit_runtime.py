"""Resolve audit paths and probe service health without starting any process."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from modstore_server.infrastructure.private_asset_storage import require_private_directory
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.surface_audit_paths import fhd_root as _fhd_root
from modstore_server.surface_audit_paths import runtime_state_root as _runtime_state_root

logger = logging.getLogger(__name__)


def _runtime_directory(override_env: str, name: str) -> Path:
    raw = os.environ.get(override_env, "").strip()
    root = _runtime_state_root() or Path(tempfile.gettempdir()) / "modstore_runtime"
    directory = require_private_directory(Path(raw) if raw else root / name)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    return directory


def _pids_dir() -> Path:
    return _runtime_directory("MODSTORE_SURFACE_AUDIT_PIDS_DIR", "surface-audit-pids")


def _logs_dir() -> Path:
    return _runtime_directory("MODSTORE_SURFACE_AUDIT_LOG_DIR", "surface-audit-logs")


def _python_bin() -> str:
    fhd = _fhd_root()
    for cand in (
        fhd / ".venv" / "bin" / "python",
        fhd / "XCAGI" / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            return str(cand)
    return shutil.which("python3") or "python3"


def _http_ok(url: str, *, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200) < 500
    except RECOVERABLE_ERRORS:
        return False


def _fhd_api_health_ok(url: str, *, timeout: float = 2.0) -> bool:
    """FHD /api/health 须 200 且 JSON 含 healthy/xcagi；避免 macOS AirPlay 占 :5000 误判。"""
    try:
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return False
            body = resp.read(1024).decode("utf-8", errors="replace").lower()
            return '"status"' in body and ("healthy" in body or "xcagi" in body)
    except RECOVERABLE_ERRORS:
        return False


def resolve_internal_api_base() -> str:
    """MODstore 内部 API 根：显式 env → DEPLOY_HEALTH_URL 去后缀 → 默认 :8788。"""
    explicit = (os.environ.get("MODSTORE_INTERNAL_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    health = (os.environ.get("MODSTORE_DEPLOY_HEALTH_URL") or "").strip().rstrip("/")
    if health:
        for suffix in ("/api/health", "/health"):
            if health.endswith(suffix):
                return health[: -len(suffix)] or health
        return health
    return "http://127.0.0.1:8788"


def _parse_port(url: str, default: int) -> int:
    try:
        p = urlparse(url).port
        return int(p) if p else default
    except RECOVERABLE_ERRORS:
        return default


def surface_audit_stop_after_enabled() -> bool:
    """digest 结束后是否关闭 FHD/Vite/模拟器等临时进程（MODstore :8788 不关）。"""
    raw = os.environ.get("MODSTORE_SURFACE_AUDIT_STOP_AFTER")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() not in ("0", "false", "no", "off")
    if (os.environ.get("MODSTORE_LOCAL_AUTOMATION") or "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return True
    if (os.environ.get("MODSTORE_AUTOMATION_PRIMARY") or "").strip().lower() == "local_mac":
        return True
    return False
