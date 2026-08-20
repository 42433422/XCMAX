# ruff: noqa: E402, F401
"""Generic super-employee dispatch channel (Codex / Claude / ...).

This is the shared engine behind every "超级员工" entity. A concrete tool
(Codex, Claude, ...) is described by a :class:`SuperEmployeeToolProfile`; the
service logic — persisting software-internal calls, optionally dispatching them
to the Para/DevFleet multi-device scheduler (排比), polling task status and
writing back results — is identical across tools.

Codex behaviour is preserved verbatim through ``CODEX_PROFILE`` so the existing
``CodexSuperEmployeeService`` is a thin subclass with no behavioural change.
"""

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
from dataclasses import dataclass
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
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

DEFAULT_PARA_API_URL = "http://127.0.0.1:3001"
DISPATCHER_MESSAGE_KIND = "dispatcher"

# 持久复用 worktree 的串行锁（按 worktree 路径隔离）。中继真仓库模式下，同一工具复用一个
# worktree（620M 只建一次），并发任务必须排队使用，避免 git 状态相互踩踏。
_RELAY_WT_LOCKS: dict[str, threading.Lock] = {}
_RELAY_WT_LOCKS_GUARD = threading.Lock()


def _relay_wt_lock(key: str) -> threading.Lock:
    with _RELAY_WT_LOCKS_GUARD:
        return _RELAY_WT_LOCKS.setdefault(key, threading.Lock())


# Para guest-token 模块级缓存。devfleet 对 /api/auth/guest 限 15min 30 次
# (authLimiter)，原来每次 invoke 都新登 → 用户连发几十条消息就触发
# "登录请求过于频繁，请稍后重试" 429。缓存按 (api_url, env_super_prefix) 隔离，
# TTL 远短于 token 真实寿命，到期重登；任何错误立即清缓存避免脏 token。
_PARA_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_PARA_TOKEN_TTL = float(os.environ.get("MODSTORE_PARA_TOKEN_TTL_SEC") or "600")

PARA_TERMINAL_TASK_STATUSES = {"completed", "failed", "merged", "merge_conflict", "cancelled"}
TASK_ID_RE = re.compile(r"任务\s*ID[:：]\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})")

# 任务类关键词：命中则走 Para 多设备派工，否则走 CLI 直答。工具无关，共享。
_TASK_MARKERS: tuple[str, ...] = (
    "修复",
    "修改",
    "改一下",
    "改成",
    "实现",
    "新增",
    "加一个",
    "接入",
    "打通",
    "任务",
    "测试",
    "验证",
    "跑测试",
    "测试一下",
    "验证一下",
    "打包",
    "构建",
    "build",
    "提交",
    "commit",
    "push",
    "上传git",
    "部署",
    "发布",
    "合并",
    "开分支",
    "派工",
    "调用",
    "调用所有设备",
    "多设备",
    "回写日志",
    "检查当前工作区",
)
# 多设备分工标签，工具无关，共享。
_SUBTASK_LABELS: tuple[str, ...] = ("需求定位与方案", "核心实现", "验证与收尾")


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _chunk_text(text: str, max_len: int = 120) -> list[str]:
    """把完整文本切成 SSE token chunk（按句号/换行，每块 <= max_len 字）。"""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?\n])", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > max_len:
            if buf:
                chunks.append(buf)
            if len(p) > max_len:
                chunks.append(p)
                buf = ""
            else:
                buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    return chunks or [text]


def _codex_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    sandbox = (
        os.environ.get("XCMAX_CODEX_SANDBOX_MODE")
        or os.environ.get("DEVFLEET_CODEX_SANDBOX_MODE")
        or "workspace-write"
    ).strip()
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        sandbox = "workspace-write"
    return [
        cli_path,
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        sandbox,
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-last-message",
        str(output_path),
        "-C",
        cwd,
        prompt,
    ]


