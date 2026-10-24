"""Idempotent work reports, acceptance and follow-up messages."""

from __future__ import annotations

from typing import Any

from app.application.group_chat.constants import _XIAOC_ASSISTANT_ID
from app.application.group_chat.evidence import ExecutionResultPolicy
from app.application.group_chat.message_formatting import ChatFormatting
from app.application.group_chat.ports import (
    GroupStore,
    MessageFactory,
    MessageStore,
    ProgressSources,
)
from app.application.group_chat.projections import ChatProjection
from app.application.group_chat.storage import GroupChatRepository


class WorkReports:
    def __init__(
        self,
        groups: GroupStore,
        messages: MessageStore,
        progress: ProgressSources,
        make_row: MessageFactory,
    ) -> None:
        self.groups = groups
        self.messages = messages
        self.progress = progress
        self.make_row = make_row

    def append_relay_work_report(self, *, task: dict[str, Any]) -> dict[str, Any] | None:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if not isinstance(context, dict):
            context = {}
        if str(context.get("source") or "") != "mobile_ai_group":
            return None
        user_id = int(task.get("created_by_user_id") or 0)
        group_id = str(context.get("group_id") or "").strip()
        employee_id = str(context.get("employee_id") or "").strip()
        task_id = str(task.get("task_id") or "").strip()
        if user_id <= 0 or not group_id or (not employee_id) or (not task_id):
            return None
        group = GroupChatRepository.find(self.groups.for_user(user_id), group_id)
        if group is None:
            return None
        work_order_id = str(context.get("work_order_id") or "")
        existing = self.relay_report_message(user_id=user_id, group_id=group_id, task_id=task_id)
        if existing is not None:
            self.append_work_acceptance_if_ready(
                user_id=user_id, group_id=group_id, work_order_id=work_order_id
            )
            return ChatProjection.public_message(existing)
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        member = next(
            (m for m in members if str(m.get("employee_id") or "") == employee_id),
            {"employee_id": employee_id, "name": employee_id, "avatar": ""},
        )
        report = WorkReports.relay_task_report(task=task, member=member)
        row = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=employee_id,
            sender_name=str(member.get("name") or employee_id),
            sender_avatar=str(member.get("avatar") or ""),
            body=ChatFormatting.format_work_report_message(member, report),
            kind="relay_work_report",
            status=str(report.get("status") or ""),
            work_order_id=work_order_id,
            payload=report,
        )
        self.messages.append([row])
        self.append_work_acceptance_if_ready(
            user_id=user_id, group_id=group_id, work_order_id=work_order_id
        )
        return ChatProjection.public_message(row)

    def relay_report_message(
        self, *, user_id: int, group_id: str, task_id: str
    ) -> dict[str, Any] | None:
        for row in self.messages.read():
            if int(row.get("user_id") or 0) != int(user_id):
                continue
            if str(row.get("group_id") or "") != str(group_id):
                continue
            if str(row.get("kind") or "") != "relay_work_report":
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if not isinstance(payload, dict):
                payload = {}
            raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
            if not isinstance(raw, dict):
                raw = {}
            if str(raw.get("task_id") or "") == str(task_id):
                return row
        return None

    def append_work_acceptance_if_ready(
        self, *, user_id: int, group_id: str, work_order_id: str
    ) -> dict[str, Any] | None:
        if not work_order_id:
            return None
        rows = [
            row
            for row in self.messages.read()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
            and (str(row.get("work_order_id") or "") == str(work_order_id))
        ]
        if not rows:
            return None
        existing = next(
            (row for row in rows if str(row.get("kind") or "") == "work_acceptance"), None
        )
        if existing is not None:
            return ChatProjection.public_message(existing)
        work_order = next((row for row in rows if str(row.get("kind") or "") == "work_order"), None)
        initial_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report"
            and ChatFormatting.report_relay_task_id(row)
        ]
        if not work_order or not initial_reports:
            return None
        expected_task_ids = [ChatFormatting.report_relay_task_id(row) for row in initial_reports]
        final_reports = [row for row in rows if str(row.get("kind") or "") == "relay_work_report"]
        final_by_task = {ChatFormatting.report_relay_task_id(row): row for row in final_reports}
        if any(task_id not in final_by_task for task_id in expected_task_ids):
            return None
        ordered_finals = [final_by_task[task_id] for task_id in expected_task_ids]
        terminal = {"completed", "done", "failed", "blocked", "cancelled"}
        statuses = [ExecutionResultPolicy.effective_report_status(row) for row in ordered_finals]
        if any(status not in terminal for status in statuses):
            return None
        ok_count = sum(1 for status in statuses if status in {"completed", "done"})
        all_ok = ok_count == len(ordered_finals)
        acceptance_status = "completed" if all_ok else "needs_review"
        row = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=ChatFormatting.format_work_acceptance_message(
                work_order=work_order,
                final_reports=ordered_finals,
                ok_count=ok_count,
                total=len(ordered_finals),
                all_ok=all_ok,
            ),
            kind="work_acceptance",
            status=acceptance_status,
            work_order_id=work_order_id,
            payload={
                "work_order_id": work_order_id,
                "status": acceptance_status,
                "total": len(ordered_finals),
                "completed": ok_count,
                "task_ids": expected_task_ids,
                "branch_context": str(
                    (
                        dict(work_order["payload"])
                        if isinstance(work_order.get("payload"), dict)
                        else {}
                    ).get("branch_context")
                    or ""
                ),
            },
        )
        self.messages.append([row])
        return ChatProjection.public_message(row)

    def append_acceptance_followup(self, *, user_id: int, group_id: str) -> dict[str, Any] | None:
        self.progress.relay(user_id=user_id, group_id=group_id)
        self.progress.super_employee(user_id=user_id, group_id=group_id)
        rows = [
            row
            for row in self.messages.read()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
        ]
        work_orders = [row for row in rows if str(row.get("kind") or "") == "work_order"]
        if not work_orders:
            row = self.make_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=_XIAOC_ASSISTANT_ID,
                sender_name="小C助理",
                sender_avatar="",
                body="【小C回访】还没有可回访的派工单。\n先输入任务后点“任务派工”，我会在群里派负责人并收口验收。",
                kind="work_followup",
                status="empty",
            )
            self.messages.append([row])
            return row
        work_order = max(work_orders, key=lambda row: str(row.get("created_at") or ""))
        work_order_id = str(work_order.get("work_order_id") or "")
        had_acceptance = any(
            str(row.get("kind") or "") == "work_acceptance"
            and str(row.get("work_order_id") or "") == work_order_id
            for row in rows
        )
        acceptance = self.append_work_acceptance_if_ready(
            user_id=user_id, group_id=group_id, work_order_id=work_order_id
        )
        if acceptance is not None and (not had_acceptance):
            return next(
                (
                    row
                    for row in self.messages.read()
                    if int(row.get("user_id") or 0) == int(user_id)
                    and str(row.get("group_id") or "") == str(group_id)
                    and str(row.get("id") or "") == str(acceptance.get("id") or "")
                ),
                None,
            )
        body = ChatFormatting.format_acceptance_followup_message(
            work_order=work_order,
            rows=[
                row
                for row in self.messages.read()
                if int(row.get("user_id") or 0) == int(user_id)
                and str(row.get("group_id") or "") == str(group_id)
                and str(row.get("work_order_id") or "") == work_order_id
            ],
            had_acceptance=bool(acceptance),
        )
        row = self.make_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=body,
            kind="work_followup",
            status="completed" if acceptance is not None else "in_progress",
            work_order_id=work_order_id,
        )
        self.messages.append([row])
        return row

    @staticmethod
    def relay_task_report(*, task: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
        raw_payload = task.get("payload")
        payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        raw_context = payload.get("context")
        context: dict[str, Any] = dict(raw_context) if isinstance(raw_context, dict) else {}
        raw_result = task.get("result")
        result: dict[str, Any] = dict(raw_result) if isinstance(raw_result, dict) else {}
        status = str(task.get("status") or "completed").strip().lower()
        summary = ChatFormatting.relay_result_summary(
            result, status, str(task.get("task_id") or "")
        )
        task_text = str(payload.get("message") or context.get("original_task") or "")
        missing_evidence = ExecutionResultPolicy.completed_report_lacks_required_evidence(
            task_text, summary, result
        )
        raw_unfinished = ExecutionResultPolicy.summary_indicates_unfinished(
            ExecutionResultPolicy.execution_evidence_text(result)
        )
        unfinished = (
            ExecutionResultPolicy.summary_indicates_unfinished(summary)
            or raw_unfinished
            or missing_evidence
        )
        if not isinstance(result, dict):
            result = {}
        success = (
            status in {"completed", "done"} and result.get("ok") is not False and (not unfinished)
        )
        effective_status = status
        if status in {"completed", "done"} and (not success):
            effective_status = (
                "failed" if ExecutionResultPolicy.summary_indicates_failed(summary) else "blocked"
            )
        dispatcher = ExecutionResultPolicy.relay_result_dispatch_value(result, "dispatcher")
        dispatch_status = ExecutionResultPolicy.relay_result_dispatch_value(result, "status")
        if not isinstance(context, dict):
            context = {}
        return {
            "work_order_id": str(context.get("work_order_id") or ""),
            "employee_id": str(context.get("employee_id") or member.get("employee_id") or ""),
            "employee_name": str(member.get("name") or member.get("employee_id") or ""),
            "task": str(payload.get("message") or ""),
            "original_task": str(context.get("original_task") or ""),
            "assignment_focus": str(context.get("assignment_focus") or ""),
            "branch_context": str(context.get("branch") or payload.get("branch") or ""),
            "status": "completed" if success and status == "done" else effective_status,
            "success": success,
            "summary": summary,
            "risk": "回报只有调研/方案或缺少改动文件、命令、测试、构建、安装证据，不能自动验收。"
            if missing_evidence
            else ChatFormatting.relay_result_risk(
                result=result,
                success=success,
                task_id=str(task.get("task_id") or ""),
                dispatcher=dispatcher,
            ),
            "raw": {
                "task_id": str(task.get("task_id") or ""),
                "relay_id": str(task.get("relay_id") or ""),
                "kind": str(task.get("kind") or ""),
                "dispatcher": dispatcher,
                "dispatch_status": dispatch_status,
                "evidence_required": missing_evidence,
            },
        }
