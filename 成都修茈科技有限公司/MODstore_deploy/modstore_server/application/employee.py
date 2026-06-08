"""Employee application boundary — orchestration over runtime port + domain events."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional

from modstore_server.domain.employee.ports import EmployeeRepository
from modstore_server.eventing.bus import NeuroBus
from modstore_server.eventing.contracts import (
    EMPLOYEE_EXECUTION_COMPLETED,
    EMPLOYEE_PACK_REGISTERED,
)
from modstore_server.eventing.events import new_event
from modstore_server.eventing.global_bus import neuro_bus as default_neuro_bus
from modstore_server.services.employee import EmployeeRuntimeClient, get_default_employee_client


class EmployeeApplicationService:
    def __init__(
        self,
        *,
        runtime: Optional[EmployeeRuntimeClient] = None,
        repository: Optional[EmployeeRepository] = None,
        bus: Optional[NeuroBus] = None,
    ):
        self._runtime = runtime or get_default_employee_client()
        self._repository = repository
        self._bus = bus or default_neuro_bus

    def list_available(self) -> list[dict[str, Any]]:
        return self._runtime.list_employees()

    def status(self, employee_id: str) -> dict[str, Any]:
        return self._runtime.get_employee_status(employee_id)

    def execute(
        self,
        employee_id: str,
        task: str,
        payload: dict[str, Any] | None = None,
        *,
        user_id: int = 0,
    ) -> dict[str, Any]:
        data = payload or {}
        try:
            out = self._runtime.execute_task(
                employee_id=employee_id,
                task=task,
                input_data=data,
                user_id=user_id,
            )
            self._bus.publish(
                new_event(
                    EMPLOYEE_EXECUTION_COMPLETED,
                    producer="employee",
                    subject_id=employee_id,
                    payload={
                        "employee_id": employee_id,
                        "user_id": user_id,
                        "task": task,
                        "status": "success",
                    },
                    idempotency_key=f"{EMPLOYEE_EXECUTION_COMPLETED}:{employee_id}:{user_id}:{task}:ok:{time.time_ns()}",
                )
            )
            return out
        except Exception:
            self._bus.publish(
                new_event(
                    EMPLOYEE_EXECUTION_COMPLETED,
                    producer="employee",
                    subject_id=employee_id,
                    payload={
                        "employee_id": employee_id,
                        "user_id": user_id,
                        "task": task,
                        "status": "failure",
                    },
                    idempotency_key=f"{EMPLOYEE_EXECUTION_COMPLETED}:{employee_id}:{user_id}:{task}:fail:{time.time_ns()}",
                )
            )
            raise

    def register_pack(self, *, author_id: int, mod_id: str, pack_id: str, version: str) -> None:
        _ = self._repository
        self._bus.publish(
            new_event(
                EMPLOYEE_PACK_REGISTERED,
                producer="employee",
                subject_id=pack_id,
                payload={
                    "pack_id": pack_id,
                    "author_id": author_id,
                    "mod_id": mod_id,
                    "version": version,
                },
                idempotency_key=f"{EMPLOYEE_PACK_REGISTERED}:{pack_id}:{version}",
            )
        )


_EMP_APP_LOCK = Lock()
_default_employee_application: EmployeeApplicationService | None = None


def get_default_employee_application_service() -> EmployeeApplicationService:
    global _default_employee_application
    with _EMP_APP_LOCK:
        if _default_employee_application is None:
            _default_employee_application = EmployeeApplicationService()
        return _default_employee_application


def set_default_employee_application_service(svc: EmployeeApplicationService | None) -> None:
    global _default_employee_application
    with _EMP_APP_LOCK:
        _default_employee_application = svc


__all__ = [
    "EmployeeApplicationService",
    "get_default_employee_application_service",
    "set_default_employee_application_service",
]
