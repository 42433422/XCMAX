"""Employee domain persistence adapters."""

from __future__ import annotations

from modstore_server.domain.employee.types import EmployeeExecution, EmployeePack


class InMemoryEmployeeRepository:
    def __init__(self) -> None:
        self.packs: dict[str, EmployeePack] = {}

    def save_pack(self, pack: EmployeePack) -> None:
        self.packs[pack.pack_id] = pack

    def get_pack(self, pack_id: str) -> EmployeePack | None:
        return self.packs.get(pack_id)


class InMemoryEmployeeMetricsRepository:
    def __init__(self) -> None:
        self.executions: list[EmployeeExecution] = []

    def record_execution(self, execution: EmployeeExecution) -> None:
        self.executions.append(execution)

    def list_recent(self, employee_id: str, *, limit: int = 20) -> list[dict]:
        return [{"employee_id": employee_id, "n": len(self.executions)}]


__all__ = ["InMemoryEmployeeMetricsRepository", "InMemoryEmployeeRepository"]
