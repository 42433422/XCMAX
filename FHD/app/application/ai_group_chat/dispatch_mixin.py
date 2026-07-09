"""Work dispatch and employee execution for AI group chat."""

from __future__ import annotations

import asyncio
import uuid
from inspect import isawaitable
from typing import Any

from .constants import (
    _SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_RELAY_KINDS,
)


class AiGroupChatDispatchMixin:
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
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task = {
            "task_id": task_id,
            "relay_id": str(raw.get("relay_id") or ""),
            "kind": str(raw.get("kind") or ""),
        }
        return self._message_row(
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
        )

    async def _execute_employee_work(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        assigned_task: str,
        assignment_focus: str,
        work_order_id: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
    ) -> dict[str, Any]:
        employee_id = str(member.get("employee_id") or "").strip()
        employee_name = str(member.get("name") or employee_id).strip()
        input_data = {
            "source": "ai_group_chat",
            "client_surface": "ai_group",
            "invoke_mode": "group_dispatch",
            "trigger": "ai_group_dispatch",
            "allow_medium_risk": True,
            "group_id": str(group.get("id") or ""),
            "group_name": str(group.get("name") or ""),
            "work_order_id": work_order_id,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "original_task": task,
            "assigned_task": assigned_task,
            "assignment_focus": assignment_focus,
            "sender_name": sender_name,
        }
        if branch_context:
            input_data["branch"] = branch_context
            input_data["branch_context"] = branch_context
        try:
            if employee_id in _SUPER_EMPLOYEE_IDS and not self._has_custom_employee_executor:
                # 同步派工（含阻塞 CLI invoke 与中继 DB 写）放到工作线程，
                # 否则会阻塞事件循环、让其它群聊在派工期间发不出消息。
                maybe_result = await asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id=employee_id,
                    task=assigned_task,
                    input_data=input_data,
                    user_id=int(user_id),
                )
            else:
                maybe_result = self._employee_executor_fn(
                    employee_id, assigned_task, input_data, int(user_id)
                )
            raw = await maybe_result if isawaitable(maybe_result) else maybe_result
            result = (
                raw
                if isinstance(raw, dict)
                else {"success": False, "status": "failed", "message": str(raw)}
            )
            success = bool(result.get("success"))
            summary = self._execution_summary(result)
            # 误判验收修复：CLI（尤其只读沙箱的 Codex）常返回 success=True，正文却是
            # "不能执行命令/权限不足/仅提供方案/先不动代码"等拒绝语——这类必须判失败，
            # 否则小 C 会把"没真做"当成验收通过。
            result_status = str(result.get("status") or "").strip().lower()
            missing_evidence = (
                success
                and not self._has_custom_employee_executor
                and result_status in {"completed", "done"}
                and self._completed_report_lacks_required_evidence(
                    assigned_task or task, summary, result
                )
            )
            if success and self._summary_indicates_unfinished(summary):
                success = False
            if missing_evidence:
                success = False
            # 改派真能执行的 Claude：非 Claude 的超级员工拒绝执行时自动改派一次
            # （Codex 只读沙箱执行不了 → 交给有 acceptEdits 的 Claude 真跑）。
            reassigned_from = ""
            if (
                not success
                and employee_id in _SUPER_EMPLOYEE_IDS
                and employee_id != "claude-super-employee"
                and not self._has_custom_employee_executor
                and self._summary_indicates_unfinished(summary)
            ):
                claude_raw = await asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id="claude-super-employee",
                    task=assigned_task,
                    input_data={**input_data, "reassigned_from": employee_id},
                    user_id=int(user_id),
                )
                claude_result = claude_raw if isinstance(claude_raw, dict) else {"success": False}
                claude_summary = self._execution_summary(claude_result)
                claude_missing_evidence = self._completed_report_lacks_required_evidence(
                    assigned_task or task,
                    claude_summary,
                    claude_result,
                )
                claude_ok = (
                    bool(claude_result.get("success"))
                    and not self._summary_indicates_unfinished(claude_summary)
                    and not claude_missing_evidence
                )
                if claude_ok:
                    reassigned_from = employee_id
                    result, success, summary = claude_result, True, claude_summary
                    employee_id, employee_name = "claude-super-employee", "Claude 超级员工"
                    missing_evidence = False
            status = str(result.get("status") or "").strip().lower()
            if not status or (status in {"completed", "done"} and not success):
                status = (
                    "done"
                    if success
                    else ("failed" if self._summary_indicates_failed(summary) else "blocked")
                )
            report = {
                "work_order_id": work_order_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "task": assigned_task,
                "original_task": task,
                "assignment_focus": assignment_focus,
                "branch_context": branch_context,
                "status": status,
                "success": success,
                "summary": summary,
                "risk": (
                    "回报缺少改动文件、命令、测试、构建或安装证据，不能自动验收。"
                    if missing_evidence
                    else self._execution_risk(result, success)
                ),
                "raw": self._compact_result(result),
            }
            if reassigned_from:
                report["reassigned_from"] = reassigned_from
            return report
        except Exception as exc:  # noqa: BLE001 - 单个员工失败不能阻断其他员工汇报
            return {
                "work_order_id": work_order_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "task": assigned_task,
                "original_task": task,
                "assignment_focus": assignment_focus,
                "branch_context": branch_context,
                "status": "failed",
                "success": False,
                "summary": str(exc)[:500],
                "risk": "执行入口异常，需要重试或改派。",
                "raw": {"error": str(exc)[:500]},
            }

    def _invoke_super_employee_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: dict[str, Any],
        user_id: int,
    ) -> dict[str, Any]:
        relay_result = self._create_super_employee_relay_task(
            employee_id=employee_id,
            task=task,
            input_data=input_data,
            user_id=user_id,
        )
        if relay_result is not None:
            return relay_result
        service = self._super_employee_service(employee_id)
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
        dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
        assistant = (
            result.get("assistant_message")
            if isinstance(result.get("assistant_message"), dict)
            else {}
        )
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

    def _create_super_employee_relay_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: dict[str, Any],
        user_id: int,
    ) -> dict[str, Any] | None:
        kind = _SUPER_EMPLOYEE_RELAY_KINDS.get(employee_id)
        if not kind:
            return None
        try:
            relay = self._mobile_relay_service()
            desktop = self._latest_relay_desktop(relay.list_desktops(user_id=int(user_id)))
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
                        if (input_data.get("branch_context") or input_data.get("branch"))
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
                            if (input_data.get("branch_context") or input_data.get("branch"))
                            else {}
                        ),
                    },
                },
            )
        except Exception:  # noqa: BLE001 - relay 不可用时退回超级员工原通道
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
    def _latest_relay_desktop(desktops: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [
            item
            for item in desktops
            if isinstance(item, dict)
            and str(item.get("relay_id") or "").strip()
            and str(item.get("status") or "").strip().lower() == "paired"
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
    def _mobile_relay_service():
        from app.services.mobile_relay_service import MobileRelayService

        return MobileRelayService()

    @staticmethod
    def _super_employee_service(employee_id: str):
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

