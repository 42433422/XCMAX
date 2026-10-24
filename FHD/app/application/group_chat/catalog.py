"""Group membership, presentation preferences and legacy room migration."""

from __future__ import annotations

import uuid
from typing import Any

from app.application.group_chat.constants import _SUPER_EMPLOYEE_IDS
from app.application.group_chat.employee_registry import (
    _is_required_group_member,
    _utc_now,
    _with_required_group_members,
)
from app.application.group_chat.ports import DirectoryActions, GroupStore, MessageStore
from app.application.group_chat.projections import ChatProjection
from app.application.group_chat.storage import GroupChatRepository


class GroupCatalog:
    def __init__(
        self, groups: GroupStore, messages: MessageStore, directory: DirectoryActions, *, mode: str
    ) -> None:
        self.groups = groups
        self.messages = messages
        self.directory = directory
        self.mode = mode

    def list_groups(self, *, user_id: int, include_hidden: bool = False) -> list[dict[str, Any]]:
        self.groups.compact()
        groups = self.groups.for_user(user_id)
        if not groups:
            groups = self.directory.seed(user_id)
        else:
            self.directory.backfill(groups)
            self.ensure_required_members(user_id)
            self.ensure_special_group_names(user_id)
            self.merge_duplicate_super_development_groups(user_id)
            groups = self.groups.for_user(user_id)
        previews = self.messages.previews(user_id)
        if not include_hidden:
            groups = [g for g in groups if not g.get("is_hidden")]

        def _sort_key(g: dict[str, Any]) -> tuple:
            pinned = 1 if g.get("is_pinned") else 0
            preview = previews.get(str(g.get("id")))
            last_at = (preview or {}).get("created_at") or g.get("created_at") or ""
            return (pinned, last_at)

        groups.sort(key=_sort_key, reverse=True)
        return [ChatProjection.public_group(g, previews.get(str(g.get("id")))) for g in groups]

    def ensure_required_members(self, user_id: int) -> None:
        all_groups = self.groups.all()
        changed = False
        for g in all_groups:
            if not isinstance(g, dict) or int(g.get("user_id") or 0) != int(user_id):
                continue
            current = [m for m in g.get("members", []) if isinstance(m, dict)]
            merged = _with_required_group_members(current)
            if merged != current:
                g["members"] = merged
                changed = True
        if changed:
            self.groups.rewrite(all_groups)

    def ensure_special_group_names(self, user_id: int) -> None:
        """Backfill canonical names for system-like groups.

        Older mobile builds created a super-development group with the member
        roster as the title, e.g. "小C助理、超级员工-Codex、...". That breaks the
        message-list SSOT because the same room stops looking like
        "超级开发部" after leaving and re-entering.
        """
        all_groups = self.groups.all()
        changed = False
        for group in all_groups:
            if not isinstance(group, dict) or int(group.get("user_id") or 0) != int(user_id):
                continue
            canonical = ChatProjection.canonical_group_name(group)
            if canonical and str(group.get("name") or "") != canonical:
                group["name"] = canonical
                changed = True
        if changed:
            self.groups.rewrite(all_groups)

    def merge_duplicate_super_development_groups(self, user_id: int) -> None:
        """Keep one visible Super Development room and preserve old IDs as aliases."""
        all_groups = self.groups.all()
        user_groups = [
            g
            for g in all_groups
            if isinstance(g, dict) and int(g.get("user_id") or 0) == int(user_id)
        ]
        super_groups = [
            g for g in user_groups if ChatProjection.canonical_group_name(g) == "超级开发部"
        ]
        if len(super_groups) <= 1:
            return
        messages = self.messages.read()
        latest_by_group: dict[str, str] = {}
        for row in messages:
            if int(row.get("user_id") or 0) != int(user_id):
                continue
            gid = str(row.get("group_id") or "")
            created_at = str(row.get("created_at") or "")
            if created_at >= latest_by_group.get(gid, ""):
                latest_by_group[gid] = created_at

        def sort_key(group: dict[str, Any]) -> tuple[str, str]:
            gid = str(group.get("id") or "")
            return (
                latest_by_group.get(gid, ""),
                str(group.get("updated_at") or group.get("created_at") or ""),
            )

        keeper = max(super_groups, key=sort_key)
        keeper_id = str(keeper.get("id") or "")
        if not keeper_id:
            return
        merged_members = _with_required_group_members(
            [m for g in super_groups for m in g.get("members", []) if isinstance(m, dict)]
        )
        changed_groups = False
        changed_messages = False
        for group in all_groups:
            if not isinstance(group, dict) or int(group.get("user_id") or 0) != int(user_id):
                continue
            gid = str(group.get("id") or "")
            if gid == keeper_id:
                if group.get("name") != "超级开发部":
                    group["name"] = "超级开发部"
                    changed_groups = True
                if group.get("members") != merged_members:
                    group["members"] = merged_members
                    changed_groups = True
                if group.get("is_hidden"):
                    group["is_hidden"] = False
                    changed_groups = True
                continue
            if group in super_groups:
                if group.get("name") != "超级开发部":
                    group["name"] = "超级开发部"
                    changed_groups = True
                if group.get("alias_group_id") != keeper_id:
                    group["alias_group_id"] = keeper_id
                    changed_groups = True
                if not group.get("is_hidden"):
                    group["is_hidden"] = True
                    changed_groups = True
                if group.get("members") != merged_members:
                    group["members"] = merged_members
                    changed_groups = True
        alias_ids = {
            str(group.get("id") or "")
            for group in super_groups
            if str(group.get("id") or "") and str(group.get("id") or "") != keeper_id
        }
        if alias_ids:
            for row in messages:
                if (
                    int(row.get("user_id") or 0) == int(user_id)
                    and str(row.get("group_id") or "") in alias_ids
                ):
                    row["group_id"] = keeper_id
                    changed_messages = True
        if changed_groups:
            self.groups.rewrite(all_groups)
        if changed_messages:
            self.messages.rewrite(messages)

    def create_group(self, *, user_id: int, name: str) -> dict[str, Any]:
        title = (name or "").strip()
        if not title:
            raise ValueError("群名不能为空")
        group = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "name": title[:60],
            "department_key": "",
            "members": _with_required_group_members([]),
            "is_pinned": False,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 0,
            "created_at": _utc_now(),
        }
        self.groups.append(group)
        return ChatProjection.public_group(group, None)

    def add_member(self, *, user_id: int, group_id: str, member: dict[str, Any]) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        employee_id = str(member.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id 不能为空")
        if self.mode != "admin" and employee_id in _SUPER_EMPLOYEE_IDS:
            raise ValueError("超级员工仅管理端可邀请")
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        members = _with_required_group_members(members)
        if any(str(m.get("employee_id")) == employee_id for m in members):
            group["members"] = members
            self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
            return ChatProjection.public_group(group, None)
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
        group["members"] = _with_required_group_members(members)
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def remove_member(self, *, user_id: int, group_id: str, employee_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        if _is_required_group_member(employee_id):
            group["members"] = _with_required_group_members(
                [m for m in group.get("members", []) if isinstance(m, dict)]
            )
            self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
            return ChatProjection.public_group(group, None)
        group["members"] = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id")) != str(employee_id)
        ]
        group["members"] = _with_required_group_members(group["members"])
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def toggle_pinned(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_pinned"] = not bool(group.get("is_pinned"))
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def mark_unread(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        current = int(group.get("unread_count") or 0)
        group["unread_count"] = max(1, current + 1 if current > 0 else 1)
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def mark_read(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["unread_count"] = 0
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def toggle_followed(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_followed"] = not bool(group.get("is_followed", True))
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def toggle_hidden(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self.groups.resolve(user_id=user_id, group_id=group_id)
        groups = self.groups.for_user(user_id)
        group = GroupChatRepository.find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_hidden"] = not bool(group.get("is_hidden"))
        self.groups.rewrite(GroupChatRepository.replace(self.groups.all(), group))
        return ChatProjection.public_group(group, None)

    def delete_group(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self.groups.all()
        key = int(user_id), str(group_id)
        remaining = [g for g in groups if GroupChatRepository.group_key(g) != key]
        if len(remaining) == len(groups):
            raise ValueError("群不存在")
        self.groups.rewrite(remaining)
        return {"deleted": True, "id": str(group_id)}
