"""Employee runtime service port.

When the Employee domain is extracted to its own process, the only thing the
rest of the codebase has to swap is the implementation registered via
``set_default_employee_client``. The default in-process implementation lazily
imports ``employee_executor`` so this module stays cheap to import even from
non-Employee callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


class EmployeeRuntimeClient(ABC):
    """Public surface other domains may rely on."""

    @abstractmethod
    def list_employees(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_employee_status(self, employee_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    def execute_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        bench_llm_override: Optional[Tuple[str, str]] = None,
    ) -> Dict[str, Any]: ...


class InProcessEmployeeRuntimeClient(EmployeeRuntimeClient):
    """Wraps the legacy ``employee_executor`` calls so existing behavior is
    preserved while we migrate callers off direct imports."""

    def list_employees(self) -> List[Dict[str, Any]]:
        from modstore_server.employee_executor import list_employees as _list_employees

        return list(_list_employees())

    def get_employee_status(self, employee_id: str) -> Dict[str, Any]:
        from modstore_server.employee_executor import get_employee_status as _status

        return _status(employee_id)

    def execute_task(
        self,
        *,
        employee_id: str,
        task: str,
        input_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        bench_llm_override: Optional[Tuple[str, str]] = None,
    ) -> Dict[str, Any]:
        from modstore_server.employee_executor import execute_employee_task

        return execute_employee_task(
            employee_id, task, input_data or {}, user_id, bench_llm_override=bench_llm_override
        )


_LOCK = Lock()
_default: EmployeeRuntimeClient | None = None


def get_default_employee_client() -> EmployeeRuntimeClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessEmployeeRuntimeClient()
        return _default


def set_default_employee_client(client: Optional[EmployeeRuntimeClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "EmployeeRuntimeClient",
    "InProcessEmployeeRuntimeClient",
    "get_default_employee_client",
    "set_default_employee_client",
]
