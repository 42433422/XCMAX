"""AI 群聊服务（微信式多 AI 群组）。

自包含、按用户隔离、jsonl 持久化（与超级员工服务同一套存储惯例），
不触碰现有人际 IM（``ImConversation`` 等）以零回归。

SSOT 架构（双模式）：
- **admin 模式**（管理端）：6 部门 + 编制员工均来自 ``config/duty_roster.json``；
  ``duty_employee_registry.json`` 与 employee manifest 只补展示元数据。
- **enterprise 模式**（企业端）：4 部门（工具层/执行层/服务层/管理层）+ 上架员工（MODstore）+ 未上架员工（宿主定制）

部门 → 员工映射为自动派生：
- admin: 从 ``duty_roster.json`` 的 departments/subzones 展平员工归属
- enterprise: ``resolve_enterprise_org_layer(emp_id, ...)`` 从 manifest enterprise_layer / ID 表 / 关键词推断
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any

from app.application.group_chat.constants import (
    _LEGACY_SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_IDS,
    _SUPER_EMPLOYEE_RELAY_KINDS,
    _XIAOC_ASSISTANT_ID,
    CHAT_ACCEPTANCE_SUMMARY_CHARS,
    CHAT_REPORT_SUMMARY_CHARS,
    CONTEXT_TURNS,
    MAX_RESPONDERS,
    RELAY_PROGRESS_MIN_INTERVAL_SEC,
    CompletionFn,
    EmployeeExecutorFn,
)
from app.application.group_chat.constants import (
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS as PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    PUBLIC_CHAT_BODY_MAX_CHARS as PUBLIC_CHAT_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC as SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_DEFAULT_ROUNDS as SUPER_DISCUSSION_DEFAULT_ROUNDS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_MAX_ROUNDS as SUPER_DISCUSSION_MAX_ROUNDS,
)
from app.application.group_chat.constants import (
    _env_float as _env_float,
)
from app.application.group_chat.dispatch_router import AiGroupChatDispatchMixin
from app.application.group_chat.employee_registry import (
    _FALLBACK_DEPARTMENTS,
    _FALLBACK_ENTERPRISE_DEPARTMENTS,
    _default_completion,
    _default_departments,
    _default_duty_employee_loader,
    _default_employee_executor,
    _default_enterprise_departments,
    _default_enterprise_employee_loader,
    _is_required_group_member,
    _member_employee_id,
    _normalize_branch_context,
    _utc_now,
    _with_required_group_members,
)
from app.application.group_chat.employee_registry import (
    _append_super_employees as _append_super_employees,
)
from app.application.group_chat.employee_registry import (
    _dept_key_to_employee_ids as _dept_key_to_employee_ids,
)
from app.application.group_chat.employee_registry import (
    _employee_manifest as _employee_manifest,
)
from app.application.group_chat.employee_registry import (
    _member_public_shape as _member_public_shape,
)
from app.application.group_chat.employee_registry import (
    _safe_json_line as _safe_json_line,
)
from app.application.group_chat.employee_registry import (
    _xiaoc_assistant_member as _xiaoc_assistant_member,
)
from app.application.group_chat.message_formatting import AiGroupChatFormattingMixin
from app.application.group_chat.storage import AiGroupChatStorageMixin
from app.utils.path_utils import get_app_data_dir


class AiGroupChatService(
    AiGroupChatDispatchMixin,
    AiGroupChatFormattingMixin,
    AiGroupChatStorageMixin,
):
    """微信式 AI 群聊：建群 / 拉 AI 成员 / 群内多 AI 回复。

    ``mode`` 决定部门模型 + 员工 SSOT：
    - ``"admin"``（默认）：6 部门 + 上岗员工
    - ``"enterprise"``：4 部门 + 上架/未上架员工
    """

    def __init__(
        self,
        storage_root: str | Path | None = None,
        completion_fn: CompletionFn | None = None,
        employee_executor_fn: EmployeeExecutorFn | None = None,
        department_loader: Callable[[], dict[str, Any]] | None = None,
        employee_loader: Callable[[], list[dict[str, Any]]] | None = None,
        mode: str = "admin",
    ) -> None:
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._root = root / "ai_group_chat"
        self._root.mkdir(parents=True, exist_ok=True)
        self._groups_path = self._root / "groups.jsonl"
        self._messages_path = self._root / "messages.jsonl"
        self._completion_fn = completion_fn or _default_completion
        self._has_custom_employee_executor = employee_executor_fn is not None
        self._employee_executor_fn = employee_executor_fn or _default_employee_executor
        self._mode = mode if mode in ("admin", "enterprise") else "admin"
        if department_loader is not None:
            self._department_loader = department_loader
        else:
            self._department_loader = (
                _default_enterprise_departments
                if self._mode == "enterprise"
                else _default_departments
            )
        if employee_loader is not None:
            self._employee_loader = employee_loader
        else:
            self._employee_loader = (
                _default_enterprise_employee_loader
                if self._mode == "enterprise"
                else _default_duty_employee_loader
            )

    # ── 公开 API ──

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

    def get_messages(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
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
            and self._report_relay_task_id(row) not in final_task_ids
        ]
        if not pending_reports:
            return
        try:
            relay = self._mobile_relay_service()
        except Exception:  # noqa: BLE001
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        for report in pending_reports:
            task_id = self._report_relay_task_id(report)
            try:
                task = relay.get_task(user_id=int(user_id), task_id=task_id)
            except Exception:  # noqa: BLE001
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

    def _sync_super_employee_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Mirror Codex/Cursor/Claude DevFleet results back into the group chat."""
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
            and str(row.get("sender_id") or "") in _SUPER_EMPLOYEE_IDS
            and self._report_relay_task_id(row)
            and self._report_relay_task_id(row) not in final_task_ids
        ]
        if not pending_reports:
            return
        progress_rows = [row for row in rows if str(row.get("kind") or "") == "work_progress"]
        messages_by_employee: dict[str, list[dict[str, Any]]] = {}
        for report in pending_reports:
            employee_id = str(report.get("sender_id") or "").strip()
            task_id = self._report_relay_task_id(report)
            if not employee_id or not task_id:
                continue
            if employee_id not in messages_by_employee:
                try:
                    messages_by_employee[employee_id] = self._super_employee_service(
                        employee_id
                    ).list_messages(user_id=int(user_id), limit=200)
                except Exception:  # noqa: BLE001
                    messages_by_employee[employee_id] = []
            employee_messages = messages_by_employee[employee_id]
            result_msg = self._super_employee_result_message_for_task(employee_messages, task_id)
            if result_msg is not None:
                self.append_relay_work_report(
                    task=self._super_employee_result_task(
                        user_id=user_id,
                        group_id=group_id,
                        report=report,
                        result_msg=result_msg,
                    )
                )
                continue
            status_msg = self._super_employee_dispatch_message_for_task(employee_messages, task_id)
            status = self._super_employee_task_status(status_msg)
            if status in {"completed", "done", "merged", "failed", "blocked", "cancelled"}:
                self.append_relay_work_report(
                    task=self._super_employee_result_task(
                        user_id=user_id,
                        group_id=group_id,
                        report=report,
                        result_msg=status_msg or {},
                    )
                )
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
                sender_id=employee_id,
                sender_name=str(report.get("sender_name") or "负责人"),
                sender_avatar=str(report.get("sender_avatar") or ""),
                body=self._format_relay_progress_message(
                    report=report,
                    task={"task_id": task_id, "kind": "super_employee"},
                    status=status,
                ),
                kind="work_progress",
                status=status,
                work_order_id=str(report.get("work_order_id") or ""),
                payload={
                    "work_order_id": str(report.get("work_order_id") or ""),
                    "employee_id": employee_id,
                    "employee_name": str(report.get("sender_name") or ""),
                    "status": status,
                    "summary": self._relay_progress_summary(status, task_id),
                    "raw": {"task_id": task_id, "kind": "super_employee"},
                },
            )
            self._append_messages([progress])
            progress_rows.append(progress)

    @staticmethod
    def _super_employee_result_message_for_task(
        messages: list[dict[str, Any]], task_id: str
    ) -> dict[str, Any] | None:
        for item in reversed(messages):
            if str(item.get("task_id") or "") != str(task_id):
                continue
            kind = str(item.get("kind") or "")
            if kind in {"codex_result", "cursor_result", "claude_result"}:
                return item
            if (
                str(item.get("role") or "") == "assistant"
                and kind != "dispatcher"
                and str(item.get("body") or "").strip()
            ):
                return item
        return None

    @staticmethod
    def _super_employee_dispatch_message_for_task(
        messages: list[dict[str, Any]], task_id: str
    ) -> dict[str, Any] | None:
        for item in reversed(messages):
            if (
                str(item.get("task_id") or "") == str(task_id)
                and str(item.get("kind") or "") == "dispatcher"
            ):
                return item
        return None

    @staticmethod
    def _super_employee_task_status(message: dict[str, Any] | None) -> str:
        if not isinstance(message, dict):
            return ""
        status = str(message.get("task_status") or message.get("status") or "").strip().lower()
        if status == "merged":
            return "completed"
        return status

    def _super_employee_result_task(
        self,
        *,
        user_id: int,
        group_id: str,
        report: dict[str, Any],
        result_msg: dict[str, Any],
    ) -> dict[str, Any]:
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task_id = self._report_relay_task_id(report)
        status = self._super_employee_task_status(result_msg) or "completed"
        body = str(result_msg.get("body") or "").strip()
        return {
            "created_by_user_id": int(user_id),
            "task_id": task_id,
            "relay_id": "super_employee",
            "kind": str(raw.get("kind") or raw.get("dispatcher") or "super_employee"),
            "status": status,
            "payload": {
                "message": str(payload.get("task") or payload.get("original_task") or ""),
                "context": {
                    "source": "mobile_ai_group",
                    "group_id": group_id,
                    "work_order_id": str(
                        report.get("work_order_id") or payload.get("work_order_id") or ""
                    ),
                    "employee_id": str(payload.get("employee_id") or report.get("sender_id") or ""),
                    "assignment_focus": str(payload.get("assignment_focus") or ""),
                    "original_task": str(payload.get("original_task") or payload.get("task") or ""),
                    "branch": str(payload.get("branch_context") or payload.get("branch") or ""),
                },
            },
            "result": {
                "summary": body,
                "dispatcher": str(raw.get("dispatcher") or "super_employee"),
                "status": status,
                "assistant_message": {"body": body},
            },
        }

    @staticmethod
    def _latest_progress_row(rows: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
        for row in reversed(rows):
            if AiGroupChatService._report_relay_task_id(row) == task_id:
                return row
        return None

    @staticmethod
    def _should_append_progress(*, last: dict[str, Any] | None, status: str) -> bool:
        if last is None:
            return True
        last_status = str(last.get("status") or "").strip().lower()
        if last_status and last_status != status:
            return True
        last_at = AiGroupChatService._parse_created_at(str(last.get("created_at") or ""))
        if last_at is None:
            return True
        elapsed = (datetime.now(UTC) - last_at).total_seconds()
        return elapsed >= RELAY_PROGRESS_MIN_INTERVAL_SEC

    @staticmethod
    def _parse_created_at(value: str) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _relay_progress_summary(status: str, task_id: str) -> str:
        label = {
            "queued": "还在服务器队列中",
            "accepted": "执行端已接单",
            "assigned": "执行端已接单",
            "running": "电脑执行端正在处理",
            "processing": "电脑执行端正在处理",
            "in_progress": "电脑执行端正在处理",
        }.get(status, "还在处理中")
        return f"{label}，任务号：{task_id[:8]}。"

    @classmethod
    def _format_relay_progress_message(
        cls, *, report: dict[str, Any], task: dict[str, Any], status: str
    ) -> str:
        name = str(report.get("sender_name") or "负责人")
        payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
        focus = str(payload.get("assignment_focus") or "").strip()
        branch = str(payload.get("branch_context") or payload.get("branch") or "").strip()
        task_id = str(task.get("task_id") or cls._report_relay_task_id(report))
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
        return (
            f"【{name} 进度回访】\n"
            f"状态：{status_label}\n"
            f"{focus_line}"
            f"{branch_line}"
            f"结果：{cls._relay_progress_summary(status, task_id)}我会继续等执行端回写，不需要你退出重进。\n"
            "风险：暂无新的阻塞；如果执行端超时，群里会保留这条任务号方便追踪。\n"
            "下一步：继续执行，完成后自动发员工回报并交给小C验收。"
        )

    def delete_message(self, *, user_id: int, group_id: str, message_id: str) -> dict[str, Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        msg_id = str(message_id or "").strip()
        if not msg_id:
            raise ValueError("消息不存在")
        rows = self._read_messages()
        target = next(
            (
                r
                for r in rows
                if int(r.get("user_id") or 0) == int(user_id)
                and str(r.get("group_id")) == str(group_id)
                and str(r.get("id")) == msg_id
            ),
            None,
        )
        if target is None:
            raise ValueError("消息不存在")
        if str(target.get("role") or "") != "user" or str(target.get("sender_id") or "") != "user":
            raise ValueError("只能删除自己发送的消息")
        self._rewrite_messages([r for r in rows if str(r.get("id")) != msg_id])
        return {"deleted": True, "id": msg_id}

    def append_relay_work_report(self, *, task: dict[str, Any]) -> dict[str, Any] | None:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if str(context.get("source") or "") != "mobile_ai_group":
            return None
        user_id = int(task.get("created_by_user_id") or 0)
        group_id = str(context.get("group_id") or "").strip()
        employee_id = str(context.get("employee_id") or "").strip()
        task_id = str(task.get("task_id") or "").strip()
        if user_id <= 0 or not group_id or not employee_id or not task_id:
            return None
        group = self._find(self._user_groups(user_id), group_id)
        if group is None:
            return None
        work_order_id = str(context.get("work_order_id") or "")
        existing = self._relay_report_message(user_id=user_id, group_id=group_id, task_id=task_id)
        if existing is not None:
            self._append_work_acceptance_if_ready(
                user_id=user_id,
                group_id=group_id,
                work_order_id=work_order_id,
            )
            return self._public_message(existing)
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        member = next(
            (m for m in members if str(m.get("employee_id") or "") == employee_id),
            {"employee_id": employee_id, "name": employee_id, "avatar": ""},
        )
        report = self._relay_task_report(task=task, member=member)
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=employee_id,
            sender_name=str(member.get("name") or employee_id),
            sender_avatar=str(member.get("avatar") or ""),
            body=self._format_work_report_message(member, report),
            kind="relay_work_report",
            status=str(report.get("status") or ""),
            work_order_id=work_order_id,
            payload=report,
        )
        self._append_messages([row])
        self._append_work_acceptance_if_ready(
            user_id=user_id,
            group_id=group_id,
            work_order_id=work_order_id,
        )
        return self._public_message(row)

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
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
        action_context = context if isinstance(context, dict) else {}
        tool_action = str(action_context.get("tool_action") or "").strip()
        branch_context = _normalize_branch_context(branch_context)
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = _with_required_group_members(
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
        history = self.get_messages(user_id=user_id, group_id=group_id, limit=CONTEXT_TURNS)

        work_orders: list[dict[str, Any]] = []
        if dispatch:
            responders = self._pick_dispatch_targets(members, body, mentions)
            discussion_messages: list[dict[str, Any]] = []
            if self._should_run_super_discussion(responders):
                discussion_messages, responders = await self._run_super_discussion_then_route(
                    group=group,
                    task=body,
                    candidates=responders,
                    user_id=user_id,
                    history=history,
                    mentions=mentions,
                    persist=True,
                )
                new_messages.extend(discussion_messages)
            dispatch_messages, work_orders = await self._dispatch_work(
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
        result: dict[str, Any] = {
            "group": self._public_group(group, previews.get(str(group.get("id")))),
            "messages": [self._public_message(m) for m in new_messages],
        }
        if dispatch:
            result["work_orders"] = work_orders
        return result

    def _append_acceptance_followup(self, *, user_id: int, group_id: str) -> dict[str, Any] | None:
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
                sender_id=_XIAOC_ASSISTANT_ID,
                sender_name="小C助理",
                sender_avatar="",
                body="【小C回访】还没有可回访的派工单。\n先输入任务后点“任务派工”，我会在群里派负责人并收口验收。",
                kind="work_followup",
                status="empty",
            )
            self._append_messages([row])
            return row
        work_order = max(work_orders, key=lambda row: str(row.get("created_at") or ""))
        work_order_id = str(work_order.get("work_order_id") or "")
        had_acceptance = any(
            str(row.get("kind") or "") == "work_acceptance"
            and str(row.get("work_order_id") or "") == work_order_id
            for row in rows
        )
        acceptance = self._append_work_acceptance_if_ready(
            user_id=user_id,
            group_id=group_id,
            work_order_id=work_order_id,
        )
        if acceptance is not None and not had_acceptance:
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
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=body,
            kind="work_followup",
            status="completed" if acceptance is not None else "in_progress",
            work_order_id=work_order_id,
        )
        self._append_messages([row])
        return row

    @classmethod
    def _format_acceptance_followup_message(
        cls,
        *,
        work_order: dict[str, Any],
        rows: list[dict[str, Any]],
        had_acceptance: bool,
    ) -> str:
        payload = work_order.get("payload") if isinstance(work_order.get("payload"), dict) else {}
        task = str(payload.get("task") or "").strip() or cls._strip_label_from_body(
            str(work_order.get("body") or ""),
            "【小C派单】",
        )
        if had_acceptance:
            return (
                "【小C回访】最新派工已有验收结论。\n"
                f"任务：{task[:80]}\n"
                "你可以继续补充问题，或直接派下一步。"
            )
        reports = [
            row
            for row in rows
            if str(row.get("kind") or "") in {"work_report", "work_progress", "relay_work_report"}
        ]
        if not reports:
            return (
                "【小C回访】最新派工已发出，正在等待负责人接单或回报。\n"
                f"任务：{task[:80]}\n"
                "我会继续把进度同步到群里。"
            )
        latest_by_task: dict[str, dict[str, Any]] = {}
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
                str(row.get("body") or ""),
                limit=54,
                include_detail_note=False,
            )
            lines.append(f"- {name}：{status}。{summary}")
        return (
            "【小C回访】最新派工还在处理中。\n"
            f"任务：{task[:80]}\n"
            + ("进度：\n" + "\n".join(lines) + "\n" if lines else "")
            + "结论：暂未达到自动验收条件。"
        )

    async def _execute_employee_work(
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
            if employee_id in _SUPER_EMPLOYEE_IDS and not self._has_custom_employee_executor:
                # 同步派工（含阻塞 CLI invoke 与中继 DB 写）放到工作线程，
                # 否则会阻塞事件循环、让其它群聊在派工期间发不出消息。
                maybe_result = await asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id=employee_id,
                    task=assigned_task,
                    input_data=input_data,
                    user_id=int(user_id),
                )
            else:
                maybe_result = self._employee_executor_fn(
                    employee_id, assigned_task, input_data, int(user_id)
                )
            raw = await maybe_result if isawaitable(maybe_result) else maybe_result
            result = (
                raw
                if isinstance(raw, dict)
                else {"success": False, "status": "failed", "message": str(raw)}
            )
            success = bool(result.get("success"))
            summary = self._execution_summary(result)
            # 误判验收修复：CLI（尤其只读沙箱的 Codex）常返回 success=True，正文却是
            # "不能执行命令/权限不足/仅提供方案/先不动代码"等拒绝语——这类必须判失败，
            # 否则小 C 会把"没真做"当成验收通过。
            result_status = str(result.get("status") or "").strip().lower()
            missing_evidence = (
                success
                and not self._has_custom_employee_executor
                and result_status in {"completed", "done"}
                and self._completed_report_lacks_required_evidence(
                    assigned_task or task, summary, result
                )
            )
            if success and self._summary_indicates_unfinished(summary):
                success = False
            if missing_evidence:
                success = False
            # 改派真能执行的 Claude：非 Claude 的超级员工拒绝执行时自动改派一次
            # （Codex 只读沙箱执行不了 → 交给有 acceptEdits 的 Claude 真跑）。
            reassigned_from = ""
            if (
                not success
                and employee_id in _SUPER_EMPLOYEE_IDS
                and employee_id != "claude-super-employee"
                and not self._has_custom_employee_executor
                and self._summary_indicates_unfinished(summary)
            ):
                claude_raw = await asyncio.to_thread(
                    self._invoke_super_employee_task,
                    employee_id="claude-super-employee",
                    task=assigned_task,
                    input_data={**input_data, "reassigned_from": employee_id},
                    user_id=int(user_id),
                )
                claude_result = claude_raw if isinstance(claude_raw, dict) else {"success": False}
                claude_summary = self._execution_summary(claude_result)
                claude_missing_evidence = self._completed_report_lacks_required_evidence(
                    assigned_task or task,
                    claude_summary,
                    claude_result,
                )
                claude_ok = (
                    bool(claude_result.get("success"))
                    and not self._summary_indicates_unfinished(claude_summary)
                    and not claude_missing_evidence
                )
                if claude_ok:
                    reassigned_from = employee_id
                    result, success, summary = claude_result, True, claude_summary
                    employee_id, employee_name = "claude-super-employee", "Claude 超级员工"
                    missing_evidence = False
            status = str(result.get("status") or "").strip().lower()
            if not status or (status in {"completed", "done"} and not success):
                status = (
                    "done"
                    if success
                    else ("failed" if self._summary_indicates_failed(summary) else "blocked")
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
                "risk": (
                    "回报缺少改动文件、命令、测试、构建或安装证据，不能自动验收。"
                    if missing_evidence
                    else self._execution_risk(result, success)
                ),
                "raw": self._compact_result(result),
            }
            if reassigned_from:
                report["reassigned_from"] = reassigned_from
            return report
        except Exception as exc:  # noqa: BLE001 - 单个员工失败不能阻断其他员工汇报
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

    def _invoke_super_employee_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: dict[str, Any],
        user_id: int,
    ) -> dict[str, Any]:
        relay_result = self._create_super_employee_relay_task(
            employee_id=employee_id,
            task=task,
            input_data=input_data,
            user_id=user_id,
        )
        if relay_result is not None:
            return relay_result
        service = self._super_employee_service(employee_id)
        branch_context = str(input_data.get("branch_context") or input_data.get("branch") or "")
        result = service.invoke(
            user_id=int(user_id),
            message=task,
            context={
                "mode": "task",
                "source": "mobile_ai_group",
                "group_id": input_data.get("group_id"),
                "group_name": input_data.get("group_name"),
                "work_order_id": input_data.get("work_order_id"),
                "original_task": input_data.get("original_task") or task,
                "assigned_task": input_data.get("assigned_task") or task,
                "assignment_focus": input_data.get("assignment_focus") or "",
                **({"branch": branch_context} if branch_context else {}),
            },
        )
        dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
        assistant = (
            result.get("assistant_message")
            if isinstance(result.get("assistant_message"), dict)
            else {}
        )
        status = str(dispatch.get("status") or assistant.get("status") or "queued").strip()
        accepted = dispatch.get("accepted") is True or status in {
            "queued",
            "accepted",
            "assigned",
            "running",
            "completed",
            "done",
        }
        summary = str(assistant.get("body") or "").strip()
        if not summary:
            summary = "已进入超级员工执行队列。"
        return {
            "success": accepted,
            "status": status or ("queued" if accepted else "failed"),
            "summary": summary,
            "risk": "执行已交给对应超级员工；完成状态以该超级员工会话和派工回执为准。"
            if accepted
            else str(dispatch.get("reason") or "超级员工执行入口未接受任务"),
            "dispatch_request_id": str(dispatch.get("request_id") or ""),
            "task_id": str(dispatch.get("task_id") or ""),
            "dispatcher": str(dispatch.get("dispatcher") or ""),
            "branch_context": branch_context,
        }

    def _create_super_employee_relay_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: dict[str, Any],
        user_id: int,
    ) -> dict[str, Any] | None:
        kind = _SUPER_EMPLOYEE_RELAY_KINDS.get(employee_id)
        if not kind:
            return None
        try:
            relay = self._mobile_relay_service()
            desktop = self._latest_relay_desktop(relay.list_desktops(user_id=int(user_id)))
            relay_id = str((desktop or {}).get("relay_id") or "").strip()
            if not relay_id:
                return None
            relay_task = relay.create_task(
                user_id=int(user_id),
                relay_id=relay_id,
                kind=kind,
                payload={
                    "message": task,
                    **(
                        {"branch": input_data.get("branch_context") or input_data.get("branch")}
                        if (input_data.get("branch_context") or input_data.get("branch"))
                        else {}
                    ),
                    "context": {
                        "source": "mobile_ai_group",
                        "client_surface": "ai_group",
                        "mode": "code",
                        "group_id": input_data.get("group_id"),
                        "group_name": input_data.get("group_name"),
                        "work_order_id": input_data.get("work_order_id"),
                        "employee_id": employee_id,
                        "original_task": input_data.get("original_task") or task,
                        "assigned_task": input_data.get("assigned_task") or task,
                        "assignment_focus": input_data.get("assignment_focus") or "",
                        **(
                            {"branch": input_data.get("branch_context") or input_data.get("branch")}
                            if (input_data.get("branch_context") or input_data.get("branch"))
                            else {}
                        ),
                    },
                },
            )
        except Exception:  # noqa: BLE001 - relay 不可用时退回超级员工原通道
            return None
        if not isinstance(relay_task, dict):
            return None
        relay_task_id = str(relay_task.get("task_id") or "").strip()
        if not relay_task_id:
            return None
        return {
            "success": True,
            "status": str(relay_task.get("status") or "queued"),
            "summary": f"已接单，正在电脑执行端处理。任务号：{relay_task_id[:8]}。",
            "risk": "暂无阻塞；执行完成后会自动回到群里汇报。",
            "dispatch_request_id": relay_task_id,
            "task_id": relay_task_id,
            "dispatcher": "mobile_relay",
            "relay_id": relay_id,
            "branch_context": str(
                input_data.get("branch_context") or input_data.get("branch") or ""
            ),
        }

    @staticmethod
    def _latest_relay_desktop(desktops: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [
            item
            for item in desktops
            if isinstance(item, dict)
            and str(item.get("relay_id") or "").strip()
            and str(item.get("status") or "").strip().lower() == "paired"
        ]
        if not candidates:
            return None

        def sort_key(item: dict[str, Any]) -> str:
            return (
                str(item.get("last_seen_at") or "").strip()
                or str(item.get("updated_at") or "").strip()
                or str(item.get("paired_at") or "").strip()
                or str(item.get("created_at") or "").strip()
            )

        return max(candidates, key=sort_key)

    @staticmethod
    def _mobile_relay_service():
        from app.services.mobile_relay_service import MobileRelayService

        return MobileRelayService()

    @staticmethod
    def _super_employee_service(employee_id: str):
        from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
        from app.application.codex_super_employee_service import CodexSuperEmployeeService
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService
        from app.application.trae_super_employee_service import TraeSuperEmployeeService

        if employee_id == "codex-super-employee":
            return CodexSuperEmployeeService()
        if employee_id == "cursor-super-employee":
            return CursorSuperEmployeeService()
        if employee_id == "trae-super-employee":
            return TraeSuperEmployeeService()
        return ClaudeSuperEmployeeService()

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
            line = AiGroupChatService._clean_chat_summary_line(line)
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

    # ── 部门种子 ──

    def _seed_department_groups(self, user_id: int) -> list[dict[str, Any]]:
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
                _FALLBACK_ENTERPRISE_DEPARTMENTS
                if self._mode == "enterprise"
                else _FALLBACK_DEPARTMENTS
            )
        # 按 department_key 预分桶员工，种子群直接带入编制成员（微信式"部门群天然有人"）。
        # 企业端 4 部门初始只保留必备小C助理，员工不预铺；仅管理端按编制预铺。
        members_by_dept: dict[str, list[dict[str, Any]]] = {}
        try:
            for emp in (self._employee_loader() or []) if self._mode == "admin" else []:
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
        except Exception:  # noqa: BLE001 - 员工加载失败不阻断建群
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
            self._append_group(g)
        return seeded

__all__ = [
    "AiGroupChatService",
    "CHAT_ACCEPTANCE_SUMMARY_CHARS",
    "CHAT_REPORT_SUMMARY_CHARS",
    "MAX_RESPONDERS",
    "PUBLIC_ACCEPTANCE_BODY_MAX_CHARS",
    "PUBLIC_CHAT_BODY_MAX_CHARS",
    "SUPER_DISCUSSION_DEFAULT_ROUNDS",
    "SUPER_DISCUSSION_MAX_ROUNDS",
]
