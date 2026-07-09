"""Generic super-employee dispatch — re-export shim (split into super_employee/)."""

from __future__ import annotations

import shutil as shutil
import subprocess as subprocess
from pathlib import Path as Path

from app.application.relay_workspace import (
    resolve_verified_relay_workspace_root as resolve_verified_relay_workspace_root,
)
from app.utils.path_utils import get_app_data_dir as get_app_data_dir

from .super_employee.profiles import (
    _PARA_TOKEN_CACHE as _PARA_TOKEN_CACHE,
)
from .super_employee.profiles import (
    _PARA_TOKEN_TTL as _PARA_TOKEN_TTL,
)
from .super_employee.profiles import (
    CLAUDE_PROFILE as CLAUDE_PROFILE,
)
from .super_employee.profiles import CODEX_PROFILE as CODEX_PROFILE
from .super_employee.profiles import CURSOR_PROFILE as CURSOR_PROFILE
from .super_employee.profiles import (
    DEFAULT_PARA_API_URL as DEFAULT_PARA_API_URL,
)
from .super_employee.profiles import (
    DISPATCHER_MESSAGE_KIND as DISPATCHER_MESSAGE_KIND,
)
from .super_employee.profiles import (
    PARA_TERMINAL_TASK_STATUSES as PARA_TERMINAL_TASK_STATUSES,
)
from .super_employee.profiles import TASK_ID_RE as TASK_ID_RE
from .super_employee.profiles import TRAE_PROFILE as TRAE_PROFILE
from .super_employee.profiles import (
    SuperEmployeeToolProfile as SuperEmployeeToolProfile,
)
from .super_employee.profiles import (
    _chunk_text as _chunk_text,
)
from .super_employee.profiles import (
    _claude_cli_command as _claude_cli_command,
)
from .super_employee.profiles import (
    _codex_cli_command as _codex_cli_command,
)
from .super_employee.profiles import _coerce_list as _coerce_list
from .super_employee.profiles import (
    _cursor_cli_command as _cursor_cli_command,
)
from .super_employee.profiles import (
    _safe_json_line as _safe_json_line,
)
from .super_employee.profiles import (
    _trae_cli_command as _trae_cli_command,
)
from .super_employee.profiles import _utc_now as _utc_now
from .super_employee.service import SuperEmployeeService as SuperEmployeeService

__all__ = [
    "DISPATCHER_MESSAGE_KIND",
    "CODEX_PROFILE",
    "CLAUDE_PROFILE",
    "CURSOR_PROFILE",
    "TRAE_PROFILE",
    "SuperEmployeeService",
    "SuperEmployeeToolProfile",
]
