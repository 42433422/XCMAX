"""Employee result validation, execution evidence and fallback assignment."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from inspect import isawaitable
from typing import Any

from app.application.group_chat.constants import _SUPER_EMPLOYEE_IDS, EmployeeExecutorFn
from app.application.group_chat.evidence import ExecutionResultPolicy
from app.application.group_chat.ports import InvokeSuperTask
from app.utils.operational_errors import RECOVERABLE_ERRORS


class EmployeeExecution:
    def __init__(
        self,
        *,
        execute: EmployeeExecutorFn,
        has_custom_executor: Callable[[], bool],
        invoke_super: InvokeSuperTask,
    ) -> None:
        self.execute = execute
        self.has_custom_executor = has_custom_executor
        self.invoke_super = invoke_super

    async def execute_employee_work(
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
            if employee_id in _SUPER_EMPLOYEE_IDS and (not self.has_custom_executor()):
                raw = await asyncio.to_thread(
                    self.invoke_super,
                    employee_id=employee_id,
                    task=assigned_task,
                    input_data=input_data,
                    user_id=int(user_id),
                )
            else:
                executor_result = self.execute(employee_id, assigned_task, input_data, int(user_id))
                raw = await executor_result if isawaitable(executor_result) else executor_result
            result = (
                raw
                if isinstance(raw, dict)
                else {"success": False, "status": "failed", "message": str(raw)}
            )
            success = bool(result.get("success"))
            summary = ExecutionResultPolicy.execution_summary(result)
            result_status = str(result.get("status") or "").strip().lower()
            missing_evidence = (
                success
                and (not self.has_custom_executor())
                and (result_status in {"completed", "done"})
                and ExecutionResultPolicy.completed_report_lacks_required_evidence(
                    assigned_task or task, summary, result
                )
            )
            if success and ExecutionResultPolicy.summary_indicates_unfinished(summary):
                success = False
            if missing_evidence:
                success = False
            reassigned_from = ""
            if (
                not success
                and employee_id in _SUPER_EMPLOYEE_IDS
                and (employee_id != "claude-super-employee")
                and (not self.has_custom_executor())
                and ExecutionResultPolicy.summary_indicates_unfinished(summary)
            ):
                claude_raw = await asyncio.to_thread(
                    self.invoke_super,
                    employee_id="claude-super-employee",
                    task=assigned_task,
                    input_data={**input_data, "reassigned_from": employee_id},
                    user_id=int(user_id),
                )
                claude_result = claude_raw if isinstance(claude_raw, dict) else {"success": False}
                claude_summary = ExecutionResultPolicy.execution_summary(claude_result)
                claude_missing_evidence = (
                    ExecutionResultPolicy.completed_report_lacks_required_evidence(
                        assigned_task or task, claude_summary, claude_result
                    )
                )
                claude_ok = (
                    bool(claude_result.get("success"))
                    and (not ExecutionResultPolicy.summary_indicates_unfinished(claude_summary))
                    and (not claude_missing_evidence)
                )
                if claude_ok:
                    reassigned_from = employee_id
                    result, success, summary = (claude_result, True, claude_summary)
                    employee_id, employee_name = ("claude-super-employee", "Claude 超级员工")
                    missing_evidence = False
            status = str(result.get("status") or "").strip().lower()
            if not status or (status in {"completed", "done"} and (not success)):
                status = (
                    "done"
                    if success
                    else "failed"
                    if ExecutionResultPolicy.summary_indicates_failed(summary)
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
                else ExecutionResultPolicy.execution_risk(result, success),
                "raw": ExecutionResultPolicy.compact_result(result),
            }
            if reassigned_from:
                report["reassigned_from"] = reassigned_from
            return report
        except RECOVERABLE_ERRORS as exc:
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
