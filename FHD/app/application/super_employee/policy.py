"""Tool-specific chat intent, prompts, CLI discovery, and runtime settings."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from .common import _TASK_MARKERS
from .profiles import SuperEmployeeToolProfile


class EmployeePolicy:
    def __init__(self, profile: SuperEmployeeToolProfile) -> None:
        self._p = profile

    def should_reply_with_cli(self, text: str, context: dict[str, Any]) -> bool:
        force_direct = (
            (
                os.environ.get(f"{self._p.env_tool_prefix}_FORCE_CLI_DIRECT")
                or os.environ.get("XCMAX_FORCE_CLI_DIRECT")
                or ""
            )
            .strip()
            .lower()
        )
        if force_direct in {"1", "true", "yes", "on"}:
            return True
        if context.get("force_cli_direct") is True:
            return True
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return True
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return False
        normalized = re.sub("\\s+", "", text.strip().lower())
        if not normalized:
            return False
        return not any(marker in normalized for marker in _TASK_MARKERS)

    def is_task_intent(self, text: str, context: dict[str, Any]) -> bool:
        """是否为开发任务（需要真改代码），与 force-direct 无关，仅看 mode/关键词。"""
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return False
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return True
        normalized = re.sub("\\s+", "", text.strip().lower())
        if not normalized:
            return False
        return any(marker in normalized for marker in _TASK_MARKERS)

    def direct_reply_body(self, text: str) -> str:
        normalized = re.sub("[\\s，。！？!?、,.]+", "", text.strip().lower())
        if not normalized:
            return ""
        tool = self._p.display_tool
        name = self._p.employee_name
        identity_prompts = {
            "你是谁",
            "你是誰",
            "你谁",
            "你是哪个",
            "你是什么",
            "whoareyou",
            "whatareyou",
        }
        help_prompts = {
            "你能做什么",
            "你能干什么",
            "你会什么",
            "怎么用",
            "如何使用",
            "帮助",
            "help",
        }
        greeting_prompts = {"你好", "在吗", "在不在", "hello", "hi"}
        slow_prompts = {"为什么这么慢", "为啥这么慢", "为什么出不来", "怎么出不来"}
        if normalized in identity_prompts:
            return f"我是{name}。你在软件里发普通问题时，我会直接回复；你发开发、测试、打包、提交、跨设备协作这类任务时，我会调用可用的 {tool} 工作设备完成。"
        if normalized in help_prompts:
            return "你可以直接给我派开发任务，例如修复某个页面、跑测试、打包移动端、提交代码。如果只是问身份、用法或状态，我会在这里直接回复，不进入多设备派工。"
        if normalized in greeting_prompts:
            return "我在。需要改代码、跑验证或跨设备协作时，直接把任务发给我。"
        if normalized in slow_prompts:
            return "慢是因为这类消息之前被误当成开发任务派到多设备队列，必须等工作设备回传才显示结果。现在身份、帮助和问候类消息会直接回复；真正的开发任务才进入派工。"
        return ""

    def cli_prompt(self, text: str) -> str:
        return f"你是 XCMAX 软件内的{self._p.employee_name}。请直接回答用户的问题。这是普通对话通道：不要执行命令，不要修改文件，不要调用工具。如果用户询问额度、账户余额、订阅或实时账户状态，而你无法从当前会话读取真实账户数据，请明确说明不能查看，不要编造数字。\n\n用户问题：{text.strip()}"

    def cli_work_prompt(self, text: str, cwd: str) -> str:
        """开发任务 prompt：授权 Claude 真正读写/修改工作区文件（配合 --permission-mode acceptEdits）。"""
        return f"你是 XCMAX 软件内的{self._p.employee_name}，运行在项目工作区，拥有完整的文件读写与代码修改能力。请直接动手完成下面的开发任务：按需读取、创建、修改工作区内的文件来实现需求；不要只给建议或只解释，要真正改代码。完成后用一两句话总结你改了哪些文件、做了什么。\n\n工作区根目录：{cwd}\n\n开发任务：\n{text.strip()}"

    def cli_fix_prompt(self, verify_msg: str, cwd: str) -> str:
        return (
            f"你刚才在工作区 {cwd} 的改动未通过验证。请直接修改文件修复下面的错误，改到能通过为止，不要只解释。\n\n验证错误：\n"
            + verify_msg[:1500]
        )

    def conversation_mode_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_CONVERSATION")
                or os.environ.get("XCMAX_CLAUDE_CONVERSATION")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def dev_loop_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_DEV_LOOP")
                or os.environ.get("XCMAX_CLAUDE_DEV_LOOP")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def cli_path(self) -> str:
        candidates = [
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_PATH", ""),
            shutil.which(self._p.cli_binary) or "",
            *self._p.cli_extra_candidates,
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value and Path(value).is_file():
                return value
        return ""

    def cli_idle_timeout_seconds(self) -> float:
        raw = (
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_IDLE_TIMEOUT_SEC")
            or os.environ.get(f"{self._p.env_tool_prefix}_CLI_TIMEOUT_SEC")
            or "180"
        )
        try:
            return max(15.0, float(raw))
        except (TypeError, ValueError):
            return 180.0

    def cli_hard_cap_seconds(self) -> float:
        raw = os.environ.get(f"{self._p.env_tool_prefix}_CLI_HARD_CAP_SEC") or "3600"
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 3600.0

    def cli_timeout_seconds(self) -> float:
        """Backward-compat alias for _cli_idle_timeout_seconds (used by tests)."""
        return self.cli_idle_timeout_seconds()
