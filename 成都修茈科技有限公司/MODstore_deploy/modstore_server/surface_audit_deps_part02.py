# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.surface_audit_deps")


def ensure_surface_audit_deps() -> _facade().Dict[str, _facade().Any]:
    """截图前确保本地依赖就绪；返回各服务探活/拉起结果。"""
    out: _facade().Dict[str, _facade().Any] = {"ok": True, "services": {}}
    ps_enabled = (
        _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or ""
    ).strip().lower() not in ("0", "false", "no", "off")
    ps_base = (
        _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PS_BASE_URL")
        or _facade().os.environ.get("SURFACE_AUDIT_BASE_URL")
        or "http://127.0.0.1:5001"
    ).rstrip("/")
    api_url = (
        _facade().os.environ.get("SURFACE_AUDIT_API_URL")
        or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
        or "http://127.0.0.1:5102"
    ).rstrip("/")
    digest_base = (
        _facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com"
    ).rstrip("/")
    internal_api = _facade().resolve_internal_api_base()
    api_port = _facade()._parse_port(api_url, 5102)
    web_port = _facade()._parse_port(ps_base, 5001)
    modstore_port = _facade()._parse_port(internal_api, 8788)
    out["services"]["playwright"] = _facade()._ensure_playwright()
    if ps_enabled and _facade()._is_local_url(ps_base):
        out["services"]["fhd_api"] = _facade()._ensure_fhd_api(api_port)
        out["services"]["vite_ps"] = _facade()._ensure_vite(web_port, api_port)
    if _facade()._is_local_url(digest_base):
        mkt_port = _facade()._parse_port(
            _facade().os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:5176",
            5176,
        )
        out["services"]["marketing"] = _facade()._ensure_marketing_static(mkt_port)
    if _facade()._is_local_url(internal_api):
        out["services"]["modstore_api"] = _facade()._ensure_modstore_api(modstore_port)
    out["services"]["android_emulator"] = _facade()._ensure_android_emulator()
    failures: _facade().List[str] = []
    for name, svc in out["services"].items():
        if not isinstance(svc, dict):
            continue
        if svc.get("error"):
            failures.append(f"{name}:{svc.get('error')}")
        elif name == "android_emulator":
            android_on = (
                _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or ""
            ).strip().lower() not in ("0", "false", "no", "off")
            if android_on and (not (svc.get("skipped") or svc.get("ok"))):
                failures.append(f"{name}:not_ready")
        elif name in ("fhd_api", "vite_ps", "modstore_api", "marketing") and (
            not (svc.get("skipped") or svc.get("ready"))
        ):
            failures.append(f"{name}:not_ready")
    out["ok"] = not failures
    if failures:
        out["failures"] = failures
        _facade().logger.warning("surface audit deps incomplete: %s", failures)
    else:
        _facade().logger.info("surface audit deps ready")
    return out


def surface_audit_stop_after_enabled() -> bool:
    """digest 结束后是否关闭 FHD/Vite/模拟器等临时进程（MODstore :8788 不关）。"""
    raw = _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_STOP_AFTER")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() not in ("0", "false", "no", "off")
    if (_facade().os.environ.get("MODSTORE_LOCAL_AUTOMATION") or "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return True
    if (
        _facade().os.environ.get("MODSTORE_AUTOMATION_PRIMARY") or ""
    ).strip().lower() == "local_mac":
        return True
    return False


def _kill_pid_file(label: str, pid_file: _facade().Path) -> None:
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return
    try:
        _facade().os.kill(pid, 0)
    except OSError:
        pid_file.unlink(missing_ok=True)
        return
    try:
        _facade().os.kill(pid, 15)
        _facade().time.sleep(0.5)
        try:
            _facade().os.kill(pid, 0)
            _facade().os.kill(pid, 9)
        except OSError:
            pass
        _facade().logger.info("surface audit deps: stopped %s pid=%s", label, pid)
    except OSError as exc:
        _facade().logger.warning("surface audit deps: stop %s pid=%s failed: %s", label, pid, exc)
    pid_file.unlink(missing_ok=True)


def stop_surface_audit_ephemeral() -> _facade().Dict[str, _facade().Any]:
    """关闭 ``ensure_surface_audit_deps`` 拉起的临时服务（不含 MODstore 日更栈）。"""
    stopped: _facade().List[str] = []
    pids_dir = _facade()._pids_dir()
    if pids_dir.is_dir():
        for pid_file in sorted(pids_dir.glob("surface-audit-*.pid")):
            _facade()._kill_pid_file(pid_file.stem, pid_file)
            stopped.append(pid_file.stem)
    emu_pid_raw = (_facade().os.environ.get("XCAGI_ANDROID_EMULATOR_PID_FILE") or "").strip()
    emu_pid = (
        _facade().Path(emu_pid_raw).expanduser().resolve()
        if emu_pid_raw
        else _facade()._fhd_root() / "data" / "surface_audit" / ".android-emulator.pid"
    )
    if emu_pid.is_file():
        _facade()._kill_pid_file("android-emulator", emu_pid)
        stopped.append("android-emulator")
    return {"ok": True, "stopped": stopped}
