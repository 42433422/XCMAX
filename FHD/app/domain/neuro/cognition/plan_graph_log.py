"""PlanGraph 强制落盘——多步任务必须留下计划→执行→修订轨迹。

单步意图可跳过；多步（nodes>=2 或 todo_steps>=2）必须写入 JSONL。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _log_path() -> Path:
    override = (os.environ.get("XCAGI_PLAN_GRAPH_LOG") or "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[4]
        / "resources"
        / "routing_policies"
        / "plan_graphs.jsonl"
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def requires_plan_log(plan: Any) -> bool:
    """多步任务强制落盘。"""
    if plan is None:
        return False
    nodes = getattr(plan, "nodes", None)
    todos = getattr(plan, "todo_steps", None)
    if isinstance(plan, dict):
        nodes = plan.get("nodes")
        todos = plan.get("todo_steps")
    n_nodes = len(nodes or [])
    n_todos = len(todos or [])
    return n_nodes >= 2 or n_todos >= 2


def plan_to_record(
    plan: Any,
    *,
    phase: str,
    trace_id: str | None = None,
    revision_of: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if hasattr(plan, "plan_id"):
        plan_id = str(plan.plan_id or "")
        intent = str(getattr(plan, "intent", "") or "")
        nodes = getattr(plan, "nodes", []) or []
        todos = getattr(plan, "todo_steps", []) or []
        risk = str(getattr(plan, "risk_level", "") or "")
        metadata = dict(getattr(plan, "metadata", {}) or {})
        node_summaries = []
        for node in nodes:
            node_summaries.append(
                {
                    "node_id": str(getattr(node, "node_id", "") or ""),
                    "tool_id": str(getattr(node, "tool_id", "") or ""),
                    "action": str(getattr(node, "action", "") or ""),
                    "depends_on": list(getattr(node, "depends_on", []) or []),
                }
            )
    elif isinstance(plan, dict):
        plan_id = str(plan.get("plan_id") or "")
        intent = str(plan.get("intent") or "")
        nodes = plan.get("nodes") or []
        todos = plan.get("todo_steps") or []
        risk = str(plan.get("risk_level") or "")
        metadata = dict(plan.get("metadata") or {})
        node_summaries = []
        for node in nodes:
            if isinstance(node, dict):
                node_summaries.append(
                    {
                        "node_id": str(node.get("node_id") or ""),
                        "tool_id": str(node.get("tool_id") or ""),
                        "action": str(node.get("action") or ""),
                        "depends_on": list(node.get("depends_on") or []),
                    }
                )
    else:
        plan_id = ""
        intent = ""
        todos = []
        risk = ""
        metadata = {}
        node_summaries = []

    return {
        "ts": _utc_now(),
        "ts_unix": time.time(),
        "phase": phase,  # planned | probed | revised | executed | failed
        "trace_id": trace_id or "",
        "revision_of": revision_of or "",
        "plan_id": plan_id,
        "intent": intent,
        "risk_level": risk,
        "todo_steps": list(todos)[:32],
        "nodes": node_summaries[:64],
        "node_count": len(node_summaries),
        "metadata_keys": sorted(str(k) for k in metadata.keys())[:32],
        "extra": dict(extra or {}),
    }


def append_plan_graph(
    plan: Any,
    *,
    phase: str = "planned",
    trace_id: str | None = None,
    revision_of: str | None = None,
    force: bool = False,
    extra: dict[str, Any] | None = None,
) -> bool:
    """写入 PlanGraph 日志。多步强制；force=True 时单步也写。"""
    if not force and not requires_plan_log(plan):
        return False
    record = plan_to_record(
        plan,
        phase=phase,
        trace_id=trace_id,
        revision_of=revision_of,
        extra=extra,
    )
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except RECOVERABLE_ERRORS:
        logger.debug("append_plan_graph failed", exc_info=True)
        return False
