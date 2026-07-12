"""Shared constants for AI group chat."""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

MAX_RESPONDERS = 6
# 喂给单个 AI 的群历史条数。
CONTEXT_TURNS = 10


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


# 超级员工执行任务前的群内讨论轮数：每轮每个超级员工最多发言一次。
SUPER_DISCUSSION_DEFAULT_ROUNDS = 1
SUPER_DISCUSSION_MAX_ROUNDS = 2
# 手机聊天气泡里只放能看懂的摘要，完整执行输出留在中继任务结果里。
CHAT_REPORT_SUMMARY_CHARS = 180
CHAT_ACCEPTANCE_SUMMARY_CHARS = 44
PUBLIC_CHAT_BODY_MAX_CHARS = 900
PUBLIC_ACCEPTANCE_BODY_MAX_CHARS = 620
RELAY_PROGRESS_MIN_INTERVAL_SEC = 30
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]{1,100})\]\([^)]+\)")
_BROKEN_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]{1,100})\]\([^，。；\s]*")
_TEMP_PATH_RE = re.compile(r"(/private)?/var/folders/[^\s，。；)]+")
_RELAY_TASK_ID_RE = re.compile(r"；中继任务：[0-9a-f]{16,}。?")
_UNFINISHED_REPORT_MARKERS = (
    "BLOCKED",
    "blocked",
    "未完成",
    "无法完成",
    "不能完成",
    "没有完成",
    "执行失败",
    "失败：",
    "验证未通过",
    "合并有冲突",
    "merge conflict",
    "无改动可提交",
    "未产生可提交改动",
    "先不动代码",
    "只给出执行方案",
    "仅提供方案",
    "不能执行命令",
    "不能执行",
    "不能读工作区",
    "不能读取工作区",
    "不能跑测试",
    "只读沙盒",
    "只读环境",
    "read-only sandbox",
    "read only sandbox",
    "写入被",
    "写入失败",
    "落盘失败",
    "未落盘",
    "没有落盘",
    "没能落盘",
    "无法落盘",
    "补丁未应用",
    "patch 未应用",
    "patch没有应用",
    "patch 没有应用",
    "apply_patch failed",
    "apply_patch 没能",
    "apply_patch没能",
    "未跑测试",
    "没有跑测试",
    "不能安装 APK",
    "未安装 APK",
    "没有安装 APK",
    "权限不足",
    "没有真实执行",
    "没有实际改动",
    "未修改文件",
    "无测试证据",
    "没有测试证据",
    "不能给你伪造",
    "正在搜索",
    "正在实现",
    "正在处理",
    "正在执行",
    "搜索代码库",
    "我只出",
    "只出验收口径",
    "只出风险",
    "只出收口",
    "仅做验收",
    "仅做风险",
    "仅做收口",
    "仅做分析",
    "还在",
    "待回写",
    "等待回写",
    "❌",
)
_FAILED_REPORT_MARKERS = (
    "失败",
    "failed",
    "合并有冲突",
    "merge conflict",
    "验证未通过",
    "❌",
    "error",
    "Error",
)
_RESEARCH_ONLY_REPORT_MARKERS = (
    "调研",
    "调查",
    "分析",
    "定位",
    "建议",
    "方案",
    "思路",
    "可以这样",
    "后续可以",
    "下一步可以",
)
_EXECUTION_EVIDENCE_MARKERS = (
    "已修改",
    "修改了",
    "新增",
    "删除了",
    "更新了",
    "改动文件",
    "文件：",
    "测试通过",
    "验证通过",
    "编译通过",
    "构建通过",
    "安装成功",
    "pytest",
    "ruff",
    "gradle",
    "assemble",
    "adb",
    "git diff",
    "commit",
    "changed files",
    "tests passed",
    "test passed",
    "command:",
    "commands:",
    "命令：",
    "运行：",
    "验证：",
    "测试：",
    "构建：",
    "安装：",
    "手机复测",
    "真机复测",
    "群里复测",
)
_DEV_TASK_MARKERS = (
    "修复",
    "实现",
    "开发",
    "添加",
    "新增",
    "更新",
    "删除",
    "改造",
    "优化",
    "测试",
    "验收",
    "构建",
    "编译",
    "安装",
    "合并",
    "bug",
    "功能",
    "页面",
    "接口",
    "代码",
    "apk",
    "branch",
    "merge",
)
_PURE_RESEARCH_TASK_MARKERS = ("调研", "调查", "分析一下", "评估", "讨论", "方案")
_EVIDENCE_FILE_RE = re.compile(
    r"(?i)\b[\w./-]+\.(py|kt|java|ts|tsx|js|jsx|json|ya?ml|md|gradle|xml|sql|swift|go|rs)\b"
)
# 群内执行前讨论不能把手机端派工长时间卡死；超时后走确定性分流兜底。
SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC = max(
    0.5,
    min(_env_float("XCAGI_GROUP_DISCUSSION_LLM_TIMEOUT_SEC", 3.0), 30.0),
)
# 超级员工 employee_id 集合：命中时走专用 invoke 通道而非 mod_employee_complete。
_SUPER_EMPLOYEE_IDS: frozenset[str] = frozenset(
    {
        "codex-super-employee",
        "claude-super-employee",
        "cursor-super-employee",
        "trae-super-employee",
    }
)
_LEGACY_SUPER_EMPLOYEE_IDS: frozenset[str] = frozenset(
    {
        "codex-super-employee",
        "claude-super-employee",
        "cursor-super-employee",
    }
)
_DEFAULT_SINGLE_CLI_EMPLOYEE_ID = "codex-super-employee"
_SUPER_EMPLOYEE_RELAY_KINDS: dict[str, str] = {
    "codex-super-employee": "codex.invoke",
    "cursor-super-employee": "cursor.invoke",
    "claude-super-employee": "claude.invoke",
    "trae-super-employee": "trae.invoke",
}
_XIAOC_ASSISTANT_ID = "xcagi-assistant"
_REQUIRED_GROUP_MEMBER_IDS: frozenset[str] = frozenset({_XIAOC_ASSISTANT_ID})
_BRANCH_SAFE_RE = re.compile(r"[^A-Za-z0-9._/-]+")

CompletionFn = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]
EmployeeExecutorFn = Callable[
    [str, str, dict[str, Any], int],
    dict[str, Any] | Awaitable[dict[str, Any]],
]

