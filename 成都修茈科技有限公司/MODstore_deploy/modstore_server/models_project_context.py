"""项目级 / 员工级 持久上下文备忘（cross-task context memo）。

为什么单独一个文件：
    - 模型表通过 ``Base.metadata.create_all`` 注册即可，无需 Alembic 迁移；
      把它独立放是为了让 ``employee_executor`` 可以 lazy-import 而不被
      ``models.py`` 的循环引用拖累。
    - 写入是 best-effort（出错降级为内存 dict），保证不卡住主流程。

模型概念：
    - ``scope``：'project' / 'employee' / 'global'
    - ``scope_key``：项目 root（绝对路径或仓库 URL hash）/ employee_id / 'global'
    - ``key``：自由命名（如 'last_outcome' / 'open_followups' / 'risky_paths'）
    - ``value_json``：JSON
    - ``updated_at``：自动维护
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from modstore_server.models import Base, get_session_factory

logger = logging.getLogger(__name__)


class ProjectContextMemo(Base):
    """跨任务持久上下文（项目级 / 员工级 / 全局）。"""

    __tablename__ = "project_context_memos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(32), nullable=False, index=True, default="project")
    scope_key = Column(String(512), nullable=False, default="", index=True)
    key = Column(String(128), nullable=False, default="")
    value_json = Column(Text, default="{}")
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("scope", "scope_key", "key", name="uq_pctx_scope_key"),
        Index("ix_pctx_scope_key_updated", "scope", "scope_key", "updated_at"),
    )


# ─── helpers ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_loads(raw: str, default: Any = None) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return default if default is not None else {}


def _ensure_context_table(session: Any) -> None:
    try:
        ProjectContextMemo.__table__.create(bind=session.get_bind(), checkfirst=True)
    except Exception:
        logger.debug("project_context_memos ensure table failed", exc_info=True)


def upsert_memo(
    *,
    scope: str,
    scope_key: str,
    key: str,
    value: Any,
    merge: bool = False,
) -> Dict[str, Any]:
    """写入 / 覆盖 / 合并一条备忘。

    - ``merge=True`` 且 value 为 dict：与现有值做浅合并。
    - 写入失败不抛异常，返回 ``{"ok": False, ...}``。
    """
    try:
        sf = get_session_factory()
        with sf() as session:
            _ensure_context_table(session)
            row = (
                session.query(ProjectContextMemo)
                .filter_by(scope=scope, scope_key=scope_key, key=key)
                .first()
            )
            new_payload = value
            if merge and row and isinstance(value, dict):
                old = _safe_loads(row.value_json, {})
                if isinstance(old, dict):
                    old.update(value)
                    new_payload = old
            blob = json.dumps(new_payload, ensure_ascii=False, default=str)[:200_000]
            if row:
                row.value_json = blob
                row.updated_at = datetime.now(timezone.utc)
            else:
                row = ProjectContextMemo(
                    scope=scope,
                    scope_key=scope_key,
                    key=key,
                    value_json=blob,
                )
                session.add(row)
            session.commit()
            return {"ok": True, "id": int(row.id)}
    except Exception as exc:
        logger.warning("project_context_memo upsert failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def get_memos(
    *,
    scope: str,
    scope_key: str,
    keys: Optional[List[str]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """读取一组备忘，返回 ``{key: value}``。"""
    try:
        sf = get_session_factory()
        with sf() as session:
            _ensure_context_table(session)
            q = session.query(ProjectContextMemo).filter(
                ProjectContextMemo.scope == scope,
                ProjectContextMemo.scope_key == scope_key,
            )
            if keys:
                q = q.filter(ProjectContextMemo.key.in_(list(keys)))
            rows = (
                q.order_by(ProjectContextMemo.updated_at.desc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
            out: Dict[str, Any] = {}
            for r in rows:
                out[r.key] = _safe_loads(r.value_json, {})
            return out
    except Exception as exc:
        logger.warning("project_context_memo get failed: %s", exc)
        return {}


def append_event(
    *,
    scope: str,
    scope_key: str,
    key: str,
    event: Dict[str, Any],
    max_keep: int = 50,
) -> Dict[str, Any]:
    """把 event 追加到列表型备忘的尾部，保留最近 max_keep 条。"""
    try:
        sf = get_session_factory()
        with sf() as session:
            _ensure_context_table(session)
            row = (
                session.query(ProjectContextMemo)
                .filter_by(scope=scope, scope_key=scope_key, key=key)
                .first()
            )
            now = _now_iso()
            evt = dict(event)
            evt.setdefault("at", now)
            if row:
                arr = _safe_loads(row.value_json, [])
                if not isinstance(arr, list):
                    arr = []
                arr.append(evt)
                if len(arr) > max_keep:
                    arr = arr[-max_keep:]
                row.value_json = json.dumps(arr, ensure_ascii=False, default=str)[:300_000]
                row.updated_at = datetime.now(timezone.utc)
            else:
                row = ProjectContextMemo(
                    scope=scope,
                    scope_key=scope_key,
                    key=key,
                    value_json=json.dumps([evt], ensure_ascii=False, default=str),
                )
                session.add(row)
            session.commit()
            return {"ok": True, "id": int(row.id)}
    except Exception as exc:
        logger.warning("project_context_memo append failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ─── helpers tailored to employee_executor ──────────────────────────────────


def _project_key_from_input(input_data: Dict[str, Any]) -> str:
    """尝试从 input_data 推导项目 key：优先 project_root，其次 repo / workspace。"""
    if not isinstance(input_data, dict):
        return ""
    for k in ("project_root", "workspace_root", "repo", "repo_url", "project_id"):
        v = input_data.get(k)
        if v:
            return str(v)[:512]
    return ""


def _list_from_value(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _load_previous_loop_memory(input_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(input_data, dict):
        return {}
    for key in (
        "previous_loop_memory",
        "self_maintenance_loop_memory",
        "loop_memory",
        "loop_memory_json",
    ):
        raw = input_data.get(key)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            parsed = _safe_loads(raw, {})
            if isinstance(parsed, dict):
                return parsed
    return {}


def _resolved_run_ids(input_data: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(input_data, dict):
        return []
    raw = input_data.get("resolved_run_ids") or input_data.get("closed_run_ids")
    return [str(item) for item in _list_from_value(raw) if str(item or "").strip()]


def _dedupe_followups(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("source_run_id") or ""),
            str(item.get("step") or ""),
            str(item.get("kind") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _followups_from_loop_memory(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(memory, dict):
        return []
    followups: List[Dict[str, Any]] = []
    open_items = memory.get("open_items")
    if isinstance(open_items, list):
        for item in open_items:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id") or item.get("source_run_id") or "").strip()
            kind = str(item.get("kind") or "loop_open_item")
            steps = _list_from_value(item.get("steps"))
            if not steps:
                steps = [item.get("step") or kind]
            for step in steps:
                step_name = str(step or kind).strip()
                if not run_id or not step_name:
                    continue
                followups.append(
                    {
                        "created_at": _now_iso(),
                        "kind": kind,
                        "reason": item.get("reason"),
                        "source": "previous_loop_memory.open_items",
                        "source_run_id": run_id,
                        "status": "open",
                        "step": step_name,
                    }
                )
    recent_runs = memory.get("recent_runs")
    if isinstance(recent_runs, list):
        for run in recent_runs:
            if not isinstance(run, dict):
                continue
            if str(run.get("status") or "") not in {"failed", "abandoned_stale"}:
                continue
            run_id = str(run.get("run_id") or "").strip()
            if not run_id:
                continue
            followups.append(
                {
                    "branch": run.get("branch"),
                    "created_at": _now_iso(),
                    "kind": "failed_run",
                    "reason": run.get("action") or "failed",
                    "source": "previous_loop_memory.recent_runs",
                    "source_run_id": run_id,
                    "status": "open",
                    "step": "run",
                }
            )
    return _dedupe_followups(followups)


def _update_self_maintenance_followups(
    *,
    employee_id: str,
    input_data: Optional[Dict[str, Any]],
    status: str,
) -> None:
    memory = _load_previous_loop_memory(input_data)
    resolved = set(_resolved_run_ids(input_data))
    if not memory and not resolved:
        return

    scope_key = str(employee_id or "")[:128]
    current = get_memos(
        scope="employee",
        scope_key=scope_key,
        keys=["open_followups", "closed_followups"],
    )
    open_followups = current.get("open_followups")
    if not isinstance(open_followups, list):
        open_followups = []
    closed_followups = current.get("closed_followups")
    if not isinstance(closed_followups, list):
        closed_followups = []

    incoming = _followups_from_loop_memory(memory)
    combined_open = _dedupe_followups([*open_followups, *incoming])
    remaining_open: List[Dict[str, Any]] = []
    newly_closed: List[Dict[str, Any]] = []

    for item in combined_open:
        source_run_id = str(item.get("source_run_id") or "")
        if source_run_id and source_run_id in resolved:
            closed = dict(item)
            closed["closed_at"] = _now_iso()
            closed["closed_by_status"] = status
            closed["status"] = "closed"
            newly_closed.append(closed)
            continue
        remaining_open.append(item)

    closed_followups = _dedupe_followups([*closed_followups, *newly_closed])[-100:]
    remaining_open = _dedupe_followups(remaining_open)[-100:]
    next_focus: Dict[str, Any]
    if remaining_open:
        next_focus = {
            "status": "open",
            "item": remaining_open[0],
            "open_count": len(remaining_open),
        }
    else:
        next_focus = {"status": "clear", "open_count": 0}

    upsert_memo(
        scope="employee",
        scope_key=scope_key,
        key="open_followups",
        value=remaining_open,
    )
    upsert_memo(
        scope="employee",
        scope_key=scope_key,
        key="closed_followups",
        value=closed_followups,
    )
    upsert_memo(
        scope="employee",
        scope_key=scope_key,
        key="next_self_maintenance_focus",
        value=next_focus,
    )


def gather_for_employee(
    *,
    employee_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    employee_max: int = 8,
    project_max: int = 8,
) -> Dict[str, Any]:
    """供 employee_executor._memory_real 调用，组合多 scope 上下文。

    返回结构：
        {
          "employee": {key: value, ...},
          "project":  {key: value, ...},
          "global":   {key: value, ...}
        }
    """
    out = {"employee": {}, "project": {}, "global": {}}
    try:
        out["employee"] = get_memos(
            scope="employee",
            scope_key=str(employee_id or "")[:128],
            limit=employee_max,
        )
        proj_key = _project_key_from_input(input_data or {})
        if proj_key:
            out["project"] = get_memos(scope="project", scope_key=proj_key, limit=project_max)
        out["global"] = get_memos(scope="global", scope_key="global", limit=4)
    except Exception:
        logger.debug("gather_for_employee failed", exc_info=True)
    return out


def record_execution_outcome(
    *,
    employee_id: str,
    task: str,
    input_data: Optional[Dict[str, Any]],
    outcome: Dict[str, Any],
    status: str,
) -> None:
    """每次员工执行完毕后写一条 'last_outcome' 备忘 + 追加到 'recent_runs' 列表。

    best-effort：失败仅 debug。
    """
    try:
        ts = _now_iso()
        emp_payload = {
            "task": (task or "")[:200],
            "status": status,
            "at": ts,
            "summary": (outcome or {}).get("summary") if isinstance(outcome, dict) else None,
        }
        upsert_memo(
            scope="employee",
            scope_key=str(employee_id or "")[:128],
            key="last_outcome",
            value=emp_payload,
        )
        append_event(
            scope="employee",
            scope_key=str(employee_id or "")[:128],
            key="recent_runs",
            event=emp_payload,
            max_keep=20,
        )
        proj_key = _project_key_from_input(input_data or {})
        if proj_key:
            upsert_memo(
                scope="project",
                scope_key=proj_key,
                key="last_run_by_employee",
                value={employee_id: emp_payload},
                merge=True,
            )
            append_event(
                scope="project",
                scope_key=proj_key,
                key="task_log",
                event={"employee_id": employee_id, **emp_payload},
                max_keep=50,
            )
        _update_self_maintenance_followups(
            employee_id=employee_id,
            input_data=input_data,
            status=status,
        )
    except Exception:
        logger.debug("record_execution_outcome failed", exc_info=True)


__all__ = [
    "ProjectContextMemo",
    "upsert_memo",
    "get_memos",
    "append_event",
    "gather_for_employee",
    "record_execution_outcome",
]
