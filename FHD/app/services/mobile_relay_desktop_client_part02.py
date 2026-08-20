# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.mobile_relay_desktop_client")


def _execute_task(task: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    kind = str(task.get("kind") or "codex.invoke").strip()
    raw_payload = task.get("payload")
    payload: dict[str, _facade().Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    if kind in _facade().GIT_OP_KINDS:
        return _facade().handle_git_op(kind, payload)
    message = str(
        payload.get("message")
        or payload.get("body")
        or payload.get("prompt")
        or payload.get("task")
        or ""
    ).strip()
    if not message:
        return {"error": "任务缺少 message"}
    parsed_git_op = _facade()._git_op_from_message(payload, message)
    if parsed_git_op is not None:
        (git_kind, git_payload) = parsed_git_op
        return _facade().handle_git_op(git_kind, git_payload)
    _facade()._ensure_super_employee_service_classes()
    claude_service_class = _facade().ClaudeSuperEmployeeService
    codex_service_class = _facade().CodexSuperEmployeeService
    cursor_service_class = _facade().CursorSuperEmployeeService
    trae_service_class = _facade().TraeSuperEmployeeService
    if (
        claude_service_class is None
        or codex_service_class is None
        or cursor_service_class is None
        or (trae_service_class is None)
    ):
        return {"error": "超级员工服务加载失败"}
    if kind.startswith("claude"):
        service: _facade().Any = claude_service_class()
        tool_label = "Claude"
    elif kind.startswith("cursor"):
        service = cursor_service_class()
        tool_label = "Cursor"
    elif kind.startswith("trae"):
        service = trae_service_class()
        tool_label = "Trae"
    elif kind.startswith("codex"):
        service = codex_service_class()
        tool_label = "Codex"
    else:
        return {"error": f"暂不支持的任务类型：{kind}"}
    if not isinstance(task, dict):
        task = {}
    user_id = int(task.get("created_by_user_id") or payload.get("user_id") or 1)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    branch = str(payload.get("branch") or "").strip()
    if not isinstance(context, dict):
        context = {}
    workspace_root = str(
        context.get("workspace_root") or payload.get("workspace_root") or ""
    ).strip()
    orig_surface = str(context.get("client_surface") or "").strip().lower()
    is_work_order = (
        orig_surface == "ai_group"
        or bool(str(context.get("work_order_id") or "").strip())
        or bool(str(context.get("assigned_task") or "").strip())
    )
    context = {
        **context,
        "source": "mobile_relay",
        "relay_task_id": str(task.get("task_id") or ""),
        "client_surface": orig_surface or "mobile",
        "target_devices": ["all"],
        "force_cli_direct": True,
    }
    if branch and (not str(context.get("branch") or "").strip()):
        context["branch"] = branch
    if workspace_root and (not str(context.get("workspace_root") or "").strip()):
        context["workspace_root"] = workspace_root
    if is_work_order:
        context["mode"] = "code"
    elif str(context.get("mode") or "").strip().lower() in {
        "code",
        "task",
        "dispatch",
        "dev",
        "develop",
    }:
        context.pop("mode", None)
    try:
        result = service.invoke(user_id=user_id, message=message, context=context)
        dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
        dispatch_status = str(dispatch.get("status") or "").strip().lower()
        if dispatch_status == "completed":
            assistant = (
                result.get("assistant_message")
                if isinstance(result.get("assistant_message"), dict)
                else {}
            )
            (ok, relay_status, error) = _facade()._classify_terminal_result(
                assistant, message=message
            )
            tool_calls = _facade()._extract_tool_calls(assistant, tool_label)
            if tool_calls:
                result["tool_calls"] = tool_calls
            if ok:
                return {"ok": True, "codex": result, "_relay_status": "completed"}
            return {
                "ok": False,
                "error": error or f"{tool_label} 回写显示任务未完成",
                "codex": result,
                "_relay_status": relay_status,
            }
        if dispatch.get("accepted") is not True:
            reason = str(dispatch.get("reason") or f"{tool_label}/MCP 调度器当前不可用").strip()
            return {"error": reason, "codex": result, "_relay_status": "blocked"}
        request_id = str(dispatch.get("request_id") or "").strip()
        task_id = str(dispatch.get("task_id") or "").strip()
        timeout = max(
            0.0, float(_facade().os.environ.get("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC") or "300")
        )
        interval = max(
            0.05, float(_facade().os.environ.get("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC") or "2")
        )
        deadline = _facade().time.monotonic() + timeout
        while True:
            terminal = _facade()._terminal_codex_message(
                service.list_messages(user_id=user_id, limit=200),
                request_id=request_id,
                task_id=task_id,
            )
            if terminal:
                result["assistant_message"] = terminal
                (ok, relay_status, error) = _facade()._classify_terminal_result(
                    terminal, message=message
                )
                if ok:
                    return {"ok": True, "codex": result, "_relay_status": "completed"}
                return {
                    "ok": False,
                    "error": error or f"{tool_label} 回写显示任务未完成",
                    "codex": result,
                    "_relay_status": relay_status,
                }
            if _facade().time.monotonic() >= deadline:
                break
            _facade().time.sleep(min(interval, max(0.0, deadline - _facade().time.monotonic())))
        suffix = f"（task_id={task_id}）" if task_id else ""
        return {
            "error": f"{tool_label} 已派发，但在 {timeout:g} 秒内未回写{suffix}",
            "codex": result,
            "_relay_status": "blocked",
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("mobile relay Codex task failed")
        return {"error": str(exc)[:1000]}


def _git_op_from_message(
    payload: dict[str, _facade().Any], message: str
) -> tuple[str, dict[str, _facade().Any]] | None:
    text = str(message or "").strip()
    lowered = text.lower()
    explicit = str(payload.get("git_op") or payload.get("op") or "").strip()
    explicit_git_op = explicit in _facade().GIT_OP_KINDS
    if explicit in _facade().GIT_OP_KINDS:
        git_kind = explicit
    elif any(marker in lowered for marker in _facade()._MERGE_TEXT_MARKERS):
        git_kind = "git.merge"
    elif any(marker in lowered for marker in _facade()._DIFF_TEXT_MARKERS):
        git_kind = "git.diff"
    elif any(marker in lowered for marker in _facade()._DISCARD_TEXT_MARKERS):
        git_kind = "git.discard"
    else:
        return None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    text_source = _facade()._extract_branch_after(
        text, "SOURCE_", "_TARGET"
    ) or _facade()._extract_merge_source(text)
    allow_selected_branch = explicit_git_op or _facade()._text_mentions_branch_op(text, lowered)
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
    ).strip() or _facade()._extract_target_branch(text)
    if git_kind == "git.merge" and (not target):
        target = _facade()._extract_merge_target(text)
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
    pattern = _facade().re.compile(
        f"{_facade().re.escape(prefix)}(?P<branch>[A-Za-z0-9._/-]+?){_facade().re.escape(suffix)}",
        _facade().re.IGNORECASE,
    )
    match = pattern.search(text)
    return _facade()._trim_branch_token(match.group("branch")) if match else ""


def _extract_target_branch(text: str) -> str:
    match = _facade().re.search(
        "TARGET(?:_CURRENT)?_(?P<branch>[A-Za-z0-9._/-]+)", text, _facade().re.IGNORECASE
    )
    return _facade()._trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_source(text: str) -> str:
    match = _facade().re.search(
        "(?:合并|merge)\\s+(?:分支\\s*)?(?P<branch>[A-Za-z0-9._/-]+)", text, _facade().re.IGNORECASE
    )
    return _facade()._trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_target(text: str) -> str:
    match = _facade().re.search(
        "(?:到|至|into|->)\\s*(?:分支\\s*)?(?P<branch>[A-Za-z0-9._/-]+)",
        text,
        _facade().re.IGNORECASE,
    )
    return _facade()._trim_branch_token(match.group("branch")) if match else ""


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
    match = _facade()._BRANCH_TOKEN_RE.search(branch)
    return match.group(0) if match else ""


def _classify_terminal_result(
    row: dict[str, _facade().Any], *, message: str
) -> tuple[bool, str, str]:
    status = str(row.get("status") or row.get("task_status") or "").strip().lower()
    body = str(row.get("body") or row.get("summary") or row.get("message") or "").strip()
    if status in _facade()._FAILED_STATUSES:
        return (False, "failed", _facade()._terminal_error_summary(body, "执行端回写失败"))
    if status in _facade()._BLOCKED_STATUSES:
        return (False, "blocked", _facade()._terminal_error_summary(body, "执行端回写阻塞"))
    if body and _facade()._body_indicates_unfinished(body):
        relay_status = "failed" if _facade()._body_indicates_failed(body) else "blocked"
        return (
            False,
            relay_status,
            _facade()._terminal_error_summary(body, "执行端回写显示未完成"),
        )
    if _facade()._message_requires_execution_evidence(message) and (
        not _facade()._body_has_execution_evidence(body)
    ):
        return (
            False,
            "blocked",
            _facade()._terminal_error_summary(
                body, "执行端回写缺少改动文件、命令、测试、构建或手机复测证据"
            ),
        )
    if status in _facade()._COMPLETED_STATUSES or body:
        return (True, "completed", "")
    return (True, "completed", "")


def _body_indicates_unfinished(body: str) -> bool:
    if not body:
        return False
    compact = body.replace(" ", "")
    return any(
        marker in body or marker.replace(" ", "") in compact
        for marker in _facade()._FAILURE_BODY_MARKERS
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
    return any(marker.lower() in text for marker in _facade()._EXECUTION_MESSAGE_MARKERS)


def _body_has_execution_evidence(body: str) -> bool:
    text = str(body or "")
    if not text or _facade()._body_indicates_unfinished(text):
        return False
    lower = text.lower()
    if any(marker.lower() in lower for marker in _facade()._EXECUTION_EVIDENCE_MARKERS):
        return True
    return _facade()._EVIDENCE_FILE_RE.search(text) is not None


def _terminal_error_summary(body: str, fallback: str) -> str:
    for line in body.splitlines():
        clean = line.strip().strip("-*# ")
        if clean:
            return clean[:500]
    return fallback


def _terminal_codex_message(
    messages: list[dict[str, _facade().Any]], *, request_id: str, task_id: str
) -> dict[str, _facade().Any] | None:
    for row in reversed(messages):
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
