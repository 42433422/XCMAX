"""Workflow application boundary — composition over engine + cross-domain clients."""

from __future__ import annotations

from typing import Any, Optional

from modstore_server.eventing.bus import NeuroBus
from modstore_server.eventing.global_bus import neuro_bus as default_neuro_bus
from modstore_server.services.employee import EmployeeRuntimeClient, get_default_employee_client
from modstore_server.services.llm import LlmChatClient, get_default_llm_client
from modstore_server.services.workflow import WorkflowEngineClient, get_default_workflow_client


class WorkflowApplicationService:
    """Thin orchestration façade; sandbox side-effects live in ``workflow_engine``."""

    def __init__(
        self,
        *,
        workflow_client: Optional[WorkflowEngineClient] = None,
        employee_client: Optional[EmployeeRuntimeClient] = None,
        llm_client: Optional[LlmChatClient] = None,
        bus: Optional[NeuroBus] = None,
    ):
        self._workflow = workflow_client or get_default_workflow_client()
        self._employees = employee_client or get_default_employee_client()
        self._llm = llm_client or get_default_llm_client()
        self._bus = bus or default_neuro_bus

    @property
    def workflow_client(self) -> WorkflowEngineClient:
        return self._workflow

    @property
    def employee_client(self) -> EmployeeRuntimeClient:
        return self._employees

    @property
    def llm_client(self) -> LlmChatClient:
        return self._llm

    @property
    def bus(self) -> NeuroBus:
        return self._bus

    def run_sandbox(
        self,
        workflow_id: int,
        input_data: dict[str, Any],
        *,
        mock_employees: bool = True,
        validate_only: bool = False,
        user_id: int = 0,
    ) -> dict[str, Any]:
        return self._workflow.run_sandbox(
            workflow_id=workflow_id,
            input_data=input_data,
            mock_employees=mock_employees,
            validate_only=validate_only,
            user_id=user_id,
        )
