# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.surface_audit_deps")


def _pids_dir() -> _facade().Path:
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PIDS_DIR") or "").strip()
    if raw:
        d = _facade().Path(raw).expanduser().resolve()
    else:
        root = _facade()._runtime_state_root()
        d = (
            root / "surface-audit-pids"
            if root is not None
            else _facade()._repo_root() / ".xcmax-pids"
        )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> _facade().Path:
    raw = (_facade().os.environ.get("MODSTORE_SURFACE_AUDIT_LOG_DIR") or "").strip()
    if raw:
        d = _facade().Path(raw).expanduser().resolve()
    else:
        root = _facade()._runtime_state_root()
        d = (
            root / "surface-audit-logs"
            if root is not None
            else _facade()._repo_root() / ".xcmax-logs"
        )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _python_bin() -> str:
    fhd = _facade()._fhd_root()
    for cand in (
        fhd / ".venv" / "bin" / "python",
        fhd / "XCAGI" / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            return str(cand)
    return _facade().shutil.which("python3") or "python3"


def _http_ok(url: str, *, timeout: float = 2.0) -> bool:
    try:
        req = _facade().urllib.request.Request(url, method="GET")
        with _facade().urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200) < 500
    except _facade().RECOVERABLE_ERRORS:
        return False


def _fhd_api_health_ok(url: str, *, timeout: float = 2.0) -> bool:
    """FHD /api/health 须 200 且 JSON 含 healthy/xcagi；避免 macOS AirPlay 占 :5000 误判。"""
    try:
        req = _facade().urllib.request.Request(
            url, method="GET", headers={"Accept": "application/json"}
        )
        with _facade().urllib.request.urlopen(req, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return False
            body = resp.read(1024).decode("utf-8", errors="replace").lower()
            return '"status"' in body and ("healthy" in body or "xcagi" in body)
    except _facade().RECOVERABLE_ERRORS:
        return False


def _wait_http(url: str, *, label: str, tries: int = 45) -> bool:
    for _ in range(max(1, tries)):
        if _facade()._http_ok(url):
            _facade().logger.info("surface audit deps: %s ready %s", label, url)
            return True
        _facade().time.sleep(1)
    _facade().logger.warning("surface audit deps: %s not ready after %ds (%s)", label, tries, url)
    return False


def _wait_fhd_api_health(url: str, *, label: str, tries: int = 45) -> bool:
    for _ in range(max(1, tries)):
        if _facade()._fhd_api_health_ok(url):
            _facade().logger.info("surface audit deps: %s ready %s", label, url)
            return True
        _facade().time.sleep(1)
    _facade().logger.warning("surface audit deps: %s not ready after %ds (%s)", label, tries, url)
    return False


def _spawn(
    name: str,
    cmd: _facade().List[str],
    *,
    cwd: _facade().Path,
    env: _facade().Optional[_facade().Dict[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    pid_file = _facade()._pids_dir() / f"surface-audit-{name}.pid"
    if pid_file.is_file():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
            _facade().os.kill(old_pid, 0)
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_running",
                "pid": old_pid,
            }
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)
    log_path = _facade()._logs_dir() / f"surface-audit-{name}.log"
    merged = {**_facade().os.environ, **(env or {})}
    with open(log_path, "a", encoding="utf-8") as logf:
        proc = _facade().subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=merged,
            stdout=logf,
            stderr=_facade().subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    _facade().logger.info(
        "surface audit deps: started %s pid=%s cmd=%s",
        name,
        proc.pid,
        " ".join(cmd[:4]),
    )
    return {"ok": True, "started": True, "pid": proc.pid, "log": str(log_path)}


def _ensure_fhd_api(api_port: int) -> _facade().Dict[str, _facade().Any]:
    health = f"http://127.0.0.1:{api_port}/api/health"
    if _facade()._fhd_api_health_ok(health):
        return {"ok": True, "skipped": True, "url": health}
    if not _facade()._auto_start_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "auto_start_disabled",
            "url": health,
        }
    fhd = _facade()._fhd_root()
    xcagi = fhd / "XCAGI"
    py = _facade()._python_bin()
    data_dir = _facade().os.environ.get("XCAGI_DATA_DIR", str(xcagi / "data" / "desktop-dev"))
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
        _facade().os.environ.get("MODSTORE_INTERNAL_API_BASE")
        or _facade().os.environ.get("XCAGI_MARKET_BASE_URL")
        or "http://127.0.0.1:8788"
    )
    env["XCAGI_MARKET_BASE_URL"] = market_base.rstrip("/")
    env["MODSTORE_LOCAL_BASE_URL"] = market_base.rstrip("/")
    run_py = xcagi / "run_fastapi.py"
    if not run_py.is_file():
        run_py = fhd / "run.py"
    if not run_py.is_file():
        return {"ok": False, "error": f"FHD entry not found under {fhd}"}
    cmd = [py, str(run_py)]
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
    out = _facade()._spawn("fhd-api", cmd, cwd=xcagi if run_py.parent == xcagi else fhd, env=env)
    out["ready"] = _facade()._wait_fhd_api_health(health, label="FHD API")
    out["url"] = health
    return out


