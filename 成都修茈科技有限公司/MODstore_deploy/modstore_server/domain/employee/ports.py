"""Employee domain ports."""

from __future__ import annotations

from typing import Any, Protocol

from modstore_server.domain.employee.types import EmployeeExecution, EmployeePack


class EmployeeRepository(Protocol):
    """Persistence for employee packs and metadata."""

    def save_pack(self, pack: EmployeePack) -> None: ...

    def get_pack(self, pack_id: str) -> EmployeePack | None: ...


class EmployeeMetricsRepository(Protocol):
    """Execution metrics / audit trail."""

    def record_execution(self, execution: EmployeeExecution) -> None: ...

    def list_recent(self, employee_id: str, *, limit: int = 20) -> list[dict[str, Any]]: ...


__all__ = ["EmployeeRepository", "EmployeeMetricsRepository"]
