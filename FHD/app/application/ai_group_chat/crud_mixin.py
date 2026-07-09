"""CRUD / membership APIs for AI group chat."""

from __future__ import annotations

import uuid
from typing import Any

from .constants import (
    _LEGACY_SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_IDS,
    _XIAOC_ASSISTANT_ID,
)
from .loaders import (
    _is_required_group_member,
    _member_employee_id,
    _utc_now,
    _with_required_group_members,
)


class AiGroupChatCrudMixin:
    def list_groups(self, *, user_id: int, include_hidden: bool = False) -> list[dict[str, Any]]:
        self._compact_groups_file_if_needed()
        groups = self._user_groups(user_id)
        if not groups:
            groups = self._seed_department_groups(user_id)
        else:
            # 回填：旧群会按最新编制补齐新增员工，避免 roster 升级后手机仍显示旧人数。
            self._backfill_department_members(groups)
            self._ensure_required_members(user_id)
            self._ensure_special_group_names(user_id)
            self._merge_duplicate_super_development_groups(user_id)
            groups = self._user_groups(user_id)
        previews = self._latest_previews(user_id)
        if not include_hidden:
            groups = [g for g in groups if not g.get("is_hidden")]

        # 置顶群排前，其他按 last_message_at 倒序（有最新消息在前，无消息按创建时间）。
        def _sort_key(g: dict[str, Any]) -> tuple:
            pinned = 1 if g.get("is_pinned") else 0
            preview = previews.get(str(g.get("id")))
            last_at = (preview or {}).get("created_at") or g.get("created_at") or ""
            return (pinned, last_at)

        groups.sort(key=_sort_key, reverse=True)
        return [self._public_group(g, previews.get(str(g.get("id")))) for g in groups]

    def _ensure_required_members(self, user_id: int) -> None:
        all_groups = self._all_groups()
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
            self._rewrite_groups(all_groups)

    def _ensure_special_group_names(self, user_id: int) -> None:
        """Backfill canonical names for system-like groups.

        Older mobile builds created a super-development group with the member
        roster as the title, e.g. "小C助理、超级员工-Codex、...". That breaks the
        message-list SSOT because the same room stops looking like
        "超级开发部" after leaving and re-entering.
        """
        all_groups = self._all_groups()
        changed = False
        for group in all_groups:
            if not isinstance(group, dict) or int(group.get("user_id") or 0) != int(user_id):
                continue
            canonical = self._canonical_group_name(group)
            if canonical and str(group.get("name") or "") != canonical:
                group["name"] = canonical
                changed = True
        if changed:
            self._rewrite_groups(all_groups)

    def _merge_duplicate_super_development_groups(self, user_id: int) -> None:
        """Keep one visible Super Development room and preserve old IDs as aliases."""
        all_groups = self._all_groups()
        user_groups = [
            g
            for g in all_groups
            if isinstance(g, dict) and int(g.get("user_id") or 0) == int(user_id)
        ]
        super_groups = [g for g in user_groups if self._canonical_group_name(g) == "超级开发部"]
        if len(super_groups) <= 1:
            return
        messages = self._read_messages()
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
            if not isinstance(group, dict):
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
            self._rewrite_groups(all_groups)
        if changed_messages:
            self._rewrite_messages(messages)

    @staticmethod
    def _canonical_group_name(group: dict[str, Any]) -> str:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        ids = {str(m.get("employee_id") or "").strip() for m in members}
        name = str(group.get("name") or "").strip()
        has_super_roster = _SUPER_EMPLOYEE_IDS.issubset(ids) or _LEGACY_SUPER_EMPLOYEE_IDS.issubset(
            ids
        )
        if has_super_roster and _XIAOC_ASSISTANT_ID in ids:
            roster_like = (
                not name
                or name in {"新建群聊", "群聊"}
                or (
                    "超级员工-Codex" in name
                    and "超级员工-Cursor" in name
                    and "超级员工-Claude" in name
                )
            )
            if roster_like:
                return "超级开发部"
        return name

    def _backfill_department_members(self, groups: list[dict[str, Any]]) -> None:
        """按最新编制补齐部门群成员。

        早期版本只在 ``members_seeded`` 为空时补一次员，新增编制员工不会进入旧群。
        管理端部门群应反映当前员工 SSOT，因此每次访问都只追加 SSOT 新增员工；
        已同步过又被用户手动移出的员工不会反复加回。
        """
        if self._mode != "admin":
            # 企业端 4 部门初始只保留必备小C助理，不自动铺员工（按需/装 mod 后由生态同步进入）。
            return
        targets = [
            g for g in groups if isinstance(g, dict) and str(g.get("department_key") or "").strip()
        ]
        if not targets:
            return
        members_by_dept: dict[str, list[dict[str, Any]]] = {}
        try:
            for emp in self._employee_loader() or []:
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
                        "avatar_key": str(emp.get("avatar_key") or ""),
                        "summary": str(emp.get("summary") or "")[:280],
                    }
                )
        except Exception:  # noqa: BLE001 - 加载失败则不回填，下次再试
            return
        if not members_by_dept:
            # 员工加载为空也标记已尝试，避免每次 list_groups 都重试（下次重启服务再试）。
            # 但为兼容"员工尚未同步"的时序，仅在确实拿到员工列表（空）时才标记。
            # 这里 members_by_dept 为空可能只是 duty_roster 暂缺，不标记，下次再试。
            return
        changed = False
        all_groups = self._all_groups()
        for g in all_groups:
            if not isinstance(g, dict):
                continue
            dk = str(g.get("department_key") or "").strip()
            if not dk:
                continue
            existing = {_member_employee_id(m) for m in g.get("members", []) if isinstance(m, dict)}
            existing.discard("")
            fresh = members_by_dept.get(dk, [])
            roster_ids = {_member_employee_id(m) for m in fresh if _member_employee_id(m)}
            seeded_raw = g.get("members_seeded_employee_ids")
            if isinstance(seeded_raw, list):
                seeded_ids = {str(item).strip() for item in seeded_raw if str(item).strip()}
            else:
                seeded_ids = set()
            merged = list(g.get("members", []))
            for m in fresh:
                employee_id = _member_employee_id(m)
                if not employee_id:
                    continue
                if employee_id not in existing and employee_id not in seeded_ids:
                    merged.append(m)
                    existing.add(employee_id)
            next_seeded_ids = sorted(seeded_ids | roster_ids)
            if (
                merged != g.get("members")
                or not g.get("members_seeded")
                or g.get("members_seeded_employee_ids") != next_seeded_ids
            ):
                g["members"] = merged
                g["members_seeded"] = True
                g["members_seeded_employee_ids"] = next_seeded_ids
                changed = True
        if changed:
            self._rewrite_groups(all_groups)

    def list_member_candidates(self) -> list[dict[str, Any]]:
        """返回可拉入群聊的全部 AI 员工候选（普通员工 + 超级员工）。

        数据源为本服务 mode 对应的 ``employee_loader``（admin/enterprise），
        其中已通过 :func:`_append_super_employees` 追加 Codex / Claude 超级员工，
        因此手机端选人列表据此即可覆盖全部 AI 员工，无需在前端硬编码超级员工 ID。

        返回 ``[{employee_id, mod_id, name, avatar, summary, department_key, is_super}]``，
        按 ``employee_id`` 去重。``is_super`` 供前端打"超级员工"徽标用。
        """
        try:
            raw = self._employee_loader() or []
        except Exception:  # noqa: BLE001 - 加载失败返回空列表，前端优雅降级
            raw = []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for emp in raw:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("employee_id") or "").strip()
            if not eid or eid in seen:
                continue
            if self._mode != "admin" and eid in _SUPER_EMPLOYEE_IDS:
                # 超级员工仅管理端可选：企业端选人列表一律剔除，与 loader 来源无关。
                continue
            seen.add(eid)
            out.append(
                {
                    "employee_id": eid,
                    "mod_id": str(emp.get("mod_id") or ""),
                    "name": str(emp.get("name") or eid)[:60],
                    "avatar": str(emp.get("avatar") or ""),
                    "summary": str(emp.get("summary") or "")[:280],
                    "department_key": str(emp.get("department_key") or ""),
                    "is_super": eid in _SUPER_EMPLOYEE_IDS,
                }
            )
        return out

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
        self._append_group(group)
        return self._public_group(group, None)

    def add_member(self, *, user_id: int, group_id: str, member: dict[str, Any]) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        employee_id = str(member.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id 不能为空")
        if self._mode != "admin" and employee_id in _SUPER_EMPLOYEE_IDS:
            # 超级员工仅管理端可邀请：企业端即便绕过选人器也不能把超级员工拉入群。
            raise ValueError("超级员工仅管理端可邀请")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        members = _with_required_group_members(members)
        if any(str(m.get("employee_id")) == employee_id for m in members):
            group["members"] = members
            self._rewrite_groups(self._replace(self._all_groups(), group))
            return self._public_group(group, None)  # 已在群里，幂等
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
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def remove_member(self, *, user_id: int, group_id: str, employee_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        if _is_required_group_member(employee_id):
            group["members"] = _with_required_group_members(
                [m for m in group.get("members", []) if isinstance(m, dict)]
            )
            self._rewrite_groups(self._replace(self._all_groups(), group))
            return self._public_group(group, None)
        group["members"] = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id")) != str(employee_id)
        ]
        group["members"] = _with_required_group_members(group["members"])
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_pinned(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_pinned"] = not bool(group.get("is_pinned"))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_unread(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        current = int(group.get("unread_count") or 0)
        group["unread_count"] = max(1, current + 1 if current > 0 else 1)
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_read(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["unread_count"] = 0
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_followed(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_followed"] = not bool(group.get("is_followed", True))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_hidden(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_hidden"] = not bool(group.get("is_hidden"))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def delete_group(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self._all_groups()
        remaining = [g for g in groups if str(g.get("id")) != str(group_id)]
        if len(remaining) == len(groups):
            raise ValueError("群不存在")
        self._rewrite_groups(remaining)
        return {"deleted": True, "id": str(group_id)}
