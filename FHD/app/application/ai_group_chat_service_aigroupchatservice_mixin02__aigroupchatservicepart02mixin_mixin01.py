# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class __AiGroupChatServicePart02MixinPart01Mixin:
    def _sync_super_employee_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Mirror Codex/Cursor/Claude DevFleet results back into the group chat."""
        rows = [
            row
            for row in self._read_messages()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
        ]
        if not rows:
            return
        final_task_ids = {
            self._report_relay_task_id(row)
            for row in rows
            if str(row.get("kind") or "") == "relay_work_report"
        }
        pending_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report"
            and str(row.get("sender_id") or "") in _facade()._SUPER_EMPLOYEE_IDS
            and self._report_relay_task_id(row)
            and (self._report_relay_task_id(row) not in final_task_ids)
        ]
        if not pending_reports:
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        messages_by_employee: dict[str, list[dict[str, _facade().Any]]] = {}
        for report in pending_reports:
            employee_id = str(report.get("sender_id") or "").strip()
            task_id = self._report_relay_task_id(report)
            if not employee_id or not task_id:
                continue
            if employee_id not in messages_by_employee:
                try:
                    messages_by_employee[employee_id] = self._super_employee_service(
                        employee_id
                    ).list_messages(user_id=int(user_id), limit=200)
                except _facade().RECOVERABLE_ERRORS:
                    messages_by_employee[employee_id] = []
            employee_messages = messages_by_employee[employee_id]
            result_msg = self._super_employee_result_message_for_task(employee_messages, task_id)
            if result_msg is not None:
                self.append_relay_work_report(
                    task=self._super_employee_result_task(
                        user_id=user_id, group_id=group_id, report=report, result_msg=result_msg
                    )
                )
                continue
            status_msg = self._super_employee_dispatch_message_for_task(employee_messages, task_id)
            status = self._super_employee_task_status(status_msg)
            if status in {"completed", "done", "merged", "failed", "blocked", "cancelled"}:
                self.append_relay_work_report(
                    task=self._super_employee_result_task(
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
            last = self._latest_progress_row(progress_rows, task_id)
            if not self._should_append_progress(last=last, status=status):
                continue
            progress = self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=employee_id,
                sender_name=str(report.get("sender_name") or "负责人"),
                sender_avatar=str(report.get("sender_avatar") or ""),
                body=self._format_relay_progress_message(
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
                    "summary": self._relay_progress_summary(status, task_id),
                    "raw": {"task_id": task_id, "kind": "super_employee"},
                },
            )
            self._append_messages([progress])
            progress_rows.append(progress)

    @staticmethod
    def _super_employee_result_message_for_task(
        messages: list[dict[str, _facade().Any]], task_id: str
    ) -> dict[str, _facade().Any] | None:
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
    def _super_employee_dispatch_message_for_task(
        messages: list[dict[str, _facade().Any]], task_id: str
    ) -> dict[str, _facade().Any] | None:
        for item in reversed(messages):
            if (
                str(item.get("task_id") or "") == str(task_id)
                and str(item.get("kind") or "") == "dispatcher"
            ):
                return item
        return None

    @staticmethod
    def _super_employee_task_status(message: dict[str, _facade().Any] | None) -> str:
        if not isinstance(message, dict):
            return ""
        status = str(message.get("task_status") or message.get("status") or "").strip().lower()
        if status == "merged":
            return "completed"
        return status

    def _super_employee_result_task(
        self,
        *,
        user_id: int,
        group_id: str,
        report: dict[str, _facade().Any],
        result_msg: dict[str, _facade().Any],
    ) -> dict[str, _facade().Any]:
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task_id = self._report_relay_task_id(report)
        status = self._super_employee_task_status(result_msg) or "completed"
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
    def _latest_progress_row(
        rows: list[dict[str, _facade().Any]], task_id: str
    ) -> dict[str, _facade().Any] | None:
        for row in reversed(rows):
            if _facade().AiGroupChatService._report_relay_task_id(row) == task_id:
                return row
        return None

    @staticmethod
    def _should_append_progress(*, last: dict[str, _facade().Any] | None, status: str) -> bool:
        if last is None:
            return True
        last_status = str(last.get("status") or "").strip().lower()
        if last_status and last_status != status:
            return True
        last_at = _facade().AiGroupChatService._parse_created_at(str(last.get("created_at") or ""))
        if last_at is None:
            return True
        elapsed = (_facade().datetime.now(_facade().UTC) - last_at).total_seconds()
        return elapsed >= _facade().RELAY_PROGRESS_MIN_INTERVAL_SEC

    @staticmethod
    def _parse_created_at(value: str) -> _facade().datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = _facade().datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=_facade().UTC)
        return parsed.astimezone(_facade().UTC)

    @staticmethod
    def _relay_progress_summary(status: str, task_id: str) -> str:
        label = {
            "queued": "还在服务器队列中",
            "accepted": "执行端已接单",
            "assigned": "执行端已接单",
            "running": "电脑执行端正在处理",
            "processing": "电脑执行端正在处理",
            "in_progress": "电脑执行端正在处理",
        }.get(status, "还在处理中")
        return f"{label}，任务号：{task_id[:8]}。"

    @classmethod
    def _format_relay_progress_message(
        cls, *, report: dict[str, _facade().Any], task: dict[str, _facade().Any], status: str
    ) -> str:
        name = str(report.get("sender_name") or "负责人")
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        focus = str(payload.get("assignment_focus") or "").strip()
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        task_id = str(task.get("task_id") or cls._report_relay_task_id(report))
        status_label = {
            "queued": "排队中",
            "accepted": "已接单",
            "assigned": "已接单",
            "running": "执行中",
            "processing": "执行中",
            "in_progress": "执行中",
        }.get(status, "处理中")
        focus_line = f"负责：{focus}\n" if focus else ""
        branch_line = f"分支：{branch}\n" if branch else ""
        return f"【{name} 进度回访】\n状态：{status_label}\n{focus_line}{branch_line}结果：{cls._relay_progress_summary(status, task_id)}我会继续等执行端回写，不需要你退出重进。\n风险：暂无新的阻塞；如果执行端超时，群里会保留这条任务号方便追踪。\n下一步：继续执行，完成后自动发员工回报并交给小C验收。"

    def delete_message(
        self, *, user_id: int, group_id: str, message_id: str
    ) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        msg_id = str(message_id or "").strip()
        if not msg_id:
            raise ValueError("消息不存在")
        rows = self._read_messages()
        target = next(
            (
                r
                for r in rows
                if int(r.get("user_id") or 0) == int(user_id)
                and str(r.get("group_id")) == str(group_id)
                and (str(r.get("id")) == msg_id)
            ),
            None,
        )
        if target is None:
            raise ValueError("消息不存在")
        if str(target.get("role") or "") != "user" or str(target.get("sender_id") or "") != "user":
            raise ValueError("只能删除自己发送的消息")
        self._rewrite_messages([r for r in rows if str(r.get("id")) != msg_id])
        return {"deleted": True, "id": msg_id}

    def append_relay_work_report(
        self, *, task: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any] | None:
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
        group = self._find(self._user_groups(user_id), group_id)
        if group is None:
            return None
        work_order_id = str(context.get("work_order_id") or "")
        existing = self._relay_report_message(user_id=user_id, group_id=group_id, task_id=task_id)
        if existing is not None:
            self._append_work_acceptance_if_ready(
                user_id=user_id, group_id=group_id, work_order_id=work_order_id
            )
            return self._public_message(existing)
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        member = next(
            (m for m in members if str(m.get("employee_id") or "") == employee_id),
            {"employee_id": employee_id, "name": employee_id, "avatar": ""},
        )
        report = self._relay_task_report(task=task, member=member)
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=employee_id,
            sender_name=str(member.get("name") or employee_id),
            sender_avatar=str(member.get("avatar") or ""),
            body=self._format_work_report_message(member, report),
            kind="relay_work_report",
            status=str(report.get("status") or ""),
            work_order_id=work_order_id,
            payload=report,
        )
        self._append_messages([row])
        self._append_work_acceptance_if_ready(
            user_id=user_id, group_id=group_id, work_order_id=work_order_id
        )
        return self._public_message(row)
