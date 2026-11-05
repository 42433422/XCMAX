"""Pure work-message text, summaries and task status labels."""

from __future__ import annotations

from typing import Any

from app.application.group_chat.constants import (
    _BROKEN_MARKDOWN_LINK_RE,
    _MARKDOWN_LINK_RE,
    _TEMP_PATH_RE,
    CHAT_ACCEPTANCE_SUMMARY_CHARS,
    CHAT_REPORT_SUMMARY_CHARS,
)
from app.application.group_chat.evidence import ExecutionResultPolicy


class ChatFormatting:
    @staticmethod
    def clean_chat_summary_line(line: str) -> str:
        text = _TEMP_PATH_RE.sub("临时执行工作区", str(line or ""))
        text = _MARKDOWN_LINK_RE.sub("\\1", text)
        text = _BROKEN_MARKDOWN_LINK_RE.sub("\\1", text)
        for token in ("**", "__", "`"):
            text = text.replace(token, "")
        return " ".join(text.split()).strip("；，。 ")

    @staticmethod
    def chat_friendly_summary(
        value: str, limit: int = CHAT_REPORT_SUMMARY_CHARS, *, include_detail_note: bool = True
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
            line = ChatFormatting.clean_chat_summary_line(line)
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
    def relay_result_risk(
        *, result: dict[str, Any], success: bool, task_id: str, dispatcher: str
    ) -> str:
        for value in (result.get("risk"), result.get("error"), result.get("reason")):
            text = ExecutionResultPolicy.stringify_summary(value)
            if text:
                return text[:500]
        if not success:
            text = ExecutionResultPolicy.stringify_summary(result.get("reply"))
            if text:
                return ChatFormatting.chat_friendly_summary(
                    text, limit=500, include_detail_note=False
                )
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

    @staticmethod
    def relay_result_summary(result: dict[str, Any], status: str, task_id: str) -> str:
        for value in (
            result.get("summary"),
            result.get("message"),
            result.get("output"),
            result.get("report"),
            result.get("reply"),
            result.get("error"),
        ):
            text = ExecutionResultPolicy.stringify_summary(value)
            if text:
                return ChatFormatting.chat_friendly_summary(text)
        for value in result.values():
            if not isinstance(value, dict):
                continue
            assistant = value.get("assistant_message")
            if isinstance(assistant, dict):
                text = ExecutionResultPolicy.stringify_summary(assistant.get("body"))
                if text:
                    return ChatFormatting.chat_friendly_summary(text)
            text = ExecutionResultPolicy.stringify_summary(
                value.get("summary") or value.get("message")
            )
            if text:
                return ChatFormatting.chat_friendly_summary(text)
        return f"中继任务已{status or '完成'}（task_id={task_id}）。"

    @staticmethod
    def report_relay_task_id(row: dict[str, Any]) -> str:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        return str(raw.get("task_id") or payload.get("task_id") or "").strip()

    @staticmethod
    def public_status_label(status: str) -> str:
        return {
            "completed": "完成",
            "done": "完成",
            "failed": "失败",
            "blocked": "阻塞",
            "cancelled": "已取消",
        }.get(str(status or "").strip().lower(), str(status or "已回报"))

    @staticmethod
    def strip_label_from_body(body: str, label: str) -> str:
        text = (body or "").strip()
        if text.startswith(label):
            text = text[len(label) :].strip()
        return text.splitlines()[0][:160] if text else ""

    @staticmethod
    def format_work_order_message(
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
        return f"【小C派单】{task}\n负责人：{owners}\n{branch_line}{assignment_block}\n流程：接单 → 执行 → 回报 → 小C验收。\n你不用翻执行端，我会把最终结果收口到这条群聊里。"

    @staticmethod
    def format_work_report_message(member: dict[str, Any], report: dict[str, Any]) -> str:
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
        return f"【{name} 执行汇报】\n状态：{status}\n{focus_line}{branch_line}结果：{summary}\n风险：{risk}\n下一步：{next_step}"

    @staticmethod
    def format_work_acceptance_message(
        *,
        work_order: dict[str, Any],
        final_reports: list[dict[str, Any]],
        ok_count: int,
        total: int,
        all_ok: bool,
    ) -> str:
        raw_payload = work_order.get("payload")
        payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        task = str(payload.get("task") or "").strip() or ChatFormatting.strip_label_from_body(
            str(work_order.get("body") or ""), "【小C派单】"
        )
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        conclusion = "可以验收" if all_ok else "需要复核"
        lines: list[str] = []
        for row in final_reports:
            raw_report = row.get("payload")
            report: dict[str, Any] = dict(raw_report) if isinstance(raw_report, dict) else {}
            name = str((row or {}).get("sender_name") or report.get("employee_name") or "负责人")
            status = ExecutionResultPolicy.effective_report_status(row)
            focus = str(report.get("assignment_focus") or "").strip()
            summary = ChatFormatting.chat_friendly_summary(
                str(report.get("summary") or row.get("body") or ""),
                limit=CHAT_ACCEPTANCE_SUMMARY_CHARS,
                include_detail_note=False,
            )
            prefix = f"{name}（{focus}）" if focus else name
            lines.append(f"- {prefix}：{ChatFormatting.public_status_label(status)}。{summary}")
        risk = "未发现阻塞。" if all_ok else "有负责人未完成或回报异常，需要你复核后再继续。"
        return (
            f"【小C验收】这单已收口\n结论：{conclusion}（{ok_count}/{total} 个负责人已完成）\n任务：{task[:80]}\n"
            + (f"分支：{branch[:120]}\n" if branch else "")
            + "成员：\n"
            + "\n".join(lines[:6])
            + f"\n风险：{risk}\n下一步：满意就继续派下一步；不满意就直接说要谁补什么。"
        )

    @staticmethod
    def format_acceptance_followup_message(
        *, work_order: dict[str, Any], rows: list[dict[str, Any]], had_acceptance: bool
    ) -> str:
        payload = work_order.get("payload") if isinstance(work_order.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        task = str(payload.get("task") or "").strip() or ChatFormatting.strip_label_from_body(
            str(work_order.get("body") or ""), "【小C派单】"
        )
        if had_acceptance:
            return f"【小C回访】最新派工已有验收结论。\n任务：{task[:80]}\n你可以继续补充问题，或直接派下一步。"
        reports = [
            row
            for row in rows
            if str(row.get("kind") or "") in {"work_report", "work_progress", "relay_work_report"}
        ]
        if not reports:
            return f"【小C回访】最新派工已发出，正在等待负责人接单或回报。\n任务：{task[:80]}\n我会继续把进度同步到群里。"
        latest_by_task: dict[str, dict[str, Any]] = {}
        for row in reports:
            task_id = ChatFormatting.report_relay_task_id(row) or str(row.get("id") or "")
            old = latest_by_task.get(task_id)
            if old is None or str(row.get("created_at") or "") >= str(old.get("created_at") or ""):
                latest_by_task[task_id] = row
        lines = []
        for row in list(latest_by_task.values())[:6]:
            name = str(row.get("sender_name") or "负责人")
            status = ChatFormatting.public_status_label(
                ExecutionResultPolicy.effective_report_status(row)
            )
            summary = ChatFormatting.chat_friendly_summary(
                str(row.get("body") or ""), limit=54, include_detail_note=False
            )
            lines.append(f"- {name}：{status}。{summary}")
        return (
            f"【小C回访】最新派工还在处理中。\n任务：{task[:80]}\n"
            + ("进度：\n" + "\n".join(lines) + "\n" if lines else "")
            + "结论：暂未达到自动验收条件。"
        )

    @staticmethod
    def format_relay_progress_message(
        *, report: dict[str, Any], task: dict[str, Any], status: str
    ) -> str:
        name = str(report.get("sender_name") or "负责人")
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        focus = str(payload.get("assignment_focus") or "").strip()
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        task_id = str(task.get("task_id") or ChatFormatting.report_relay_task_id(report))
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
        return f"【{name} 进度回访】\n状态：{status_label}\n{focus_line}{branch_line}结果：{ChatFormatting.relay_progress_summary(status, task_id)}我会继续等执行端回写，不需要你退出重进。\n风险：暂无新的阻塞；如果执行端超时，群里会保留这条任务号方便追踪。\n下一步：继续执行，完成后自动发员工回报并交给小C验收。"

    @staticmethod
    def relay_progress_summary(status: str, task_id: str) -> str:
        label = {
            "queued": "还在服务器队列中",
            "accepted": "执行端已接单",
            "assigned": "执行端已接单",
            "running": "电脑执行端正在处理",
            "processing": "电脑执行端正在处理",
            "in_progress": "电脑执行端正在处理",
        }.get(status, "还在处理中")
        return f"{label}，任务号：{task_id[:8]}。"
