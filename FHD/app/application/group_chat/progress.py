"""Reconcile relay and super-employee progress into persisted group messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.group_chat.constants import (
    _SUPER_EMPLOYEE_IDS,
    RELAY_PROGRESS_MIN_INTERVAL_SEC,
)
from app.application.group_chat.message_formatting import ChatFormatting
from app.application.group_chat.protocols import (
    AppendReport,
    EmployeeProviders,
    MessageFactory,
    MessageStore,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ProgressSync:
    def __init__(
        self,
        messages: MessageStore,
        providers: EmployeeProviders,
        append_report: AppendReport,
        make_row: MessageFactory,
    ) -> None:
        self.messages = messages
        self.providers = providers
        self.append_report = append_report
        self.make_row = make_row

    def sync_relay_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Append human-readable relay progress while the desktop executor works.

        The mobile screen polls this endpoint. Without side-effectful progress
        rows the user sees "已接单" for minutes and cannot tell whether the team
        is actually working. This method is intentionally rate-limited per relay
        task to avoid chat spam and mobile memory pressure.
        """
        rows = [
            row
            for row in self.messages.read()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
        ]
        if not rows:
            return
        final_task_ids = {
            ChatFormatting.report_relay_task_id(row)
            for row in rows
            if str(row.get("kind") or "") == "relay_work_report"
        }
        pending_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report"
            and ChatFormatting.report_relay_task_id(row)
            and (ChatFormatting.report_relay_task_id(row) not in final_task_ids)
        ]
        if not pending_reports:
            return
        try:
            relay = self.providers.relay()
        except RECOVERABLE_ERRORS:
            return
        get_task = getattr(relay, "get_task", None)
        if not callable(get_task):
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        for report in pending_reports:
            task_id = ChatFormatting.report_relay_task_id(report)
            try:
                task = get_task(user_id=int(user_id), task_id=task_id)
            except RECOVERABLE_ERRORS:
                continue
            if not isinstance(task, dict) or not task:
                continue
            status = str(task.get("status") or report.get("status") or "").strip().lower()
            if status in {"completed", "done", "failed", "blocked", "cancelled"}:
                self.append_report(task=task)
                continue
            if status not in {
                "queued",
                "accepted",
                "assigned",
                "running",
                "processing",
                "in_progress",
            }:
                continue
            last = ProgressSync.latest_progress_row(progress_rows, task_id)
            if not ProgressSync.should_append_progress(last=last, status=status):
                continue
            progress = self.make_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(report.get("sender_id") or ""),
                sender_name=str(report.get("sender_name") or "负责人"),
                sender_avatar=str(report.get("sender_avatar") or ""),
                body=ChatFormatting.format_relay_progress_message(
                    report=report, task=task, status=status
                ),
                kind="work_progress",
                status=status,
                work_order_id=str(report.get("work_order_id") or ""),
                payload={
                    "work_order_id": str(report.get("work_order_id") or ""),
                    "employee_id": str(report.get("sender_id") or ""),
                    "employee_name": str(report.get("sender_name") or ""),
                    "status": status,
                    "summary": ChatFormatting.relay_progress_summary(status, task_id),
                    "raw": {
                        "task_id": task_id,
                        "relay_id": str(task.get("relay_id") or ""),
                        "kind": str(task.get("kind") or ""),
                    },
                },
            )
            self.messages.append([progress])
            progress_rows.append(progress)

    def sync_super_employee_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Mirror Codex/Cursor/Claude DevFleet results back into the group chat."""
        rows = [
            row
            for row in self.messages.read()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
        ]
        if not rows:
            return
        final_task_ids = {
            ChatFormatting.report_relay_task_id(row)
            for row in rows
            if str(row.get("kind") or "") == "relay_work_report"
        }
        pending_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report"
            and str(row.get("sender_id") or "") in _SUPER_EMPLOYEE_IDS
            and ChatFormatting.report_relay_task_id(row)
            and (ChatFormatting.report_relay_task_id(row) not in final_task_ids)
        ]
        if not pending_reports:
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        messages_by_employee: dict[str, list[dict[str, Any]]] = {}
        for report in pending_reports:
            employee_id = str(report.get("sender_id") or "").strip()
            task_id = ChatFormatting.report_relay_task_id(report)
            if not employee_id or not task_id:
                continue
            if employee_id not in messages_by_employee:
                try:
                    messages_by_employee[employee_id] = self.providers.super_employee(
                        employee_id
                    ).list_messages(user_id=int(user_id), limit=200)
                except RECOVERABLE_ERRORS:
                    messages_by_employee[employee_id] = []
            employee_messages = messages_by_employee[employee_id]
            result_msg = ProgressSync.super_employee_result_message_for_task(
                employee_messages, task_id
            )
            if result_msg is not None:
                self.append_report(
                    task=ProgressSync.super_employee_result_task(
                        user_id=user_id, group_id=group_id, report=report, result_msg=result_msg
                    )
                )
                continue
            status_msg = ProgressSync.super_employee_dispatch_message_for_task(
                employee_messages, task_id
            )
            status = ProgressSync.super_employee_task_status(status_msg)
            if status in {"completed", "done", "merged", "failed", "blocked", "cancelled"}:
                self.append_report(
                    task=ProgressSync.super_employee_result_task(
                        user_id=user_id,
                        group_id=group_id,
                        report=report,
                        result_msg=status_msg or {},
                    )
                )
                continue
            if status not in {
                "queued",
                "accepted",
                "assigned",
                "running",
                "processing",
                "in_progress",
            }:
                continue
            last = ProgressSync.latest_progress_row(progress_rows, task_id)
            if not ProgressSync.should_append_progress(last=last, status=status):
                continue
            progress = self.make_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=employee_id,
                sender_name=str(report.get("sender_name") or "负责人"),
                sender_avatar=str(report.get("sender_avatar") or ""),
                body=ChatFormatting.format_relay_progress_message(
                    report=report,
                    task={"task_id": task_id, "kind": "super_employee"},
                    status=status,
                ),
                kind="work_progress",
                status=status,
                work_order_id=str(report.get("work_order_id") or ""),
                payload={
                    "work_order_id": str(report.get("work_order_id") or ""),
                    "employee_id": employee_id,
                    "employee_name": str(report.get("sender_name") or ""),
                    "status": status,
                    "summary": ChatFormatting.relay_progress_summary(status, task_id),
                    "raw": {"task_id": task_id, "kind": "super_employee"},
                },
            )
            self.messages.append([progress])
            progress_rows.append(progress)

    @staticmethod
    def super_employee_result_message_for_task(
        messages: list[dict[str, Any]], task_id: str
    ) -> dict[str, Any] | None:
        item: dict[str, Any]
        for item in reversed(messages):
            if str(item.get("task_id") or "") != str(task_id):
                continue
            kind = str(item.get("kind") or "")
            if kind in {"codex_result", "cursor_result", "claude_result"}:
                return item
            if (
                str(item.get("role") or "") == "assistant"
                and kind != "dispatcher"
                and str(item.get("body") or "").strip()
            ):
                return item
        return None

    @staticmethod
    def super_employee_dispatch_message_for_task(
        messages: list[dict[str, Any]], task_id: str
    ) -> dict[str, Any] | None:
        item: dict[str, Any]
        for item in reversed(messages):
            if (
                str(item.get("task_id") or "") == str(task_id)
                and str(item.get("kind") or "") == "dispatcher"
            ):
                return item
        return None

    @staticmethod
    def super_employee_task_status(message: dict[str, Any] | None) -> str:
        if not isinstance(message, dict):
            return ""
        status = str(message.get("task_status") or message.get("status") or "").strip().lower()
        if status == "merged":
            return "completed"
        return status

    @staticmethod
    def super_employee_result_task(
        *, user_id: int, group_id: str, report: dict[str, Any], result_msg: dict[str, Any]
    ) -> dict[str, Any]:
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task_id = ChatFormatting.report_relay_task_id(report)
        status = ProgressSync.super_employee_task_status(result_msg) or "completed"
        body = str(result_msg.get("body") or "").strip()
        if not isinstance(raw, dict):
            raw = {}
        if not isinstance(report, dict):
            report = {}
        return {
            "created_by_user_id": int(user_id),
            "task_id": task_id,
            "relay_id": "super_employee",
            "kind": str(raw.get("kind") or raw.get("dispatcher") or "super_employee"),
            "status": status,
            "payload": {
                "message": str(payload.get("task") or payload.get("original_task") or ""),
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group_id,
                    "work_order_id": str(
                        report.get("work_order_id") or payload.get("work_order_id") or ""
                    ),
                    "employee_id": str(payload.get("employee_id") or report.get("sender_id") or ""),
                    "assignment_focus": str(payload.get("assignment_focus") or ""),
                    "original_task": str(payload.get("original_task") or payload.get("task") or ""),
                    "branch": str(payload.get("branch_context") or payload.get("branch") or ""),
                },
            },
            "result": {
                "summary": body,
                "dispatcher": str(raw.get("dispatcher") or "super_employee"),
                "status": status,
                "assistant_message": {"body": body},
            },
        }

    @staticmethod
    def latest_progress_row(rows: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
        row: dict[str, Any]
        for row in reversed(rows):
            if ChatFormatting.report_relay_task_id(row) == task_id:
                return row
        return None

    @staticmethod
    def should_append_progress(*, last: dict[str, Any] | None, status: str) -> bool:
        if last is None:
            return True
        last_status = str(last.get("status") or "").strip().lower()
        if last_status and last_status != status:
            return True
        last_at = ProgressSync.parse_created_at(str(last.get("created_at") or ""))
        if last_at is None:
            return True
        elapsed = (datetime.now(UTC) - last_at).total_seconds()
        return elapsed >= RELAY_PROGRESS_MIN_INTERVAL_SEC

    @staticmethod
    def parse_created_at(value: str) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
