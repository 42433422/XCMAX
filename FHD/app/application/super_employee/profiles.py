"""Tool identity and command construction; independent of dispatch or persistence."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


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