def _ensure_vite(web_port: int, api_port: int) -> _facade().Dict[str, _facade().Any]:
    url = f"http://127.0.0.1:{web_port}/"
    if _facade()._http_ok(url):
        return {"ok": True, "skipped": True, "url": url}
    if not _facade()._auto_start_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "auto_start_disabled",
            "url": url,
        }
    frontend = _facade()._fhd_root() / "frontend"
    if not (frontend / "package.json").is_file():
        return {"ok": False, "error": f"frontend missing: {frontend}"}
    npm = _facade().shutil.which("npm") or "npm"
    env = {
        "VITE_XCAGI_PRODUCT_SKU": _facade().os.environ.get(
            "SURFACE_AUDIT_PRODUCT_SKU", "enterprise"
        ),
        "VITE_API_BASE": f"http://127.0.0.1:{api_port}",
    }
    out = _facade()._spawn(
        "vite-ps",
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port)],
        cwd=frontend,
        env=env,
    )
    out["ready"] = _facade()._wait_http(url, label="Vite P-S")
    out["url"] = url
    return out


def _ensure_modstore_api(port: int) -> _facade().Dict[str, _facade().Any]:
    health = f"http://127.0.0.1:{port}/api/health"
    if _facade()._http_ok(health):
        return {"ok": True, "skipped": True, "url": health}
    if not _facade()._auto_start_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "auto_start_disabled",
            "url": health,
        }
    deploy = _facade()._modstore_deploy_root()
    py = _facade()._python_bin()
    out = _facade()._spawn(
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
    out["ready"] = _facade()._wait_http(health, label="MODstore API")
    out["url"] = health
    return out


def _ensure_marketing_static(port: int) -> _facade().Dict[str, _facade().Any]:
    url = f"http://127.0.0.1:{port}/"
    if _facade()._http_ok(url):
        return {"ok": True, "skipped": True, "url": url}
    if not _facade()._auto_start_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "auto_start_disabled",
            "url": url,
        }
    root = _facade()._repo_root()
    marketing = root / "成都修茈科技有限公司"
    if not marketing.is_dir():
        marketing = root
    py = _facade()._python_bin()
    serve = _facade()._fhd_root() / "scripts" / "serve_static_cached.py"
    if not serve.is_file():
        return {"ok": False, "error": f"serve_static_cached.py missing: {serve}"}
    out = _facade()._spawn(
        "marketing",
        [py, str(serve), "--port", str(port), "--directory", str(marketing)],
        cwd=_facade()._fhd_root(),
    )
    out["ready"] = _facade()._wait_http(url, label="marketing static")
    out["url"] = url
    return out


def _ensure_playwright() -> _facade().Dict[str, _facade().Any]:
    try:
        from playwright.async_api import async_playwright

        _ = async_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "playwright not installed (pip install playwright)",
        }
    if not _facade()._auto_start_enabled():
        return {"ok": True, "skipped": True, "reason": "auto_start_disabled"}
    py = _facade()._python_bin()
    try:
        _facade().subprocess.run(
            [py, "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            timeout=300,
        )
        return {"ok": True, "installed": True}
    except _facade().BOUNDARY_ERRORS as exc:
        _facade().logger.warning("surface audit deps: playwright install failed: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}


def resolve_internal_api_base() -> str:
    """MODstore 内部 API 根：显式 env → DEPLOY_HEALTH_URL 去后缀 → 默认 :8788。"""
    explicit = (_facade().os.environ.get("MODSTORE_INTERNAL_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    health = (_facade().os.environ.get("MODSTORE_DEPLOY_HEALTH_URL") or "").strip().rstrip("/")
    if health:
        for suffix in ("/api/health", "/health"):
            if health.endswith(suffix):
                return health[: -len(suffix)] or health
        return health
    return "http://127.0.0.1:8788"


def _parse_port(url: str, default: int) -> int:
    try:
        p = _facade().urlparse(url).port
        return int(p) if p else default
    except _facade().RECOVERABLE_ERRORS:
        return default


def _ensure_android_emulator() -> _facade().Dict[str, _facade().Any]:
    """P-App adb 截图：无设备时尝试 ``start_android_emulator.sh``（需 MODSTORE_SURFACE_AUDIT_AUTO_START=1）。"""
    enabled = (
        _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or ""
    ).strip().lower() not in ("0", "false", "no", "off")
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
    if not _facade()._auto_start_enabled():
        return {
            "ok": False,
            "error": "no adb device (bash FHD/scripts/dev/start_android_emulator.sh)",
            "adb": adb,
        }
    started = _try_start_emulator()
    if started:
        _ensure_fhd_for_emulator()
    return {"ok": started, "started": started, "adb": adb}
