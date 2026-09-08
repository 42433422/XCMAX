"""Publish due recurring occurrences into the existing approval/task lifecycle."""

import hashlib
import logging
from typing import Any

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.recurrence import next_occurrence, normalize_recurrence
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.schedule_repository import ScheduleRepository
from app.application.agent_orchestrator.task_schedule import normalize_scheduled_at
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.infrastructure.auth.agent_principal import AgentPrincipal, bind_agent_runtime_context
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RecurringScheduleService:
    def __init__(
        self,
        repository: ScheduleRepository | None = None,
        orchestrator: AgentOrchestrator | None = None,
    ):
        self.repository = repository or ScheduleRepository()
        self.orchestrator = orchestrator

    def create(self, data: dict[str, Any], principal: AgentPrincipal) -> dict[str, Any]:
        tool_id, action = str(data.get("tool_id") or ""), str(data.get("action") or "")
        params = data.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
        params = {key: value for key, value in params.items() if key != "_runtime_context"}
        validation = validate_tool_call(tool_id, action, params)
        if not validation.ok:
            raise ValueError(validation.message)
        due = normalize_scheduled_at(data.get("scheduled_at"))
        if not due:
            raise ValueError("必须指定首次执行时间")
        recurrence = normalize_recurrence(data.get("recurrence"))
        context = bind_agent_runtime_context({"source": "recurring_schedule"}, principal)
        return self.repository.create(
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            request_id=str(data.get("task_id") or ""),
            due=due,
            payload={
                "tool_id": tool_id,
                "action": action,
                "params": params,
                "title": str(data.get("title") or f"周期任务 {tool_id}.{action}")[:80],
                "recurrence": recurrence,
                "runtime_context": context,
                "approval_policy": "each_occurrence",
            },
        )

    def tick(self, owner: str, *, now: str | None = None) -> bool:
        current = normalize_scheduled_at(now or utc_now_iso())
        row = self.repository.claim(owner, now=current)
        if row is None:
            return False
        payload = row["payload"]
        try:
            orchestrator = self.orchestrator or AgentOrchestrator()
            # A pending occurrence suppresses catch-up bursts. Do not accumulate
            # unapproved jobs or overlap a long-running business operation.
            last = (
                orchestrator.get_task(
                    user_id=row["user_id"], tenant_id=row["tenant_id"], task_id=row["last_task_id"]
                )
                if row["last_task_id"]
                else None
            )
            task_id = row["last_task_id"]
            if last is None or last.status in {"completed", "failed", "cancelled"}:
                suffix = hashlib.sha256(row["next_run_at"].encode()).hexdigest()[:24]
                task_id = f"schedule-{row['schedule_id']}-{suffix}"
                create_unified_task(
                    orchestrator=orchestrator,
                    user_id=row["user_id"],
                    task_id=task_id,
                    title=payload["title"],
                    message=payload["title"],
                    tool_id=payload["tool_id"],
                    action=payload["action"],
                    params=payload["params"],
                    runtime_context=payload["runtime_context"],
                    scheduled_at=row["next_run_at"],
                )
            following = next_occurrence(payload["recurrence"], row["next_run_at"], current)
            self.repository.finish(
                row["schedule_id"], owner, next_run_at=following, task_id=task_id
            )
        except RECOVERABLE_ERRORS:
            logger.exception("recurring schedule occurrence publication failed: %s", row["schedule_id"])
            self.repository.finish(
                row["schedule_id"],
                owner,
                next_run_at=row["next_run_at"],
                error="occurrence_publication_failed",
            )
        return True
