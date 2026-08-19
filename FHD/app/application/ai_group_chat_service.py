# ruff: noqa: E402, F401, I001
"""AI 群聊服务（微信式多 AI 群组）。

自包含、按用户隔离、jsonl 持久化（与超级员工服务同一套存储惯例），
不触碰现有人际 IM（``ImConversation`` 等）以零回归。

SSOT 架构（双模式）：
- **admin 模式**（管理端）：6 部门 + 编制员工均来自 ``config/duty_roster.json``；
  ``duty_employee_registry.json`` 与 employee manifest 只补展示元数据。
- **enterprise 模式**（企业端）：4 部门（工具层/执行层/服务层/管理层）+ 上架员工（MODstore）+ 未上架员工（宿主定制）

部门 → 员工映射为自动派生：
- admin: 从 ``duty_roster.json`` 的 departments/subzones 展平员工归属
- enterprise: ``resolve_enterprise_org_layer(emp_id, ...)`` 从 manifest enterprise_layer / ID 表 / 关键词推断
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any, cast

from app.application.group_chat.constants import (
    _LEGACY_SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_RELAY_KINDS,
    _XIAOC_ASSISTANT_ID,
    CHAT_ACCEPTANCE_SUMMARY_CHARS,
    CHAT_REPORT_SUMMARY_CHARS,
    CONTEXT_TURNS,
    MAX_RESPONDERS,
    RELAY_PROGRESS_MIN_INTERVAL_SEC,
    CompletionFn,
    EmployeeExecutorFn,
)
from app.application.group_chat.constants import (
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS as PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    PUBLIC_CHAT_BODY_MAX_CHARS as PUBLIC_CHAT_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC as SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_DEFAULT_ROUNDS as SUPER_DISCUSSION_DEFAULT_ROUNDS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_MAX_ROUNDS as SUPER_DISCUSSION_MAX_ROUNDS,
)
from app.application.group_chat.constants import (
    _env_float as _env_float,
)
from app.application.group_chat.dispatch_router import AiGroupChatDispatchMixin
from app.application.group_chat.employee_registry import (
    _FALLBACK_DEPARTMENTS,
    _FALLBACK_ENTERPRISE_DEPARTMENTS,
    _default_completion,
    _default_departments,
    _default_duty_employee_loader,
    _default_employee_executor,
    _default_enterprise_departments,
    _default_enterprise_employee_loader,
    _is_required_group_member,
    _member_employee_id,
    _normalize_branch_context,
    _utc_now,
    _with_required_group_members,
)
from app.application.group_chat.employee_registry import (
    _append_super_employees as _append_super_employees,
)
from app.application.group_chat.employee_registry import (
    _dept_key_to_employee_ids as _dept_key_to_employee_ids,
)
from app.application.group_chat.employee_registry import (
    _employee_manifest as _employee_manifest,
)
from app.application.group_chat.employee_registry import (
    _member_public_shape as _member_public_shape,
)
from app.application.group_chat.employee_registry import (
    _safe_json_line as _safe_json_line,
)
from app.application.group_chat.employee_registry import (
    _xiaoc_assistant_member as _xiaoc_assistant_member,
)
from app.application.group_chat.message_formatting import AiGroupChatFormattingMixin
from app.application.group_chat.storage import AiGroupChatStorageMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir


from app.application.ai_group_chat_service_aigroupchatservice_mixin01 import (
    _AiGroupChatServicePart01Mixin,
)
from app.application.ai_group_chat_service_aigroupchatservice_mixin02 import (
    _AiGroupChatServicePart02Mixin,
)
from app.application.ai_group_chat_service_aigroupchatservice_mixin03 import (
    _AiGroupChatServicePart03Mixin,
)


class AiGroupChatService(_AiGroupChatServicePart01Mixin, _AiGroupChatServicePart02Mixin, _AiGroupChatServicePart03Mixin, AiGroupChatDispatchMixin, AiGroupChatFormattingMixin, AiGroupChatStorageMixin):
    """微信式 AI 群聊：建群 / 拉 AI 成员 / 群内多 AI 回复。

    ``mode`` 决定部门模型 + 员工 SSOT：
    - ``"admin"``（默认）：6 部门 + 上岗员工
    - ``"enterprise"``：4 部门 + 上架/未上架员工
    """


    # ── 公开 API ──



















































    # ── 部门种子 ──



__all__ = [
    "AiGroupChatService",
    "CHAT_ACCEPTANCE_SUMMARY_CHARS",
    "CHAT_REPORT_SUMMARY_CHARS",
    "MAX_RESPONDERS",
    "PUBLIC_ACCEPTANCE_BODY_MAX_CHARS",
    "PUBLIC_CHAT_BODY_MAX_CHARS",
    "SUPER_DISCUSSION_DEFAULT_ROUNDS",
    "SUPER_DISCUSSION_MAX_ROUNDS",
]
