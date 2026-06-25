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

import asyncio
import json
import os
import re
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
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


# 超级员工执行任务前的群内讨论轮数：每轮每个超级员工最多发言一次。
SUPER_DISCUSSION_DEFAULT_ROUNDS = 1
SUPER_DISCUSSION_MAX_ROUNDS = 2
# 手机聊天气泡里只放能看懂的摘要，完整执行输出留在中继任务结果里。
CHAT_REPORT_SUMMARY_CHARS = 180
CHAT_ACCEPTANCE_SUMMARY_CHARS = 44
PUBLIC_CHAT_BODY_MAX_CHARS = 900
PUBLIC_ACCEPTANCE_BODY_MAX_CHARS = 620
RELAY_PROGRESS_MIN_INTERVAL_SEC = 30
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]{1,100})\]\([^)]+\)")
_BROKEN_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]{1,100})\]\([^，。；\s]*")
_TEMP_PATH_RE = re.compile(r"(/private)?/var/folders/[^\s，。；)]+")
_RELAY_TASK_ID_RE = re.compile(r"；中继任务：[0-9a-f]{16,}。?")
_UNFINISHED_REPORT_MARKERS = (
    "BLOCKED",
    "blocked",
    "未完成",
    "无法完成",
    "不能完成",
    "没有完成",
    "执行失败",
    "失败：",
    "验证未通过",
    "合并有冲突",
    "merge conflict",
    "无改动可提交",
    "未产生可提交改动",
    "先不动代码",
    "只给出执行方案",
    "仅提供方案",
    "不能执行命令",
    "不能执行",
    "不能读工作区",
    "不能读取工作区",
    "不能跑测试",
    "未跑测试",
    "没有跑测试",
    "不能安装 APK",
    "未安装 APK",
    "没有安装 APK",
    "权限不足",
    "没有真实执行",
    "没有实际改动",
    "未修改文件",
    "无测试证据",
    "没有测试证据",
    "不能给你伪造",
    "正在搜索",
    "正在实现",
    "正在处理",
    "正在执行",
    "搜索代码库",
    "我只出",
    "只出验收口径",
    "只出风险",
    "只出收口",
    "仅做验收",
    "仅做风险",
    "仅做收口",
    "仅做分析",
    "还在",
    "待回写",
    "等待回写",
    "❌",
)
_FAILED_REPORT_MARKERS = (
    "失败",
    "failed",
    "合并有冲突",
    "merge conflict",
    "验证未通过",
    "❌",
    "error",
    "Error",
)
_RESEARCH_ONLY_REPORT_MARKERS = (
    "调研",
    "调查",
    "分析",
    "定位",
    "建议",
    "方案",
    "思路",
    "可以这样",
    "后续可以",
    "下一步可以",
)
_EXECUTION_EVIDENCE_MARKERS = (
    "已修改",
    "修改了",
    "新增",
    "删除了",
    "更新了",
    "改动文件",
    "文件：",
    "测试通过",
    "验证通过",
    "编译通过",
    "构建通过",
    "安装成功",
    "pytest",
    "ruff",
    "gradle",
    "assemble",
    "adb",
    "git diff",
    "commit",
    "changed files",
    "tests passed",
    "test passed",
    "command:",
    "commands:",
    "命令：",
    "运行：",
    "验证：",
    "测试：",
    "构建：",
    "安装：",
    "手机复测",
    "真机复测",
    "群里复测",
)
_DEV_TASK_MARKERS = (
    "修复",
    "实现",
    "开发",
    "添加",
    "新增",
    "更新",
    "删除",
    "改造",
    "优化",
    "测试",
    "验收",
    "构建",
    "编译",
    "安装",
    "合并",
    "bug",
    "功能",
    "页面",
    "接口",
    "代码",
    "apk",
    "branch",
    "merge",
)
_PURE_RESEARCH_TASK_MARKERS = ("调研", "调查", "分析一下", "评估", "讨论", "方案")
_EVIDENCE_FILE_RE = re.compile(
    r"(?i)\b[\w./-]+\.(py|kt|java|ts|tsx|js|jsx|json|ya?ml|md|gradle|xml|sql|swift|go|rs)\b"
)
# 群内执行前讨论不能把手机端派工长时间卡死；超时后走确定性分流兜底。
SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC = max(
    0.5,
    min(_env_float("XCAGI_GROUP_DISCUSSION_LLM_TIMEOUT_SEC", 3.0), 30.0),
)
# 超级员工 employee_id 集合：命中时走专用 invoke 通道而非 mod_employee_complete。
_SUPER_EMPLOYEE_IDS: frozenset[str] = frozenset(
    {"codex-super-employee", "claude-super-employee", "cursor-super-employee"}
)
_DEFAULT_SINGLE_CLI_EMPLOYEE_ID = "codex-super-employee"
_SUPER_EMPLOYEE_RELAY_KINDS: dict[str, str] = {
    "codex-super-employee": "codex.invoke",
    "cursor-super-employee": "cursor.invoke",
    "claude-super-employee": "claude.invoke",
}
_XIAOC_ASSISTANT_ID = "xcagi-assistant"
_REQUIRED_GROUP_MEMBER_IDS: frozenset[str] = frozenset({_XIAOC_ASSISTANT_ID})
_BRANCH_SAFE_RE = re.compile(r"[^A-Za-z0-9._/-]+")

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


def _xiaoc_assistant_member() -> dict[str, Any]:
    return {
        "employee_id": _XIAOC_ASSISTANT_ID,
        "mod_id": "xcagi-core-assistant",
        "name": "小C助理",
        "avatar": "",
        "summary": "企业智能助手，负责群内上下文、任务拆解和工作汇报串联。",
        "department_key": "",
    }


def _member_public_shape(member: dict[str, Any]) -> dict[str, Any]:
    employee_id = str(member.get("employee_id") or "").strip()
    return {
        "employee_id": employee_id,
        "mod_id": str(member.get("mod_id") or ""),
        "name": str(member.get("name") or employee_id)[:60],
        "avatar": str(member.get("avatar") or ""),
        "summary": str(member.get("summary") or "")[:280],
    }


def _with_required_group_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for member in [_xiaoc_assistant_member(), *members]:
        if not isinstance(member, dict):
            continue
        shaped = _member_public_shape(member)
        employee_id = shaped["employee_id"]
        if not employee_id or employee_id in seen:
            continue
        seen.add(employee_id)
        out.append(shaped)
    return out


def _is_required_group_member(employee_id: str) -> bool:
    return str(employee_id or "").strip() in _REQUIRED_GROUP_MEMBER_IDS


def _normalize_branch_context(raw: Any) -> str:
    branch = str(raw or "").strip()
    if branch.startswith("origin/"):
        branch = branch[len("origin/") :]
    branch = _BRANCH_SAFE_RE.sub("-", branch.replace(" ", "-"))
    branch = re.sub(r"/+", "/", branch).strip("/.")
    while ".." in branch:
        branch = branch.replace("..", ".")
    if branch in {"", ".", "..", "HEAD"}:
        return ""
    return branch[:180]


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
        groups = self._user_groups(user_id)
        if not groups:
            groups = self._seed_department_groups(user_id)
        else:
            # 回填：早期种子群成员为空，首次访问时按编制补员（仅一次，用户后续移人不会被覆盖）。
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
            g for g in all_groups if isinstance(g, dict) and int(g.get("user_id") or 0) == int(user_id)
        ]
        super_groups = [
            g for g in user_groups if self._canonical_group_name(g) == "超级开发部"
        ]
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
            [
                m
                for g in super_groups
                for m in g.get("members", [])
                if isinstance(m, dict)
            ]
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
        if _SUPER_EMPLOYEE_IDS.issubset(ids) and _XIAOC_ASSISTANT_ID in ids:
            roster_like = (
                not name
                or name in {"新建群聊", "群聊"}
                or ("超级员工-Codex" in name and "超级员工-Cursor" in name and "超级员工-Claude" in name)
            )
            if roster_like:
                return "超级开发部"
        return name

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
            if status not in {"queued", "accepted", "assigned", "running", "processing", "in_progress"}:
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
            if status not in {"queued", "accepted", "assigned", "running", "processing", "in_progress"}:
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
            if str(item.get("task_id") or "") == str(task_id) and str(item.get("kind") or "") == "dispatcher":
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
                    "work_order_id": str(report.get("work_order_id") or payload.get("work_order_id") or ""),
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
    ) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValueError("message 不能为空")
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

    # ── 回复编排 ──

    def _pick_responders(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        if self._is_broadcast_mention(text):
            return members[:MAX_RESPONDERS]
        explicit = self._explicit_member_ids(members, text, mentions)
        if explicit:
            targeted = [m for m in members if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        xiaoc = next(
            (
                m
                for m in members
                if str(m.get("employee_id") or "") == _XIAOC_ASSISTANT_ID
            ),
            None,
        )
        # 真实工作群默认不会全员接话：先由小C接待，点名/广播才拉对应员工响应。
        return [xiaoc or members[0]]

    def _pick_dispatch_targets(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> list[dict[str, Any]]:
        work_capable = [
            m
            for m in members
            if not _is_required_group_member(str(m.get("employee_id") or ""))
        ]
        if not work_capable:
            return []
        if self._is_broadcast_mention(text):
            return work_capable[:MAX_RESPONDERS]
        explicit = self._explicit_member_ids(members, text, mentions)
        if explicit:
            targeted = [m for m in work_capable if str(m.get("employee_id")) in explicit]
            return targeted[:MAX_RESPONDERS]
        return work_capable[:MAX_RESPONDERS]

    def _explicit_member_ids(
        self,
        members: list[dict[str, Any]],
        text: str,
        mentions: list[str] | None,
    ) -> set[str]:
        explicit = {str(m).strip() for m in (mentions or []) if str(m).strip()}
        for member in members:
            employee_id = str(member.get("employee_id") or "").strip()
            name = str(member.get("name") or "").strip()
            if name and f"@{name}" in text:
                explicit.add(employee_id)
            if employee_id and f"@{employee_id}" in text:
                explicit.add(employee_id)
        return explicit

    @staticmethod
    def _is_broadcast_mention(text: str) -> bool:
        lower = (text or "").lower()
        return any(
            marker in lower
            for marker in ("@所有人", "@全体", "@全员", "@all", "@everyone")
        )

    @staticmethod
    def _should_run_super_discussion(members: list[dict[str, Any]]) -> bool:
        super_count = sum(
            1 for m in members if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        )
        return super_count >= 2

    async def _run_super_discussion_then_route(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        user_id: int,
        history: list[dict[str, Any]],
        mentions: list[str] | None,
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        super_members = [
            m for m in candidates if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ][:3]
        discussion_rows: list[dict[str, Any]] = []
        discussion_turns: list[dict[str, str]] = []
        rounds = self._discussion_round_count()
        assessment = self._xiaoc_dispatch_assessment(task=task, candidates=candidates)
        discussion_turns.append(
            {
                "employee_id": _XIAOC_ASSISTANT_ID,
                "name": "小C助理",
                "body": assessment,
                "round": "0",
            }
        )
        assessment_row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=_XIAOC_ASSISTANT_ID,
            sender_name="小C助理",
            sender_avatar="",
            body=assessment,
            kind="discussion",
            status="completed",
            payload={
                "round": 0,
                "task": task,
                "phase": "pre_dispatch_assessment",
                "difficulty": self._dispatch_difficulty(task),
            },
        )
        discussion_rows.append(assessment_row)
        if persist:
            self._append_messages([assessment_row])
        for round_index in range(1, rounds + 1):
            for member in super_members:
                content = await self._super_discussion_reply(
                    group=group,
                    member=member,
                    task=task,
                    history=history,
                    discussion_turns=discussion_turns,
                    round_index=round_index,
                )
                turn = {
                    "employee_id": str(member.get("employee_id") or ""),
                    "name": str(member.get("name") or member.get("employee_id") or ""),
                    "body": content,
                    "round": str(round_index),
                }
                discussion_turns.append(turn)
                row = self._message_row(
                    user_id=user_id,
                    group_id=group_id,
                    role="ai",
                    sender_id=turn["employee_id"],
                    sender_name=turn["name"],
                    sender_avatar=str(member.get("avatar") or ""),
                    body=content,
                    kind="discussion",
                    status="completed",
                    payload={"round": round_index, "task": task, "phase": "pre_dispatch"},
                )
                discussion_rows.append(row)
                if persist:
                    self._append_messages([row])

        selected, rationale = await self._route_after_discussion(
            group=group,
            task=task,
            candidates=candidates,
            discussion_turns=discussion_turns,
            mentions=mentions,
        )
        selected_names = "、".join(str(m.get("name") or m.get("employee_id") or "") for m in selected)
        row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=self._format_routing_decision_message(selected_names, rationale),
            kind="routing_decision",
            status="completed" if selected else "blocked",
            payload={
                "task": task,
                "target_employee_ids": [str(m.get("employee_id") or "") for m in selected],
                "discussion_rounds": rounds,
                "rationale": rationale,
            },
        )
        discussion_rows.append(row)
        if persist:
            self._append_messages([row])
        return discussion_rows, selected

    def _xiaoc_dispatch_assessment(
        self, *, task: str, candidates: list[dict[str, Any]]
    ) -> str:
        difficulty = self._dispatch_difficulty(task)
        difficulty_label = {
            "simple": "简单",
            "medium": "中等",
            "large": "较大",
        }.get(difficulty, "中等")
        candidate_names = "、".join(
            str(m.get("name") or m.get("employee_id") or "")
            for m in candidates
            if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        )
        if difficulty == "simple":
            strategy = "先讨论是否需要拆分；若无跨端风险，只选 1 个最合适负责人。"
        elif difficulty == "large":
            strategy = "先讨论模块边界和风险，再按职责拆给多人并行，避免多人做同一件事。"
        else:
            strategy = "先讨论工作量和风险，优先选 1 个负责人；只有跨端或需要复核时才加第 2 人。"
        return (
            "【任务讨论】小C先评估，再选负责人。\n"
            f"难度：{difficulty_label}\n"
            f"候选：{candidate_names or '暂无超级员工'}\n"
            f"策略：{strategy}"
        )

    def _discussion_round_count(self) -> int:
        return max(1, min(SUPER_DISCUSSION_DEFAULT_ROUNDS, SUPER_DISCUSSION_MAX_ROUNDS))

    async def _super_discussion_reply(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        history: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        round_index: int,
    ) -> str:
        me = str(member.get("name") or member.get("employee_id") or "超级员工")
        group_name = str(group.get("name") or "AI 群聊")
        roster = "、".join(
            str(m.get("name") or "") for m in group.get("members", []) if isinstance(m, dict)
        )
        transcript = "\n".join(
            f"{m.get('sender_name')}：{m.get('body')}" for m in history[-CONTEXT_TURNS:]
        )
        prior = "\n".join(
            f"{turn.get('name')}：{turn.get('body')}" for turn in discussion_turns[-6:]
        )
        system = (
            f"你是群聊「{group_name}」里的超级员工「{me}」。群成员有：{roster}。\n"
            "这是执行前讨论阶段，只能做判断、拆解和建议，不要声称已经执行，不要调用 CLI，不要修改文件。\n"
            "讨论最多 1-2 轮，所以每次发言必须短、具体、可分工。\n"
            "先判断任务难度和工作量：简单任务建议只派一个最合适 CLI；只有跨领域或工作量大才多人并行，避免多人做同一件事。"
        )
        user_content = (
            f"【用户任务】\n{task}\n\n"
            f"【群最近对话】\n{transcript or '无'}\n\n"
            f"【前序讨论】\n{prior or '无'}\n\n"
            f"第 {round_index} 轮，请以「{me}」身份给出你的执行判断："
            "任务难不难、是否值得拆、你适合负责什么、需要谁配合、下一步如何派工。用 1-2 句话。"
        )
        try:
            res = await asyncio.wait_for(
                self._completion_fn(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
            )
        except TimeoutError:
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型讨论超时",
            )
        except Exception:  # noqa: BLE001
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="我这边暂时不能参与讨论",
            )
        if isinstance(res, dict) and res.get("success") and str(res.get("content") or "").strip():
            content = str(res["content"]).strip()[:600]
            if not self._discussion_reply_is_placeholder(content):
                return content
            return self._fallback_super_discussion_reply(
                group=group,
                member=member,
                task=task,
                round_index=round_index,
                reason="模型回复过于空泛",
            )
        err = str((res or {}).get("error") or "").strip() if isinstance(res, dict) else ""
        return self._fallback_super_discussion_reply(
            group=group,
            member=member,
            task=task,
            round_index=round_index,
            reason=err or "模型没有给出有效讨论",
        )

    def _fallback_super_discussion_reply(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        round_index: int,
        reason: str = "",
    ) -> str:
        employee_id = str(member.get("employee_id") or "").strip()
        me = str(member.get("name") or employee_id or "超级员工")
        difficulty = self._dispatch_difficulty(task)
        difficulty_label = {
            "simple": "简单",
            "medium": "中等",
            "large": "较大",
        }.get(difficulty, "中等")
        group_members = [
            m
            for m in group.get("members", [])
            if isinstance(m, dict) and str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ]
        preferred = self._preferred_single_dispatch_target(group_members or [member], task)
        preferred_name = str((preferred or {}).get("name") or (preferred or {}).get("employee_id") or me)
        focus = self._super_employee_focus(employee_id, task)
        if difficulty == "simple":
            split_advice = f"不建议拆分，派 {preferred_name} 一个负责人就够，避免重复消耗。"
        elif difficulty == "large":
            split_advice = "建议按端侧、服务端、验收边界拆开并行，各自只做自己的部分。"
        else:
            split_advice = f"先派 {preferred_name} 主责推进；只有遇到跨端阻塞再加第二人。"
        collaboration = {
            "codex-super-employee": "我适合补服务端链路、接口状态和自动化测试证据。",
            "cursor-super-employee": "我适合看移动端页面、交互细节和可见 UI 结果。",
            "claude-super-employee": "我适合做验收口径、风险收口和是否需要拆分的判断。",
        }.get(employee_id, f"我适合负责{focus}。")
        reason_line = f"（{reason}，走确定性讨论兜底）" if reason else ""
        return (
            f"{me}：我判断这是{difficulty_label}任务，{split_advice}"
            f"{collaboration}如果派到我，我只处理这条边界，并在群里回报改动文件、命令和测试结果。{reason_line}"
        )[:600]

    @staticmethod
    def _discussion_reply_is_placeholder(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return True
        compact = text.replace(" ", "")
        if len(compact) <= 18 and any(k in compact for k in ("收到", "待命", "执行", "派工")):
            return True
        generic_markers = ("按职责待命", "等派工", "派到我", "收到", "先判断再派工")
        judgment_markers = (
            "判断",
            "简单",
            "中等",
            "较大",
            "难度",
            "工作量",
            "拆",
            "负责人",
            "适合",
            "风险",
            "建议",
        )
        has_judgment = any(k in text for k in judgment_markers)
        if len(compact) <= 34 and not has_judgment:
            return True
        return any(k in text for k in generic_markers) and not has_judgment

    async def _route_after_discussion(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        mentions: list[str] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        if self._is_broadcast_mention(task) or self._explicit_member_ids(candidates, task, mentions):
            return candidates[:MAX_RESPONDERS], "用户已明确点名或广播，按指定成员执行。"
        candidate_lines = "\n".join(
            f"- {m.get('employee_id')}: {m.get('name')}，{m.get('summary')}"
            for m in candidates
        )
        discussion = "\n".join(
            f"{turn.get('name')}：{turn.get('body')}" for turn in discussion_turns
        )
        system = (
            "你是 XCAGI 群聊工作流调度器。请根据任务、候选员工和讨论，"
            "先判断工作量，再选择最少但足够的执行员工。简单任务只能选 1 人；"
            "中等任务优先 1 人、最多 2 人；大任务才多人并行，且不能让多人做同一件事。"
            "只输出 JSON，不要输出 Markdown。"
        )
        user_content = (
            f"【群】{group.get('name')}\n"
            f"【任务】{task}\n"
            f"【候选员工】\n{candidate_lines}\n"
            f"【讨论】\n{discussion or '无'}\n\n"
            '输出格式：{"difficulty":"simple|medium|large","target_employee_ids":["..."],"rationale":"一句话说明任务难度、为什么派这些人"}'
        )
        difficulty = self._dispatch_difficulty(task)
        try:
            res = await asyncio.wait_for(
                self._completion_fn(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ]
                ),
                timeout=SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
            )
            content = str(res.get("content") or "") if isinstance(res, dict) else ""
            target_ids, rationale = self._parse_routing_json(content, candidates)
            if target_ids:
                by_id = {str(m.get("employee_id") or ""): m for m in candidates}
                selected = [by_id[eid] for eid in target_ids if eid in by_id]
                if difficulty == "simple":
                    selected = selected[:1]
                if selected:
                    return selected[:MAX_RESPONDERS], rationale or "按讨论结论分流执行。"
        except Exception:  # noqa: BLE001 - 调度 LLM 不可用时走确定性兜底
            pass
        selected = self._heuristic_dispatch_targets(candidates, task)
        names = "、".join(str(m.get("name") or m.get("employee_id") or "") for m in selected)
        difficulty_label = {"simple": "简单任务", "medium": "中等任务", "large": "大任务"}.get(difficulty, "任务")
        return selected, f"{difficulty_label}，按工作量和成员职责分工给：{names or '无'}。"

    @staticmethod
    def _parse_routing_json(
        content: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[str], str]:
        text = (content or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return [], ""
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return [], ""
        valid_ids = {str(m.get("employee_id") or "") for m in candidates}
        raw_ids = data.get("target_employee_ids")
        if not isinstance(raw_ids, list):
            raw_ids = data.get("targets")
        target_ids = [
            str(item).strip()
            for item in (raw_ids if isinstance(raw_ids, list) else [])
            if str(item).strip() in valid_ids
        ]
        rationale = str(data.get("rationale") or data.get("reason") or "").strip()
        return target_ids[:MAX_RESPONDERS], rationale[:500]

    @staticmethod
    def _heuristic_dispatch_targets(
        candidates: list[dict[str, Any]],
        task: str,
    ) -> list[dict[str, Any]]:
        by_id = {str(m.get("employee_id") or ""): m for m in candidates}
        text = (task or "").lower()
        if AiGroupChatService._dispatch_difficulty(task) == "simple":
            preferred = AiGroupChatService._preferred_single_dispatch_target(candidates, task)
            return [preferred] if preferred else []
        wanted: list[str] = []
        if any(k in text for k in ("android", "移动端", "手机", "compose", "kotlin", "页面", "输入框", "样式", "ui", "ux", "体验", "头像", "语音")):
            wanted.append("cursor-super-employee")
        if any(k in text for k in ("后端", "接口", "api", "pytest", "测试", "覆盖", "服务", "python", "修复", "实现")):
            wanted.append("codex-super-employee")
        if any(k in text for k in ("架构", "方案", "评审", "验收", "acceptance", "summary", "汇总", "规划", "路由", "分流", "链路")):
            wanted.append("claude-super-employee")
        selected = [by_id[eid] for eid in wanted if eid in by_id]
        if selected:
            return selected[:MAX_RESPONDERS]
        preferred = AiGroupChatService._preferred_single_dispatch_target(candidates, task)
        return [preferred] if preferred else []

    @staticmethod
    def _dispatch_difficulty(task: str) -> str:
        text = (task or "").lower()
        simple_markers = ("简单", "小bug", "小 bug", "复制", "删除", "长按", "样式", "文案", "小问题")
        large_markers = (
            "全链路",
            "整套",
            "架构",
            "重构",
            "多端",
            "大规模",
            "全部",
            "多个模块",
            "一起工作",
            "并行",
        )
        if any(k in text for k in large_markers):
            return "large"
        if any(k in text for k in simple_markers) or len(text) <= 90:
            return "simple"
        return "medium"

    @staticmethod
    def _preferred_single_dispatch_target(
        candidates: list[dict[str, Any]],
        task: str,
    ) -> dict[str, Any] | None:
        if not candidates:
            return None
        by_id = {str(m.get("employee_id") or ""): m for m in candidates}
        text = (task or "").lower()
        dev_markers = (
            "后端",
            "接口",
            "api",
            "pytest",
            "测试",
            "test",
            "tests",
            "changed files",
            "命令",
            "服务",
            "python",
            "代码",
            "修复",
            "实现",
            "开发",
            "添加",
            "新增",
            "更新",
            "合并",
        )
        review_markers = ("架构", "方案", "评审", "验收", "规划", "路由", "分流")
        ui_markers = (
            "android",
            "移动端",
            "手机",
            "compose",
            "kotlin",
            "页面",
            "样式",
            "ui",
            "ux",
            "体验",
        )
        has_dev_work = any(k in text for k in dev_markers)
        if any(k in text for k in review_markers) and not has_dev_work:
            priority = ["claude-super-employee", _DEFAULT_SINGLE_CLI_EMPLOYEE_ID, "cursor-super-employee"]
        elif any(k in text for k in ui_markers) and not has_dev_work:
            priority = ["cursor-super-employee", _DEFAULT_SINGLE_CLI_EMPLOYEE_ID, "claude-super-employee"]
        else:
            priority = [_DEFAULT_SINGLE_CLI_EMPLOYEE_ID, "cursor-super-employee", "claude-super-employee"]
        for employee_id in priority:
            if employee_id in by_id:
                return by_id[employee_id]
        return next(
            (m for m in candidates if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS),
            candidates[0],
        )

    @staticmethod
    def _format_routing_decision_message(target_names: str, rationale: str) -> str:
        if not target_names:
            return f"【小C分工】这单暂时没有找到可执行负责人。\n原因：{rationale or '候选员工为空。'}"
        is_single = "、" not in target_names and "," not in target_names and "，" not in target_names
        intro = "这单先不拆，派一个负责人推进。" if is_single else "我先按职责拆给对应负责人。"
        return (
            f"【小C分工】{intro}\n"
            f"负责人：{target_names}\n"
            f"分工依据：{rationale or '按任务类型和成员能力分流。'}\n"
            "我会等大家回报后给你一条验收结论。"
        )

    def _build_dispatch_assignments(
        self,
        task: str,
        members: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not members:
            return []
        super_members = [
            m for m in members if str(m.get("employee_id") or "") in _SUPER_EMPLOYEE_IDS
        ]
        should_split = len(super_members) >= 2 and len(super_members) == len(members)
        assignments: list[dict[str, Any]] = []
        for member in members:
            assigned = dict(member)
            employee_id = str(member.get("employee_id") or "")
            if should_split:
                focus = self._super_employee_focus(employee_id, task)
                assigned["assignment_focus"] = focus
                assigned["assigned_task"] = self._format_assigned_task(
                    original_task=task,
                    employee_id=employee_id,
                    focus=focus,
                )
            else:
                assigned["assignment_focus"] = "主负责人"
                assigned["assigned_task"] = task
            assignments.append(assigned)
        return assignments

    @staticmethod
    def _super_employee_focus(employee_id: str, task: str) -> str:
        text = (task or "").lower()
        if employee_id == "cursor-super-employee":
            return "移动端体验、前端交互和可见 UI 验证"
        if employee_id == "codex-super-employee":
            return "服务端链路、数据状态、接口和自动化测试证据"
        if employee_id == "claude-super-employee":
            return "方案拆解、风险评审、验收标准和最终收口"
        if "测试" in text or "验收" in text:
            return "按岗位职责完成验收相关部分"
        return "按岗位职责处理"

    @staticmethod
    def _format_assigned_task(*, original_task: str, employee_id: str, focus: str) -> str:
        boundary = {
            "cursor-super-employee": "只负责移动端/前端体验相关判断，不重复做后端日志核查。",
            "codex-super-employee": "只负责服务端/接口/测试证据，不重复做 UI 体验评价。",
            "claude-super-employee": "只负责验收口径、风险和团队收口，不重复实现或跑同一套检查。",
        }.get(employee_id, "只处理自己职责范围内的部分。")
        return (
            f"子任务：{focus}。\n"
            f"原始需求：{original_task}\n"
            f"边界：{boundary}\n"
            "输出要求：只汇报你的职责结论、风险和下一步，不要代替其他成员完成同一部分。"
        )

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
        branch_context: str = "",
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        group_id = str(group.get("id") or "")
        work_order_id = uuid.uuid4().hex
        assignments = self._build_dispatch_assignments(task, members)
        target_names = [str(a.get("name") or a.get("employee_id") or "") for a in assignments]
        work_order_row = self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body=self._format_work_order_message(
                task,
                target_names,
                assignments=assignments,
                branch_context=branch_context,
            ),
            kind="work_order",
            status="assigned" if assignments else "blocked",
            work_order_id=work_order_id,
            payload={
                "task": task,
                "branch_context": branch_context,
                "target_employee_ids": [
                    str(a.get("employee_id") or "") for a in assignments
                ],
                "assignments": [
                    {
                        "employee_id": str(a.get("employee_id") or ""),
                        "employee_name": str(a.get("name") or a.get("employee_id") or ""),
                        "focus": str(a.get("assignment_focus") or ""),
                        "task": str(a.get("assigned_task") or task),
                    }
                    for a in assignments
                ],
            },
        )
        messages: list[dict[str, Any]] = [work_order_row]
        if persist:
            self._append_messages([work_order_row])
        if not assignments:
            return messages, [
                {
                    "work_order_id": work_order_id,
                    "status": "blocked",
                    "task": task,
                    "branch_context": branch_context,
                    "target_employee_ids": [],
                }
            ]

        work_orders: list[dict[str, Any]] = []
        for member in assignments:
            report = await self._execute_employee_work(
                group=group,
                member=member,
                task=task,
                assigned_task=str(member.get("assigned_task") or task),
                assignment_focus=str(member.get("assignment_focus") or ""),
                work_order_id=work_order_id,
                user_id=user_id,
                sender_name=sender_name,
                branch_context=branch_context,
            )
            work_orders.append(report)
            row = self._message_row(
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
            messages.append(row)
            if persist:
                self._append_messages([row])
            progress = self._initial_relay_progress_from_report(
                user_id=user_id,
                group_id=group_id,
                report_row=row,
            )
            if progress is not None:
                messages.append(progress)
                if persist:
                    self._append_messages([progress])
        return messages, work_orders

    def _initial_relay_progress_from_report(
        self,
        *,
        user_id: int,
        group_id: str,
        report_row: dict[str, Any],
    ) -> dict[str, Any] | None:
        task_id = self._report_relay_task_id(report_row)
        if not task_id:
            return None
        status = str(report_row.get("status") or "").strip().lower()
        if status not in {"queued", "accepted", "assigned", "running", "processing", "in_progress"}:
            return None
        payload = report_row.get("payload") if isinstance(report_row.get("payload"), dict) else {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        task = {
            "task_id": task_id,
            "relay_id": str(raw.get("relay_id") or ""),
            "kind": str(raw.get("kind") or ""),
        }
        return self._message_row(
            user_id=user_id,
            group_id=group_id,
            role="ai",
            sender_id=str(report_row.get("sender_id") or ""),
            sender_name=str(report_row.get("sender_name") or "负责人"),
            sender_avatar=str(report_row.get("sender_avatar") or ""),
            body=self._format_relay_progress_message(
                report=report_row,
                task=task,
                status=status,
            ),
            kind="work_progress",
            status=status,
            work_order_id=str(report_row.get("work_order_id") or ""),
            payload={
                "work_order_id": str(report_row.get("work_order_id") or ""),
                "employee_id": str(report_row.get("sender_id") or ""),
                "employee_name": str(report_row.get("sender_name") or ""),
                "status": status,
                "summary": self._relay_progress_summary(status, task_id),
                "raw": task,
            },
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
                and self._completed_report_lacks_required_evidence(assigned_task or task, summary, result)
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
                claude_ok = bool(
                    claude_result.get("success")
                ) and not self._summary_indicates_unfinished(claude_summary) and not claude_missing_evidence
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
        assistant = result.get("assistant_message") if isinstance(result.get("assistant_message"), dict) else {}
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
            "branch_context": str(input_data.get("branch_context") or input_data.get("branch") or ""),
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

        if employee_id == "codex-super-employee":
            return CodexSuperEmployeeService()
        if employee_id == "cursor-super-employee":
            return CursorSuperEmployeeService()
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
        assignment_block = (
            "\n分工：\n" + "\n".join(assignment_lines)
            if assignment_lines
            else ""
        )
        branch_line = f"工作分支：{branch_context}\n" if branch_context else "工作分支：自动隔离分支\n"
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
        existing = next((row for row in rows if str(row.get("kind") or "") == "work_acceptance"), None)
        if existing is not None:
            return self._public_message(existing)
        work_order = next((row for row in rows if str(row.get("kind") or "") == "work_order"), None)
        initial_reports = [
            row
            for row in rows
            if str(row.get("kind") or "") == "work_report"
            and self._report_relay_task_id(row)
        ]
        if not work_order or not initial_reports:
            return None
        expected_task_ids = [self._report_relay_task_id(row) for row in initial_reports]
        final_reports = [
            row for row in rows if str(row.get("kind") or "") == "relay_work_report"
        ]
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
        unfinished = self._summary_indicates_unfinished(summary) or missing_evidence
        success = status in {"completed", "done"} and result.get("ok") is not False and not unfinished
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

    @staticmethod
    def _clean_chat_summary_line(line: str) -> str:
        text = _TEMP_PATH_RE.sub("临时执行工作区", str(line or ""))
        text = _MARKDOWN_LINK_RE.sub(r"\1", text)
        text = _BROKEN_MARKDOWN_LINK_RE.sub(r"\1", text)
        for token in ("**", "__", "`"):
            text = text.replace(token, "")
        return " ".join(text.split()).strip("；，。 ")

    @classmethod
    def _relay_result_risk(
        cls,
        *,
        result: dict[str, Any],
        success: bool,
        task_id: str,
        dispatcher: str,
    ) -> str:
        for value in (result.get("risk"), result.get("error"), result.get("reason")):
            text = cls._stringify_summary(value)
            if text:
                return text[:500]
        if not success:
            text = cls._stringify_summary(result.get("reply"))
            if text:
                return cls._chat_friendly_summary(text, limit=500, include_detail_note=False)
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

    @classmethod
    def _effective_report_status(cls, row: dict[str, Any]) -> str:
        report = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        status = str(row.get("status") or report.get("status") or "").strip().lower()
        summary = cls._stringify_summary(report.get("summary") or row.get("body") or "")
        success = report.get("success")
        task = cls._stringify_summary(report.get("original_task") or report.get("task") or "")
        missing_evidence = cls._completed_report_lacks_required_evidence(
            task,
            summary,
            report.get("raw") if isinstance(report.get("raw"), dict) else report,
        )
        if status in {"completed", "done"} and (
            success is False or cls._summary_indicates_unfinished(summary) or missing_evidence
        ):
            return "failed" if cls._summary_indicates_failed(summary) else "blocked"
        return "completed" if status == "done" else status

    @staticmethod
    def _summary_indicates_unfinished(text: str) -> bool:
        if not text:
            return False
        compact = str(text).replace(" ", "")
        return any(
            marker in text or marker.replace(" ", "") in compact
            for marker in _UNFINISHED_REPORT_MARKERS
        )

    @staticmethod
    def _summary_indicates_failed(text: str) -> bool:
        return any(marker in str(text or "") for marker in _FAILED_REPORT_MARKERS)

    @classmethod
    def _completed_report_lacks_required_evidence(
        cls,
        task: str,
        summary: str,
        raw: Any = None,
    ) -> bool:
        if not cls._task_requires_execution_evidence(task):
            return False
        evidence_text = " ".join(
            part for part in (str(summary or ""), cls._stringify_summary(raw)) if part
        )
        return not cls._has_execution_evidence(evidence_text)

    @staticmethod
    def _task_requires_execution_evidence(task: str) -> bool:
        text = str(task or "").strip().lower()
        if not text:
            return False
        has_dev_marker = any(marker.lower() in text for marker in _DEV_TASK_MARKERS)
        if not has_dev_marker:
            return False
        research_only = any(marker.lower() in text for marker in _PURE_RESEARCH_TASK_MARKERS)
        if research_only and not any(
            marker in text
            for marker in ("修复", "实现", "开发", "添加", "新增", "更新", "测试", "验收", "合并")
        ):
            return False
        return True

    @classmethod
    def _has_execution_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value or cls._summary_indicates_unfinished(value):
            return False
        lower = value.lower()
        if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
            return True
        if _EVIDENCE_FILE_RE.search(value):
            return True
        return False

    @classmethod
    def _summary_is_research_only_without_evidence(cls, text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        if cls._has_execution_evidence(value):
            return False
        return any(marker in value for marker in _RESEARCH_ONLY_REPORT_MARKERS)

    @staticmethod
    def _relay_result_dispatch_value(result: dict[str, Any], key: str) -> str:
        for value in result.values():
            if not isinstance(value, dict):
                continue
            dispatch = value.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get(key) is not None:
                return str(dispatch.get(key) or "")
        return ""

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
        for key in (
            "success",
            "status",
            "message",
            "summary",
            "task_id",
            "run_id",
            "error",
            "dispatch_request_id",
            "dispatcher",
            "relay_id",
        ):
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
            # 阻塞的 CLI 子进程调用放到工作线程跑，避免冻住事件循环、
            # 导致同一服务上其它群聊/接口在本次「思考」期间全部卡住。
            result = await asyncio.to_thread(
                service.invoke,
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
                    "members": _with_required_group_members(members_by_dept.get(key, [])),
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
            "name": self._canonical_group_name(group),
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
        kind = str(row.get("kind") or "")
        body = str(row.get("body") or "")
        if kind in {"work_report", "work_progress", "relay_work_report", "work_acceptance"}:
            body = self._clean_public_chat_body(body)
            if kind == "work_acceptance":
                body = self._compact_public_acceptance_body(body)
            body = self._cap_public_chat_body(
                body,
                limit=PUBLIC_ACCEPTANCE_BODY_MAX_CHARS
                if kind == "work_acceptance"
                else PUBLIC_CHAT_BODY_MAX_CHARS,
            )
        out: dict[str, Any] = {
            "id": str(row.get("id") or ""),
            "group_id": str(row.get("group_id") or ""),
            "role": str(row.get("role") or "ai"),
            "sender_id": str(row.get("sender_id") or ""),
            "sender_name": str(row.get("sender_name") or ""),
            "sender_avatar": str(row.get("sender_avatar") or ""),
            "body": body,
            "created_at": str(row.get("created_at") or ""),
        }
        for key in ("kind", "status", "work_order_id"):
            if row.get(key):
                out[key] = str(row.get(key) or "")
        payload = row.get("payload")
        if isinstance(payload, dict):
            out["payload"] = payload
        return out

    @staticmethod
    def _cap_public_chat_body(body: str, limit: int = PUBLIC_CHAT_BODY_MAX_CHARS) -> str:
        text = str(body or "").strip()
        if len(text) <= limit:
            return text
        return (
            text[:limit].rstrip()
            + "\n\n（聊天里已折叠长执行输出；完整内容保留在执行端记录。）"
        )

    @classmethod
    def _clean_public_chat_body(cls, body: str) -> str:
        lines = []
        for raw_line in str(body or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
            line = _TEMP_PATH_RE.sub("临时执行工作区", raw_line)
            line = _MARKDOWN_LINK_RE.sub(r"\1", line)
            line = _BROKEN_MARKDOWN_LINK_RE.sub(r"\1", line)
            line = _RELAY_TASK_ID_RE.sub("。", line)
            for token in ("**", "__", "`"):
                line = line.replace(token, "")
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    @classmethod
    def _compact_public_acceptance_body(cls, body: str) -> str:
        lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
        if not lines:
            return ""
        title = next((line for line in lines if line.startswith("【小C验收】")), "【小C验收】这单已收口")
        conclusion = next((line for line in lines if line.startswith("结论：")), "")
        task = next((line for line in lines if line.startswith("任务：")), "")
        risk = next((line for line in lines if line.startswith("风险：")), "")
        member_lines = [line for line in lines if line.startswith("- ")][:4]
        compact_members = [
            f"- {cls._chat_friendly_summary(line, limit=70, include_detail_note=False)}"
            for line in member_lines
        ]
        out = [title]
        if conclusion:
            out.append(conclusion)
        if task:
            out.append(cls._chat_friendly_summary(task, limit=72, include_detail_note=False))
        if compact_members:
            out.append("成员：")
            out.extend(compact_members)
        if risk:
            out.append(risk)
        out.append("下一步：满意就继续派下一步；不满意就直接说要谁补什么。")
        return "\n".join(out)

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

    def _rewrite_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("w", encoding="utf-8") as fh:
            for m in messages:
                fh.write(_safe_json_line(m))

    def _resolve_group_id(self, *, user_id: int, group_id: str) -> str:
        raw = str(group_id or "").strip()
        if not raw:
            return raw
        group = self._find(self._user_groups(user_id), raw)
        alias = str((group or {}).get("alias_group_id") or "").strip()
        if not alias:
            return raw
        target = self._find(self._user_groups(user_id), alias)
        return alias if target is not None else raw

    @staticmethod
    def _find(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
        return next((g for g in groups if str(g.get("id")) == str(group_id)), None)

    @staticmethod
    def _replace(groups: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
        return [updated if str(g.get("id")) == str(updated.get("id")) else g for g in groups]


__all__ = ["AiGroupChatService", "MAX_RESPONDERS"]
