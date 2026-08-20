# ruff: noqa: E402, F401
from __future__ import annotations

import copy
import logging
import time
from typing import Any, cast

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import (
    apply_ai_budget_metadata,
    budget_exceeded_payload,
    refresh_ai_budget_metadata,
)
from app.application.agent_orchestrator.repair_advisor import (
    is_llm_repair_enabled,
    llm_repair_attempt_limit,
    request_llm_repair,
)
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    LLMCall,
    RunEvent,
    ToolCall,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    SQLAlchemyAgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.task_background import (
    AgentOrchestratorTaskMixin,
    task_execution_context,
)
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTERNAL_RUN_ERROR = "agent_run_internal_error"


from app.application.agent_orchestrator.orchestrator_agentorchestrator_mixin01 import (
    _AgentOrchestratorPart01Mixin,
)
from app.application.agent_orchestrator.orchestrator_agentorchestrator_mixin02 import (
    _AgentOrchestratorPart02Mixin,
)


class AgentOrchestrator(
    _AgentOrchestratorPart01Mixin, _AgentOrchestratorPart02Mixin, AgentOrchestratorTaskMixin
):
    pass
