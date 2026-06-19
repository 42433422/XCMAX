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
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    repo = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    if repo:
        p = Path(repo).expanduser().resolve()
        if (p / "FHD").is_dir():
            return p
    try:
        from modstore_server.daily_digest import _repo_root as root_fn

        return Path(root_fn())
    except Exception:
        return Path(__file__).resolve().parents[3]


def _fhd_root() -> Path:
    candidates: List[Path] = []
    explicit = (
        os.environ.get("XCAGI_FHD_ROOT")
        or os.environ.get("MODSTORE_DAILY_FHD_ROOT")
        or ""
    ).strip()
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        candidates.append(Path(mono).expanduser().resolve() / "FHD")
    root = _repo_root()
    candidates.extend((root / "FHD", root.parent / "FHD"))
    for fhd in candidates:
        if fhd.is_dir():
            return fhd
    return candidates[0] if candidates else root / "FHD"


def _modstore_deploy_root() -> Path:
    root = _repo_root()
    deploy = root / "成都修茈科技有限公司" / "MODstore_deploy"
    if deploy.is_dir():
        return deploy
    local = root / "MODstore_deploy"
    return local if local.is_dir() else deploy


def _runtime_state_root() -> Optional[Path]:
    for key in ("MODSTORE_RUNTIME_STATE_ROOT", "MODSTORE_RUNTIME_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return None


def _pids_dir() -> Path:
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_PIDS_DIR") or "").strip()
    if raw:
        d = Path(raw).expanduser().resolve()
    else:
        root = _runtime_state_root()
        d = (root / "surface-audit-pids") if root is not None else (_repo_root() / ".xcmax-pids")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> Path:
    raw = (os.environ.get("MODSTORE_SURFACE_AUDIT_LOG_DIR") or "").strip()
    if raw:
        d = Path(raw).expanduser().resolve()
    else:
        root = _runtime_state_root()
        d = (root / "surface-audit-logs") if root is not None else (_repo_root() / ".xcmax-logs")
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


def _fhd_api_health_ok(url: str, *, timeout: float = 2.0) -> bool:
    """FHD /api/health 须 200 且 JSON 含 healthy/xcagi；避免 macOS AirPlay 占 :5000 误判。"""
    try:
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return False
            body = resp.read(1024).decode("utf-8", errors="replace").lower()
            return '"status"' in body and ("healthy" in body or "xcagi" in body)
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


def _wait_fhd_api_health(url: str, *, label: str, tries: int = 45) -> bool:
    for _ in range(max(1, tries)):
        if _fhd_api_health_ok(url):
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
    if _fhd_api_health_ok(health):
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
        "DATABASE_URL": "",
        "VECTOR_DB_URL": "",
        "REDIS_URL": "",
        "CACHE_REDIS_URL": "",
        "XCAGI_REDIS_URL": "",
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
        cmd += [
            "--desktop",
            "--headless",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--data-dir",
            data_dir,
        ]
    else:
        env["FASTAPI_PORT"] = str(api_port)

    out = _spawn("fhd-api", cmd, cwd=xcagi if run_py.parent == xcagi else fhd, env=env)
    out["ready"] = _wait_fhd_api_health(health, label="FHD API")
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
        [
            py,
            "-m",
            "uvicorn",
            "modstore_server.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
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
    except Exception:
        return default


def _ensure_android_emulator() -> Dict[str, Any]:
    """P-App adb 截图：无设备时尝试 ``start_android_emulator.sh``（需 MODSTORE_SURFACE_AUDIT_AUTO_START=1）。"""
    enabled = (os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if not enabled:
        return {"ok": True, "skipped": True, "reason": "android_disabled"}
    try:
        from modstore_server.daily_digest_surface_audit_android import (
            _adb_bin,
            _adb_has_device,
            _ensure_fhd_for_emulator,
            _try_start_emulator,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"android audit module: {exc}"}

    adb = _adb_bin()
    if _adb_has_device(adb):
        _ensure_fhd_for_emulator()
        return {"ok": True, "skipped": True, "device": True, "adb": adb}
    if not _auto_start_enabled():
        return {
            "ok": False,
            "error": "no adb device (bash FHD/scripts/dev/start_android_emulator.sh)",
            "adb": adb,
        }
    started = _try_start_emulator()
    if started:
        _ensure_fhd_for_emulator()
    return {"ok": started, "started": started, "adb": adb}


def ensure_surface_audit_deps() -> Dict[str, Any]:
    """截图前确保本地依赖就绪；返回各服务探活/拉起结果。"""
    out: Dict[str, Any] = {"ok": True, "services": {}}

    ps_enabled = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or ""
    ).strip().lower() not in (
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
        or "http://127.0.0.1:5102"
    ).rstrip("/")
    digest_base = (
        os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com"
    ).rstrip("/")
    internal_api = resolve_internal_api_base()

    api_port = _parse_port(api_url, 5102)
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

    out["services"]["android_emulator"] = _ensure_android_emulator()

    failures: List[str] = []
    for name, svc in out["services"].items():
        if not isinstance(svc, dict):
            continue
        if svc.get("error"):
            failures.append(f"{name}:{svc.get('error')}")
        elif name == "android_emulator":
            android_on = (
                os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or ""
            ).strip().lower() not in ("0", "false", "no", "off")
            if android_on and not (svc.get("skipped") or svc.get("ok")):
                failures.append(f"{name}:not_ready")
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


def surface_audit_stop_after_enabled() -> bool:
    """digest 结束后是否关闭 FHD/Vite/模拟器等临时进程（MODstore :8788 不关）。"""
    raw = os.environ.get("MODSTORE_SURFACE_AUDIT_STOP_AFTER")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() not in ("0", "false", "no", "off")
    if (os.environ.get("MODSTORE_LOCAL_AUTOMATION") or "").strip() in ("1", "true", "yes"):
        return True
    if (os.environ.get("MODSTORE_AUTOMATION_PRIMARY") or "").strip().lower() == "local_mac":
        return True
    return False


def _kill_pid_file(label: str, pid_file: Path) -> None:
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 0)
    except OSError:
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 15)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, 9)
        except OSError:
            pass
        logger.info("surface audit deps: stopped %s pid=%s", label, pid)
    except OSError as exc:
        logger.warning("surface audit deps: stop %s pid=%s failed: %s", label, pid, exc)
    pid_file.unlink(missing_ok=True)


def stop_surface_audit_ephemeral() -> Dict[str, Any]:
    """关闭 ``ensure_surface_audit_deps`` 拉起的临时服务（不含 MODstore 日更栈）。"""
    stopped: List[str] = []
    pids_dir = _pids_dir()
    if pids_dir.is_dir():
        for pid_file in sorted(pids_dir.glob("surface-audit-*.pid")):
            _kill_pid_file(pid_file.stem, pid_file)
            stopped.append(pid_file.stem)

    emu_pid_raw = (os.environ.get("XCAGI_ANDROID_EMULATOR_PID_FILE") or "").strip()
    emu_pid = Path(emu_pid_raw).expanduser().resolve() if emu_pid_raw else (_fhd_root() / "data" / "surface_audit" / ".android-emulator.pid")
    if emu_pid.is_file():
        _kill_pid_file("android-emulator", emu_pid)
        stopped.append("android-emulator")

    return {"ok": True, "stopped": stopped}
