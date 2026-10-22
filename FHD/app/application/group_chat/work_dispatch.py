"""Create assignments and persist execution reports for a work order."""

from __future__ import annotations

import uuid
from typing import Any

from app.application.group_chat.dispatch_targeting import DispatchTargeting
from app.application.group_chat.message_formatting import ChatFormatting
from app.application.group_chat.ports import ExecuteWork, MessageFactory, MessageStore


class WorkDispatch:
    def __init__(
        self, messages: MessageStore, execute: ExecuteWork, make_row: MessageFactory
    ) -> None:
        self.messages = messages
        self.execute = execute
        self.make_row = make_row

    async def dispatch_work(
        self,
        *,
        group: dict[str, Any],
        members: list[dict[str, Any]],
        task: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        work_order_id = uuid.uuid4().hex
        assignments = DispatchTargeting.build_dispatch_assignments(task, members)
        target_names = [str(a.get("name") or a.get("employee_id") or "") for a in assignments]
        work_order_row = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=ChatFormatting.format_work_order_message(
                task, target_names, assignments=assignments, branch_context=branch_context
            ),
            kind="work_order",
            status="assigned" if assignments else "blocked",
            work_order_id=work_order_id,
            payload={
                "task": task,
                "branch_context": branch_context,
                "target_employee_ids": [str(a.get("employee_id") or "") for a in assignments],
                "assignments": [
                    {
                        "employee_id": str(a.get("employee_id") or ""),
                        "employee_name": str(a.get("name") or a.get("employee_id") or ""),
                        "focus": str(a.get("assignment_focus") or ""),
                        "task": str(a.get("assigned_task") or task),
                    }
                    for a in assignments
                ],
            },
        )
        messages: list[dict[str, Any]] = [work_order_row]
        if persist:
            self.messages.append([work_order_row])
        if not assignments:
            return (
                messages,
                [
                    {
                        "work_order_id": work_order_id,
                        "status": "blocked",
                        "task": task,
                        "branch_context": branch_context,
                        "target_employee_ids": [],
                    }
                ],
            )
        work_orders: list[dict[str, Any]] = []
        for member in assignments:
            report = await self.execute(
                group=group,
                member=member,
                task=task,
                assigned_task=str(member.get("assigned_task") or task),
                assignment_focus=str(member.get("assignment_focus") or ""),
                work_order_id=work_order_id,
                user_id=user_id,
                sender_name=sender_name,
                branch_context=branch_context,
            )
            work_orders.append(report)
            row = self.make_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(member.get("employee_id") or ""),
                sender_name=str(member.get("name") or member.get("employee_id") or ""),
                sender_avatar=str(member.get("avatar") or ""),
                body=ChatFormatting.format_work_report_message(member, report),
                kind="work_report",
                status=str(report.get("status") or ""),
                work_order_id=work_order_id,
                payload=report,
            )
            messages.append(row)
            if persist:
                self.messages.append([row])
            progress = self.initial_relay_progress_from_report(
                user_id=user_id, group_id=group_id, report_row=row
            )
            if progress is not None:
                messages.append(progress)
                if persist:
                    self.messages.append([progress])
        return (messages, work_orders)

    def initial_relay_progress_from_report(
        self, *, user_id: int, group_id: str, report_row: dict[str, Any]
    ) -> dict[str, Any] | None:
        task_id = ChatFormatting.report_relay_task_id(report_row)
        if not task_id:
            return None
        status = str(report_row.get("status") or "").strip().lower()
        if status not in {"queued", "accepted", "assigned", "running", "processing", "in_progress"}:
            return None
        payload = report_row.get("payload") if isinstance(report_row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        task = {
            "task_id": task_id,
            "relay_id": str(raw.get("relay_id") or ""),
            "kind": str(raw.get("kind") or ""),
        }
        return self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=str(report_row.get("sender_id") or ""),
            sender_name=str(report_row.get("sender_name") or "负责人"),
            sender_avatar=str(report_row.get("sender_avatar") or ""),
            body=ChatFormatting.format_relay_progress_message(
                report=report_row, task=task, status=status
            ),
            kind="work_progress",
            status=status,
            work_order_id=str(report_row.get("work_order_id") or ""),
            payload={
                "work_order_id": str(report_row.get("work_order_id") or ""),
                "employee_id": str(report_row.get("sender_id") or ""),
                "employee_name": str(report_row.get("sender_name") or ""),
                "status": status,
                "summary": ChatFormatting.relay_progress_summary(status, task_id),
                "raw": task,
            },
        )
