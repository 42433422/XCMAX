"""Prepare desktop, market and browser services through explicit runtime ports."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Protocol

from modstore_server.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)
ServiceResult = dict[str, Any]


class ProcessStarter(Protocol):
    def __call__(
        self, name: str, cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
    ) -> ServiceResult: ...


class HealthWaiter(Protocol):
    def __call__(self, url: str, *, label: str, tries: int = 45) -> bool: ...


def wait_for_health(
    url: str, *, label: str, probe: Callable[[str], bool], tries: int = 45
) -> bool:
    for _ in range(max(1, tries)):
        if probe(url):
            logger.info("surface audit deps: %s ready %s", label, url)
            return True
        time.sleep(1)
    logger.warning("surface audit deps: %s not ready after %ds (%s)", label, tries, url)
    return False


@dataclass(frozen=True)
class SurfaceServices:
    fhd_root: Callable[[], Path]
    deploy_root: Callable[[], Path]
    repo_root: Callable[[], Path]
    python_bin: Callable[[], str]
    auto_start_enabled: Callable[[], bool]
    http_ok: Callable[[str], bool]
    fhd_health_ok: Callable[[str], bool]
    spawn: ProcessStarter
    wait_http: HealthWaiter
    wait_fhd_health: HealthWaiter

    def fhd_api(self, api_port: int) -> Dict[str, Any]:
        health = f"http://127.0.0.1:{api_port}/api/health"
        if self.fhd_health_ok(health):
            return {"ok": True, "skipped": True, "url": health}
        if not self.auto_start_enabled():
            return {
                "ok": False,
                "skipped": True,
                "reason": "auto_start_disabled",
                "url": health,
            }
        fhd = self.fhd_root()
        xcagi = fhd / "XCAGI"
        py = self.python_bin()
        data_dir = os.environ.get("XCAGI_DATA_DIR", str(xcagi / "data" / "desktop-dev"))
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
        out = self.spawn(
            "fhd-api", cmd, cwd=xcagi if run_py.parent == xcagi else fhd, env=env
        )
        out["ready"] = self.wait_fhd_health(health, label="FHD API")
        out["url"] = health
        return out

    def vite(self, web_port: int, api_port: int) -> Dict[str, Any]:
        url = f"http://127.0.0.1:{web_port}/"
        if self.http_ok(url):
            return {"ok": True, "skipped": True, "url": url}
        if not self.auto_start_enabled():
            return {
                "ok": False,
                "skipped": True,
                "reason": "auto_start_disabled",
                "url": url,
            }
        frontend = self.fhd_root() / "frontend"
        if not (frontend / "package.json").is_file():
            return {"ok": False, "error": f"frontend missing: {frontend}"}
        npm = shutil.which("npm") or "npm"
        env = {
            "VITE_XCAGI_PRODUCT_SKU": os.environ.get(
                "SURFACE_AUDIT_PRODUCT_SKU", "enterprise"
            ),
            "VITE_API_BASE": f"http://127.0.0.1:{api_port}",
        }
        out = self.spawn(
            "vite-ps",
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port)],
            cwd=frontend,
            env=env,
        )
        out["ready"] = self.wait_http(url, label="Vite P-S")
        out["url"] = url
        return out

    def modstore_api(self, port: int) -> Dict[str, Any]:
        health = f"http://127.0.0.1:{port}/api/health"
        if self.http_ok(health):
            return {"ok": True, "skipped": True, "url": health}
        if not self.auto_start_enabled():
            return {
                "ok": False,
                "skipped": True,
                "reason": "auto_start_disabled",
                "url": health,
            }
        deploy = self.deploy_root()
        py = self.python_bin()
        out = self.spawn(
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
        out["ready"] = self.wait_http(health, label="MODstore API")
        out["url"] = health
        return out

    def marketing_static(self, port: int) -> Dict[str, Any]:
        url = f"http://127.0.0.1:{port}/"
        if self.http_ok(url):
            return {"ok": True, "skipped": True, "url": url}
        if not self.auto_start_enabled():
            return {
                "ok": False,
                "skipped": True,
                "reason": "auto_start_disabled",
                "url": url,
            }
        root = self.repo_root()
        marketing = root / "成都修茈科技有限公司"
        if not marketing.is_dir():
            marketing = root
        py = self.python_bin()
        serve = self.fhd_root() / "scripts" / "serve_static_cached.py"
        if not serve.is_file():
            return {"ok": False, "error": f"serve_static_cached.py missing: {serve}"}
        out = self.spawn(
            "marketing",
            [py, str(serve), "--port", str(port), "--directory", str(marketing)],
            cwd=self.fhd_root(),
        )
        out["ready"] = self.wait_http(url, label="marketing static")
        out["url"] = url
        return out

    def playwright(self) -> Dict[str, Any]:
        try:
            from playwright.async_api import async_playwright

            _ = async_playwright
        except ImportError:
            return {
                "ok": False,
                "error": "playwright not installed (pip install playwright)",
            }
        if not self.auto_start_enabled():
            return {"ok": True, "skipped": True, "reason": "auto_start_disabled"}
        py = self.python_bin()
        try:
            result = subprocess.run(
                [py, "-m", "playwright", "install", "chromium"],
                check=False,
                capture_output=True,
                timeout=300,
            )
            if result.returncode != 0:
                stderr = result.stderr
                detail = (
                    stderr.decode("utf-8", errors="replace")
                    if isinstance(stderr, bytes)
                    else str(stderr or "")
                )
                return {
                    "ok": False,
                    "error": f"playwright install failed ({result.returncode}): {detail[:300]}",
                }
            return {"ok": True, "installed": True}
        except BOUNDARY_ERRORS as exc:
            logger.warning("surface audit deps: playwright install failed: %s", exc)
            return {"ok": False, "error": str(exc)[:300]}

    def android_emulator(self) -> Dict[str, Any]:
        """P-App adb 截图：无设备时尝试 ``start_android_emulator.sh``（需 MODSTORE_SURFACE_AUDIT_AUTO_START=1）。"""
        enabled = (
            os.environ.get("MODSTORE_SURFACE_AUDIT_ANDROID", "1") or ""
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
        if not self.auto_start_enabled():
            return {
                "ok": False,
                "error": "no adb device (bash FHD/scripts/dev/start_android_emulator.sh)",
                "adb": adb,
            }
        started = _try_start_emulator()
        if started:
            _ensure_fhd_for_emulator()
        return {"ok": started, "started": started, "adb": adb}
