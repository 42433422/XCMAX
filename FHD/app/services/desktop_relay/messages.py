"""Pure relay message interpretation and terminal-result policy."""

from __future__ import annotations

import re
from typing import Any

from app.services.relay_gitops import GIT_OP_KINDS

_BRANCH_TOKEN_RE = re.compile("[A-Za-z0-9][A-Za-z0-9._/-]{0,179}")

_MERGE_TEXT_MARKERS = ("合并", "merge")

_DIFF_TEXT_MARKERS = ("diff", "查看改动", "看改动")

_DISCARD_TEXT_MARKERS = ("discard", "丢弃", "删除分支", "废弃")

_FAILURE_BODY_MARKERS = (
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
    "未跑测试",
    "没有跑测试",
    "权限不足",
    "没有真实执行",
    "没有实际改动",
    "未修改文件",
    "无测试证据",
    "没有测试证据",
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
    "待回写",
    "等待回写",
    "❌",
)

_EXECUTION_MESSAGE_MARKERS = (
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

_EVIDENCE_FILE_RE = re.compile(
    "(?i)\\b[\\w./-]+\\.(py|kt|java|ts|tsx|js|jsx|json|ya?ml|md|gradle|xml|sql|swift|go|rs)\\b"
)

_FAILED_STATUSES = {"failed", "error", "merge_conflict", "cancelled"}

_BLOCKED_STATUSES = {"blocked", "timeout"}

_COMPLETED_STATUSES = {"completed", "done", "merged"}


def _git_op_from_message(
    payload: dict[str, Any], message: str
) -> tuple[str, dict[str, Any]] | None:
    text = str(message or "").strip()
    lowered = text.lower()
    explicit = str(payload.get("git_op") or payload.get("op") or "").strip()
    explicit_git_op = explicit in GIT_OP_KINDS
    if explicit in GIT_OP_KINDS:
        git_kind = explicit
    elif any(marker in lowered for marker in _MERGE_TEXT_MARKERS):
        git_kind = "git.merge"
    elif any(marker in lowered for marker in _DIFF_TEXT_MARKERS):
        git_kind = "git.diff"
    elif any(marker in lowered for marker in _DISCARD_TEXT_MARKERS):
        git_kind = "git.discard"
    else:
        return None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    text_source = _extract_branch_after(text, "SOURCE_", "_TARGET") or _extract_merge_source(text)
    allow_selected_branch = explicit_git_op or _text_mentions_branch_op(text, lowered)
    if not isinstance(context, dict):
        context = {}
    source = (
        str(payload.get("source_branch") or "").strip()
        or text_source
        or (str(payload.get("branch") or "").strip() if allow_selected_branch else "")
        or (str(context.get("branch") or "").strip() if allow_selected_branch else "")
    )
    target = str(
        payload.get("target_branch") or payload.get("target") or payload.get("base") or ""
    ).strip() or _extract_target_branch(text)
    if git_kind == "git.merge" and (not target):
        target = _extract_merge_target(text)
    if not source:
        return None
    git_payload = {**payload, "branch": source, "message": text}
    if target:
        git_payload["target_branch"] = target
    return (git_kind, git_payload)


def _text_mentions_branch_op(text: str, lowered: str) -> bool:
    return any(
        marker in text or marker in lowered
        for marker in (
            "合并分支",
            "这个分支",
            "当前分支",
            "待合并分支",
            "merge branch",
            "current branch",
            "source branch",
            "target branch",
            "查看分支",
            "丢弃分支",
            "删除分支",
        )
    )


def _extract_branch_after(text: str, prefix: str, suffix: str) -> str:
    pattern = re.compile(
        f"{re.escape(prefix)}(?P<branch>[A-Za-z0-9._/-]+?){re.escape(suffix)}",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_target_branch(text: str) -> str:
    match = re.search("TARGET(?:_CURRENT)?_(?P<branch>[A-Za-z0-9._/-]+)", text, re.IGNORECASE)
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_source(text: str) -> str:
    match = re.search(
        "(?:合并|merge)\\s+(?:分支\\s*)?(?P<branch>[A-Za-z0-9._/-]+)", text, re.IGNORECASE
    )
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_target(text: str) -> str:
    match = re.search(
        "(?:到|至|into|->)\\s*(?:分支\\s*)?(?P<branch>[A-Za-z0-9._/-]+)",
        text,
        re.IGNORECASE,
    )
    return _trim_branch_token(match.group("branch")) if match else ""


def _trim_branch_token(value: str) -> str:
    branch = str(value or "").strip().strip("，,。.;；")
    for marker in (
        "_CHECK",
        "_IF",
        "_RUN",
        "_REPORT",
        "_DO",
        "_SAFE",
        "_STATUS",
        "_FIRST",
        "_THEN",
    ):
        idx = branch.upper().find(marker)
        if idx > 0:
            branch = branch[:idx]
            break
    match = _BRANCH_TOKEN_RE.search(branch)
    return match.group(0) if match else ""


def _classify_terminal_result(row: dict[str, Any], *, message: str) -> tuple[bool, str, str]:
    status = str(row.get("status") or row.get("task_status") or "").strip().lower()
    body = str(row.get("body") or row.get("summary") or row.get("message") or "").strip()
    if status in _FAILED_STATUSES:
        return (False, "failed", _terminal_error_summary(body, "执行端回写失败"))
    if status in _BLOCKED_STATUSES:
        return (False, "blocked", _terminal_error_summary(body, "执行端回写阻塞"))
    if body and _body_indicates_unfinished(body):
        relay_status = "failed" if _body_indicates_failed(body) else "blocked"
        return (
            False,
            relay_status,
            _terminal_error_summary(body, "执行端回写显示未完成"),
        )
    if _message_requires_execution_evidence(message) and (not _body_has_execution_evidence(body)):
        return (
            False,
            "blocked",
            _terminal_error_summary(body, "执行端回写缺少改动文件、命令、测试、构建或手机复测证据"),
        )
    if status in _COMPLETED_STATUSES or body:
        return (True, "completed", "")
    return (True, "completed", "")


def _body_indicates_unfinished(body: str) -> bool:
    if not body:
        return False
    compact = body.replace(" ", "")
    return any(
        marker in body or marker.replace(" ", "") in compact for marker in _FAILURE_BODY_MARKERS
    )


def _body_indicates_failed(body: str) -> bool:
    return any(
        marker in body
        for marker in (
            "失败",
            "failed",
            "合并有冲突",
            "merge conflict",
            "验证未通过",
            "❌",
            "error",
            "Error",
        )
    )


def _message_requires_execution_evidence(message: str) -> bool:
    text = str(message or "").lower()
    return any(marker.lower() in text for marker in _EXECUTION_MESSAGE_MARKERS)


def _body_has_execution_evidence(body: str) -> bool:
    text = str(body or "")
    if not text or _body_indicates_unfinished(text):
        return False
    lower = text.lower()
    if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
        return True
    return _EVIDENCE_FILE_RE.search(text) is not None


def _terminal_error_summary(body: str, fallback: str) -> str:
    for line in body.splitlines():
        clean = line.strip().strip("-*# ")
        if clean:
            return clean[:500]
    return fallback


def _terminal_codex_message(
    messages: list[dict[str, Any]], *, request_id: str, task_id: str
) -> dict[str, Any] | None:
    for row in messages[::-1]:
        if str(row.get("role") or "").strip().lower() != "assistant":
            continue
        kind = str(row.get("kind") or "").strip().lower()
        if not (kind.endswith("_result") or kind.endswith("_direct")):
            continue
        row_request = str(row.get("dispatch_request_id") or row.get("request_id") or "").strip()
        row_task = str(row.get("task_id") or "").strip()
        if request_id and row_request != request_id:
            continue
        if task_id and row_task != task_id:
            continue
        if str(row.get("body") or "").strip():
            return row
    return None


def _extract_tool_calls(assistant: dict[str, Any], tool_label: str) -> list[dict[str, Any]]:
    """从 assistant_message body 里提取 dev-loop 关键步骤，供手机端时间线展示。

    dev-loop 结束文本含 "闭环结果" 段落（分支/验证/推送），据此解析。
    非开发任务（闲聊直答）返回空列表。
    """
    body = str(assistant.get("body") or assistant.get("content") or "").strip()
    if not body or "闭环结果" not in body:
        return []
    import re

    calls: list[dict[str, Any]] = []
    m = re.search("分支[：:]\\s*(\\S+)", body)
    if m:
        calls.append(
            {
                "action": "create_branch",
                "icon": "branch",
                "label": f"创建分支 {m.group(1)}",
                "detail": m.group(1),
            }
        )
    m = re.search("验证[：:]\\s*(通过|未通过)[（(]([^)）]*)", body)
    if m:
        ok = m.group(1) == "通过"
        calls.append(
            {
                "action": "verify",
                "icon": "check",
                "label": f"验证{('通过' if ok else '未通过')}",
                "detail": m.group(2)[:200],
                "success": ok,
            }
        )
    m = re.search("推送[：:]\\s*(.+?)(?:\\n|$)", body)
    if m:
        push_text = m.group(1).strip()[:200]
        calls.append(
            {
                "action": "push",
                "icon": "upload",
                "label": "推送分支",
                "detail": push_text,
                "success": "成功" in push_text or "已推送" in push_text,
            }
        )
    calls.insert(
        0,
        {
            "action": "cli_run",
            "icon": "terminal",
            "label": f"{tool_label} CLI 执行",
            "detail": "调用无头 agent 修改代码",
        },
    )
    return calls
