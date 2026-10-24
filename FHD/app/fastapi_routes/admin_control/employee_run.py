"""One-attempt employee execution and tenant-scoped ledger completion."""

from dataclasses import dataclass
from typing import Protocol

from .ports import JsonObject


@dataclass(frozen=True)
class EmployeeWork:
    employee_id: str
    task: str
    payload: JsonObject
    user_id: int
    tenant_id: int
    session_id: str
    workspace_root: str | None


class EmployeeBackend(Protocol):
    def start(self, work: EmployeeWork) -> int: ...
    def execute(self, work: EmployeeWork, run_id: int) -> object: ...
    def verify(self, employee_id: str, result: JsonObject) -> tuple[bool, str]: ...
    def requires_reconciliation(self, result: JsonObject) -> bool: ...
    def awaits_approval(self, result: JsonObject) -> bool: ...
    def finish(
        self,
        run_id: int,
        *,
        tenant_id: int,
        status: str,
        output: JsonObject,
        error: str,
        verified: bool,
    ) -> None: ...


class EmployeeRunner:
    def __init__(self, backend: EmployeeBackend) -> None:
        self._backend = backend

    def run(self, work: EmployeeWork) -> JsonObject:
        run_id = self._backend.start(work)
        work.payload["run_id"] = run_id
        # A replay of the whole request can repeat writes. Reconciliation stays on this run.
        raw = self._backend.execute(work, run_id)
        result = (
            raw
            if isinstance(raw, dict)
            else {
                "success": False,
                "error": "invalid employee result",
                "execution_state": "unknown",
                "reconciliation_required": True,
            }
        )
        ok, reason = self._backend.verify(work.employee_id, result)
        success = ok and result.get("success") is not False
        error = (
            ""
            if success
            else reason or str(result.get("message") or result.get("error") or "执行失败")
        )
        status = (
            "success"
            if success
            else "unknown"
            if self._backend.requires_reconciliation(result)
            else "awaiting_approval"
            if self._backend.awaits_approval(result)
            else "failed"
        )
        self._backend.finish(
            run_id,
            tenant_id=work.tenant_id,
            status=status,
            output=result,
            error=error,
            verified=success,
        )
        response: JsonObject = {
            "success": success,
            "source": "local",
            "run_id": run_id,
            "attempts": 1,
            "data": result,
        }
        if not success:
            response["message"] = error
        return response
