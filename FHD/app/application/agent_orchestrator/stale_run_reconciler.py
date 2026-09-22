"""启动对账：收敛被进程中断遗留的 running AgentRun。

后端进程退出（正常退出、崩溃、被强杀）时不会为在途任务补写终态，于是
``agent_runs`` / ``agent_tasks`` 会永久停留在 running，界面显示「进行中」而存储
侧再无任何状态写入（M15）。本模块在启动阶段把超过心跳窗口仍未更新的在途状态收敛为
failed，并同步 ``agent_tasks``，使界面口径与存储口径一致。

边界（不得越权）：
- 只收敛 planning/running/retrying 等在途状态。``queued`` 属于可恢复的持久队列，
  由 ``task_dispatcher`` 的 claim()/重认领负责，启动对账失败它会破坏队列。
- 仍持有**未过期租约**的 run 交给既有租约+重认领机制，启动对账不改写。
- 不在此处「修正」业务结果，也不改动任何权益、审批或安全门禁状态。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.agent_orchestrator.run_models import utc_now_iso
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

INTERRUPTED_ERROR_CODE = "interrupted_by_restart"
INTERRUPTED_MESSAGE = "运行被中断：后端进程在任务结束前退出，已由启动对账标记为失败"
IN_FLIGHT_RUN_STATUSES = ("planning", "running", "retrying")
DEFAULT_STALE_AFTER_SECONDS = 60.0


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except RECOVERABLE_ERRORS:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _stale_cutoff(now: str, stale_after_seconds: float) -> str:
    parsed = _parse_timestamp(now) or datetime.now(UTC)
    window = max(1.0, float(stale_after_seconds))
    return (parsed - timedelta(seconds=window)).isoformat()


def _load_payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except RECOVERABLE_ERRORS:
        return {}
    return data if isinstance(data, dict) else {}


def _task_identity(payload: dict[str, Any], run_id: str) -> tuple[str, str]:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    context = metadata.get("task_context")
    context = context if isinstance(context, dict) else {}
    runtime = metadata.get("runtime_context")
    runtime = runtime if isinstance(runtime, dict) else {}
    return str(context.get("task_id") or run_id), str(runtime.get("tenant_id") or "")


def reconcile_stale_running_runs(
    *,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    now: str | None = None,
) -> int:
    """把启动时仍停留在在途状态的 AgentRun 收敛为 failed，返回收敛条数。"""
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import (
        SQLAlchemyAgentRunRepository,
    )

    repository = get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        return 0

    current = str(now or utc_now_iso())
    cutoff = _stale_cutoff(current, stale_after_seconds)
    reconciled = 0
    with repository.transaction() as db:
        from app.db.models.agent import (
            AgentRunRecord,
            AgentTaskExecutionRecord,
            AgentTaskRecord,
        )

        records = (
            db.query(AgentRunRecord)
            .filter(
                AgentRunRecord.status.in_(IN_FLIGHT_RUN_STATUSES),
                AgentRunRecord.updated_at <= cutoff,
            )
            .all()
        )
        for record in records:
            execution = db.get(AgentTaskExecutionRecord, record.run_id)
            if (
                execution is not None
                and execution.state == "claimed"
                and str(execution.lease_expires_at or "") > current
            ):
                # 租约仍有效：交由既有重认领机制处理，启动对账不越权改写。
                continue
            payload = _load_payload(record.payload_json)
            payload["status"] = "failed"
            payload["error"] = str(payload.get("error") or "") or INTERRUPTED_MESSAGE
            payload["updated_at"] = current
            metadata = payload.get("metadata")
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            metadata["interrupted"] = {
                "error_code": INTERRUPTED_ERROR_CODE,
                "reconciled_at": current,
                "previous_status": str(record.status or ""),
            }
            payload["metadata"] = metadata
            record.status = "failed"
            record.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
            record.updated_at = current
            task_id, tenant_id = _task_identity(payload, record.run_id)
            task_record = (
                db.query(AgentTaskRecord)
                .filter(
                    AgentTaskRecord.tenant_id == tenant_id,
                    AgentTaskRecord.user_id == record.user_id,
                    AgentTaskRecord.task_id == task_id,
                )
                .one_or_none()
            )
            if task_record is not None and str(task_record.status or "") in IN_FLIGHT_RUN_STATUSES:
                task_record.status = "failed"
                task_record.attention_state = "failed"
                task_record.updated_at = current
            reconciled += 1
    if reconciled:
        logger.warning(
            "agent run startup reconciliation: %s interrupted run(s) marked failed (error_code=%s)",
            reconciled,
            INTERRUPTED_ERROR_CODE,
        )
    return reconciled


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "IN_FLIGHT_RUN_STATUSES",
    "INTERRUPTED_ERROR_CODE",
    "INTERRUPTED_MESSAGE",
    "reconcile_stale_running_runs",
]
