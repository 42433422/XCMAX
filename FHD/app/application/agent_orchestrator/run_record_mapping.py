"""Decode persisted Agent records without owning transactions or repository state."""

from __future__ import annotations

import json
import logging

from app.application.agent_orchestrator.run_models import AgentRun, agent_run_from_dict
from app.application.agent_orchestrator.task_models import (
    AgentTask,
    TaskControlCommand,
    agent_task_from_dict,
    task_control_from_dict,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _task_record_to_model(record) -> AgentTask:
    return agent_task_from_dict(
        {
            "task_id": record.task_id,
            "user_id": record.user_id,
            "tenant_id": record.tenant_id,
            "title": record.title,
            "source": record.source,
            "task_type": record.task_type,
            "status": record.status,
            "attention_state": record.attention_state,
            "active_run_id": record.active_run_id,
            "root_run_id": record.root_run_id,
            "conversation_id": record.conversation_id,
            "workspace_id": record.workspace_id,
            "workspace_path": record.workspace_path,
            "workspace_isolation": record.workspace_isolation,
            "attempt": record.attempt,
            "run_count": record.run_count,
            "archived_at": record.archived_at,
            "metadata": json.loads(record.metadata_json or "{}"),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    )


def _command_record_to_model(record) -> TaskControlCommand:
    return task_control_from_dict(
        {
            "command_id": record.command_id,
            "task_id": record.task_id,
            "run_id": record.run_id,
            "action": record.action,
            "status": record.status,
            "requested_by": record.requested_by,
            "metadata": json.loads(record.metadata_json or "{}"),
            "created_at": record.created_at,
            "applied_at": record.applied_at,
        }
    )


def _record_to_run(record) -> AgentRun | None:
    try:
        data = json.loads(record.payload_json or "{}")
        if isinstance(data, dict):
            return agent_run_from_dict(data)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("agent run payload invalid: %s", exc)
    return None
