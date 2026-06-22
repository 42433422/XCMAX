"""Codex super-employee dispatch channel for the admin information console.

The dispatch engine now lives in :mod:`app.application.super_employee_service`;
this module keeps the Codex-specific identity/profile and the public name
``CodexSuperEmployeeService`` for backward compatibility.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

from app.application.super_employee_service import (
    CODEX_PROFILE,
    DEFAULT_PARA_API_URL,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    SuperEmployeeService,
)

CODEX_SUPER_EMPLOYEE_ID = CODEX_PROFILE.employee_id
CODEX_SUPER_EMPLOYEE_NAME = CODEX_PROFILE.employee_name
CODEX_RESULT_MESSAGE_KIND = CODEX_PROFILE.result_kind
CODEX_DIRECT_MESSAGE_KIND = CODEX_PROFILE.direct_kind

__all__ = [
    "CODEX_SUPER_EMPLOYEE_ID",
    "CODEX_SUPER_EMPLOYEE_NAME",
    "CODEX_RESULT_MESSAGE_KIND",
    "CODEX_DIRECT_MESSAGE_KIND",
    "DISPATCHER_MESSAGE_KIND",
    "DEFAULT_PARA_API_URL",
    "PARA_TERMINAL_TASK_STATUSES",
    "CodexSuperEmployeeService",
]


class CodexSuperEmployeeService(SuperEmployeeService):
    """Persist software-internal Codex calls and optionally dispatch them out."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        codex_cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        super().__init__(
            CODEX_PROFILE,
            storage_root=storage_root,
            http_client_factory=http_client_factory,
            cli_runner=codex_cli_runner,
        )
