"""Trae super-employee dispatch channel.

Trae CN currently exposes a VS Code-style command line entry, not a stable
headless agent interface. This service registers Trae as a first-class
super-employee and routes real work through the shared relay / Para dispatcher.
Local CLI direct execution is deliberately disabled to avoid false completion.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

from app.application.super_employee_service import (
    TRAE_PROFILE,
    SuperEmployeeService,
)

TRAE_SUPER_EMPLOYEE_ID = TRAE_PROFILE.employee_id
TRAE_SUPER_EMPLOYEE_NAME = TRAE_PROFILE.employee_name
TRAE_RESULT_MESSAGE_KIND = TRAE_PROFILE.result_kind
TRAE_DIRECT_MESSAGE_KIND = TRAE_PROFILE.direct_kind

__all__ = [
    "TRAE_SUPER_EMPLOYEE_ID",
    "TRAE_SUPER_EMPLOYEE_NAME",
    "TRAE_RESULT_MESSAGE_KIND",
    "TRAE_DIRECT_MESSAGE_KIND",
    "TraeSuperEmployeeService",
]


class TraeSuperEmployeeService(SuperEmployeeService):
    """Persist software-internal Trae calls and dispatch them to Trae devices."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        trae_cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        super().__init__(
            TRAE_PROFILE,
            storage_root=storage_root,
            http_client_factory=http_client_factory,
            cli_runner=trae_cli_runner,
        )

    def _conversation_mode_enabled(self) -> bool:
        return False

    def _cli_reply_body(self, text: str, context: dict) -> str:
        # Trae CN CLI can open the app and manage MCP/extensions, but it does not
        # provide a Cursor/Claude-style `agent --print` or `--print` interface.
        # Returning empty keeps simple identity/help replies on the deterministic
        # parent fallback and sends real work through trae.invoke relay/Para.
        return ""