__all__ = [
    "MAX_RESPONDERS",
    "CONTEXT_TURNS",
    "_env_float",
    "SUPER_DISCUSSION_DEFAULT_ROUNDS",
    "SUPER_DISCUSSION_MAX_ROUNDS",
    "CHAT_REPORT_SUMMARY_CHARS",
    "CHAT_ACCEPTANCE_SUMMARY_CHARS",
    "PUBLIC_CHAT_BODY_MAX_CHARS",
    "PUBLIC_ACCEPTANCE_BODY_MAX_CHARS",
    "RELAY_PROGRESS_MIN_INTERVAL_SEC",
    "_MARKDOWN_LINK_RE",
    "_BROKEN_MARKDOWN_LINK_RE",
    "_TEMP_PATH_RE",
    "_RELAY_TASK_ID_RE",
    "_UNFINISHED_REPORT_MARKERS",
    "_FAILED_REPORT_MARKERS",
    "_RESEARCH_ONLY_REPORT_MARKERS",
    "_EXECUTION_EVIDENCE_MARKERS",
    "_DEV_TASK_MARKERS",
    "_PURE_RESEARCH_TASK_MARKERS",
    "_EVIDENCE_FILE_RE",
    "SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC",
    "_SUPER_EMPLOYEE_IDS",
    "_LEGACY_SUPER_EMPLOYEE_IDS",
    "_DEFAULT_SINGLE_CLI_EMPLOYEE_ID",
    "_SUPER_EMPLOYEE_RELAY_KINDS",
    "_XIAOC_ASSISTANT_ID",
    "_REQUIRED_GROUP_MEMBER_IDS",
    "_BRANCH_SAFE_RE",
    "CompletionFn",
    "EmployeeExecutorFn",
]

