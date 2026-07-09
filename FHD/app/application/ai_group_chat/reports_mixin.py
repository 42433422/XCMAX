"""Work-report / acceptance formatting for AI group chat."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .constants import (
    _BROKEN_MARKDOWN_LINK_RE,
    _DEV_TASK_MARKERS,
    _EVIDENCE_FILE_RE,
    _EXECUTION_EVIDENCE_MARKERS,
    _FAILED_REPORT_MARKERS,
    _MARKDOWN_LINK_RE,
    _PURE_RESEARCH_TASK_MARKERS,
    _RESEARCH_ONLY_REPORT_MARKERS,
    _TEMP_PATH_RE,
    _UNFINISHED_REPORT_MARKERS,
    _XIAOC_ASSISTANT_ID,
    CHAT_ACCEPTANCE_SUMMARY_CHARS,
    CHAT_REPORT_SUMMARY_CHARS,
    CONTEXT_TURNS,
    _facade_attr,
)


class AiGroupChatReportsMixin:
    @staticmethod
    def _format_work_order_message(
        task: str,
        target_names: list[str],
        *,
        assignments: list[dict[str, Any]] | None = None,
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
        return (
            f"【小C派单】{task}\n"
            f"负责人：{owners}\n"
            f"{branch_line}"
            f"{assignment_block}\n"
            "流程：接单 → 执行 → 回报 → 小C验收。\n"
            "你不用翻执行端，我会把最终结果收口到这条群聊里。"
        )

    @staticmethod
    def _format_work_report_message(member: dict[str, Any], report: dict[str, Any]) -> str:
        name = str(member.get("name") or member.get("employee_id") or "员工")
        ok = bool(report.get("success"))
        raw_status = str(report.get("status") or "").strip().lower()
        status = {
            "queued": "已接单",
            "accepted": "已接单",
            "assigned": "已接单",
            "running": "执行中",
            "in_progress": "执行中",
            "completed": "完成",
            "done": "完成",
            "failed": "失败",
            "blocked": "阻塞",
        }.get(raw_status, "完成" if ok else "失败")
        focus = str(report.get("assignment_focus") or "").strip()
        branch = str(report.get("branch_context") or report.get("branch") or "").strip()
        summary = str(report.get("summary") or "").strip() or "无结果摘要"
        risk = str(report.get("risk") or "").strip() or ("未发现阻塞。" if ok else "存在执行阻塞。")
        if raw_status == "queued":
            next_step = "我完成后会自动回到群里汇报。"
        elif ok:
            next_step = "等其他负责人回报后，小C会给出总体验收。"
        else:
            next_step = "请查看失败原因后重试、改派或补充上下文。"
        focus_line = f"负责：{focus}\n" if focus else ""
        branch_line = f"分支：{branch}\n" if branch else ""
        return (
            f"【{name} 执行汇报】\n"
            f"状态：{status}\n"
            f"{focus_line}"
            f"{branch_line}"
            f"结果：{summary}\n"
            f"风险：{risk}\n"
            f"下一步：{next_step}"
        )

    def _relay_report_message(
        self, *, user_id: int, group_id: str, task_id: str
    ) -> dict[str, Any] | None:
        for row in self._read_messages():
            if int(row.get("user_id") or 0) != int(user_id):
                continue
            if str(row.get("group_id") or "") != str(group_id):
                continue
            if str(row.get("kind") or "") != "relay_work_report":
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
            if str(raw.get("task_id") or "") == str(task_id):
                return row
        return None

    def _append_work_acceptance_if_ready(
        self, *, user_id: int, group_id: str, work_order_id: str
    ) -> dict[str, Any] | None:
        if not work_order_id:
            return None
        rows = [
            row
            for row in self._read_messages()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
            and str(row.get("work_order_id") or "") == str(work_order_id)
        ]
        if not rows:
            return None
        existing = next(
            (row for row in rows if str(row.get("kind") or "") == "work_acceptance"), None
        )
        if existing is not None:
            return self._public_message(existing)
        work_order = next((row for row in rows if str(row.get("kind") or "") == "work_order"), None)
        initial_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report" and self._report_relay_task_id(row)
        ]
        if not work_order or not initial_reports:
            return None
        expected_task_ids = [self._report_relay_task_id(row) for row in initial_reports]
        final_reports = [row for row in rows if str(row.get("kind") or "") == "relay_work_report"]
        final_by_task = {self._report_relay_task_id(row): row for row in final_reports}
        if any(task_id not in final_by_task for task_id in expected_task_ids):
            return None
        ordered_finals = [final_by_task[task_id] for task_id in expected_task_ids]
        terminal = {"completed", "done", "failed", "blocked", "cancelled"}
        statuses = [self._effective_report_status(row) for row in ordered_finals]
        if any(status not in terminal for status in statuses):
            return None
        ok_count = sum(1 for status in statuses if status in {"completed", "done"})
        all_ok = ok_count == len(ordered_finals)
        acceptance_status = "completed" if all_ok else "needs_review"
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=self._format_work_acceptance_message(
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
                        work_order.get("payload")
                        if isinstance(work_order.get("payload"), dict)
                        else {}
                    ).get("branch_context")
                    or ""
                ),
            },
        )
        self._append_messages([row])
        return self._public_message(row)

    @classmethod
    def _format_work_acceptance_message(
        cls,
        *,
        work_order: dict[str, Any],
        final_reports: list[dict[str, Any]],
        ok_count: int,
        total: int,
        all_ok: bool,
    ) -> str:
        payload = work_order.get("payload") if isinstance(work_order.get("payload"), dict) else {}
        task = str(payload.get("task") or "").strip() or cls._strip_label_from_body(
            str(work_order.get("body") or ""),
            "【小C派单】",
        )
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        conclusion = "可以验收" if all_ok else "需要复核"
        lines: list[str] = []
        for row in final_reports:
            report = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            name = str(row.get("sender_name") or report.get("employee_name") or "负责人")
            status = cls._effective_report_status(row)
            focus = str(report.get("assignment_focus") or "").strip()
            summary = cls._chat_friendly_summary(
                str(report.get("summary") or row.get("body") or ""),
                limit=CHAT_ACCEPTANCE_SUMMARY_CHARS,
                include_detail_note=False,
            )
            prefix = f"{name}（{focus}）" if focus else name
            lines.append(f"- {prefix}：{cls._public_status_label(status)}。{summary}")
        risk = "未发现阻塞。" if all_ok else "有负责人未完成或回报异常，需要你复核后再继续。"
        return (
            "【小C验收】这单已收口\n"
            f"结论：{conclusion}（{ok_count}/{total} 个负责人已完成）\n"
            f"任务：{task[:80]}\n"
            + (f"分支：{branch[:120]}\n" if branch else "")
            + "成员：\n"
            + "\n".join(lines[:6])
            + "\n"
            f"风险：{risk}\n"
            "下一步：满意就继续派下一步；不满意就直接说要谁补什么。"
        )

    @staticmethod
    def _report_relay_task_id(row: dict[str, Any]) -> str:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        return str(raw.get("task_id") or payload.get("task_id") or "").strip()

    @staticmethod
    def _public_status_label(status: str) -> str:
        return {
            "completed": "完成",
            "done": "完成",
            "failed": "失败",
            "blocked": "阻塞",
            "cancelled": "已取消",
        }.get(str(status or "").strip().lower(), str(status or "已回报"))

    @staticmethod
    def _strip_label_from_body(body: str, label: str) -> str:
        text = (body or "").strip()
        if text.startswith(label):
            text = text[len(label) :].strip()
        return text.splitlines()[0][:160] if text else ""

    def _relay_task_report(self, *, task: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        status = str(task.get("status") or "completed").strip().lower()
        summary = self._relay_result_summary(result, status, str(task.get("task_id") or ""))
        task_text = str(payload.get("message") or context.get("original_task") or "")
        missing_evidence = self._completed_report_lacks_required_evidence(
            task_text,
            summary,
            result,
        )
        raw_unfinished = self._summary_indicates_unfinished(self._execution_evidence_text(result))
        unfinished = (
            self._summary_indicates_unfinished(summary) or raw_unfinished or missing_evidence
        )
        success = (
            status in {"completed", "done"} and result.get("ok") is not False and not unfinished
        )
        effective_status = status
        if status in {"completed", "done"} and not success:
            effective_status = "failed" if self._summary_indicates_failed(summary) else "blocked"
        dispatcher = self._relay_result_dispatch_value(result, "dispatcher")
        dispatch_status = self._relay_result_dispatch_value(result, "status")
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
            "risk": (
                "回报只有调研/方案或缺少改动文件、命令、测试、构建、安装证据，不能自动验收。"
                if missing_evidence
                else self._relay_result_risk(
                    result=result,
                    success=success,
                    task_id=str(task.get("task_id") or ""),
                    dispatcher=dispatcher,
                )
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

    @classmethod
    def _relay_result_summary(cls, result: dict[str, Any], status: str, task_id: str) -> str:
        for value in (
            result.get("summary"),
            result.get("message"),
            result.get("output"),
            result.get("report"),
            result.get("reply"),
            result.get("error"),
        ):
            text = cls._stringify_summary(value)
            if text:
                return cls._chat_friendly_summary(text)
        for value in result.values():
            if not isinstance(value, dict):
                continue
            assistant = value.get("assistant_message")
            if isinstance(assistant, dict):
                text = cls._stringify_summary(assistant.get("body"))
                if text:
                    return cls._chat_friendly_summary(text)
            text = cls._stringify_summary(value.get("summary") or value.get("message"))
            if text:
                return cls._chat_friendly_summary(text)
        return f"中继任务已{status or '完成'}（task_id={task_id}）。"

    @staticmethod
    def _chat_friendly_summary(
        value: str,
        limit: int = CHAT_REPORT_SUMMARY_CHARS,
        *,
        include_detail_note: bool = True,
    ) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return ""
        useful: list[str] = []
        in_code = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code or line in {"---", "***"} or line.startswith("|"):
                continue
            line = line.lstrip("#").strip()
            line = line.lstrip("-*•> ").strip()
            line = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._clean_chat_summary_line(line)
            if not line:
                continue
            useful.append(line)
            if len("；".join(useful)) >= limit or len(useful) >= 3:
                break
        summary = "；".join(useful) if useful else text.replace("\n", "；")
        if len(summary) > limit:
            summary = summary[: limit - 1].rstrip() + "…"
        if include_detail_note and len(text) > len(summary) + 80:
            summary += "（详细结果已保留在执行端记录）"
        return summary

    @staticmethod
    def _clean_chat_summary_line(line: str) -> str:
        text = _TEMP_PATH_RE.sub("临时执行工作区", str(line or ""))
        text = _MARKDOWN_LINK_RE.sub(r"\1", text)
        text = _BROKEN_MARKDOWN_LINK_RE.sub(r"\1", text)
        for token in ("**", "__", "`"):
            text = text.replace(token, "")
        return " ".join(text.split()).strip("；，。 ")

    @classmethod
    def _relay_result_risk(
        cls,
        *,
        result: dict[str, Any],
        success: bool,
        task_id: str,
        dispatcher: str,
    ) -> str:
        for value in (result.get("risk"), result.get("error"), result.get("reason")):
            text = cls._stringify_summary(value)
            if text:
                return text[:500]
        if not success:
            text = cls._stringify_summary(result.get("reply"))
            if text:
                return cls._chat_friendly_summary(text, limit=500, include_detail_note=False)
        parts: list[str] = []
        if success:
            parts.append("未发现阻塞")
        else:
            parts.append("中继任务未成功完成")
        if dispatcher:
            parts.append(f"执行端：{dispatcher}")
        if task_id:
            parts.append(f"中继任务：{task_id}")
        return "；".join(parts) + "。"

    @classmethod
    def _effective_report_status(cls, row: dict[str, Any]) -> str:
        report = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        status = str(row.get("status") or report.get("status") or "").strip().lower()
        summary = cls._stringify_summary(report.get("summary") or row.get("body") or "")
        success = report.get("success")
        task = cls._stringify_summary(report.get("original_task") or report.get("task") or "")
        missing_evidence = cls._completed_report_lacks_required_evidence(
            task,
            summary,
            report.get("raw") if isinstance(report.get("raw"), dict) else report,
        )
        raw_unfinished = cls._summary_indicates_unfinished(cls._execution_evidence_text(report))
        if status in {"completed", "done"} and (
            success is False
            or cls._summary_indicates_unfinished(summary)
            or raw_unfinished
            or missing_evidence
        ):
            return "failed" if cls._summary_indicates_failed(summary) else "blocked"
        return "completed" if status == "done" else status

    @staticmethod
    def _summary_indicates_unfinished(text: str) -> bool:
        if not text:
            return False
        compact = str(text).replace(" ", "")
        return any(
            marker in text or marker.replace(" ", "") in compact
            for marker in _UNFINISHED_REPORT_MARKERS
        )

    @staticmethod
    def _summary_indicates_failed(text: str) -> bool:
        return any(marker in str(text or "") for marker in _FAILED_REPORT_MARKERS)

    @classmethod
    def _completed_report_lacks_required_evidence(
        cls,
        task: str,
        summary: str,
        raw: Any = None,
    ) -> bool:
        if not cls._task_requires_execution_evidence(task):
            return False
        evidence_text = cls._execution_evidence_text(summary, raw)
        return not cls._has_execution_evidence(evidence_text)

    @staticmethod
    def _task_requires_execution_evidence(task: str) -> bool:
        text = str(task or "").strip().lower()
        if not text:
            return False
        has_dev_marker = any(marker.lower() in text for marker in _DEV_TASK_MARKERS)
        if not has_dev_marker:
            return False
        research_only = any(marker.lower() in text for marker in _PURE_RESEARCH_TASK_MARKERS)
        if research_only and not any(
            marker in text
            for marker in ("修复", "实现", "开发", "添加", "新增", "更新", "测试", "验收", "合并")
        ):
            return False
        return True

    @classmethod
    def _has_execution_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value or cls._summary_indicates_unfinished(value):
            return False
        lower = value.lower()
        if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
            return True
        if _EVIDENCE_FILE_RE.search(value):
            return True
        return False

    @classmethod
    def _execution_evidence_text(cls, *values: Any) -> str:
        chunks: list[str] = []

        def walk(value: Any, *, depth: int = 0) -> None:
            if value is None or depth > 6 or len(" ".join(chunks)) > 20000:
                return
            if isinstance(value, str):
                text = value.strip()
                if text:
                    chunks.append(text)
                return
            if isinstance(value, dict):
                priority = (
                    "body",
                    "summary",
                    "message",
                    "output",
                    "report",
                    "reply",
                    "error",
                    "reason",
                    "risk",
                    "assistant_message",
                    "result",
                    "data",
                )
                seen: set[str] = set()
                for key in priority:
                    if key in value:
                        seen.add(key)
                        walk(value.get(key), depth=depth + 1)
                for key, child in value.items():
                    if key not in seen:
                        walk(child, depth=depth + 1)
                return
            if isinstance(value, list | tuple):
                for item in value:
                    walk(item, depth=depth + 1)
                return
            text = cls._stringify_summary(value)
            if text:
                chunks.append(text)

        for value in values:
            walk(value)
        return " ".join(chunks)[:20000]

    @classmethod
    def _summary_is_research_only_without_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        if cls._has_execution_evidence(value):
            return False
        return any(marker in value for marker in _RESEARCH_ONLY_REPORT_MARKERS)

    @staticmethod
    def _relay_result_dispatch_value(result: dict[str, Any], key: str) -> str:
        for value in result.values():
            if not isinstance(value, dict):
                continue
            dispatch = value.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get(key) is not None:
                return str(dispatch.get(key) or "")
        return ""

    @staticmethod
    def _execution_summary(result: dict[str, Any]) -> str:
        candidates = (
            result.get("summary"),
            result.get("message"),
            result.get("output"),
            result.get("result"),
            result.get("report"),
        )
        for value in candidates:
            text = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(value)
            if text:
                return text[:1200]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("summary", "message", "output", "result", "report"):
                text = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(data.get(key))
                if text:
                    return text[:1200]
        return _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(result)[:1200]

    @staticmethod
    def _execution_risk(result: dict[str, Any], success: bool) -> str:
        candidates = (result.get("risk"), result.get("risks"), result.get("blocker"))
        for value in candidates:
            text = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(value)
            if text:
                return text[:500]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("risk", "risks", "blocker"):
                text = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(data.get(key))
                if text:
                    return text[:500]
        return "未发现阻塞。" if success else "执行失败，需负责人介入。"

    @staticmethod
    def _stringify_summary(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1200]
        except TypeError:
            return str(value)[:1200]

    @staticmethod
    def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "success",
            "status",
            "message",
            "summary",
            "task_id",
            "run_id",
            "error",
            "dispatch_request_id",
            "dispatcher",
            "relay_id",
        ):
            if key in result:
                value = result[key]
                if value is None or isinstance(value, str | int | float | bool):
                    compact[key] = value
                else:
                    compact[key] = _facade_attr("AiGroupChatService", AiGroupChatReportsMixin)._stringify_summary(value)
        return compact

    async def _super_employee_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        """超级员工群聊回复：调用专用 invoke 通道（CLI 直答 / Para 派工）。

        超级员工的回复结果会写入其自身会话的 messages.jsonl（由 invoke 内部完成），
        群聊消息则写入 ai_group_chat/messages.jsonl（由调用方 post_message 完成），
        两者独立持久化，互不干扰。
        """
        from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
        from app.application.codex_super_employee_service import CodexSuperEmployeeService
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService
        from app.application.trae_super_employee_service import TraeSuperEmployeeService

        employee_id = str(member.get("employee_id") or "")
        me = str(member.get("name") or employee_id)
        group_name = str(group.get("name") or "AI 群聊")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        prompt = (
            f"你是群聊「{group_name}」里的成员「{me}」。\n"
            f"群成员有：{roster}。\n"
            f"【群最近对话】\n{transcript}\n\n"
            f"请以「{me}」身份回应最新这条消息，用一两句话简洁回应。"
        )
        try:
            if employee_id == "codex-super-employee":
                service = CodexSuperEmployeeService()
            elif employee_id == "cursor-super-employee":
                service = CursorSuperEmployeeService()
            elif employee_id == "trae-super-employee":
                service = TraeSuperEmployeeService()
            else:
                service = ClaudeSuperEmployeeService()
            # 群聊场景强制走 CLI 直答（mode=chat），避免 transcript 里包含
            # "修改/测试/调用"等 _TASK_MARKERS 词被误判为任务走派工流程，
            # 导致本机无 Para 时只返回"思考中..."而永远等不到答案。
            # 阻塞的 CLI 子进程调用放到工作线程跑，避免冻住事件循环、
            # 导致同一服务上其它群聊/接口在本次「思考」期间全部卡住。
            result = await asyncio.to_thread(
                service.invoke,
                user_id=int(user_id),
                message=prompt,
                context={"mode": "chat"},
            )
            assistant = result.get("assistant_message") or {}
            body = str(assistant.get("body") or "").strip()
            if body:
                return body
            return f"（{me} 暂时无法回应）"
        except Exception as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"

    # ── 部门种子 ──
