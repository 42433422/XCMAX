"""Desktop-side cloud relay client.

The desktop runtime registers itself with the cloud relay, persists the private
desktop token locally, and polls the cloud for tasks submitted by the mobile app.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, cast

import httpx

from app.services.relay_gitops import GIT_OP_KINDS, handle_git_op
from app.utils.device_system.device_identity import get_stable_device_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir, get_desktop_state_dir

logger = logging.getLogger(__name__)

ClaudeSuperEmployeeService: Any | None = None
CodexSuperEmployeeService: Any | None = None
CursorSuperEmployeeService: Any | None = None
TraeSuperEmployeeService: Any | None = None

_STATE_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
# 配对凭证落在稳定的桌面态目录，绝不随源码 cwd 漂移（见 get_desktop_state_dir 文档）。
# 历史上 get_app_data_dir() 源码直跑会回落到仓库根，桌面便以与手机已配对 relay 不同
# 的身份去轮询，任务永远卡在「排队中」。
_CONFIG_FILE = Path(get_desktop_state_dir()) / "mobile_relay_desktop.json"


from app.services.mobile_relay_desktop_client_part01 import (
    _api_url as _api_url,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _complete_relay_task as _complete_relay_task,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _ensure_super_employee_service_classes as _ensure_super_employee_service_classes,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _extract_tool_calls as _extract_tool_calls,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _gc_orphan_workspaces as _gc_orphan_workspaces,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _max_concurrent as _max_concurrent,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _migrate_legacy_config_once as _migrate_legacy_config_once,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _poll_loop as _poll_loop,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _poll_once as _poll_once,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _public_payload_from_config as _public_payload_from_config,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _read_config as _read_config,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _relay_base_url as _relay_base_url,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _relay_http_client as _relay_http_client,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _relay_poll_backoff_seconds as _relay_poll_backoff_seconds,
)
from app.services.mobile_relay_desktop_client_part01 import (
    _write_config as _write_config,
)
from app.services.mobile_relay_desktop_client_part01 import (
    cached_desktop_relay_payload as cached_desktop_relay_payload,
)
from app.services.mobile_relay_desktop_client_part01 import (
    register_desktop_relay as register_desktop_relay,
)
from app.services.mobile_relay_desktop_client_part01 import (
    start_desktop_relay_poller as start_desktop_relay_poller,
)
from app.services.mobile_relay_desktop_client_part01 import (
    stop_desktop_relay_poller as stop_desktop_relay_poller,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _body_has_execution_evidence as _body_has_execution_evidence,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _body_indicates_failed as _body_indicates_failed,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _body_indicates_unfinished as _body_indicates_unfinished,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _classify_terminal_result as _classify_terminal_result,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _execute_task as _execute_task,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _extract_branch_after as _extract_branch_after,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _extract_merge_source as _extract_merge_source,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _extract_merge_target as _extract_merge_target,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _extract_target_branch as _extract_target_branch,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _git_op_from_message as _git_op_from_message,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _message_requires_execution_evidence as _message_requires_execution_evidence,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _terminal_codex_message as _terminal_codex_message,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _terminal_error_summary as _terminal_error_summary,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _text_mentions_branch_op as _text_mentions_branch_op,
)
from app.services.mobile_relay_desktop_client_part02 import (
    _trim_branch_token as _trim_branch_token,
)

# ruff: noqa: F401

_LEGACY_CONFIG_FILE = Path(get_app_data_dir()) / 'mobile_relay_desktop.json'

_LEGACY_MIGRATION_DONE = False

_INFLIGHT: set[str] = set()

_INFLIGHT_LOCK = threading.Lock()

_BRANCH_TOKEN_RE = re.compile('[A-Za-z0-9][A-Za-z0-9._/-]{0,179}')

_MERGE_TEXT_MARKERS = ('合并', 'merge')

_DIFF_TEXT_MARKERS = ('diff', '查看改动', '看改动')

_DISCARD_TEXT_MARKERS = ('discard', '丢弃', '删除分支', '废弃')

_FAILURE_BODY_MARKERS = ('BLOCKED', 'blocked', '未完成', '无法完成', '不能完成', '没有完成', '执行失败', '失败：', '验证未通过', '合并有冲突', 'merge conflict', '无改动可提交', '未产生可提交改动', '先不动代码', '只给出执行方案', '仅提供方案', '不能执行命令', '不能执行', '不能读工作区', '不能读取工作区', '不能跑测试', '未跑测试', '没有跑测试', '权限不足', '没有真实执行', '没有实际改动', '未修改文件', '无测试证据', '没有测试证据', '正在搜索', '正在实现', '正在处理', '正在执行', '搜索代码库', '我只出', '只出验收口径', '只出风险', '只出收口', '仅做验收', '仅做风险', '仅做收口', '仅做分析', '待回写', '等待回写', '❌')

_EXECUTION_MESSAGE_MARKERS = ('修复', '实现', '开发', '添加', '新增', '更新', '删除', '改造', '优化', '测试', '验收', '构建', '编译', '安装', '合并', 'bug', '功能', '页面', '接口', '代码', 'apk', 'branch', 'merge')

_EXECUTION_EVIDENCE_MARKERS = ('已修改', '修改了', '新增', '删除了', '更新了', '改动文件', '文件：', '测试通过', '验证通过', '编译通过', '构建通过', '安装成功', 'pytest', 'ruff', 'gradle', 'assemble', 'adb', 'git diff', 'commit', 'changed files', 'tests passed', 'test passed', 'command:', 'commands:', '命令：', '运行：', '验证：', '测试：', '构建：', '安装：', '手机复测', '真机复测', '群里复测')

_EVIDENCE_FILE_RE = re.compile('(?i)\\b[\\w./-]+\\.(py|kt|java|ts|tsx|js|jsx|json|ya?ml|md|gradle|xml|sql|swift|go|rs)\\b')

_FAILED_STATUSES = {'failed', 'error', 'merge_conflict', 'cancelled'}

_BLOCKED_STATUSES = {'blocked', 'timeout'}

_COMPLETED_STATUSES = {'completed', 'done', 'merged'}
