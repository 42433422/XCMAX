# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class _AiGroupChatServicePart03Mixin:
    @staticmethod
    def _format_work_report_message(
        member: dict[str, _facade().Any], report: dict[str, _facade().Any]
    ) -> str:
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

    def _relay_report_message(
        self, *, user_id: int, group_id: str, task_id: str
    ) -> dict[str, _facade().Any] | None:
        for row in self._read_messages():
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

    def _append_work_acceptance_if_ready(
        self, *, user_id: int, group_id: str, work_order_id: str
    ) -> dict[str, _facade().Any] | None:
        if not work_order_id:
            return None
        rows = [
            row
            for row in self._read_messages()
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
            sender_id=_facade()._XIAOC_ASSISTANT_ID,
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
                        dict(work_order["payload"])
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
        work_order: dict[str, _facade().Any],
        final_reports: list[dict[str, _facade().Any]],
        ok_count: int,
        total: int,
        all_ok: bool,
    ) -> str:
        raw_payload = work_order.get("payload")
        payload: dict[str, _facade().Any] = (
            dict(raw_payload) if isinstance(raw_payload, dict) else {}
        )
        task = str(payload.get("task") or "").strip() or cls._strip_label_from_body(
            str(work_order.get("body") or ""), "【小C派单】"
        )
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        conclusion = "可以验收" if all_ok else "需要复核"
        lines: list[str] = []
        for row in final_reports:
            raw_report = row.get("payload")
            report: dict[str, _facade().Any] = (
                dict(raw_report) if isinstance(raw_report, dict) else {}
            )
            name = str((row or {}).get("sender_name") or report.get("employee_name") or "负责人")
            status = cls._effective_report_status(row)
            focus = str(report.get("assignment_focus") or "").strip()
            summary = cls._chat_friendly_summary(
                str(report.get("summary") or row.get("body") or ""),
                limit=_facade().CHAT_ACCEPTANCE_SUMMARY_CHARS,
                include_detail_note=False,
            )
            prefix = f"{name}（{focus}）" if focus else name
            lines.append(f"- {prefix}：{cls._public_status_label(status)}。{summary}")
        risk = "未发现阻塞。" if all_ok else "有负责人未完成或回报异常，需要你复核后再继续。"
        return (
            f"【小C验收】这单已收口\n结论：{conclusion}（{ok_count}/{total} 个负责人已完成）\n任务：{task[:80]}\n"
            + (f"分支：{branch[:120]}\n" if branch else "")
            + "成员：\n"
            + "\n".join(lines[:6])
            + f"\n风险：{risk}\n下一步：满意就继续派下一步；不满意就直接说要谁补什么。"
        )

    @staticmethod
    def _report_relay_task_id(row: dict[str, _facade().Any]) -> str:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        if not isinstance(raw, dict):
            raw = {}
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

    def _relay_task_report(
        self, *, task: dict[str, _facade().Any], member: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any]:
        raw_payload = task.get("payload")
        payload: dict[str, _facade().Any] = (
            dict(raw_payload) if isinstance(raw_payload, dict) else {}
        )
        raw_context = payload.get("context")
        context: dict[str, _facade().Any] = (
            dict(raw_context) if isinstance(raw_context, dict) else {}
        )
        raw_result = task.get("result")
        result: dict[str, _facade().Any] = dict(raw_result) if isinstance(raw_result, dict) else {}
        status = str(task.get("status") or "completed").strip().lower()
        summary = self._relay_result_summary(result, status, str(task.get("task_id") or ""))
        task_text = str(payload.get("message") or context.get("original_task") or "")
        missing_evidence = self._completed_report_lacks_required_evidence(
            task_text, summary, result
        )
        raw_unfinished = self._summary_indicates_unfinished(self._execution_evidence_text(result))
        unfinished = (
            self._summary_indicates_unfinished(summary) or raw_unfinished or missing_evidence
        )
        if not isinstance(result, dict):
            result = {}
        success = (
            status in {"completed", "done"} and result.get("ok") is not False and (not unfinished)
        )
        effective_status = status
        if status in {"completed", "done"} and (not success):
            effective_status = "failed" if self._summary_indicates_failed(summary) else "blocked"
        dispatcher = self._relay_result_dispatch_value(result, "dispatcher")
        dispatch_status = self._relay_result_dispatch_value(result, "status")
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
            else self._relay_result_risk(
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

    @classmethod
    def _relay_result_summary(
        cls, result: dict[str, _facade().Any], status: str, task_id: str
    ) -> str:
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
        limit: int = _facade().CHAT_REPORT_SUMMARY_CHARS,
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
            line = _facade().AiGroupChatService._clean_chat_summary_line(line)
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

    def _seed_department_groups(self, user_id: int) -> list[dict[str, _facade().Any]]:
        depts = self._department_loader()
        pairs: list[tuple[str, str]] = []
        if isinstance(depts, dict) and depts:
            for key, info in depts.items():
                label = ""
                if isinstance(info, dict):
                    label = str(info.get("label") or "").strip()
                pairs.append((str(key), label or str(key)))
        if not pairs:
            pairs = list(
                _facade()._FALLBACK_ENTERPRISE_DEPARTMENTS
                if self._mode == "enterprise"
                else _facade()._FALLBACK_DEPARTMENTS
            )
        members_by_dept: dict[str, list[dict[str, _facade().Any]]] = {}
        try:
            for emp in self._employee_loader() or [] if self._mode == "admin" else []:
                if not isinstance(emp, dict):
                    continue
                dk = str(emp.get("department_key") or "").strip()
                if not dk:
                    continue
                members_by_dept.setdefault(dk, []).append(
                    {
                        "employee_id": str(emp.get("employee_id") or ""),
                        "mod_id": str(emp.get("mod_id") or ""),
                        "name": str(emp.get("name") or emp.get("employee_id") or "")[:60],
                        "avatar": str(emp.get("avatar") or ""),
                        "summary": str(emp.get("summary") or "")[:280],
                    }
                )
        except _facade().RECOVERABLE_ERRORS:
            members_by_dept = {}
        seeded: list[dict[str, _facade().Any]] = []
        for key, label in pairs:
            members = _facade()._with_required_group_members(members_by_dept.get(key, []))
            roster_ids = sorted(
                {
                    _facade()._member_employee_id(member)
                    for member in members_by_dept.get(key, [])
                    if _facade()._member_employee_id(member)
                }
            )
            seeded.append(
                {
                    "id": f"dept:{key}",
                    "user_id": int(user_id),
                    "name": label,
                    "department_key": key,
                    "members": members,
                    "members_seeded": bool(roster_ids),
                    "members_seeded_employee_ids": roster_ids,
                    "is_pinned": False,
                    "is_hidden": False,
                    "is_followed": True,
                    "unread_count": 0,
                    "created_at": _facade()._utc_now(),
                }
            )
        for g in seeded:
            self._append_group(g)
        return seeded
