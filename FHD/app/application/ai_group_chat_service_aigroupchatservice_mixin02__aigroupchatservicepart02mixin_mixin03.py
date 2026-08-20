# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class __AiGroupChatServicePart02MixinPart03Mixin:
    async def _execute_employee_work(
        self,
        *,
        group: dict[str, _facade().Any],
        member: dict[str, _facade().Any],
        task: str,
        assigned_task: str,
        assignment_focus: str,
        work_order_id: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
    ) -> dict[str, _facade().Any]:
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
            if employee_id in _facade()._SUPER_EMPLOYEE_IDS and (
                not self._has_custom_employee_executor
            ):
                raw = await _facade().asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id=employee_id,
                    task=assigned_task,
                    input_data=input_data,
                    user_id=int(user_id),
                )
            else:
                executor_result = self._employee_executor_fn(
                    employee_id, assigned_task, input_data, int(user_id)
                )
                raw = (
                    await executor_result
                    if _facade().isawaitable(executor_result)
                    else executor_result
                )
            result = (
                raw
                if isinstance(raw, dict)
                else {"success": False, "status": "failed", "message": str(raw)}
            )
            success = bool(result.get("success"))
            summary = self._execution_summary(result)
            result_status = str(result.get("status") or "").strip().lower()
            missing_evidence = (
                success
                and (not self._has_custom_employee_executor)
                and (result_status in {"completed", "done"})
                and self._completed_report_lacks_required_evidence(
                    assigned_task or task, summary, result
                )
            )
            if success and self._summary_indicates_unfinished(summary):
                success = False
            if missing_evidence:
                success = False
            reassigned_from = ""
            if (
                not success
                and employee_id in _facade()._SUPER_EMPLOYEE_IDS
                and (employee_id != "claude-super-employee")
                and (not self._has_custom_employee_executor)
                and self._summary_indicates_unfinished(summary)
            ):
                claude_raw = await _facade().asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id="claude-super-employee",
                    task=assigned_task,
                    input_data={**input_data, "reassigned_from": employee_id},
                    user_id=int(user_id),
                )
                claude_result = claude_raw if isinstance(claude_raw, dict) else {"success": False}
                claude_summary = self._execution_summary(claude_result)
                claude_missing_evidence = self._completed_report_lacks_required_evidence(
                    assigned_task or task, claude_summary, claude_result
                )
                claude_ok = (
                    bool(claude_result.get("success"))
                    and (not self._summary_indicates_unfinished(claude_summary))
                    and (not claude_missing_evidence)
                )
                if claude_ok:
                    reassigned_from = employee_id
                    (result, success, summary) = (claude_result, True, claude_summary)
                    (employee_id, employee_name) = ("claude-super-employee", "Claude 超级员工")
                    missing_evidence = False
            status = str(result.get("status") or "").strip().lower()
            if not status or (status in {"completed", "done"} and (not success)):
                status = (
                    "done"
                    if success
                    else "failed"
                    if self._summary_indicates_failed(summary)
                    else "blocked"
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
                "risk": "回报缺少改动文件、命令、测试、构建或安装证据，不能自动验收。"
                if missing_evidence
                else self._execution_risk(result, success),
                "raw": self._compact_result(result),
            }
            if reassigned_from:
                report["reassigned_from"] = reassigned_from
            return report
        except _facade().RECOVERABLE_ERRORS as exc:
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
        self, *, employee_id: str, task: str, input_data: dict[str, _facade().Any], user_id: int
    ) -> dict[str, _facade().Any]:
        relay_result = self._create_super_employee_relay_task(
            employee_id=employee_id, task=task, input_data=input_data, user_id=user_id
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
        self, *, employee_id: str, task: str, input_data: dict[str, _facade().Any], user_id: int
    ) -> dict[str, _facade().Any] | None:
        kind = _facade()._SUPER_EMPLOYEE_RELAY_KINDS.get(employee_id)
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
        except _facade().RECOVERABLE_ERRORS:
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
    def _latest_relay_desktop(
        desktops: list[dict[str, _facade().Any]],
    ) -> dict[str, _facade().Any] | None:
        candidates = [
            item
            for item in desktops
            if isinstance(item, dict)
            and str(item.get("relay_id") or "").strip()
            and (str(item.get("status") or "").strip().lower() == "paired")
        ]
        if not candidates:
            return None

        def sort_key(item: dict[str, _facade().Any]) -> str:
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

    @staticmethod
    def _format_work_order_message(
        task: str,
        target_names: list[str],
        *,
        assignments: list[dict[str, _facade().Any]] | None = None,
        branch_context: str = "",
    ) -> str:
        if not target_names:
            return f"【派工失败】没有可派工成员。\n任务：{task}"
        owners = "、".join(name for name in target_names if name) or "群成员"
        assignment_lines = []
        for item in assignments or []:
            name = str(item.get("name") or item.get("employee_id") or "负责人")
            focus = str(item.get("assignment_focus") or "").strip()
            if focus and focus != "主负责人":
                assignment_lines.append(f"- {name}：{focus}")
        assignment_block = "\n分工：\n" + "\n".join(assignment_lines) if assignment_lines else ""
        branch_line = (
            f"工作分支：{branch_context}\n" if branch_context else "工作分支：自动隔离分支\n"
        )
        return f"【小C派单】{task}\n负责人：{owners}\n{branch_line}{assignment_block}\n流程：接单 → 执行 → 回报 → 小C验收。\n你不用翻执行端，我会把最终结果收口到这条群聊里。"
