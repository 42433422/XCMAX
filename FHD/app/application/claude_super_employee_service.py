"""Claude super-employee dispatch channel.

A second "超级员工" entity built on the same dispatch engine as Codex
(:mod:`app.application.super_employee_service`). It reuses the 排比 Para /
DevFleet multi-device scheduler, but selects/prepares devices for the
``claude`` dev tool and answers普通对话 via the Claude Code CLI.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    SuperEmployeeService,
)

CLAUDE_SUPER_EMPLOYEE_ID = CLAUDE_PROFILE.employee_id
CLAUDE_SUPER_EMPLOYEE_NAME = CLAUDE_PROFILE.employee_name
CLAUDE_RESULT_MESSAGE_KIND = CLAUDE_PROFILE.result_kind
CLAUDE_DIRECT_MESSAGE_KIND = CLAUDE_PROFILE.direct_kind

__all__ = [
    "CLAUDE_SUPER_EMPLOYEE_ID",
    "CLAUDE_SUPER_EMPLOYEE_NAME",
    "CLAUDE_RESULT_MESSAGE_KIND",
    "CLAUDE_DIRECT_MESSAGE_KIND",
    "ClaudeSuperEmployeeService",
]


class ClaudeSuperEmployeeService(SuperEmployeeService):
    """Persist software-internal Claude calls and optionally dispatch them out."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        claude_cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        super().__init__(
            CLAUDE_PROFILE,
            storage_root=storage_root,
            http_client_factory=http_client_factory,
            cli_runner=claude_cli_runner,
        )
