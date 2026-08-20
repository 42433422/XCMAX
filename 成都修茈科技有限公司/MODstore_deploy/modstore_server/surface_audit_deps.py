# isort: skip_file
# ruff: noqa: E402, F401, I001
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
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from modstore_server.surface_audit_paths import (
    auto_start_enabled as _auto_start_enabled,
)
from modstore_server.surface_audit_paths import (
    fhd_root as _fhd_root,
)
from modstore_server.surface_audit_paths import (
    is_local_url as _is_local_url,
)
from modstore_server.surface_audit_paths import (
    modstore_deploy_root as _modstore_deploy_root,
)
from modstore_server.surface_audit_paths import (
    repo_root as _repo_root,
)
from modstore_server.surface_audit_paths import (
    runtime_state_root as _runtime_state_root,
)

logger = logging.getLogger(__name__)


from modstore_server.surface_audit_deps_part01 import (
    _pids_dir as _pids_dir,
    _logs_dir as _logs_dir,
    _python_bin as _python_bin,
    _http_ok as _http_ok,
    _fhd_api_health_ok as _fhd_api_health_ok,
    _wait_http as _wait_http,
    _wait_fhd_api_health as _wait_fhd_api_health,
    _spawn as _spawn,
    _ensure_fhd_api as _ensure_fhd_api,
    _ensure_vite as _ensure_vite,
    _ensure_modstore_api as _ensure_modstore_api,
    _ensure_marketing_static as _ensure_marketing_static,
    _ensure_playwright as _ensure_playwright,
    resolve_internal_api_base as resolve_internal_api_base,
    _parse_port as _parse_port,
    _ensure_android_emulator as _ensure_android_emulator,
)


from modstore_server.surface_audit_deps_part02 import (
    ensure_surface_audit_deps as ensure_surface_audit_deps,
    surface_audit_stop_after_enabled as surface_audit_stop_after_enabled,
    _kill_pid_file as _kill_pid_file,
    stop_surface_audit_ephemeral as stop_surface_audit_ephemeral,
)
