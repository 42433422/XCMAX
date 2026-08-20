# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class __AiGroupChatServicePart01MixinPart02Mixin:
    def add_member(
        self, *, user_id: int, group_id: str, member: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        employee_id = str(member.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id 不能为空")
        if self._mode != "admin" and employee_id in _facade()._SUPER_EMPLOYEE_IDS:
            raise ValueError("超级员工仅管理端可邀请")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        members = _facade()._with_required_group_members(members)
        if any(str(m.get("employee_id")) == employee_id for m in members):
            group["members"] = members
            self._rewrite_groups(self._replace(self._all_groups(), group))
            return self._public_group(group, None)
        members.append(
            {
                "employee_id": employee_id,
                "mod_id": str(member.get("mod_id") or ""),
                "name": str(member.get("name") or employee_id)[:60],
                "avatar": str(member.get("avatar") or ""),
                "avatar_key": str(member.get("avatar_key") or ""),
                "summary": str(member.get("summary") or "")[:280],
            }
        )
        group["members"] = _facade()._with_required_group_members(members)
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def remove_member(
        self, *, user_id: int, group_id: str, employee_id: str
    ) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        if _facade()._is_required_group_member(employee_id):
            group["members"] = _facade()._with_required_group_members(
                [m for m in group.get("members", []) if isinstance(m, dict)]
            )
            self._rewrite_groups(self._replace(self._all_groups(), group))
            return self._public_group(group, None)
        group["members"] = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id")) != str(employee_id)
        ]
        group["members"] = _facade()._with_required_group_members(group["members"])
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_pinned(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_pinned"] = not bool(group.get("is_pinned"))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_unread(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        current = int(group.get("unread_count") or 0)
        group["unread_count"] = max(1, current + 1 if current > 0 else 1)
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_read(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["unread_count"] = 0
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_followed(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_followed"] = not bool(group.get("is_followed", True))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_hidden(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_hidden"] = not bool(group.get("is_hidden"))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def delete_group(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any]:
        groups = self._all_groups()
        remaining = [g for g in groups if str(g.get("id")) != str(group_id)]
        if len(remaining) == len(groups):
            raise ValueError("群不存在")
        self._rewrite_groups(remaining)
        return {"deleted": True, "id": str(group_id)}

    def get_messages(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, _facade().Any]]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        self._sync_relay_progress_for_group(user_id=user_id, group_id=group_id)
        self._sync_super_employee_progress_for_group(user_id=user_id, group_id=group_id)
        rows = [
            self._public_message(r)
            for r in self._read_messages()
            if int(r.get("user_id") or 0) == int(user_id)
            and str(r.get("group_id")) == str(group_id)
        ]
        return rows[-max(1, min(int(limit), 300)) :]

    def _sync_relay_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Append human-readable relay progress while the desktop executor works.

        The mobile screen polls this endpoint. Without side-effectful progress
        rows the user sees "已接单" for minutes and cannot tell whether the team
        is actually working. This method is intentionally rate-limited per relay
        task to avoid chat spam and mobile memory pressure.
        """
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
            and self._report_relay_task_id(row)
            and (self._report_relay_task_id(row) not in final_task_ids)
        ]
        if not pending_reports:
            return
        try:
            relay = self._mobile_relay_service()
        except _facade().RECOVERABLE_ERRORS:
            return
        get_task = getattr(relay, "get_task", None)
        if not callable(get_task):
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        for report in pending_reports:
            task_id = self._report_relay_task_id(report)
            try:
                task = get_task(user_id=int(user_id), task_id=task_id)
            except _facade().RECOVERABLE_ERRORS:
                continue
            if not isinstance(task, dict) or not task:
                continue
            status = str(task.get("status") or report.get("status") or "").strip().lower()
            if status in {"completed", "done", "failed", "blocked", "cancelled"}:
                self.append_relay_work_report(task=task)
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
                sender_id=str(report.get("sender_id") or ""),
                sender_name=str(report.get("sender_name") or "负责人"),
                sender_avatar=str(report.get("sender_avatar") or ""),
                body=self._format_relay_progress_message(report=report, task=task, status=status),
                kind="work_progress",
                status=status,
                work_order_id=str(report.get("work_order_id") or ""),
                payload={
                    "work_order_id": str(report.get("work_order_id") or ""),
                    "employee_id": str(report.get("sender_id") or ""),
                    "employee_name": str(report.get("sender_name") or ""),
                    "status": status,
                    "summary": self._relay_progress_summary(status, task_id),
                    "raw": {
                        "task_id": task_id,
                        "relay_id": str(task.get("relay_id") or ""),
                        "kind": str(task.get("kind") or ""),
                    },
                },
            )
            self._append_messages([progress])
            progress_rows.append(progress)
