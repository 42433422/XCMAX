"""读透桥：把 MODstore collab feed 的「员工工作汇报」线程映射成 app 交流圈的只读群 + 消息。

- 真相源在 MODstore（独立服务）。这里每次请求经 ``modstore_local_client`` 实时 HTTP 拉取，
  **不复制进 jsonl**，从而单一真相源、全局可见。
- best-effort：MODstore 不可达时返回空，app 自动降级为纯人对人群聊。
- 头像/名解析由调用方注入 ``profiles``（``employee_id -> {name, avatar}``），避免与路由模块循环导入。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.application.modstore_local_client import modstore_get

logger = logging.getLogger(__name__)

_THREADS_PATH = "/api/admin/employee-autonomy/collab/threads"
_TITLE_PREFIX = "[员工交流圈]"
_DEPT_RE = re.compile(r"dept=([A-Za-z0-9_]+)")

# dept_key -> thread_id 进程内缓存（list_report_groups 时刷新）。
_DEPT_THREAD: dict[str, int] = {}


def _parse_dept(title: str) -> str:
    m = _DEPT_RE.search(title or "")
    return m.group(1) if m else ""


def _report_group_dept(group_id: str) -> str:
    return group_id.split("report:", 1)[-1] if group_id.startswith("report:") else group_id


async def list_report_groups() -> list[dict[str, Any]]:
    """列出 MODstore 上的部门汇报线程，映射成 app 群 DTO（id=``report:<dept>``）。"""
    try:
        data = await modstore_get(_THREADS_PATH, query="limit=200")
    except Exception:  # noqa: BLE001 - 读透 best-effort，MODstore 不可达即降级为空
        logger.warning("employee_report_feed: list threads failed", exc_info=True)
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    groups: list[dict[str, Any]] = []
    for t in items:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "")
        if not title.startswith(_TITLE_PREFIX):
            continue
        dept = _parse_dept(title)
        tid = int(t.get("id") or 0)
        if not dept or tid <= 0:
            continue
        _DEPT_THREAD[dept] = tid
        # "[员工交流圈] P-S 软件部 · dept=prod_software" → 取中段做展示名
        label = title[len(_TITLE_PREFIX) :].split("·", 1)[0].strip() or dept
        groups.append(
            {
                "id": f"report:{dept}",
                "name": f"{label} · 工作汇报",
                "department_key": dept,
                "member_count": 0,
                "members": [],
                "is_pinned": False,
                "is_hidden": False,
                "is_followed": True,
                "unread_count": 0,
                "created_at": str(t.get("created_at") or ""),
                "last_message_preview": "",
                "last_message_at": str(t.get("updated_at") or t.get("created_at") or ""),
                "read_only": True,
            }
        )
    return groups


async def _resolve_thread_id(dept: str) -> int:
    tid = _DEPT_THREAD.get(dept)
    if tid:
        return tid
    await list_report_groups()  # 缓存未命中：刷新一次
    return _DEPT_THREAD.get(dept, 0)


async def get_report_messages(
    *,
    group_id: str,
    limit: int = 100,
    profiles: Optional[dict[str, dict[str, str]]] = None,
) -> list[dict[str, Any]]:
    """读透某汇报群的消息，映射成 app 的 ``_public_message`` DTO（role 恒为 ai）。"""
    dept = _report_group_dept(group_id)
    tid = await _resolve_thread_id(dept)
    if tid <= 0:
        return []
    try:
        data = await modstore_get(f"{_THREADS_PATH}/{tid}/messages", query=f"limit={int(limit)}")
    except Exception:  # noqa: BLE001 - 读透 best-effort，失败降级为空
        logger.warning("employee_report_feed: list messages failed dept=%s", dept, exc_info=True)
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    items = [m for m in items if isinstance(m, dict)]
    items.sort(key=lambda m: int(m.get("id") or 0))  # 旧→新，契合 app 滚动到底
    profiles = profiles or {}
    out: list[dict[str, Any]] = []
    for m in items:
        sender = str(m.get("sender_employee_id") or "")
        prof = profiles.get(sender) or {}
        out.append(
            {
                "id": str(m.get("id") or ""),
                "group_id": f"report:{dept}",
                "role": "ai",
                "sender_id": sender,
                "sender_name": str(prof.get("name") or sender or "员工"),
                "sender_avatar": str(prof.get("avatar") or ""),
                "body": str(m.get("content") or ""),
                "created_at": str(m.get("created_at") or ""),
            }
        )
    return out
