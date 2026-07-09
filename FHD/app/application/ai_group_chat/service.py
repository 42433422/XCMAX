"""AiGroupChatService composed from domain mixins."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

from .constants import CompletionFn, EmployeeExecutorFn
from .crud_mixin import AiGroupChatCrudMixin
from .dispatch_mixin import AiGroupChatDispatchMixin
from .loaders import (
    _default_completion,
    _default_departments,
    _default_duty_employee_loader,
    _default_employee_executor,
    _default_enterprise_departments,
    _default_enterprise_employee_loader,
)
from .post_mixin import AiGroupChatPostMixin
from .progress_mixin import AiGroupChatProgressMixin
from .reports_mixin import AiGroupChatReportsMixin
from .routing_mixin import AiGroupChatRoutingMixin
from .storage_mixin import AiGroupChatStorageMixin


class AiGroupChatService(
    AiGroupChatCrudMixin,
    AiGroupChatProgressMixin,
    AiGroupChatPostMixin,
    AiGroupChatRoutingMixin,
    AiGroupChatDispatchMixin,
    AiGroupChatReportsMixin,
    AiGroupChatStorageMixin,
):
    """微信式 AI 群聊：建群 / 拉 AI 成员 / 群内多 AI 回复。

    ``mode`` 决定部门模型 + 员工 SSOT：
    - ``"admin"``（默认）：6 部门 + 上岗员工
    - ``"enterprise"``：4 部门 + 上架/未上架员工
    """

    def __init__(
        self,
        storage_root: str | Path | None = None,
        completion_fn: CompletionFn | None = None,
        employee_executor_fn: EmployeeExecutorFn | None = None,
        department_loader: Callable[[], dict[str, Any]] | None = None,
        employee_loader: Callable[[], list[dict[str, Any]]] | None = None,
        mode: str = "admin",
    ) -> None:
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._root = root / "ai_group_chat"
        self._root.mkdir(parents=True, exist_ok=True)
        self._groups_path = self._root / "groups.jsonl"
        self._messages_path = self._root / "messages.jsonl"
        self._completion_fn = completion_fn or _default_completion
        self._has_custom_employee_executor = employee_executor_fn is not None
        self._employee_executor_fn = employee_executor_fn or _default_employee_executor
        self._mode = mode if mode in ("admin", "enterprise") else "admin"
        if department_loader is not None:
            self._department_loader = department_loader
        else:
            self._department_loader = (
                _default_enterprise_departments
                if self._mode == "enterprise"
                else _default_departments
            )
        if employee_loader is not None:
            self._employee_loader = employee_loader
        else:
            self._employee_loader = (
                _default_enterprise_employee_loader
                if self._mode == "enterprise"
                else _default_duty_employee_loader
            )

