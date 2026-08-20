"""AI reply, employee work dispatch, and relay progress behavior."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from app.application.group_chat.constants import (
    _SUPER_EMPLOYEE_IDS,
    CONTEXT_TURNS,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class WorkDispatchMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    async def _ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        employee_id = str(member.get("employee_id") or "")
        # 超级员工走专用 invoke 通道（CLI 直答 / Para 多设备派工）
        if employee_id in _SUPER_EMPLOYEE_IDS:
            return cast(
                "str", await self._super_employee_reply(group, member, history, user_id=user_id)
            )
        group_name = str(group.get("name") or "AI 群聊")
        me = str(member.get("name") or member.get("employee_id"))
        summary = str(member.get("summary") or "")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        system = (
            f"你是群聊「{group_name}」里的 AI 成员「{me}」。{summary}\n"
            f"群成员有：{roster}。\n"
            "请只代表你自己、用一两句话简洁地回应群里用户的最新消息；"
            "不要替其他成员发言，不要复述别人说过的话，不要加“作为AI”之类的免责声明。"
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        user_content = f"【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息。"
        try:
            res = await self._completion_fn(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
            )
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            return str(res["content"]).strip()
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return f"（{me} 暂时无法回应{f'：{err}' if err else ''}）"

    async def _dispatch_work(
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
        assignments = self._build_dispatch_assignments(task, members)
        target_names = [str(a.get("name") or a.get("employee_id") or "") for a in assignments]
        work_order_row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=self._format_work_order_message(
                task,
                target_names,
                assignments=assignments,
                branch_context=branch_context,
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
            self._append_messages([work_order_row])
        if not assignments:
            return messages, [
                {
                    "work_order_id": work_order_id,
                    "status": "blocked",
                    "task": task,
                    "branch_context": branch_context,
                    "target_employee_ids": [],
                }
            ]

        work_orders: list[dict[str, Any]] = []
        for member in assignments:
            report = await self._execute_employee_work(
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
            row = self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(member.get("employee_id") or ""),
                sender_name=str(member.get("name") or member.get("employee_id") or ""),
                sender_avatar=str(member.get("avatar") or ""),
                body=self._format_work_report_message(member, report),
                kind="work_report",
                status=str(report.get("status") or ""),
                work_order_id=work_order_id,
                payload=report,
            )
            messages.append(row)
            if persist:
                self._append_messages([row])
            progress = self._initial_relay_progress_from_report(
                user_id=user_id,
                group_id=group_id,
                report_row=row,
            )
            if progress is not None:
                messages.append(progress)
                if persist:
                    self._append_messages([progress])
        return messages, work_orders

    def _initial_relay_progress_from_report(
        self,
        *,
        user_id: int,
        group_id: str,
        report_row: dict[str, Any],
    ) -> dict[str, Any] | None:
        task_id = self._report_relay_task_id(report_row)
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
        return cast(
            "dict[str, Any]",
            self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=str(report_row.get("sender_id") or ""),
                sender_name=str(report_row.get("sender_name") or "负责人"),
                sender_avatar=str(report_row.get("sender_avatar") or ""),
                body=self._format_relay_progress_message(
                    report=report_row,
                    task=task,
                    status=status,
                ),
                kind="work_progress",
                status=status,
                work_order_id=str(report_row.get("work_order_id") or ""),
                payload={
                    "work_order_id": str(report_row.get("work_order_id") or ""),
                    "employee_id": str(report_row.get("sender_id") or ""),
                    "employee_name": str(report_row.get("sender_name") or ""),
                    "status": status,
                    "summary": self._relay_progress_summary(status, task_id),
                    "raw": task,
                },
            ),
        )
