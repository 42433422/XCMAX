"""员工实时 handoff（执行中转交）。

实现思路（避免改动 ``employee_executor`` 内部）：
    1. 员工执行结果（dict）若包含字段 ``handoff`` 或 ``handoff_to``，本模块负责解析。
    2. 解析出的 ``HandoffDirective`` 由 ``employee_orchestrator.dispatch_subtasks``
       在每完成一层后扫描结果列表，把目标员工追加成下一层的 ``SubTask``。
    3. 为防爆栈：每条原始任务的 handoff 链长不超过 ``MAX_HANDOFF_DEPTH``（默认 4），
       且同一员工不会被同一条链路重复 handoff。

设计上保留向前兼容——员工只要在 ``cognition.action`` 输出里写：
    {"handoff_to": "doc-knowledge-curator", "task_brief": "...", "input_data": {...}}
即可触发 handoff，不需要任何上下文中间件。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

MAX_HANDOFF_DEPTH = max(1, int(os.environ.get("MODSTORE_HANDOFF_MAX_DEPTH", "4") or "4"))
"""每条原始任务最多链式 handoff N 次（默认 4）。"""


@dataclass
class HandoffDirective:
    to_employee_id: str
    task_brief: str
    input_data: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    priority: int = 5


def _coerce_directive(raw: Any, *, fallback_brief: str = "") -> Optional[HandoffDirective]:
    if not raw:
        return None
    if isinstance(raw, str):
        eid = raw.strip()
        return HandoffDirective(eid, fallback_brief or eid) if eid else None
    if not isinstance(raw, dict):
        return None
    eid = str(
        raw.get("to_employee_id") or raw.get("handoff_to") or raw.get("employee_id") or ""
    ).strip()
    if not eid:
        return None
    brief = str(raw.get("task_brief") or raw.get("task") or fallback_brief or "")[:500]
    input_data = raw.get("input_data") or raw.get("input") or {}
    if not isinstance(input_data, dict):
        input_data = {"_raw": str(input_data)[:1000]}
    reason = str(raw.get("reason") or raw.get("why") or "")[:500]
    try:
        priority = int(raw.get("priority") or 5)
    except Exception:
        priority = 5
    return HandoffDirective(
        to_employee_id=eid,
        task_brief=brief,
        input_data=input_data,
        reason=reason,
        priority=priority,
    )


def extract_handoff_directives(
    execution_outcome: Dict[str, Any],
    *,
    fallback_brief: str = "",
) -> List[HandoffDirective]:
    """从员工执行结果里把 handoff 指令拍平成有效列表。

    可识别的位置（按优先级）：
        - outcome["handoff"]                   单条 dict 或多条 list
        - outcome["handoffs"]                  list
        - outcome["result"]["handoff"]         同上嵌套
        - outcome["result"]["handoffs"]
        - outcome["cognition"]["action"]["handoff"]
    """
    if not isinstance(execution_outcome, dict):
        return []
    candidates: List[Any] = []

    def _scan(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key in ("handoff", "handoffs", "handoff_to"):
            v = node.get(key)
            if v is not None:
                candidates.append(v)

    _scan(execution_outcome)
    # Look one level deep at common nesting points used by employee_executor.
    inner = execution_outcome.get("result")
    _scan(inner)
    cog = (
        (inner or {}).get("cognition")
        if isinstance(inner, dict)
        else execution_outcome.get("cognition")
    )
    if isinstance(cog, dict):
        _scan(cog)
        action = cog.get("action")
        if isinstance(action, dict):
            _scan(action)

    flat: List[HandoffDirective] = []
    for c in candidates:
        if isinstance(c, list):
            for item in c:
                d = _coerce_directive(item, fallback_brief=fallback_brief)
                if d:
                    flat.append(d)
        else:
            d = _coerce_directive(c, fallback_brief=fallback_brief)
            if d:
                flat.append(d)
    return flat


def build_followup_subtasks(
    layer_results: List[Dict[str, Any]],
    *,
    visited: Set[str],
    depth: int,
    fallback_brief: str,
) -> List["Any"]:
    """根据上一层 results 构造下一层 SubTask，本函数返回的是 SubTask 列表。

    返回空列表表示没有 handoff 需要继续。
    被调度器：
        ``employee_orchestrator.dispatch_subtasks`` 用，避免循环 import。
    """
    from modstore_server.task_router import SubTask

    if depth >= MAX_HANDOFF_DEPTH:
        logger.info(
            "handoff: depth limit reached (%s), skipping further handoffs",
            depth,
        )
        return []

    new_subtasks: List[SubTask] = []
    for r in layer_results:
        if not r or not r.get("ok", False):
            continue
        outcome = r.get("result") if isinstance(r.get("result"), dict) else r
        directives = extract_handoff_directives(outcome, fallback_brief=fallback_brief)
        if not directives:
            continue
        from_eid = str(r.get("employee_id") or "")
        for d in directives:
            if not d.to_employee_id or d.to_employee_id in visited:
                logger.info("handoff: skip target=%s (visited or empty)", d.to_employee_id)
                continue
            input_data = dict(d.input_data or {})
            input_data.setdefault("_handoff_chain", []).append(
                {"from": from_eid, "reason": d.reason, "depth": depth}
            )
            input_data.setdefault("upstream_results", {})[from_eid] = r
            new_subtasks.append(
                SubTask(
                    employee_id=d.to_employee_id,
                    task_brief=d.task_brief or fallback_brief,
                    input_data=input_data,
                    depends_on=[],
                    priority=d.priority,
                )
            )
            visited.add(d.to_employee_id)
    return new_subtasks


__all__ = [
    "HandoffDirective",
    "MAX_HANDOFF_DEPTH",
    "extract_handoff_directives",
    "build_followup_subtasks",
]
