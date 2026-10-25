"""Public surface-audit dependency API and explicit runtime composition.

The persistent MODstore API remains running after an audit. Desktop, Vite,
marketing and emulator processes are cleaned up by the existing opt-in policy.
"""

from __future__ import annotations

import os as os
import subprocess as subprocess
import time as time
from pathlib import Path
from typing import Any

from modstore_server.surface_audit_paths import (
    auto_start_enabled as _auto_start_enabled,
)
from modstore_server.surface_audit_paths import fhd_root as _fhd_root
from modstore_server.surface_audit_paths import is_local_url as _is_local_url
from modstore_server.surface_audit_paths import (
    modstore_deploy_root as _modstore_deploy_root,
)
from modstore_server.surface_audit_paths import repo_root as _repo_root
from modstore_server.surface_audit_processes import SurfaceProcessLauncher
from modstore_server.surface_audit_processes import _kill_pid_file as _kill_pid_file
from modstore_server.surface_audit_processes import (
    stop_surface_audit_ephemeral as _stop_ephemeral,
)
from modstore_server.surface_audit_readiness import SurfaceDependencyChecks
from modstore_server.surface_audit_runtime import (
    _fhd_api_health_ok as _fhd_api_health_ok,
)
from modstore_server.surface_audit_runtime import _http_ok as _http_ok
from modstore_server.surface_audit_runtime import _logs_dir as _logs_dir
from modstore_server.surface_audit_runtime import _parse_port as _parse_port
from modstore_server.surface_audit_runtime import _pids_dir as _pids_dir
from modstore_server.surface_audit_runtime import _python_bin as _python_bin
from modstore_server.surface_audit_runtime import (
    resolve_internal_api_base as resolve_internal_api_base,
)
from modstore_server.surface_audit_runtime import (
    surface_audit_stop_after_enabled as surface_audit_stop_after_enabled,
)
from modstore_server.surface_audit_services import SurfaceServices, wait_for_health


def _spawn(
    name: str, cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    return SurfaceProcessLauncher(_pids_dir(), _logs_dir()).spawn(name, cmd, cwd=cwd, env=env)


def _wait_http(url: str, *, label: str, tries: int = 45) -> bool:
    return wait_for_health(url, label=label, probe=_http_ok, tries=tries)


def _wait_fhd_api_health(url: str, *, label: str, tries: int = 45) -> bool:
    return wait_for_health(url, label=label, probe=_fhd_api_health_ok, tries=tries)


def _services() -> SurfaceServices:
    return SurfaceServices(
        fhd_root=_fhd_root,
        deploy_root=_modstore_deploy_root,
        repo_root=_repo_root,
        python_bin=_python_bin,
        auto_start_enabled=_auto_start_enabled,
        http_ok=_http_ok,
        fhd_health_ok=_fhd_api_health_ok,
        spawn=_spawn,
        wait_http=_wait_http,
        wait_fhd_health=_wait_fhd_api_health,
    )


def _ensure_fhd_api(api_port: int) -> dict[str, Any]:
    return _services().fhd_api(api_port)


def _ensure_vite(web_port: int, api_port: int) -> dict[str, Any]:
    return _services().vite(web_port, api_port)


def _ensure_modstore_api(port: int) -> dict[str, Any]:
    return _services().modstore_api(port)


def _ensure_marketing_static(port: int) -> dict[str, Any]:
    return _services().marketing_static(port)


def _ensure_playwright() -> dict[str, Any]:
    return _services().playwright()


def _ensure_android_emulator() -> dict[str, Any]:
    return _services().android_emulator()


def ensure_surface_audit_deps() -> dict[str, Any]:
    return SurfaceDependencyChecks(
        playwright=_ensure_playwright,
        fhd_api=_ensure_fhd_api,
        vite=_ensure_vite,
        marketing=_ensure_marketing_static,
        modstore_api=_ensure_modstore_api,
        android=_ensure_android_emulator,
        internal_api_base=resolve_internal_api_base,
        is_local_url=_is_local_url,
    ).run()


def stop_surface_audit_ephemeral() -> dict[str, Any]:
    return _stop_ephemeral(
        pids_directory=_pids_dir(),
        fhd_directory=_fhd_root(),
        stop_process=_kill_pid_file,
    )
