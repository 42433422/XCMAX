"""Trae super-employee dispatch channel."""

from __future__ import annotations

import os
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
    """Persist software-internal Trae calls and optionally dispatch them out."""

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

    def _conversation_perm(self) -> str:
        return (
            os.environ.get("DEVFLEET_TRAE_PERMISSION_MODE")
            or os.environ.get("XCMAX_TRAE_PERMISSION_MODE")
            or "default"
        ).strip() or "default"

    def _conversation_cmd(
        self, cli_path: str, prompt: str, resume_session_id: str | None
    ) -> list[str]:
        cmd = [
            cli_path,
            "--print",
            "--output-format",
            "stream-json",
            "--permission-mode",
            self._conversation_perm(),
        ]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        cmd.append(prompt)
        return cmd
