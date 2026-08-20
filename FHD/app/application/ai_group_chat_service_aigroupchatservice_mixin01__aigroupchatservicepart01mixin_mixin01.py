# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


class __AiGroupChatServicePart01MixinPart01Mixin:
    def __init__(
        self,
        storage_root: str | _facade().Path | None = None,
        completion_fn: _facade().CompletionFn | None = None,
        employee_executor_fn: _facade().EmployeeExecutorFn | None = None,
        department_loader: _facade().Callable[[], dict[str, _facade().Any]] | None = None,
        employee_loader: _facade().Callable[[], list[dict[str, _facade().Any]]] | None = None,
        mode: str = "admin",
    ) -> None:
        root = (
            _facade().Path(storage_root)
            if storage_root is not None
            else _facade().Path(_facade().get_app_data_dir())
        )
        self._root = root / "ai_group_chat"
        self._root.mkdir(parents=True, exist_ok=True)
        self._groups_path = self._root / "groups.jsonl"
        self._messages_path = self._root / "messages.jsonl"
        self._completion_fn = completion_fn or _facade()._default_completion
        self._has_custom_employee_executor = employee_executor_fn is not None
        self._employee_executor_fn = employee_executor_fn or _facade()._default_employee_executor
        self._mode = mode if mode in ("admin", "enterprise") else "admin"
        if department_loader is not None:
            self._department_loader = department_loader
        else:
            self._department_loader = (
                _facade()._default_enterprise_departments
                if self._mode == "enterprise"
                else _facade()._default_departments
            )
        if employee_loader is not None:
            self._employee_loader = employee_loader
        else:
            self._employee_loader = (
                _facade()._default_enterprise_employee_loader
                if self._mode == "enterprise"
                else _facade()._default_duty_employee_loader
            )

    def list_groups(
        self, *, user_id: int, include_hidden: bool = False
    ) -> list[dict[str, _facade().Any]]:
        self._compact_groups_file_if_needed()
        groups = self._user_groups(user_id)
        if not groups:
            groups = self._seed_department_groups(user_id)
        else:
            self._backfill_department_members(groups)
            self._ensure_required_members(user_id)
            self._ensure_special_group_names(user_id)
            self._merge_duplicate_super_development_groups(user_id)
            groups = self._user_groups(user_id)
        previews = self._latest_previews(user_id)
        if not include_hidden:
            groups = [g for g in groups if not g.get("is_hidden")]

        def _sort_key(g: dict[str, _facade().Any]) -> tuple:
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
            merged = _facade()._with_required_group_members(current)
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

        def sort_key(group: dict[str, _facade().Any]) -> tuple[str, str]:
            gid = str(group.get("id") or "")
            return (
                latest_by_group.get(gid, ""),
                str(group.get("updated_at") or group.get("created_at") or ""),
            )

        keeper = max(super_groups, key=sort_key)
        keeper_id = str(keeper.get("id") or "")
        if not keeper_id:
            return
        merged_members = _facade()._with_required_group_members(
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
    def _canonical_group_name(group: dict[str, _facade().Any]) -> str:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        ids = {str(m.get("employee_id") or "").strip() for m in members}
        name = str(group.get("name") or "").strip()
        has_super_roster = _facade()._SUPER_EMPLOYEE_IDS.issubset(
            ids
        ) or _facade()._LEGACY_SUPER_EMPLOYEE_IDS.issubset(ids)
        if has_super_roster and _facade()._XIAOC_ASSISTANT_ID in ids:
            roster_like = (
                not name
                or name in {"新建群聊", "群聊"}
                or (
                    "超级员工-Codex" in name
                    and "超级员工-Cursor" in name
                    and ("超级员工-Claude" in name)
                )
            )
            if roster_like:
                return "超级开发部"
        return name

    def _backfill_department_members(self, groups: list[dict[str, _facade().Any]]) -> None:
        """按最新编制补齐部门群成员。

        早期版本只在 ``members_seeded`` 为空时补一次员，新增编制员工不会进入旧群。
        管理端部门群应反映当前员工 SSOT，因此每次访问都只追加 SSOT 新增员工；
        已同步过又被用户手动移出的员工不会反复加回。
        """
        if self._mode != "admin":
            return
        targets = [
            g for g in groups if isinstance(g, dict) and str(g.get("department_key") or "").strip()
        ]
        if not targets:
            return
        members_by_dept: dict[str, list[dict[str, _facade().Any]]] = {}
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
        except _facade().RECOVERABLE_ERRORS:
            return
        if not members_by_dept:
            return
        changed = False
        all_groups = self._all_groups()
        for g in all_groups:
            if not isinstance(g, dict):
                continue
            dk = str(g.get("department_key") or "").strip()
            if not dk:
                continue
            existing = {
                _facade()._member_employee_id(m)
                for m in g.get("members", [])
                if isinstance(m, dict)
            }
            existing.discard("")
            fresh = members_by_dept.get(dk, [])
            roster_ids = {
                _facade()._member_employee_id(m) for m in fresh if _facade()._member_employee_id(m)
            }
            seeded_raw = g.get("members_seeded_employee_ids")
            if isinstance(seeded_raw, list):
                seeded_ids = {str(item).strip() for item in seeded_raw if str(item).strip()}
            else:
                seeded_ids = set()
            merged = list(g.get("members", []))
            for m in fresh:
                employee_id = _facade()._member_employee_id(m)
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

    def list_member_candidates(self) -> list[dict[str, _facade().Any]]:
        """返回可拉入群聊的全部 AI 员工候选（普通员工 + 超级员工）。

        数据源为本服务 mode 对应的 ``employee_loader``（admin/enterprise），
        其中已通过 :func:`_append_super_employees` 追加 Codex / Claude 超级员工，
        因此手机端选人列表据此即可覆盖全部 AI 员工，无需在前端硬编码超级员工 ID。

        返回 ``[{employee_id, mod_id, name, avatar, summary, department_key, is_super}]``，
        按 ``employee_id`` 去重。``is_super`` 供前端打"超级员工"徽标用。
        """
        try:
            raw = self._employee_loader() or []
        except _facade().RECOVERABLE_ERRORS:
            raw = []
        out: list[dict[str, _facade().Any]] = []
        seen: set[str] = set()
        for emp in raw:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("employee_id") or "").strip()
            if not eid or eid in seen:
                continue
            if self._mode != "admin" and eid in _facade()._SUPER_EMPLOYEE_IDS:
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
                    "is_super": eid in _facade()._SUPER_EMPLOYEE_IDS,
                }
            )
        return out

    def create_group(self, *, user_id: int, name: str) -> dict[str, _facade().Any]:
        title = (name or "").strip()
        if not title:
            raise ValueError("群名不能为空")
        group = {
            "id": _facade().uuid.uuid4().hex,
            "user_id": int(user_id),
            "name": title[:60],
            "department_key": "",
            "members": _facade()._with_required_group_members([]),
            "is_pinned": False,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 0,
            "created_at": _facade()._utc_now(),
        }
        self._append_group(group)
        return self._public_group(group, None)