def _cursor_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    # Cursor Agent CLI headless（cursor agent --print）。stream-json 作心跳；
    # --trust 跳过无 TTY 时的 workspace 信任提示；--force 允许在 cwd 内改/建文件。
    trust_raw = (
        (
            os.environ.get("DEVFLEET_CURSOR_TRUST")
            or os.environ.get("XCMAX_CURSOR_AGENT_TRUST")
            or "1"
        )
        .strip()
        .lower()
    )
    force_raw = (
        (
            os.environ.get("DEVFLEET_CURSOR_FORCE")
            or os.environ.get("XCMAX_CURSOR_AGENT_FORCE")
            or "1"
        )
        .strip()
        .lower()
    )
    cmd = [cli_path]
    # 独立的 cursor-agent 二进制本身就是 agent，不再接 "agent" 子命令；
    # 旧的 cursor 二进制才用 `cursor agent --print`。trae-cn 沿用同构建器也无 agent 子命令。
    if os.path.basename(cli_path) not in {"cursor-agent", "trae-cn"}:
        cmd.append("agent")
    cmd += ["--print", "--output-format", "stream-json"]
    if trust_raw not in {"0", "false", "off", "disabled"}:
        cmd.append("--trust")
    if force_raw not in {"0", "false", "off", "disabled"}:
        cmd.append("--force")
    cmd.append(prompt)
    return cmd


def _trae_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    # Trae 企业版 trae-cli 无头 agent（与 cursor-agent 同族）：
    # ``trae-cli --print --output-format stream-json [-y] <prompt>``。
    # -y/--yolo 绕过工具权限确认，让它能在 cwd 内真改文件（对应 cursor 的 --force）。
    cmd = [cli_path, "--print", "--output-format", "stream-json"]
    yolo = (
        (os.environ.get("DEVFLEET_TRAE_YOLO") or os.environ.get("XCMAX_TRAE_YOLO") or "1")
        .strip()
        .lower()
    )
    if yolo not in {"0", "false", "off", "disabled"}:
        cmd.append("--yolo")
    cmd.append(prompt)
    return cmd


def _claude_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    # Claude Code 无头模式（print）。stream-json：工作时持续吐事件(工具调用/文本)，
    # 作为"还在干活"的心跳，配合 idle-timeout 实现"只要在工作就不超时"。
    # stream-json 在 print 模式需 --verbose。acceptEdits 允许在 cwd 内改/建文件。
    perm = (
        os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
    ).strip() or "acceptEdits"
    return [
        cli_path,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        perm,
        prompt,
    ]


@dataclass(frozen=True)
class SuperEmployeeToolProfile:
    """A concrete super-employee tool's identity + dispatch configuration."""

    employee_id: str
    employee_name: str
    display_tool: str  # 用户可见的工具名，如 "Codex" / "Claude"
    tool_name: str  # Para devTool / toolName，如 "codex" / "claude"
    capability_key: str  # Para 设备能力键，如 "codex_cli" / "claude_cli"
    storage_subdir: str  # 持久化子目录
    result_kind: str  # 结果消息 kind
    direct_kind: str  # 直答消息 kind
    env_super_prefix: str  # 形如 "XCMAX_CODEX_SUPER_EMPLOYEE"
    env_tool_prefix: str  # 形如 "XCMAX_CODEX"
    cli_binary: str  # 可执行名，用于 shutil.which
    cli_extra_candidates: tuple[str, ...] = ()
    cli_reads_output_file: bool = True  # 是否从 --output-last-message 文件读结果
    cli_stream_json: bool = False  # stdout 是否为 stream-json(逐事件)，需解析出最终回复
    cli_command_builder: Callable[[str, str, Path, str], list[str]] = _codex_cli_command
    avatar_key: str = ""  # 前端/App 识别：codex | claude | cursor
    avatar_path: str = ""  # 静态资源路径（相对站点根，如 /brand/cursor-app-icon.png）


CODEX_PROFILE = SuperEmployeeToolProfile(
    employee_id="codex-super-employee",
    employee_name="超级员工-Codex",
    display_tool="Codex",
    tool_name="codex",
    capability_key="codex_cli",
    storage_subdir="codex_super_employee",
    result_kind="codex_result",
    direct_kind="codex_direct",
    env_super_prefix="XCMAX_CODEX_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_CODEX",
    cli_binary="codex",
    cli_extra_candidates=("/Applications/Codex.app/Contents/Resources/codex",),
    cli_reads_output_file=True,
    cli_command_builder=_codex_cli_command,
    avatar_key="codex",
    avatar_path="/brand/codex-app-icon.png",
)

