"""Employee execution with bounded retry and tenant-scoped ledger completion."""

import time
from dataclasses import dataclass
from typing import Protocol

from app.application.admin_control.protocols import JsonObject
from app.domain.task_lifecycle.control import failure_retries, jittered_delay


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
        attempts: int = 1,
        error_code: str = "",
    ) -> None: ...


class EmployeeRunner:
    def __init__(self, backend: EmployeeBackend) -> None:
        self._backend = backend

    def run(self, work: EmployeeWork) -> JsonObject:
        run_id = self._backend.start(work)
        work.payload["run_id"] = run_id
        attempts = 1
        while True:
            # Unknown and approval results are not retried. A retryable failure
            # runs again on this same run, up to three attempts.
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
            error_code = _retryable_code(error) if status == "failed" else ""
            if failure_retries(attempts, error_code):
                time.sleep(jittered_delay(attempts, jitter_ratio=0.2, rng=_rng()))
                attempts += 1
                continue
            break
        self._backend.finish(
            run_id,
            tenant_id=work.tenant_id,
            status=status,
            output=result,
            error=error,
            verified=success,
            attempts=attempts,
            error_code=error_code,
        )
        response: JsonObject = {
            "success": success,
            "source": "local",
            "run_id": run_id,
            "attempts": attempts,
            "data": result,
        }
        if not success:
            response["message"] = error
        return response


def _retryable_code(error: str) -> str:
    lowered = error.lower()
    if "timeout" in lowered or "超时" in error:
        return "timeout"
    if "rate" in lowered:
        return "rate_limited"
    if "unavailable" in lowered or "不可用" in error:
        return "upstream_unavailable"
    return ""


def _rng():
    import random

    return random.Random()
