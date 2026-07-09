#!/usr/bin/env python3
"""Split ai_group_chat / super_employee / ai_chat monoliths (behavior-preserving)."""

from __future__ import annotations

from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
APP = FHD / "app" / "application"


def _read(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _write(rel: str, content: str) -> None:
    path = APP / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lines(src: str, start: int, end: int) -> str:
    return "".join(src.splitlines(keepends=True)[start - 1 : end])


def _dedent_methods(body: str) -> str:
    """Class-indented methods (4 spaces) → module-level mixin methods (still 4 spaces)."""
    return body


FACADE_HELPER = '''
import sys
from typing import Any

_FACADE_MODULE = "{facade}"


def _facade_attr(name: str, default: Any) -> Any:
    """Read monkeypatched symbol from facade/shim module when present."""
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is None:
        return default
    return mod.__dict__.get(name, default)
'''


def split_ai_group_chat() -> None:
    src = _read("ai_group_chat_service.py")
    docstring = _lines(src, 1, 14)
    imports = _lines(src, 16, 29)

    constants = f'''{docstring}
{imports}
{FACADE_HELPER.format(facade="app.application.ai_group_chat_service")}

{_lines(src, 31, 250)}
'''

    loaders = f'''"""Employee / department loaders for AI group chat."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

from .constants import (
    _BRANCH_SAFE_RE,
    _DEFAULT_SINGLE_CLI_EMPLOYEE_ID,
    _LEGACY_SUPER_EMPLOYEE_IDS,
    _REQUIRED_GROUP_MEMBER_IDS,
    _SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_RELAY_KINDS,
    _XIAOC_ASSISTANT_ID,
    CompletionFn,
    EmployeeExecutorFn,
    _facade_attr,
)

{_lines(src, 252, 620)}
'''

    def mixin(name: str, doc: str, start: int, end: int, extra_imports: str = "") -> str:
        body = _lines(src, start, end)
        return f'''"""{doc}"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

from .constants import *  # noqa: F403
from .loaders import (  # noqa: F401
    _append_super_employees,
    _default_completion,
    _default_departments,
    _default_duty_employee_loader,
    _default_employee_executor,
    _default_enterprise_departments,
    _default_enterprise_employee_loader,
    _dept_key_to_employee_ids,
    _employee_manifest,
    _is_required_group_member,
    _member_employee_id,
    _member_public_shape,
    _normalize_branch_context,
    _safe_json_line,
    _utc_now,
    _with_required_group_members,
    _xiaoc_assistant_member,
)
{extra_imports}

class {name}:
{body}'''

    # Method bodies keep their 4-space indent under the class
    crud = mixin(
        "AiGroupChatCrudMixin",
        "CRUD / membership APIs for AI group chat.",
        667,
        1078,
    )
    progress = mixin(
        "AiGroupChatProgressMixin",
        "Relay / super-employee progress sync for AI group chat.",
        1080,
        1509,
    )
    post = mixin(
        "AiGroupChatPostMixin",
        "post_message and acceptance follow-up for AI group chat.",
        1511,
        1740,
    )
    routing = mixin(
        "AiGroupChatRoutingMixin",
        "Responder selection, super discussion, and routing.",
        1742,
        2486,
    )
    # Patch-sensitive timeout lookups
    routing = routing.replace(
        "timeout=SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,",
        'timeout=_facade_attr("SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC", SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC),',
    )
    dispatch = mixin(
        "AiGroupChatDispatchMixin",
        "Work dispatch and employee execution for AI group chat.",
        2488,
        2959,
    )
    reports = mixin(
        "AiGroupChatReportsMixin",
        "Work-report / acceptance formatting for AI group chat.",
        2961,
        3615,
    )
    storage = mixin(
        "AiGroupChatStorageMixin",
        "JSONL persistence and public shaping for AI group chat.",
        3617,
        3965,
    )

    service = f'''"""AiGroupChatService composed from domain mixins."""

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

{_lines(src, 630, 663)}
'''

    init_pkg = '''"""AI group chat application layer package."""

from __future__ import annotations
'''

    shim = '''"""AI 群聊服务 — re-export shim (split into ai_group_chat/)."""

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
'''

    _write("ai_group_chat/__init__.py", init_pkg)
    _write("ai_group_chat/constants.py", constants)
    _write("ai_group_chat/loaders.py", loaders)
    _write("ai_group_chat/crud_mixin.py", crud)
    _write("ai_group_chat/progress_mixin.py", progress)
    _write("ai_group_chat/post_mixin.py", post)
    _write("ai_group_chat/routing_mixin.py", routing)
    _write("ai_group_chat/dispatch_mixin.py", dispatch)
    _write("ai_group_chat/reports_mixin.py", reports)
    _write("ai_group_chat/storage_mixin.py", storage)
    _write("ai_group_chat/service.py", service)
    _write("ai_group_chat_service.py", shim)


def split_super_employee() -> None:
    src = _read("super_employee_service.py")
    docstring = _lines(src, 1, 11)
    imports = _lines(src, 13, 43)

    profiles = f'''{docstring}
{imports}
{FACADE_HELPER.format(facade="app.application.super_employee_service")}

logger = logging.getLogger(__name__)

{_lines(src, 47, 360)}
'''

    def mixin(name: str, doc: str, ranges: list[tuple[int, int]]) -> str:
        parts = [_lines(src, a, b) for a, b in ranges]
        body = "".join(parts)
        text = f'''"""{doc}"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.application.execution_scope import (
    CONTEXT_TOKEN_KEY,
    FACTORY_TOKEN_ENV,
    CapabilityGrant,
)
from app.application.git_workspace_manager import GitWorkspaceManager
from app.application.message_repository import MessageRepository
from app.application.relay_workspace import resolve_verified_relay_workspace_root
from app.application.workspaces import WorkspaceError, get_workspace_registry
from app.utils.path_utils import get_app_data_dir

from .profiles import *  # noqa: F403

logger = logging.getLogger(__name__)


class {name}:
{body}'''
        # Facade-sensitive lookups for monkeypatch compatibility
        text = text.replace("subprocess.run", '_facade_attr("subprocess", subprocess).run')
        text = text.replace("subprocess.Popen", '_facade_attr("subprocess", subprocess).Popen')
        text = text.replace(
            "subprocess.CompletedProcess",
            '_facade_attr("subprocess", subprocess).CompletedProcess',
        )
        text = text.replace(
            "subprocess.SubprocessError",
            '_facade_attr("subprocess", subprocess).SubprocessError',
        )
        text = text.replace(
            "subprocess.TimeoutExpired",
            '_facade_attr("subprocess", subprocess).TimeoutExpired',
        )
        text = text.replace(
            "asyncio.subprocess.PIPE",
            "asyncio.subprocess.PIPE",
        )  # leave asyncio alone — already correct after replace? fix below
        # Undo accidental asyncio.subprocess replacements
        text = text.replace(
            'asyncio._facade_attr("subprocess", subprocess).PIPE',
            "asyncio.subprocess.PIPE",
        )
        text = text.replace("shutil.which", '_facade_attr("shutil", shutil).which')
        # Path(...) construction stays local; only .is_file via facade Path when checking candidates
        # Rewrite: if value and Path(value).is_file():
        text = text.replace(
            "if value and Path(value).is_file():",
            'if value and _facade_attr("Path", Path)(value).is_file():',
        )
        text = text.replace(
            "get_app_data_dir()",
            '_facade_attr("get_app_data_dir", get_app_data_dir)()',
        )
        text = text.replace(
            "resolve_verified_relay_workspace_root",
            '_facade_attr("resolve_verified_relay_workspace_root", resolve_verified_relay_workspace_root)',
        )
        return text

    # Careful: replace resolve_verified might break the import line — fix after
    para = mixin(
        "SuperEmployeeParaDispatchMixin",
        "Para / DevFleet dispatch mixin for super-employee service.",
        [(839, 1522)],
    )
    # Fix import that got mangled
    para = para.replace(
        "from app.application.relay_workspace import _facade_attr(",
        "from app.application.relay_workspace import resolve_verified_relay_workspace_root\n"
        "# facade helper imported from profiles; keep resolve default:\n"
        "_resolve_verified_relay_workspace_root = resolve_verified_relay_workspace_root\n"
        "from app.application.relay_workspace import _UNUSED_PLACEHOLDER as _facade_attr(",
    )
    # That approach is messy — rebuild para more carefully

    def mixin_clean(name: str, doc: str, ranges: list[tuple[int, int]]) -> str:
        parts = [_lines(src, a, b) for a, b in ranges]
        body = "".join(parts)
        text = f'''"""{doc}"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.application.execution_scope import (
    CONTEXT_TOKEN_KEY,
    FACTORY_TOKEN_ENV,
    CapabilityGrant,
)
from app.application.git_workspace_manager import GitWorkspaceManager
from app.application.message_repository import MessageRepository
from app.application.relay_workspace import resolve_verified_relay_workspace_root
from app.application.workspaces import WorkspaceError, get_workspace_registry
from app.utils.path_utils import get_app_data_dir

from .profiles import (  # noqa: F401
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DEFAULT_PARA_API_URL,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    TASK_ID_RE,
    TRAE_PROFILE,
    SuperEmployeeToolProfile,
    _PARA_TOKEN_CACHE,
    _PARA_TOKEN_TTL,
    _RELAY_WT_LOCKS,
    _RELAY_WT_LOCKS_GUARD,
    _SUBTASK_LABELS,
    _TASK_MARKERS,
    _chunk_text,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _facade_attr,
    _relay_wt_lock,
    _safe_json_line,
    _trae_cli_command,
    _utc_now,
)

logger = logging.getLogger(__name__)


class {name}:
{body}'''
        # Only replace in method body region — after "class {name}:"
        head, _, rest = text.partition(f"class {name}:\n")
        rest2 = rest
        rest2 = re_sub_subprocess(rest2)
        rest2 = rest2.replace("shutil.which", '_facade_attr("shutil", shutil).which')
        rest2 = rest2.replace(
            "if value and Path(value).is_file():",
            'if value and _facade_attr("Path", Path)(value).is_file():',
        )
        rest2 = rest2.replace(
            "get_app_data_dir()",
            '_facade_attr("get_app_data_dir", get_app_data_dir)()',
        )
        # resolve_verified_relay_workspace_root( → facade call
        rest2 = rest2.replace(
            "resolve_verified_relay_workspace_root(",
            '_facade_attr("resolve_verified_relay_workspace_root", resolve_verified_relay_workspace_root)(',
        )
        return head + f"class {name}:\n" + rest2

    def re_sub_subprocess(rest: str) -> str:
        import re as _re

        # Don't touch asyncio.subprocess
        def repl_run(m: _re.Match[str]) -> str:
            return '_facade_attr("subprocess", subprocess).run'

        def repl_popen(m: _re.Match[str]) -> str:
            return '_facade_attr("subprocess", subprocess).Popen'

        out = _re.sub(r"(?<!asyncio\.)subprocess\.run\b", repl_run, rest)
        out = _re.sub(r"(?<!asyncio\.)subprocess\.Popen\b", repl_popen, out)
        out = _re.sub(
            r"(?<!asyncio\.)subprocess\.CompletedProcess\b",
            '_facade_attr("subprocess", subprocess).CompletedProcess',
            out,
        )
        out = _re.sub(
            r"(?<!asyncio\.)subprocess\.SubprocessError\b",
            '_facade_attr("subprocess", subprocess).SubprocessError',
            out,
        )
        out = _re.sub(
            r"(?<!asyncio\.)subprocess\.TimeoutExpired\b",
            '_facade_attr("subprocess", subprocess).TimeoutExpired',
            out,
        )
        out = _re.sub(
            r"(?<!asyncio\.)subprocess\.PIPE\b",
            '_facade_attr("subprocess", subprocess).PIPE',
            out,
        )
        return out

    cli = mixin_clean(
        "SuperEmployeeCliRuntimeMixin",
        "CLI streaming / conversation runtime mixin.",
        [(656, 837), (1524, 2133)],
    )
    para = mixin_clean(
        "SuperEmployeeParaDispatchMixin",
        "Para / DevFleet dispatch mixin.",
        [(839, 1522), (2555, 2765)],
    )
    # 2555-2765 overlaps messaging — include in para for task sync
    # But 1437-1522 already in first range. Second range is fetch/upsert results.
    # Remove duplicate if any — ranges don't overlap with cli.

    # Wait: para first range ends 1522, cli second starts 1524. Good.
    # para second 2555-2765 — but messaging methods between 1407-1493 are in first range.
    # Methods 2392-2554 are clean_cli / direct reply — belong in cli or service.
    # Adjust: put 2392-2553 in cli, 2555-end in para.

    cli = mixin_clean(
        "SuperEmployeeCliRuntimeMixin",
        "CLI streaming / conversation runtime mixin.",
        [(656, 837), (1524, 2133), (2392, 2553)],
    )
    para = mixin_clean(
        "SuperEmployeeParaDispatchMixin",
        "Para / DevFleet dispatch mixin.",
        [(839, 1522), (2555, 2765)],
    )
    dev = mixin_clean(
        "SuperEmployeeDevLoopMixin",
        "Git worktree / dev-loop mixin.",
        [(2135, 2390)],
    )

    # Core service: __init__, list_messages, invoke, invoke_stream + compose
    service = f'''"""SuperEmployeeService composed from mixins."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.application.execution_scope import (
    CONTEXT_TOKEN_KEY,
    FACTORY_TOKEN_ENV,
    CapabilityGrant,
)
from app.application.git_workspace_manager import GitWorkspaceManager
from app.application.message_repository import MessageRepository
from app.application.relay_workspace import resolve_verified_relay_workspace_root
from app.application.workspaces import WorkspaceError, get_workspace_registry
from app.utils.path_utils import get_app_data_dir

from .cli_runtime import SuperEmployeeCliRuntimeMixin
from .dev_loop import SuperEmployeeDevLoopMixin
from .para_dispatch import SuperEmployeeParaDispatchMixin
from .profiles import (
    SuperEmployeeToolProfile,
    _facade_attr,
    _safe_json_line,
    _utc_now,
)

logger = logging.getLogger(__name__)


class SuperEmployeeService(
    SuperEmployeeCliRuntimeMixin,
    SuperEmployeeParaDispatchMixin,
    SuperEmployeeDevLoopMixin,
):
    """Persist software-internal tool calls and optionally dispatch them out."""

{_lines(src, 366, 654)}
'''
    # Facade in __init__ / invoke body
    head, _, rest = service.partition("class SuperEmployeeService(\n")
    # find end of class bases and apply facade to method body only
    # Simpler: apply to whole service file method section after class def
    idx = service.index('    """Persist software-internal')
    pre, post = service[:idx], service[idx:]
    post = re_sub_subprocess(post)
    post = post.replace("shutil.which", '_facade_attr("shutil", shutil).which')
    post = post.replace(
        "get_app_data_dir()",
        '_facade_attr("get_app_data_dir", get_app_data_dir)()',
    )
    post = post.replace(
        "resolve_verified_relay_workspace_root(",
        '_facade_attr("resolve_verified_relay_workspace_root", resolve_verified_relay_workspace_root)(',
    )
    service = pre + post

    init_pkg = '''"""Super-employee application layer package."""

from __future__ import annotations
'''

    shim = '''"""Generic super-employee dispatch — re-export shim (split into super_employee/)."""

from __future__ import annotations

import shutil as shutil
import subprocess as subprocess
from pathlib import Path as Path

from app.application.relay_workspace import (
    resolve_verified_relay_workspace_root as resolve_verified_relay_workspace_root,
)
from app.utils.path_utils import get_app_data_dir as get_app_data_dir

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
    _PARA_TOKEN_CACHE as _PARA_TOKEN_CACHE,
)
from .super_employee.profiles import (
    _PARA_TOKEN_TTL as _PARA_TOKEN_TTL,
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
'''

    _write("super_employee/__init__.py", init_pkg)
    _write("super_employee/profiles.py", profiles)
    _write("super_employee/cli_runtime.py", cli)
    _write("super_employee/para_dispatch.py", para)
    _write("super_employee/dev_loop.py", dev)
    _write("super_employee/service.py", service)
    _write("super_employee_service.py", shim)


def split_ai_chat() -> None:
    src = _read("ai_chat_app_service.py")
    docstring = _lines(src, 1, 18)

    helpers = f'''{docstring}
import asyncio
import json
import logging
import math
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

logger = logging.getLogger(__name__)

_FACADE_MODULE = "app.application.ai_chat_app_service"


def _facade_attr(name: str, default: Any) -> Any:
    """Read monkeypatched symbol from facade/shim module when present."""
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is None:
        return default
    return mod.__dict__.get(name, default)


{_lines(src, 46, 110)}
'''

    def mixin(name: str, doc: str, start: int, end: int) -> str:
        body = _lines(src, start, end)
        text = f'''"""{doc}"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

from .helpers import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _EXCEL_IMPORT_QTY_MEASURE_RE,
    _enrich_confirmation_inner,
    _facade_attr,
    _skip_pro_excel_deterministic_import,
)

logger = logging.getLogger(__name__)


class {name}:
{body}'''
        # Facade httpx in method bodies
        head, sep, rest = text.partition(f"class {name}:\n")
        rest = rest.replace("httpx.post", '_facade_attr("httpx", httpx).post')
        rest = rest.replace("httpx.get", '_facade_attr("httpx", httpx).get')
        return head + sep + rest

    excel = mixin(
        "AIChatExcelImportMixin",
        "Excel import helpers for AI chat application service.",
        543,
        1840,
    )
    workflow = mixin(
        "AIChatWorkflowMixin",
        "Dynamic / agentic workflow helpers for AI chat.",
        1842,
        3401,
    )
    tools = mixin(
        "AIChatToolExecutionMixin",
        "Confirmation / tool execution helpers for AI chat.",
        3403,
        3907,
    )

    service = f'''"""AIChatApplicationService composed from mixins."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

from .excel_import_mixin import AIChatExcelImportMixin
from .helpers import _facade_attr, _skip_pro_excel_deterministic_import
from .tool_execution_mixin import AIChatToolExecutionMixin
from .workflow_mixin import AIChatWorkflowMixin

logger = logging.getLogger(__name__)


class AIChatApplicationService(
    AIChatExcelImportMixin,
    AIChatWorkflowMixin,
    AIChatToolExecutionMixin,
):
    """
    AI 聊天应用服务

    编排 AI 对话和即时工具执行，负责：
    - 聊天主流程处理
    - 即时工具执行（source=pro 和普通模式）
    - 响应格式构建
    """

    def __init__(self):
        self.ai_service = _facade_attr("get_ai_conversation_service", get_ai_conversation_service)()
        self.workflow_planner = _facade_attr("LLMWorkflowPlanner", LLMWorkflowPlanner)()
        self.risk_gate = _facade_attr("HybridRiskGate", HybridRiskGate)()
        self.workflow_engine = _facade_attr("WorkflowEngine", WorkflowEngine)(
            tool_dispatcher=self._dispatch_workflow_tool
        )
        self.approval_service = _facade_attr("get_approval_service", get_approval_service)()

{_lines(src, 132, 541)}


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
'''

    init_pkg = '''"""AI chat application layer package."""

from __future__ import annotations
'''

    shim = '''"""AI 聊天应用服务 — re-export shim (split into ai_chat/)."""

from __future__ import annotations

import httpx as httpx

from app.application.workflow import HybridRiskGate as HybridRiskGate
from app.application.workflow import LLMWorkflowPlanner as LLMWorkflowPlanner
from app.application.workflow import WorkflowEngine as WorkflowEngine
from app.application.workflow import get_approval_service as get_approval_service
from app.services import get_ai_conversation_service as get_ai_conversation_service

from .ai_chat.helpers import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS as _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
)
from .ai_chat.helpers import (
    _EXCEL_IMPORT_QTY_MEASURE_RE as _EXCEL_IMPORT_QTY_MEASURE_RE,
)
from .ai_chat.helpers import (
    _enrich_confirmation_inner as _enrich_confirmation_inner,
)
from .ai_chat.helpers import (
    _skip_pro_excel_deterministic_import as _skip_pro_excel_deterministic_import,
)
from .ai_chat.service import AIChatApplicationService as AIChatApplicationService
from .ai_chat.service import get_ai_chat_app_service as get_ai_chat_app_service
'''

    _write("ai_chat/__init__.py", init_pkg)
    _write("ai_chat/helpers.py", helpers)
    _write("ai_chat/excel_import_mixin.py", excel)
    _write("ai_chat/workflow_mixin.py", workflow)
    _write("ai_chat/tool_execution_mixin.py", tools)
    _write("ai_chat/service.py", service)
    _write("ai_chat_app_service.py", shim)


def main() -> None:
    # Preserve originals as .bak only in memory — we overwrite shims in place.
    # Caller should have clean git for these three files.
    split_ai_group_chat()
    print("split ai_group_chat: ok")
    split_super_employee()
    print("split super_employee: ok")
    split_ai_chat()
    print("split ai_chat: ok")


if __name__ == "__main__":
    main()
