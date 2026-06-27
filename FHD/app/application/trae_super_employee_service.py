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
        # Trae 不走 claude 式 --resume 持久会话，统一走 dev-loop（用 _trae_cli_command）。
        return False

    # 注：旧实现曾 hard-code `_cli_reply_body` 返回空——那是因为当时只有 trae-cn(IDE 启动器，
    # 无无头 agent)。企业版 trae-cli 是真正的无头 coding agent(--print/stream-json)，因此移除该
    # 短路，回到基类按 _trae_cli_command 真执行(闲聊→直答、工单→dev-loop 真改文件→推分支)。
