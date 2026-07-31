"""可选 duty graph 执行状态回写（FHD_DUTY_GRAPH_REPORT）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.workflow.types import WorkflowRunResult

logger = logging.getLogger(__name__)

_DEFAULT_REPORT_PATH = Path("data/local_duty_graph_status.jsonl")


def duty_graph_report_enabled() -> bool:
    return os.environ.get("FHD_DUTY_GRAPH_REPORT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _report_path() -> Path:
    custom = os.environ.get("FHD_DUTY_GRAPH_REPORT_PATH", "").strip()
    return Path(custom) if custom else _DEFAULT_REPORT_PATH


def report_employee_orchestration(
    employee_id: str,
    run: WorkflowRunResult,
    *,
    plan_id: str = "",
    parallel_workers: int = 1,
) -> dict[str, Any] | None:
    if not duty_graph_report_enabled():
        return None
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "employee_id": str(employee_id or "").strip(),
        "plan_id": plan_id or getattr(run, "plan_id", ""),
        "success": bool(getattr(run, "success", False)),
        "message": str(getattr(run, "message", "") or ""),
        "parallel_workers": int(parallel_workers or 1),
        "executed_nodes": list(
            ((getattr(run, "final_context", None) or {}).get("workflow_status") or {}).get(
                "executed_nodes"
            )
            or []
        ),
        "node_results": [
            {
                "node_id": nr.node_id,
                "success": nr.success,
                "tool_id": nr.tool_id,
                "error": nr.error,
            }
            for nr in (getattr(run, "node_results", None) or [])
        ],
    }
    path = _report_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("duty graph report append failed", exc_info=True)
        return None
    return record


__all__ = ["duty_graph_report_enabled", "report_employee_orchestration"]
