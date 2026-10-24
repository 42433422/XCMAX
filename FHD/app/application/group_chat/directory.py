"""Department seeding and owner-scoped employee roster reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.application.group_chat.constants import _SUPER_EMPLOYEE_IDS
from app.application.group_chat.employee_registry import (
    _FALLBACK_DEPARTMENTS,
    _FALLBACK_ENTERPRISE_DEPARTMENTS,
    _member_employee_id,
    _utc_now,
    _with_required_group_members,
)
from app.application.group_chat.ports import GroupStore, Row, Rows
from app.application.group_chat.storage import GroupChatRepository
from app.utils.operational_errors import RECOVERABLE_ERRORS


class GroupDirectory:
    def __init__(
        self,
        groups: GroupStore,
        *,
        mode: str,
        load_employees: Callable[[], Rows],
        load_departments: Callable[[], Row],
    ) -> None:
        self.groups = groups
        self.mode = mode
        self.load_employees = load_employees
        self.load_departments = load_departments

    def backfill_department_members(self, groups: list[dict[str, Any]]) -> None:
        """按最新编制补齐部门群成员。

        早期版本只在 ``members_seeded`` 为空时补一次员，新增编制员工不会进入旧群。
        管理端部门群应反映当前员工 SSOT，因此每次访问都只追加 SSOT 新增员工；
        已同步过又被用户手动移出的员工不会反复加回。
        """
        if self.mode != "admin":
            return
        targets = [
            g for g in groups if isinstance(g, dict) and str(g.get("department_key") or "").strip()
        ]
        if not targets:
            return
        target_keys = {GroupChatRepository.group_key(group) for group in targets}
        members_by_dept: dict[str, list[dict[str, Any]]] = {}
        try:
            for emp in self.load_employees() or []:
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
        except RECOVERABLE_ERRORS:
            return
        if not members_by_dept:
            return
        changed = False
        all_groups = self.groups.all()
        for g in all_groups:
            if not isinstance(g, dict) or GroupChatRepository.group_key(g) not in target_keys:
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
            self.groups.rewrite(all_groups)

    def seed_department_groups(self, user_id: int) -> list[dict[str, Any]]:
        depts = self.load_departments()
        pairs: list[tuple[str, str]] = []
        if isinstance(depts, dict) and depts:
            for key, info in depts.items():
                label = ""
                if isinstance(info, dict):
                    label = str(info.get("label") or "").strip()
                pairs.append((str(key), label or str(key)))
        if not pairs:
            pairs = list(
                _FALLBACK_ENTERPRISE_DEPARTMENTS
                if self.mode == "enterprise"
                else _FALLBACK_DEPARTMENTS
            )
        members_by_dept: dict[str, list[dict[str, Any]]] = {}
        try:
            for emp in self.load_employees() or [] if self.mode == "admin" else []:
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
        except RECOVERABLE_ERRORS:
            members_by_dept = {}
        seeded: list[dict[str, Any]] = []
        for key, label in pairs:
            members = _with_required_group_members(members_by_dept.get(key, []))
            roster_ids = sorted(
                {
                    _member_employee_id(member)
                    for member in members_by_dept.get(key, [])
                    if _member_employee_id(member)
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
                    "created_at": _utc_now(),
                }
            )
        for g in seeded:
            self.groups.append(g)
        return seeded

    def list_member_candidates(self) -> list[dict[str, Any]]:
        """返回可拉入群聊的全部 AI 员工候选（普通员工 + 超级员工）。

        数据源为本服务 mode 对应的 ``employee_loader``（admin/enterprise），
        其中已通过 :func:`_append_super_employees` 追加 Codex / Claude 超级员工，
        因此手机端选人列表据此即可覆盖全部 AI 员工，无需在前端硬编码超级员工 ID。

        返回 ``[{employee_id, mod_id, name, avatar, summary, department_key, is_super}]``，
        按 ``employee_id`` 去重。``is_super`` 供前端打"超级员工"徽标用。
        """
        try:
            raw = self.load_employees() or []
        except RECOVERABLE_ERRORS:
            raw = []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for emp in raw:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("employee_id") or "").strip()
            if not eid or eid in seen:
                continue
            if self.mode != "admin" and eid in _SUPER_EMPLOYEE_IDS:
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
