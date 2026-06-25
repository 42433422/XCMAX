"""Cursor super-employee dispatch channel.

A third "超级员工" entity built on the same dispatch engine as Codex / Claude
(:mod:`app.application.super_employee_service`). It reuses the 排比 Para /
DevFleet multi-device scheduler for ``cursor_agent`` devices and answers
普通对话 via the Cursor Agent CLI (``cursor agent --print``).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

from app.application.super_employee_service import (
    CURSOR_PROFILE,
    SuperEmployeeService,
)

CURSOR_SUPER_EMPLOYEE_ID = CURSOR_PROFILE.employee_id
CURSOR_SUPER_EMPLOYEE_NAME = CURSOR_PROFILE.employee_name
CURSOR_RESULT_MESSAGE_KIND = CURSOR_PROFILE.result_kind
CURSOR_DIRECT_MESSAGE_KIND = CURSOR_PROFILE.direct_kind

__all__ = [
    "CURSOR_SUPER_EMPLOYEE_ID",
    "CURSOR_SUPER_EMPLOYEE_NAME",
    "CURSOR_RESULT_MESSAGE_KIND",
    "CURSOR_DIRECT_MESSAGE_KIND",
    "CursorSuperEmployeeService",
]


class CursorSuperEmployeeService(SuperEmployeeService):
    """Persist software-internal Cursor calls and optionally dispatch them out."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        cursor_cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        super().__init__(
            CURSOR_PROFILE,
            storage_root=storage_root,
            http_client_factory=http_client_factory,
            cli_runner=cursor_cli_runner,
        )

    def _conversation_mode_enabled(self) -> bool:
        # Cursor Agent CLI 尚无 claude 式 --resume 会话续接；走单次 print 路径。
        return False
