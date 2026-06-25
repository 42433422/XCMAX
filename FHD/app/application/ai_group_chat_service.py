"""AI 群聊服务（微信式多 AI 群组）。

自包含、按用户隔离、jsonl 持久化（与超级员工服务同一套存储惯例），
不触碰现有人际 IM（``ImConversation`` 等）以零回归。

SSOT 架构（双模式）：
- **admin 模式**（管理端）：6 部门 + 54 个编制员工均来自 ``config/duty_roster.json``；
  ``duty_employee_registry.json`` 与 employee manifest 只补展示元数据。
- **enterprise 模式**（企业端）：4 部门（工具层/执行层/服务层/管理层）+ 上架员工（MODstore）+ 未上架员工（宿主定制）

部门 → 员工映射为自动派生：
- admin: 从 ``duty_roster.json`` 的 departments/subzones 展平员工归属
- enterprise: ``resolve_enterprise_org_layer(emp_id, ...)`` 从 manifest enterprise_layer / ID 表 / 关键词推断
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir

# 单条用户消息最多触发的 AI 回复数，避免大群一次发太多请求。
MAX_RESPONDERS = 6
# 喂给单个 AI 的群历史条数。
CONTEXT_TURNS = 10
# 超级员工 employee_id 集合：命中时走专用 invoke 通道而非 mod_employee_complete。
_SUPER_EMPLOYEE_IDS: frozenset[str] = frozenset(
    {"codex-super-employee", "claude-super-employee", "cursor-super-employee"}
)

CompletionFn = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]
EmployeeExecutorFn = Callable[
    [str, str, dict[str, Any], int],
    dict[str, Any] | Awaitable[dict[str, Any]],
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


async def _default_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    # 延迟导入，避免在不需要 LLM 的路径（建群/拉人/读消息）上引入依赖。
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    return await mod_employee_complete(messages, max_tokens=600, temperature=0.4)


def _default_employee_executor(
    employee_id: str,
    task: str,
    input_data: dict[str, Any],
    user_id: int,
) -> dict[str, Any]:
    from app.application.employee_runtime.executor import execute_employee_task_local

    return execute_employee_task_local(employee_id, task, input_data, user_id=user_id)


def _default_departments() -> dict[str, Any]:
    """admin 模式默认部门：从 ``config/duty_roster.json`` 加载 6 部门。"""
    try:
        from app.mod_sdk.duty_roster import load_departments

        depts = load_departments()
        return depts if isinstance(depts, dict) else {}
    except Exception:  # noqa: BLE001 - 部门配置缺失时回退到内置 6 部门
        return {}


def _default_enterprise_departments() -> dict[str, Any]:
    """enterprise 模式默认部门：4 层（工具层/执行层/服务层/管理层）。"""
    from app.domain.enterprise_org_layers import enterprise_departments

    return enterprise_departments()


def _dept_key_to_employee_ids(depts: dict[str, Any]) -> dict[str, list[str]]:
    """从 duty_roster 的 departments 展平 dept_key → [employee_id]。"""
    mapping: dict[str, list[str]] = {}
    for dept_key, dept in depts.items():
        if not isinstance(dept, dict):
            continue
        ids: list[str] = []
        subzones = dept.get("subzones") or {}
        if isinstance(subzones, dict):
            for block in subzones.values():
                if not isinstance(block, dict):
                    continue
                raw = block.get("ids")
                if isinstance(raw, list):
                    ids.extend(str(x).strip() for x in raw if str(x).strip())
        if ids:
            mapping[str(dept_key)] = ids
    return mapping


def _employee_manifest(employee_id: str) -> dict[str, Any]:
    manifest = Path(__file__).resolve().parents[2] / "mods" / "_employees" / employee_id / "manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _default_duty_employee_loader() -> list[dict[str, Any]]:
    """admin 模式员工加载器：``config/duty_roster.json`` 编制员工。

    ``duty_roster.json`` 是员工 ID 与部门归属 SSOT；``duty_employee_registry.json`` 与
    本地 employee manifest 仅补充名称、描述、头像等展示元数据。
    返回 ``[{employee_id, mod_id, name, avatar, summary, department_key}]``。
    """
    from app.mod_sdk.duty_roster import load_departments, load_duty_employee_records

    depts = load_departments()
    if not isinstance(depts, dict) or not depts:
        return []
    emp_to_dept: dict[str, str] = {}
    for dept_key, ids in _dept_key_to_employee_ids(depts).items():
        for eid in ids:
            if eid not in emp_to_dept:
                emp_to_dept[eid] = str(dept_key)

    records_by_id: dict[str, dict[str, Any]] = {}
    for raw in load_duty_employee_records():
        eid = str(raw.get("id") or raw.get("pkg_id") or "").strip()
        if eid and eid not in records_by_id:
            records_by_id[eid] = raw

    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
    except Exception:  # noqa: BLE001
        get_mod_manager = None  # type: ignore[assignment]

    installed_by_id: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    if get_mod_manager is not None:
        try:
            mods = get_mod_manager().list_all_mods() or []
        except Exception:  # noqa: BLE001
            mods = []
        for m in mods:
            if not isinstance(m, dict):
                continue
            mod_id = str(m.get("id") or m.get("mod_id") or "").strip()
            wf = m.get("workflow_employees")
            if not isinstance(wf, list):
                continue
            for emp in wf:
                if not isinstance(emp, dict):
                    continue
                eid = str(emp.get("id") or "").strip()
                if eid and eid not in installed_by_id:
                    installed_by_id[eid] = (mod_id, emp, m)

    employees = []
    for eid, dept_key in emp_to_dept.items():
        raw = records_by_id.get(eid, {})
        mod_id, emp, mod = installed_by_id.get(eid, ("", {}, {}))
        manifest = _employee_manifest(eid)
        manifest_employee = (
            manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        )
        name = str(
            raw.get("name")
            or raw.get("label")
            or raw.get("title")
            or emp.get("name")
            or emp.get("label")
            or emp.get("title")
            or emp.get("panel_title")
            or manifest.get("name")
            or manifest_employee.get("label")
            or eid
        ).strip()
        employees.append(
            {
                "employee_id": eid,
                "mod_id": str(raw.get("mod_id") or raw.get("pkg_id") or mod_id or eid),
                "name": name[:60],
                "avatar": str(
                    raw.get("avatar")
                    or raw.get("logo")
                    or raw.get("icon")
                    or emp.get("avatar")
                    or emp.get("avatar_url")
                    or mod.get("avatar")
                    or mod.get("logo")
                    or manifest.get("avatar")
                    or ""
                ),
                "summary": str(
                    raw.get("panel_summary")
                    or raw.get("description")
                    or emp.get("panel_summary")
                    or emp.get("market_description")
                    or mod.get("description")
                    or manifest.get("description")
                    or ""
                )[:280],
                "department_key": dept_key,
            }
        )
    _append_super_employees(employees)
    return employees


def _append_super_employees(employees: list[dict[str, Any]]) -> None:
    """追加超级员工（Codex / Cursor / Claude）到员工列表，使其可被拉入群聊。

    超级员工不属于任何部门（department_key 留空），不参与部门群自动补员，
    仅出现在手机端选人列表中供用户手动拉入。
    """
    try:
        from app.application.super_employee_service import (
            CLAUDE_PROFILE,
            CODEX_PROFILE,
            CURSOR_PROFILE,
        )
    except Exception:  # noqa: BLE001 - 超级员工模块不可用时静默跳过
        return
    existing = {str(e.get("employee_id") or "") for e in employees if isinstance(e, dict)}
    for profile in (CODEX_PROFILE, CURSOR_PROFILE, CLAUDE_PROFILE):
        if profile.employee_id in existing:
            continue
        employees.append(
            {
                "employee_id": profile.employee_id,
                "mod_id": "super-employee",
                "name": profile.employee_name,
                "avatar": profile.avatar_path,
                "avatar_key": profile.avatar_key,
                "summary": f"{profile.display_tool} 超级员工，支持 CLI 直答与多设备派工。",
                "department_key": "",
            }
        )


def _default_enterprise_employee_loader() -> list[dict[str, Any]]:
    """enterprise 模式员工加载器：上架员工（MODstore 安装）+ 未上架员工（宿主定制）。

    数据源为 ``list_all_mods()``（已安装的 mod + employee_pack，含 host_foundation）。
    部门归属由 ``resolve_enterprise_org_layer()`` 自动派生至 4 层之一。
    """
    from app.domain.enterprise_org_layers import resolve_enterprise_org_layer

    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
    except Exception:  # noqa: BLE001
        return []

    employees: list[dict[str, Any]] = []
    try:
        mods = get_mod_manager().list_all_mods() or []
    except Exception:  # noqa: BLE001
        return []
    for m in mods:
        if not isinstance(m, dict):
            continue
        mod_id = str(m.get("id") or m.get("mod_id") or "").strip()
        wf = m.get("workflow_employees")
        if not isinstance(wf, list):
            continue
        for emp in wf:
            if not isinstance(emp, dict):
                continue
            eid = str(emp.get("id") or "").strip()
            if not eid:
                continue
            name = str(
                emp.get("name")
                or emp.get("label")
                or emp.get("title")
                or emp.get("panel_title")
                or eid
            ).strip()
            panel_title = str(emp.get("panel_title") or "")
            manifest_layer = str(emp.get("enterprise_layer") or "")
            layer = resolve_enterprise_org_layer(eid, name, panel_title, manifest_layer or None)
            employees.append(
                {
                    "employee_id": eid,
                    "mod_id": mod_id,
                    "name": name[:60],
                    "avatar": str(
                        emp.get("avatar")
                        or emp.get("avatar_url")
                        or m.get("avatar")
                        or m.get("logo")
                        or ""
                    ),
                    "summary": str(
                        emp.get("panel_summary")
                        or emp.get("market_description")
                        or m.get("description")
                        or ""
                    )[:280],
                    "department_key": layer,
                }
            )
    _append_super_employees(employees)
    return employees


# 部门配置不可用时的内置兜底（保证"默认 6 部门 6 个群"始终成立）。
_FALLBACK_DEPARTMENTS: list[tuple[str, str]] = [
    ("ops_acquisition", "O-A 获客部"),
    ("ops_partner", "O-B 伙伴部"),
    ("prod_web", "P-W 网站部"),
    ("prod_mod", "P-M Mod 部"),
    ("prod_software", "P-S 软件部"),
    ("shared_retention", "S-R 归档部"),
]

_FALLBACK_ENTERPRISE_DEPARTMENTS: list[tuple[str, str]] = [
    ("tools", "工具层"),
    ("execution", "执行层"),
    ("service", "服务层"),
    ("management", "管理层"),
]


class AiGroupChatService:
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
        groups = self._user_groups(user_id)
        if not groups:
            groups = self._seed_department_groups(user_id)
        else:
            # 回填：早期种子群成员为空，首次访问时按编制补员（仅一次，用户后续移人不会被覆盖）。
            self._backfill_department_members(groups)
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

    def _backfill_department_members(self, groups: list[dict[str, Any]]) -> None:
        """对未补过员的部门群一次性填入编制成员。

        判定标志：部门群（``department_key`` 非空）且 ``members_seeded`` 未置 True。
        补员后写 ``members_seeded=True`` 并持久化；用户手动移人后不会再次自动加回。
        """
        targets = [
            g
            for g in groups
            if isinstance(g, dict)
            and str(g.get("department_key") or "").strip()
            and not g.get("members_seeded")
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
            if not dk or g.get("members_seeded"):
                continue
            existing = {
                str(m.get("employee_id")) for m in g.get("members", []) if isinstance(m, dict)
            }
            fresh = members_by_dept.get(dk, [])
            merged = list(g.get("members", []))
            for m in fresh:
                if str(m.get("employee_id")) not in existing:
                    merged.append(m)
            g["members"] = merged
            g["members_seeded"] = True
            changed = True
        if changed:
            self._rewrite_groups(all_groups)

    def create_group(self, *, user_id: int, name: str) -> dict[str, Any]:
        title = (name or "").strip()
        if not title:
            raise ValueError("群名不能为空")
        group = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "name": title[:60],
            "department_key": "",
            "members": [],
            "is_pinned": False,
            "is_hidden": False,
            "is_followed": True,
            "unread_count": 0,
            "created_at": _utc_now(),
        }
        self._append_group(group)
        return self._public_group(group, None)

    def add_member(self, *, user_id: int, group_id: str, member: dict[str, Any]) -> dict[str, Any]:
        employee_id = str(member.get("employee_id") or "").strip()
        if not employee_id:
            raise ValueError("employee_id 不能为空")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        if any(str(m.get("employee_id")) == employee_id for m in members):
            return self._public_group(group, None)  # 已在群里，幂等
        members.append(
            {
                "employee_id": employee_id,
                "mod_id": str(member.get("mod_id") or ""),
                "name": str(member.get("name") or employee_id)[:60],
                "avatar": str(member.get("avatar") or ""),
                "summary": str(member.get("summary") or "")[:280],
            }
        )
        group["members"] = members
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def remove_member(self, *, user_id: int, group_id: str, employee_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["members"] = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id")) != str(employee_id)
        ]
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_pinned(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_pinned"] = not bool(group.get("is_pinned"))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_unread(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        current = int(group.get("unread_count") or 0)
        group["unread_count"] = max(1, current + 1 if current > 0 else 1)
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def mark_read(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["unread_count"] = 0
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_followed(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")
        group["is_followed"] = not bool(group.get("is_followed", True))
        self._rewrite_groups(self._replace(self._all_groups(), group))
        return self._public_group(group, None)

    def toggle_hidden(self, *, user_id: int, group_id: str) -> dict[str, Any]:
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
        rows = [
            self._public_message(r)
            for r in self._read_messages()
            if int(r.get("user_id") or 0) == int(user_id)
            and str(r.get("group_id")) == str(group_id)
        ]
        return rows[-max(1, min(int(limit), 300)) :]

    async def post_message(
        self,
        *,
        user_id: int,
        group_id: str,
        text: str,
        sender_name: str = "我",
        mentions: list[str] | None = None,
        dispatch: bool = False,
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError("群不存在")

        user_msg = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="user",
            sender_id="user",
            sender_name=sender_name or "我",
            sender_avatar="",
            body=body,
        )
        new_messages = [user_msg]

        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        responders = self._pick_responders(members, body, mentions)
        history = self.get_messages(user_id=user_id, group_id=group_id, limit=CONTEXT_TURNS)
        history = history + [self._public_message(user_msg)]

        work_orders: list[dict[str, Any]] = []
        if dispatch:
            dispatch_messages, work_orders = await self._dispatch_work(
                group=group,
                members=responders,
                task=body,
                user_id=user_id,
                sender_name=sender_name or "我",
            )
            new_messages.extend(dispatch_messages)
        else:
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
                history = history + [self._public_message(ai_msg)]

        self._append_messages(new_messages)
        result: dict[str, Any] = {
            "group": self._public_group(group, None),
            "messages": [self._public_message(m) for m in new_messages],
        }
        if dispatch:
            result["work_orders"] = work_orders
        return result

    # ── 回复编排 ──

    def _pick_responders(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        # 显式 mentions（employee_id）优先。
        explicit = {str(m).strip() for m in (mentions or []) if str(m).strip()}
        # 文本里的 @名字 也算定向。
        for m in members:
            name = str(m.get("name") or "")
            if name and f"@{name}" in text:
                explicit.add(str(m.get("employee_id")))
        if explicit:
            targeted = [m for m in members if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        # 无定向：全员各回一条（上限保护）。
        return members[:MAX_RESPONDERS]

    async def _ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        employee_id = str(member.get("employee_id") or "")
        # 超级员工走专用 invoke 通道（CLI 直答 / Para 多设备派工）
        if employee_id in _SUPER_EMPLOYEE_IDS:
            return await self._super_employee_reply(group, member, history, user_id=user_id)
        group_name = str(group.get("name") or "AI 群聊")
        me = str(member.get("name") or member.get("employee_id"))
        summary = str(member.get("summary") or "")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        system = (
            f"你是群聊「{group_name}」里的 AI 成员「{me}」。{summary}\n"
            f"群成员有：{roster}。\n"
            "请只代表你自己、用一两句话简洁地回应群里用户的最新消息；"
            "不要替其他成员发言，不要复述别人说过的话，不要加“作为AI”之类的免责声明。"
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        user_content = f"【群最近对话】\n{transcript}\n\n请以「{me}」身份回应最新这条消息。"
        try:
            res = await self._completion_fn(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return f"（{me} 暂时无法回应：{str(exc)[:120]}）"
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            return str(res["content"]).strip()
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return f"（{me} 暂时无法回应{f'：{err}' if err else ''}）"

    async def _dispatch_work(
        self,
        *,
        group: dict[str, Any],
        members: list[dict[str, Any]],
        task: str,
        user_id: int,
        sender_name: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        work_order_id = uuid.uuid4().hex
        target_names = [str(m.get("name") or m.get("employee_id") or "") for m in members]
        messages: list[dict[str, Any]] = [
            self._message_row(
                user_id=user_id,
                group_id=group_id,
                role="ai",
                sender_id="ai-group-dispatcher",
                sender_name="工作流调度",
                sender_avatar="",
                body=self._format_work_order_message(task, target_names),
                kind="work_order",
                status="assigned" if members else "blocked",
                work_order_id=work_order_id,
                payload={
                    "task": task,
                    "target_employee_ids": [str(m.get("employee_id") or "") for m in members],
                },
            )
        ]
        if not members:
            return messages, [
                {
                    "work_order_id": work_order_id,
                    "status": "blocked",
                    "task": task,
                    "target_employee_ids": [],
                }
            ]

        work_orders: list[dict[str, Any]] = []
        for member in members:
            report = await self._execute_employee_work(
                group=group,
                member=member,
                task=task,
                work_order_id=work_order_id,
                user_id=user_id,
                sender_name=sender_name,
            )
            work_orders.append(report)
            messages.append(
                self._message_row(
                    user_id=user_id,
                    group_id=group_id,
                    role="ai",
                    sender_id=str(member.get("employee_id") or ""),
                    sender_name=str(member.get("name") or member.get("employee_id") or ""),
                    sender_avatar=str(member.get("avatar") or ""),
                    body=self._format_work_report_message(member, report),
                    kind="work_report",
                    status=str(report.get("status") or ""),
                    work_order_id=work_order_id,
                    payload=report,
                )
            )
        return messages, work_orders

    async def _execute_employee_work(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        work_order_id: str,
        user_id: int,
        sender_name: str,
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
            "sender_name": sender_name,
        }
        try:
            maybe_result = self._employee_executor_fn(employee_id, task, input_data, int(user_id))
            raw = await maybe_result if isawaitable(maybe_result) else maybe_result
            result = raw if isinstance(raw, dict) else {"success": False, "message": str(raw)}
            success = bool(result.get("success"))
            return {
                "work_order_id": work_order_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "task": task,
                "status": str(result.get("status") or ("done" if success else "failed")),
                "success": success,
                "summary": self._execution_summary(result),
                "risk": self._execution_risk(result, success),
                "raw": self._compact_result(result),
            }
        except Exception as exc:  # noqa: BLE001 - 单个员工失败不能阻断其他员工汇报
            return {
                "work_order_id": work_order_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "task": task,
                "status": "failed",
                "success": False,
                "summary": str(exc)[:500],
                "risk": "执行入口异常，需要重试或改派。",
                "raw": {"error": str(exc)[:500]},
            }

    @staticmethod
    def _format_work_order_message(task: str, target_names: list[str]) -> str:
        if not target_names:
            return f"【派工失败】没有可派工成员。\n任务：{task}"
        owners = "、".join(name for name in target_names if name) or "群成员"
        return (
            f"【工作派单】{task}\n"
            f"负责人：{owners}\n"
            "节奏：接收任务 → 执行处理 → 在群里汇报结果、风险和下一步。"
        )

    @staticmethod
    def _format_work_report_message(member: dict[str, Any], report: dict[str, Any]) -> str:
        name = str(member.get("name") or member.get("employee_id") or "员工")
        ok = bool(report.get("success"))
        status = "完成" if ok else "失败"
        summary = str(report.get("summary") or "").strip() or "无结果摘要"
        risk = str(report.get("risk") or "").strip() or ("未发现阻塞。" if ok else "存在执行阻塞。")
        next_step = "等待负责人验收或继续派下一步。" if ok else "请查看失败原因后重试、改派或补充上下文。"
        return (
            f"【{name} 执行汇报】\n"
            f"状态：{status}\n"
            f"结果：{summary}\n"
            f"风险：{risk}\n"
            f"下一步：{next_step}"
        )

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
            text = AiGroupChatService._stringify_summary(value)
            if text:
                return text[:1200]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("summary", "message", "output", "result", "report"):
                text = AiGroupChatService._stringify_summary(data.get(key))
                if text:
                    return text[:1200]
        return AiGroupChatService._stringify_summary(result)[:1200]

    @staticmethod
    def _execution_risk(result: dict[str, Any], success: bool) -> str:
        candidates = (result.get("risk"), result.get("risks"), result.get("blocker"))
        for value in candidates:
            text = AiGroupChatService._stringify_summary(value)
            if text:
                return text[:500]
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("risk", "risks", "blocker"):
                text = AiGroupChatService._stringify_summary(data.get(key))
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
        for key in ("success", "status", "message", "summary", "task_id", "run_id", "error"):
            if key in result:
                value = result[key]
                if value is None or isinstance(value, str | int | float | bool):
                    compact[key] = value
                else:
                    compact[key] = AiGroupChatService._stringify_summary(value)
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
            else:
                service = ClaudeSuperEmployeeService()
            # 群聊场景强制走 CLI 直答（mode=chat），避免 transcript 里包含
            # "修改/测试/调用"等 _TASK_MARKERS 词被误判为任务走派工流程，
            # 导致本机无 Para 时只返回"思考中..."而永远等不到答案。
            result = service.invoke(
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
                        "summary": str(emp.get("summary") or "")[:280],
                    }
                )
        except Exception:  # noqa: BLE001 - 员工加载失败不阻断建群
            members_by_dept = {}
        seeded: list[dict[str, Any]] = []
        for key, label in pairs:
            seeded.append(
                {
                    "id": f"dept:{key}",
                    "user_id": int(user_id),
                    "name": label,
                    "department_key": key,
                    "members": members_by_dept.get(key, []),
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

    # ── 持久化 ──

    def _public_group(
        self, group: dict[str, Any], preview: dict[str, Any] | None
    ) -> dict[str, Any]:
        members = [m for m in group.get("members", []) if isinstance(m, dict)]
        return {
            "id": str(group.get("id")),
            "name": str(group.get("name") or ""),
            "department_key": str(group.get("department_key") or ""),
            "member_count": len(members),
            "members": [
                {
                    "employee_id": str(m.get("employee_id")),
                    "mod_id": str(m.get("mod_id") or ""),
                    "name": str(m.get("name") or ""),
                    "avatar": str(m.get("avatar") or ""),
                    "summary": str(m.get("summary") or ""),
                }
                for m in members
            ],
            "is_pinned": bool(group.get("is_pinned")),
            "is_hidden": bool(group.get("is_hidden")),
            "is_followed": bool(group.get("is_followed", True)),
            "unread_count": int(group.get("unread_count") or 0),
            "created_at": str(group.get("created_at") or ""),
            "last_message_preview": str((preview or {}).get("preview") or ""),
            "last_message_at": str((preview or {}).get("created_at") or ""),
        }

    def _public_message(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": str(row.get("id") or ""),
            "group_id": str(row.get("group_id") or ""),
            "role": str(row.get("role") or "ai"),
            "sender_id": str(row.get("sender_id") or ""),
            "sender_name": str(row.get("sender_name") or ""),
            "sender_avatar": str(row.get("sender_avatar") or ""),
            "body": str(row.get("body") or ""),
            "created_at": str(row.get("created_at") or ""),
        }
        for key in ("kind", "status", "work_order_id"):
            if row.get(key):
                out[key] = str(row.get(key) or "")
        payload = row.get("payload")
        if isinstance(payload, dict):
            out["payload"] = payload
        return out

    def _message_row(
        self,
        *,
        user_id: int,
        group_id: str,
        role: str,
        sender_id: str,
        sender_name: str,
        sender_avatar: str,
        body: str,
        kind: str = "chat",
        status: str = "",
        work_order_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "group_id": str(group_id),
            "role": role,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar,
            "body": body,
            "created_at": _utc_now(),
        }
        if kind and kind != "chat":
            row["kind"] = kind
        if status:
            row["status"] = status
        if work_order_id:
            row["work_order_id"] = work_order_id
        if payload:
            row["payload"] = payload
        return row

    def _latest_previews(self, user_id: int) -> dict[str, dict[str, Any]]:
        previews: dict[str, dict[str, Any]] = {}
        for r in self._read_messages():
            if int(r.get("user_id") or 0) != int(user_id):
                continue
            gid = str(r.get("group_id"))
            sender = str(r.get("sender_name") or "")
            body = str(r.get("body") or "")
            previews[gid] = {
                "preview": f"{sender}：{body}"[:60] if sender else body[:60],
                "created_at": str(r.get("created_at") or ""),
            }
        return previews

    def _user_groups(self, user_id: int) -> list[dict[str, Any]]:
        return [g for g in self._all_groups() if int(g.get("user_id") or 0) == int(user_id)]

    def _all_groups(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._groups_path)

    def _read_messages(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._messages_path)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _append_group(self, group: dict[str, Any]) -> None:
        with self._groups_path.open("a", encoding="utf-8") as fh:
            fh.write(_safe_json_line(group))

    def _rewrite_groups(self, groups: list[dict[str, Any]]) -> None:
        with self._groups_path.open("w", encoding="utf-8") as fh:
            for g in groups:
                fh.write(_safe_json_line(g))

    def _append_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("a", encoding="utf-8") as fh:
            for m in messages:
                fh.write(_safe_json_line(m))

    @staticmethod
    def _find(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
        return next((g for g in groups if str(g.get("id")) == str(group_id)), None)

    @staticmethod
    def _replace(groups: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
        return [updated if str(g.get("id")) == str(updated.get("id")) else g for g in groups]


__all__ = ["AiGroupChatService", "MAX_RESPONDERS"]
