"""Canonical employee identity and deadline adapters, bound at invocation time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import JsonObject

from .employee_run import EmployeeWork

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.db.models.user import User


@dataclass(frozen=True)
class EmployeePrincipal:
    session_id: str
    user: User
    metadata: JsonObject


def employee_identity(request: Request) -> EmployeePrincipal | JSONResponse:
    from app.application.session_account_meta import enrich_session_meta_with_tenant
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.infrastructure.auth.dependencies import resolve_session_user

    sid = _session_id_from_request(request)
    user = resolve_session_user(request) if sid else None
    if user is None:
        return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    return EmployeePrincipal(sid, user, enrich_session_meta_with_tenant(sid, user))


def trusted_tenant(metadata: JsonObject) -> int | None:
    tenant = metadata.get("tenant_id")
    return (
        tenant if isinstance(tenant, int) and not isinstance(tenant, bool) and tenant > 0 else None
    )


class CanonicalEmployeeBackend:
    def start(self, work: EmployeeWork) -> int:
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        return create_employee_run_log(
            employee_id=work.employee_id,
            input_payload={"task": work.task, **work.payload},
            tenant_id=work.tenant_id,
            session_id=work.session_id,
            user_id=work.user_id or None,
        )

    def execute(self, work: EmployeeWork, run_id: int) -> JsonObject:
        from app.application.agent_orchestrator.run_models import AgentStep
        from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline
        from app.application.agent_orchestrator.tool_spec import (
            DEFAULT_TIMEOUT_SECONDS,
            get_tool_action_spec,
        )
        from app.application.employee_runtime.executor import execute_employee_task_local

        class LocalInvocation:
            def execute(self, _step: AgentStep, *, runtime_context: JsonObject) -> JsonObject:
                return execute_employee_task_local(
                    work.employee_id,
                    work.task,
                    work.payload,
                    user_id=work.user_id,
                    workspace_root=work.workspace_root,
                    session_id=work.session_id,
                )

        spec = get_tool_action_spec("employee", "execute")
        return execute_with_tool_deadline(
            LocalInvocation(),
            AgentStep(node_id=str(run_id), tool_id="employee", action="execute"),
            runtime_context={
                "tenant_id": work.tenant_id,
                "user_id": work.user_id,
                "session_id": work.session_id,
            },
            timeout_seconds=spec.timeout_seconds if spec else DEFAULT_TIMEOUT_SECONDS,
        )

    def verify(self, employee_id: str, result: JsonObject) -> tuple[bool, str]:
        from app.application.employee_runtime.result_verifier import verify_employee_run_result

        return verify_employee_run_result(employee_id, result)

    def requires_reconciliation(self, result: JsonObject) -> bool:
        from app.application.employee_runtime.result_verifier import (
            execution_result_requires_reconciliation,
        )

        return execution_result_requires_reconciliation(result)

    def awaits_approval(self, result: JsonObject) -> bool:
        from app.application.employee_runtime.result_verifier import (
            execution_result_awaits_approval,
        )

        return execution_result_awaits_approval(result)

    def finish(
        self,
        run_id: int,
        *,
        tenant_id: int,
        status: str,
        output: JsonObject,
        error: str,
        verified: bool,
    ) -> None:
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        # Preserve the success call shape for legacy adapters and patch consumers.
        failure = {} if verified else {"error": error}
        finish_employee_run_log(
            run_id,
            tenant_id=tenant_id,
            status=status,
            output=output,
            attempts=1,
            verified=verified,
            **failure,
        )