CLAUDE_PROFILE = SuperEmployeeToolProfile(
    employee_id="claude-super-employee",
    employee_name="超级员工-Claude",
    display_tool="Claude",
    tool_name="claude_code",
    capability_key="claude_cli",
    storage_subdir="claude_super_employee",
    result_kind="claude_result",
    direct_kind="claude_direct",
    env_super_prefix="XCMAX_CLAUDE_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_CLAUDE",
    cli_binary="claude",
    cli_extra_candidates=(
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ),
    cli_reads_output_file=False,
    cli_stream_json=True,
    cli_command_builder=_claude_cli_command,
    avatar_key="claude",
    avatar_path="/brand/claude-app-icon.svg",
)

CURSOR_PROFILE = SuperEmployeeToolProfile(
    employee_id="cursor-super-employee",
    employee_name="超级员工-Cursor",
    display_tool="Cursor",
    tool_name="cursor_agent",
    capability_key="cursor_cli",
    storage_subdir="cursor_super_employee",
    result_kind="cursor_result",
    direct_kind="cursor_direct",
    env_super_prefix="XCMAX_CURSOR_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_CURSOR",
    cli_binary="cursor-agent",
    cli_extra_candidates=(
        os.path.expanduser("~/.local/bin/cursor-agent"),
        "/opt/homebrew/bin/cursor-agent",
        "/usr/local/bin/cursor-agent",
        "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
        os.path.expanduser("~/.local/bin/cursor"),
    ),
    cli_reads_output_file=False,
    cli_stream_json=True,
    cli_command_builder=_cursor_cli_command,
    avatar_key="cursor",
    avatar_path="/brand/cursor-app-icon.png",
)

TRAE_PROFILE = SuperEmployeeToolProfile(
    employee_id="trae-super-employee",
    employee_name="超级员工-Trae",
    display_tool="Trae",
    tool_name="trae",
    capability_key="trae_cli",
    storage_subdir="trae_super_employee",
    result_kind="trae_result",
    direct_kind="trae_direct",
    env_super_prefix="XCMAX_TRAE_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_TRAE",
    cli_binary="trae-cli",
    cli_extra_candidates=(
        os.path.expanduser("~/.local/bin/trae-cli"),
        os.path.expanduser("~/.local/bin/trae-agent"),
        os.path.expanduser("~/.local/bin/traecli"),
        "/opt/homebrew/bin/trae-cli",
        "/usr/local/bin/trae-cli",
    ),
    cli_reads_output_file=False,
    cli_stream_json=True,
    cli_command_builder=_trae_cli_command,
    avatar_key="trae",
    avatar_path="/brand/trae-app-icon.png",
)


from app.application.super_employee_service_superemployeeservice_mixin01 import (
    _SuperEmployeeServicePart01Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin02 import (
    _SuperEmployeeServicePart02Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin03 import (
    _SuperEmployeeServicePart03Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin04 import (
    _SuperEmployeeServicePart04Mixin,
)


class SuperEmployeeService(
    _SuperEmployeeServicePart01Mixin,
    _SuperEmployeeServicePart02Mixin,
    _SuperEmployeeServicePart03Mixin,
    _SuperEmployeeServicePart04Mixin,
):
    """Persist software-internal tool calls and optionally dispatch them out."""

    # ── 公开 API ──

    # ── LAN SSE 流式直答 ──

    # ── Para 分级派工：一级=本机单设备，二级=多设备协同 ──
    #
    # 「本机 CLI」并入 Para 后不再是绕开派工的进程内旁路，而是 Para 派工状态机里
    # 的显式一级状态(para_tier=1)：把任务派给一台在线的本机/主设备，与二级走同一
    # 条 /api/tasks 管线。默认一级优先，仅当任务确需多设备并行/分工、或本机无可用
    # 设备、或调用方显式要求时升二级。设备的配对(bind_code)与 e2e-agent 拉起属于
    # DevFleet/运维侧，FHD 只消费已在线的设备、不伪造设备行。

    # ===== 口袋 Claude Code：持久会话续接 + 隔离工作区 =====

    # ===== coding → view → push 闭环（开发任务）=====


__all__ = [
    "DISPATCHER_MESSAGE_KIND",
    "CODEX_PROFILE",
    "CLAUDE_PROFILE",
    "CURSOR_PROFILE",
    "TRAE_PROFILE",
    "SuperEmployeeService",
    "SuperEmployeeToolProfile",
]
