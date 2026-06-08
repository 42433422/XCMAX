"""Workflow engine service port.

Future state: HTTP client to a Workflow microservice. Today the default port
just delegates to ``workflow_engine`` so existing behavior is preserved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import Any, Dict, List, Optional


class WorkflowEngineClient(ABC):
    @abstractmethod
    def execute_workflow(
        self,
        *,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]] = None,
        user_id: int = 0,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    def validate_workflow(self, workflow_id: int) -> List[str]: ...

    @abstractmethod
    def run_sandbox(
        self,
        *,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]] = None,
        mock_employees: bool = True,
        validate_only: bool = False,
        user_id: int = 0,
    ) -> Dict[str, Any]: ...


class InProcessWorkflowEngineClient(WorkflowEngineClient):
    def execute_workflow(
        self,
        *,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]] = None,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        from modstore_server.workflow_engine import execute_workflow

        return execute_workflow(workflow_id, input_data or {}, user_id=user_id)

    def validate_workflow(self, workflow_id: int) -> List[str]:
        from modstore_server.workflow_engine import validate_workflow

        return list(validate_workflow(workflow_id))

    def run_sandbox(
        self,
        *,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]] = None,
        mock_employees: bool = True,
        validate_only: bool = False,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        from modstore_server.workflow_engine import run_workflow_sandbox

        return run_workflow_sandbox(
            workflow_id,
            input_data or {},
            mock_employees=mock_employees,
            validate_only=validate_only,
            user_id=user_id,
        )


_LOCK = Lock()
_default: WorkflowEngineClient | None = None


def get_default_workflow_client() -> WorkflowEngineClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessWorkflowEngineClient()
        return _default


def set_default_workflow_client(client: Optional[WorkflowEngineClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "InProcessWorkflowEngineClient",
    "WorkflowEngineClient",
    "get_default_workflow_client",
    "set_default_workflow_client",
]
