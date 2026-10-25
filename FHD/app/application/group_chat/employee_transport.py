"""Adapters for super-employee invocation and paired desktop relay tasks."""

from __future__ import annotations

from typing import Any

from app.application.group_chat.constants import _SUPER_EMPLOYEE_RELAY_KINDS
from app.application.group_chat.protocols import (
    CreateRelayTask,
    EmployeeProviders,
    MobileRelay,
    SuperEmployee,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class EmployeeTransport:
    def __init__(self, providers: EmployeeProviders, create_relay: CreateRelayTask) -> None:
        self.providers = providers
        self.create_relay = create_relay

    def invoke_super_employee_task(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any]:
        relay_result = self.create_relay(
            employee_id=employee_id, task=task, input_data=input_data, user_id=user_id
        )
        if relay_result is not None:
            return relay_result
        service = self.providers.super_employee(employee_id)
        branch_context = str(input_data.get("branch_context") or input_data.get("branch") or "")
        result = service.invoke(
            user_id=int(user_id),
            message=task,
            context={
                "mode": "task",
                "source": "mobile_ai_group",
                "group_id": input_data.get("group_id"),
                "group_name": input_data.get("group_name"),
                "work_order_id": input_data.get("work_order_id"),
                "original_task": input_data.get("original_task") or task,
                "assigned_task": input_data.get("assigned_task") or task,
                "assignment_focus": input_data.get("assignment_focus") or "",
                **({"branch": branch_context} if branch_context else {}),
            },
        )
        raw_dispatch = result.get("dispatch")
        dispatch = raw_dispatch if isinstance(raw_dispatch, dict) else {}
        raw_assistant = result.get("assistant_message")
        assistant = raw_assistant if isinstance(raw_assistant, dict) else {}
        status = str(dispatch.get("status") or assistant.get("status") or "queued").strip()
        accepted = dispatch.get("accepted") is True or status in {
            "queued",
            "accepted",
            "assigned",
            "running",
            "completed",
            "done",
        }
        summary = str(assistant.get("body") or "").strip()
        if not summary:
            summary = "已进入超级员工执行队列。"
        return {
            "success": accepted,
            "status": status or ("queued" if accepted else "failed"),
            "summary": summary,
            "risk": "执行已交给对应超级员工；完成状态以该超级员工会话和派工回执为准。"
            if accepted
            else str(dispatch.get("reason") or "超级员工执行入口未接受任务"),
            "dispatch_request_id": str(dispatch.get("request_id") or ""),
            "task_id": str(dispatch.get("task_id") or ""),
            "dispatcher": str(dispatch.get("dispatcher") or ""),
            "branch_context": branch_context,
        }

    def create_super_employee_relay_task(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None:
        kind = _SUPER_EMPLOYEE_RELAY_KINDS.get(employee_id)
        if not kind:
            return None
        try:
            relay = self.providers.relay()
            desktop = EmployeeTransport.latest_relay_desktop(
                relay.list_desktops(user_id=int(user_id))
            )
            relay_id = str((desktop or {}).get("relay_id") or "").strip()
            if not relay_id:
                return None
            relay_task = relay.create_task(
                user_id=int(user_id),
                relay_id=relay_id,
                kind=kind,
                payload={
                    "message": task,
                    **(
                        {"branch": input_data.get("branch_context") or input_data.get("branch")}
                        if input_data.get("branch_context") or input_data.get("branch")
                        else {}
                    ),
                    "context": {
                        "source": "mobile_ai_group",
                        "client_surface": "ai_group",
                        "mode": "code",
                        "group_id": input_data.get("group_id"),
                        "group_name": input_data.get("group_name"),
                        "work_order_id": input_data.get("work_order_id"),
                        "employee_id": employee_id,
                        "original_task": input_data.get("original_task") or task,
                        "assigned_task": input_data.get("assigned_task") or task,
                        "assignment_focus": input_data.get("assignment_focus") or "",
                        **(
                            {"branch": input_data.get("branch_context") or input_data.get("branch")}
                            if input_data.get("branch_context") or input_data.get("branch")
                            else {}
                        ),
                    },
                },
            )
        except RECOVERABLE_ERRORS:
            return None
        if not isinstance(relay_task, dict):
            return None
        relay_task_id = str(relay_task.get("task_id") or "").strip()
        if not relay_task_id:
            return None
        return {
            "success": True,
            "status": str(relay_task.get("status") or "queued"),
            "summary": f"已接单，正在电脑执行端处理。任务号：{relay_task_id[:8]}。",
            "risk": "暂无阻塞；执行完成后会自动回到群里汇报。",
            "dispatch_request_id": relay_task_id,
            "task_id": relay_task_id,
            "dispatcher": "mobile_relay",
            "relay_id": relay_id,
            "branch_context": str(
                input_data.get("branch_context") or input_data.get("branch") or ""
            ),
        }

    @staticmethod
    def latest_relay_desktop(desktops: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [
            item
            for item in desktops
            if isinstance(item, dict)
            and str(item.get("relay_id") or "").strip()
            and (str(item.get("status") or "").strip().lower() == "paired")
        ]
        if not candidates:
            return None

        def sort_key(item: dict[str, Any]) -> str:
            return (
                str(item.get("last_seen_at") or "").strip()
                or str(item.get("updated_at") or "").strip()
                or str(item.get("paired_at") or "").strip()
                or str(item.get("created_at") or "").strip()
            )

        return max(candidates, key=sort_key)

    @staticmethod
    def mobile_relay_service() -> MobileRelay:
        from app.domain.shared_services.mobile_relay_service import MobileRelayService

        return MobileRelayService()

    @staticmethod
    def super_employee_service(employee_id: str) -> SuperEmployee:
        from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
        from app.application.codex_super_employee_service import CodexSuperEmployeeService
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService
        from app.application.trae_super_employee_service import TraeSuperEmployeeService

        if employee_id == "codex-super-employee":
            return CodexSuperEmployeeService()
        if employee_id == "cursor-super-employee":
            return CursorSuperEmployeeService()
        if employee_id == "trae-super-employee":
            return TraeSuperEmployeeService()
        return ClaudeSuperEmployeeService()
