# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class __AiGroupChatServicePart02MixinPart02Mixin:
    async def post_message(
        self,
        *,
        user_id: int,
        group_id: str,
        text: str,
        sender_name: str = "我",
        mentions: list[str] | None = None,
        dispatch: bool = False,
        branch_context: str = "",
        context: dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
        action_context = context if isinstance(context, dict) else {}
        tool_action = str(action_context.get("tool_action") or "").strip()
        branch_context = _facade()._normalize_branch_context(branch_context)
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = _facade()._with_required_group_members(
            [m for m in group.get("members", []) if isinstance(m, dict)]
        )
        if members != group.get("members", []):
            group["members"] = members
            self._rewrite_groups(self._replace(self._all_groups(), group))
        user_msg = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="user",
            sender_id="user",
            sender_name=sender_name or "我",
            sender_avatar="",
            body=body,
            payload={"branch_context": branch_context} if dispatch and branch_context else None,
        )
        new_messages = [user_msg]
        self._append_messages([user_msg])
        if tool_action == "acceptance_followup":
            followup = self._append_acceptance_followup(user_id=user_id, group_id=group_id)
            if followup is not None:
                new_messages.append(followup)
            previews = self._latest_previews(user_id)
            return {
                "group": self._public_group(group, previews.get(str(group.get("id")))),
                "messages": [self._public_message(m) for m in new_messages],
            }
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        history = self.get_messages(
            user_id=user_id, group_id=group_id, limit=_facade().CONTEXT_TURNS
        )
        work_orders: list[dict[str, _facade().Any]] = []
        if dispatch:
            responders = self._pick_dispatch_targets(members, body, mentions)
            discussion_messages: list[dict[str, _facade().Any]] = []
            if self._should_run_super_discussion(responders):
                (discussion_messages, responders) = await self._run_super_discussion_then_route(
                    group=group,
                    task=body,
                    candidates=responders,
                    user_id=user_id,
                    history=history,
                    mentions=mentions,
                    persist=True,
                )
                new_messages.extend(discussion_messages)
            (dispatch_messages, work_orders) = await self._dispatch_work(
                group=group,
                members=responders,
                task=body,
                user_id=user_id,
                sender_name=sender_name or "我",
                branch_context=branch_context,
                persist=True,
            )
            new_messages.extend(dispatch_messages)
        else:
            responders = self._pick_responders(members, body, mentions)
            for member in responders:
                reply = await self._ai_reply(group, member, history, user_id=user_id)
                ai_msg = self._message_row(
                    user_id=user_id,
                    group_id=group_id,
                    role="ai",
                    sender_id=str(member.get("employee_id")),
                    sender_name=str(member.get("name") or member.get("employee_id")),
                    sender_avatar=str(member.get("avatar") or ""),
                    body=reply,
                )
                new_messages.append(ai_msg)
                self._append_messages([ai_msg])
                history = history + [self._public_message(ai_msg)]
        previews = self._latest_previews(user_id)
        result: dict[str, _facade().Any] = {
            "group": self._public_group(group, previews.get(str(group.get("id")))),
            "messages": [self._public_message(m) for m in new_messages],
        }
        if dispatch:
            result["work_orders"] = work_orders
        return result

    def _append_acceptance_followup(
        self, *, user_id: int, group_id: str
    ) -> dict[str, _facade().Any] | None:
        self._sync_relay_progress_for_group(user_id=user_id, group_id=group_id)
        self._sync_super_employee_progress_for_group(user_id=user_id, group_id=group_id)
        rows = [
            row
            for row in self._read_messages()
            if int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("group_id") or "") == str(group_id)
        ]
        work_orders = [row for row in rows if str(row.get("kind") or "") == "work_order"]
        if not work_orders:
            row = self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id=_facade()._XIAOC_ASSISTANT_ID,
                sender_name="小C助理",
                sender_avatar="",
                body="【小C回访】还没有可回访的派工单。\n先输入任务后点“任务派工”，我会在群里派负责人并收口验收。",
                kind="work_followup",
                status="empty",
            )
            self._append_messages([row])
            return _facade().cast("dict[str, Any] | None", row)
        work_order = max(work_orders, key=lambda row: str(row.get("created_at") or ""))
        work_order_id = str(work_order.get("work_order_id") or "")
        had_acceptance = any(
            str(row.get("kind") or "") == "work_acceptance"
            and str(row.get("work_order_id") or "") == work_order_id
            for row in rows
        )
        acceptance = self._append_work_acceptance_if_ready(
            user_id=user_id, group_id=group_id, work_order_id=work_order_id
        )
        if acceptance is not None and (not had_acceptance):
            return next(
                (
                    row
                    for row in self._read_messages()
                    if str(row.get("id") or "") == str(acceptance.get("id") or "")
                ),
                None,
            )
        body = self._format_acceptance_followup_message(
            work_order=work_order,
            rows=[
                row
                for row in self._read_messages()
                if str(row.get("work_order_id") or "") == work_order_id
            ],
            had_acceptance=bool(acceptance),
        )
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_facade()._XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=body,
            kind="work_followup",
            status="completed" if acceptance is not None else "in_progress",
            work_order_id=work_order_id,
        )
        self._append_messages([row])
        return _facade().cast("dict[str, Any] | None", row)

    @classmethod
    def _format_acceptance_followup_message(
        cls,
        *,
        work_order: dict[str, _facade().Any],
        rows: list[dict[str, _facade().Any]],
        had_acceptance: bool,
    ) -> str:
        payload = work_order.get("payload") if isinstance(work_order.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        task = str(payload.get("task") or "").strip() or cls._strip_label_from_body(
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
        latest_by_task: dict[str, dict[str, _facade().Any]] = {}
        for row in reports:
            task_id = cls._report_relay_task_id(row) or str(row.get("id") or "")
            old = latest_by_task.get(task_id)
            if old is None or str(row.get("created_at") or "") >= str(old.get("created_at") or ""):
                latest_by_task[task_id] = row
        lines = []
        for row in list(latest_by_task.values())[:6]:
            name = str(row.get("sender_name") or "负责人")
            status = cls._public_status_label(cls._effective_report_status(row))
            summary = cls._chat_friendly_summary(
                str(row.get("body") or ""), limit=54, include_detail_note=False
            )
            lines.append(f"- {name}：{status}。{summary}")
        return (
            f"【小C回访】最新派工还在处理中。\n任务：{task[:80]}\n"
            + ("进度：\n" + "\n".join(lines) + "\n" if lines else "")
            + "结论：暂未达到自动验收条件。"
        )
