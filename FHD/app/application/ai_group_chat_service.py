"""AI 群聊服务 — re-export shim (split into ai_group_chat/)."""

from __future__ import annotations

from .ai_group_chat.constants import (
    CHAT_ACCEPTANCE_SUMMARY_CHARS as CHAT_ACCEPTANCE_SUMMARY_CHARS,
)
from .ai_group_chat.constants import (
    CHAT_REPORT_SUMMARY_CHARS as CHAT_REPORT_SUMMARY_CHARS,
)
from .ai_group_chat.constants import CONTEXT_TURNS as CONTEXT_TURNS
from .ai_group_chat.constants import MAX_RESPONDERS as MAX_RESPONDERS
from .ai_group_chat.constants import (
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS as PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
)
from .ai_group_chat.constants import (
    PUBLIC_CHAT_BODY_MAX_CHARS as PUBLIC_CHAT_BODY_MAX_CHARS,
)
from .ai_group_chat.constants import (
    RELAY_PROGRESS_MIN_INTERVAL_SEC as RELAY_PROGRESS_MIN_INTERVAL_SEC,
)
from .ai_group_chat.constants import (
    SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC as SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
)
from .ai_group_chat.constants import (
    SUPER_DISCUSSION_DEFAULT_ROUNDS as SUPER_DISCUSSION_DEFAULT_ROUNDS,
)
from .ai_group_chat.constants import (
    SUPER_DISCUSSION_MAX_ROUNDS as SUPER_DISCUSSION_MAX_ROUNDS,
)
from .ai_group_chat.constants import _env_float as _env_float
from .ai_group_chat.loaders import (
    _append_super_employees as _append_super_employees,
)
from .ai_group_chat.loaders import (
    _default_departments as _default_departments,
)
from .ai_group_chat.loaders import (
    _default_duty_employee_loader as _default_duty_employee_loader,
)
from .ai_group_chat.loaders import (
    _default_enterprise_departments as _default_enterprise_departments,
)
from .ai_group_chat.loaders import (
    _default_enterprise_employee_loader as _default_enterprise_employee_loader,
)
from .ai_group_chat.loaders import (
    _dept_key_to_employee_ids as _dept_key_to_employee_ids,
)
from .ai_group_chat.loaders import (
    _employee_manifest as _employee_manifest,
)
from .ai_group_chat.loaders import (
    _is_required_group_member as _is_required_group_member,
)
from .ai_group_chat.loaders import (
    _member_public_shape as _member_public_shape,
)
from .ai_group_chat.loaders import (
    _normalize_branch_context as _normalize_branch_context,
)
from .ai_group_chat.loaders import _safe_json_line as _safe_json_line
from .ai_group_chat.loaders import _utc_now as _utc_now
from .ai_group_chat.loaders import (
    _with_required_group_members as _with_required_group_members,
)
from .ai_group_chat.loaders import (
    _xiaoc_assistant_member as _xiaoc_assistant_member,
)
from .ai_group_chat.service import AiGroupChatService as AiGroupChatService

__all__ = ["AiGroupChatService", "MAX_RESPONDERS"]
