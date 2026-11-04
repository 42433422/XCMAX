"""Relay task dispatch, execution context and correlated terminal results."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.application.desktop_relay.protocols import (
    ClassifyResultCall,
    JsonObject,
    SuperEmployee,
    SuperEmployeeFactory,
    TerminalMessageCall,
)
from app.infrastructure.relay.gitops import GIT_OP_KINDS
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class ExecutionPorts:
    ensure_services: Callable[[], None]
    claude_factory: Callable[[], SuperEmployeeFactory | None]
    codex_factory: Callable[[], SuperEmployeeFactory | None]
    cursor_factory: Callable[[], SuperEmployeeFactory | None]
    trae_factory: Callable[[], SuperEmployeeFactory | None]
    git_op: Callable[[str, JsonObject], JsonObject]
    git_message: Callable[[JsonObject, str], tuple[str, JsonObject] | None]
    classify_result: ClassifyResultCall
    terminal_message: TerminalMessageCall
    tool_calls: Callable[[JsonObject, str], list[JsonObject]]
    environment: Callable[[], Mapping[str, str]]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]


class RelayTaskExecutor:
    def __init__(self, ports: ExecutionPorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger

    def execute(self, task: JsonObject) -> JsonObject:
        kind = str(task.get("kind") or "codex.invoke").strip()
        raw_payload = task.get("payload")
        payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        if kind in GIT_OP_KINDS:
            return self.ports.git_op(kind, payload)
        message = str(
            payload.get("message")
            or payload.get("body")
            or payload.get("prompt")
            or payload.get("task")
            or ""
        ).strip()
        if not message:
            return {"error": "任务缺少 message"}
        parsed_git_op = self.ports.git_message(payload, message)
        if parsed_git_op is not None:
            (git_kind, git_payload) = parsed_git_op
            return self.ports.git_op(git_kind, git_payload)
        self.ports.ensure_services()
        claude_service_class = self.ports.claude_factory()
        codex_service_class = self.ports.codex_factory()
        cursor_service_class = self.ports.cursor_factory()
        trae_service_class = self.ports.trae_factory()
        if (
            claude_service_class is None
            or codex_service_class is None
            or cursor_service_class is None
            or (trae_service_class is None)
        ):
            return {"error": "超级员工服务加载失败"}
        if kind.startswith("claude"):
            service: SuperEmployee = claude_service_class()
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
            raw_dispatch = result.get("dispatch")
            dispatch: JsonObject = raw_dispatch if isinstance(raw_dispatch, dict) else {}
            dispatch_status = str(dispatch.get("status") or "").strip().lower()
            if dispatch_status == "completed":
                raw_assistant = result.get("assistant_message")
                assistant: JsonObject = raw_assistant if isinstance(raw_assistant, dict) else {}
                (ok, relay_status, error) = self.ports.classify_result(assistant, message=message)
                tool_calls = self.ports.tool_calls(assistant, tool_label)
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
            if not request_id and not task_id:
                return {
                    "error": f"{tool_label} 已派发，但缺少回写关联标识",
                    "codex": result,
                    "_relay_status": "blocked",
                }
            timeout = max(
                0.0,
                float(self.ports.environment().get("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC") or "300"),
            )
            interval = max(
                0.05,
                float(self.ports.environment().get("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC") or "2"),
            )
            deadline = self.ports.monotonic() + timeout
            while True:
                terminal = self.ports.terminal_message(
                    service.list_messages(user_id=user_id, limit=200),
                    request_id=request_id,
                    task_id=task_id,
                )
                if terminal:
                    result["assistant_message"] = terminal
                    (ok, relay_status, error) = self.ports.classify_result(
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
                if self.ports.monotonic() >= deadline:
                    break
                self.ports.sleep(min(interval, max(0.0, deadline - self.ports.monotonic())))
            suffix = f"（task_id={task_id}）" if task_id else ""
            return {
                "error": f"{tool_label} 已派发，但在 {timeout:g} 秒内未回写{suffix}",
                "codex": result,
                "_relay_status": "blocked",
            }
        except RECOVERABLE_ERRORS as exc:
            self.logger.exception("mobile relay Codex task failed")
            return {"error": str(exc)[:1000]}
