"""三端截图巡检依赖：截图前自动检测并拉起本地服务。

默认在 ``build_surface_audit_html_sync`` / ``run_surface_audit_async`` 入口调用。
可通过 ``MODSTORE_SURFACE_AUDIT_AUTO_START=0`` 关闭自动拉起（仅探活、记日志）。

本地依赖（按 lane）：
- P-S：FHD API（默认 :5000）+ Vite 企业端（默认 :5001）
- P-W/P-App（base 为 localhost 时）：本地营销/market 静态服（默认 :5176）
- 目录/登录：MODstore 内部 API（``MODSTORE_INTERNAL_API_BASE``，默认 :8788）
- Playwright Chromium（``playwright install chromium``）
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _auto_start_enabled() -> bool:
    return (os.environ.get("MODSTORE_SURFACE_AUDIT_AUTO_START", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _repo_root() -> Path:
    try:
        from modstore_server.daily_digest import _repo_root as root_fn

        return Path(root_fn())
    except Exception:
        mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
        if mono:
            return Path(mono).expanduser().resolve()
        return Path(__file__).resolve().parents[3]


def _fhd_root() -> Path:
    root = _repo_root()
    fhd = root / "FHD"
    if fhd.is_dir():
        return fhd
    alt = root.parent / "FHD"
    return alt if alt.is_dir() else fhd


def _modstore_deploy_root() -> Path:
    root = _repo_root()
    deploy = root / "成都修茈科技有限公司" / "MODstore_deploy"
    if deploy.is_dir():
        return deploy
    local = root / "MODstore_deploy"
    return local if local.is_dir() else deploy


def _pids_dir() -> Path:
    d = _repo_root() / ".xcmax-pids"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> Path:
    d = _repo_root() / ".xcmax-logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _python_bin() -> str:
    fhd = _fhd_root()
    for cand in (fhd / ".venv" / "bin" / "python", fhd / "XCAGI" / ".venv" / "bin" / "python"):
        if cand.is_file():
            return str(cand)
    return shutil.which("python3") or "python3"


def _http_ok(url: str, *, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200) < 500
    except Exception:
        return False


def _wait_http(url: str, *, label: str, tries: int = 45) -> bool:
    for _ in range(max(1, tries)):
        if _http_ok(url):
            logger.info("surface audit deps: %s ready %s", label, url)
            return True
        time.sleep(1)
    logger.warning("surface audit deps: %s not ready after %ds (%s)", label, tries, url)
    return False


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _spawn(
    name: str,
    cmd: List[str],
    *,
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    pid_file = _pids_dir() / f"surface-audit-{name}.pid"
    if pid_file.is_file():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            return {"ok": True, "skipped": True, "reason": "already_running", "pid": old_pid}
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    log_path = _logs_dir() / f"surface-audit-{name}.log"
    merged = {**os.environ, **(env or {})}
    with open(log_path, "a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=merged,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    logger.info("surface audit deps: started %s pid=%s cmd=%s", name, proc.pid, " ".join(cmd[:4]))
    return {"ok": True, "started": True, "pid": proc.pid, "log": str(log_path)}


def _ensure_fhd_api(api_port: int) -> Dict[str, Any]:
    health = f"http://127.0.0.1:{api_port}/api/health"
    if _http_ok(health):
        return {"ok": True, "skipped": True, "url": health}
    if not _auto_start_enabled():
        return {"ok": False, "skipped": True, "reason": "auto_start_disabled", "url": health}

    fhd = _fhd_root()
    xcagi = fhd / "XCAGI"
    py = _python_bin()
    data_dir = os.environ.get(
        "XCAGI_DATA_DIR",
        str(xcagi / "data" / "desktop-dev"),
    )
    env = {
        "XCAGI_DESKTOP_MODE": "1",
        "XCAGI_MOD_ISOLATED_DATABASES": "0",
        "XCAGI_DESKTOP_FORCE_LOCAL_DATABASE": "1",
        "XCAGI_USE_LOCAL_MARKET": "1",
        "XCAGI_GLOBAL_RATE_LIMIT": "0",
        "XCAGI_AUTH_RATE_LIMIT": "0",
    }
    market_base = (
        os.environ.get("MODSTORE_INTERNAL_API_BASE")
        or os.environ.get("XCAGI_MARKET_BASE_URL")
        or "http://127.0.0.1:8788"
    )
    env["XCAGI_MARKET_BASE_URL"] = market_base.rstrip("/")
    env["MODSTORE_LOCAL_BASE_URL"] = market_base.rstrip("/")
    run_py = xcagi / "run_fastapi.py"
    if not run_py.is_file():
        run_py = fhd / "run.py"
    if not run_py.is_file():
        return {"ok": False, "error": f"FHD entry not found under {fhd}"}

    cmd = [
        py,
        str(run_py),
    ]
    if run_py.name == "run_fastapi.py":
        cmd += ["--desktop", "--headless", "--host", "127.0.0.1", "--port", str(api_port), "--data-dir", data_dir]
    else:
        env["FASTAPI_PORT"] = str(api_port)

    out = _spawn("fhd-api", cmd, cwd=xcagi if run_py.parent == xcagi else fhd, env=env)
    out["ready"] = _wait_http(health, label="FHD API")
    out["url"] = health
    return out


def _ensure_vite(web_port: int, api_port: int) -> Dict[str, Any]:
    url = f"http://127.0.0.1:{web_port}/"
    if _http_ok(url):
        return {"ok": True, "skipped": True, "url": url}
    if not _auto_start_enabled():
        return {"ok": False, "skipped": True, "reason": "auto_start_disabled", "url": url}

    frontend = _fhd_root() / "frontend"
    if not (frontend / "package.json").is_file():
        return {"ok": False, "error": f"frontend missing: {frontend}"}
    npm = shutil.which("npm") or "npm"
    env = {
        "VITE_XCAGI_PRODUCT_SKU": os.environ.get("SURFACE_AUDIT_PRODUCT_SKU", "enterprise"),
        "VITE_API_BASE": f"http://127.0.0.1:{api_port}",
    }
    out = _spawn(
        "vite-ps",
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port)],
        cwd=frontend,
        env=env,
    )
    out["ready"] = _wait_http(url, label="Vite P-S")
    out["url"] = url
    return out


def _ensure_modstore_api(port: int) -> Dict[str, Any]:
    health = f"http://127.0.0.1:{port}/api/health"
    if _http_ok(health):
        return {"ok": True, "skipped": True, "url": health}
    if not _auto_start_enabled():
        return {"ok": False, "skipped": True, "reason": "auto_start_disabled", "url": health}

    deploy = _modstore_deploy_root()
    py = _python_bin()
    out = _spawn(
        "modstore",
        [py, "-m", "uvicorn", "modstore_server.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=deploy,
    )
    out["ready"] = _wait_http(health, label="MODstore API")
    out["url"] = health
    return out


def _ensure_marketing_static(port: int) -> Dict[str, Any]:
    url = f"http://127.0.0.1:{port}/"
    if _http_ok(url):
        return {"ok": True, "skipped": True, "url": url}
    if not _auto_start_enabled():
        return {"ok": False, "skipped": True, "reason": "auto_start_disabled", "url": url}

    root = _repo_root()
    marketing = root / "成都修茈科技有限公司"
    if not marketing.is_dir():
        marketing = root
    py = _python_bin()
    serve = _fhd_root() / "scripts" / "serve_static_cached.py"
    if not serve.is_file():
        return {"ok": False, "error": f"serve_static_cached.py missing: {serve}"}
    out = _spawn(
        "marketing",
        [py, str(serve), "--port", str(port), "--directory", str(marketing)],
        cwd=_fhd_root(),
    )
    out["ready"] = _wait_http(url, label="marketing static")
    out["url"] = url
    return out


def _ensure_playwright() -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return {
            "ok": False,
            "error": "playwright not installed (pip install playwright)",
        }
    if not _auto_start_enabled():
        return {"ok": True, "skipped": True, "reason": "auto_start_disabled"}
    py = _python_bin()
    try:
        subprocess.run(
            [py, "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            timeout=300,
        )
        return {"ok": True, "installed": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("surface audit deps: playwright install failed: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}


def _parse_port(url: str, default: int) -> int:
    try:
        p = urlparse(url).port
        return int(p) if p else default
    except Exception:
        return default


def ensure_surface_audit_deps() -> Dict[str, Any]:
    """截图前确保本地依赖就绪；返回各服务探活/拉起结果。"""
    out: Dict[str, Any] = {"ok": True, "services": {}}

    ps_enabled = (os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    ps_base = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_PS_BASE_URL")
        or os.environ.get("SURFACE_AUDIT_BASE_URL")
        or "http://127.0.0.1:5001"
    ).rstrip("/")
    api_url = (
        os.environ.get("SURFACE_AUDIT_API_URL")
        or os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
        or "http://127.0.0.1:5000"
    ).rstrip("/")
    digest_base = (
        os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com"
    ).rstrip("/")
    internal_api = (
        os.environ.get("MODSTORE_INTERNAL_API_BASE") or "http://127.0.0.1:8788"
    ).rstrip("/")

    api_port = _parse_port(api_url, 5000)
    web_port = _parse_port(ps_base, 5001)
    modstore_port = _parse_port(internal_api, 8788)

    out["services"]["playwright"] = _ensure_playwright()

    if ps_enabled and _is_local_url(ps_base):
        out["services"]["fhd_api"] = _ensure_fhd_api(api_port)
        out["services"]["vite_ps"] = _ensure_vite(web_port, api_port)

    if _is_local_url(digest_base):
        mkt_port = _parse_port(
            os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:5176",
            5176,
        )
        out["services"]["marketing"] = _ensure_marketing_static(mkt_port)

    if _is_local_url(internal_api):
        out["services"]["modstore_api"] = _ensure_modstore_api(modstore_port)

    failures: List[str] = []
    for name, svc in out["services"].items():
        if not isinstance(svc, dict):
            continue
        if svc.get("error"):
            failures.append(f"{name}:{svc.get('error')}")
        elif name in ("fhd_api", "vite_ps", "modstore_api", "marketing") and not (
            svc.get("skipped") or svc.get("ready")
        ):
            failures.append(f"{name}:not_ready")

    out["ok"] = not failures
    if failures:
        out["failures"] = failures
        logger.warning("surface audit deps incomplete: %s", failures)
    else:
        logger.info("surface audit deps ready")
    return out
