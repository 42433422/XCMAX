"""Trusted tenant execution, one-attempt deadline, and run-ledger completion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.application.admin_control.protocols import ErrorPolicy, JsonObject

from .employee_backend import EmployeePrincipal, trusted_tenant
from .employee_run import EmployeeWork


def _request_key(body: dict[str, Any], request: Request) -> str:
    values = [
        body.get("idempotency_key"),
        body.get("turn_id"),
        request.headers.get("Idempotency-Key"),
    ]
    supplied = [value for value in values if value is not None and value != ""]
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 160 for value in supplied
    ):
        raise HTTPException(status_code=400, detail="请求标识必须是1至160字符的字符串")
    keys = {str(value).strip() for value in supplied}
    if len(keys) > 1:
        raise HTTPException(status_code=400, detail="turn_id 与 idempotency_key 必须一致")
    return next(iter(keys), "")


def _trusted_context(request: Request, user_id: int, tenant_id: int) -> dict[str, Any]:
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context

    context = request_runtime_context(request)
    if str(context.get("user_id")) != str(user_id) or str(context.get("tenant_id")) != str(
        tenant_id
    ):
        raise HTTPException(status_code=403, detail="员工请求的授权主体不一致")
    return context


class EmployeeExecution:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        identity: Callable[[Request], EmployeePrincipal | JSONResponse],
        run: Callable[[EmployeeWork], JsonObject],
    ) -> None:
        self._errors = errors
        self._identity = identity
        self._run = run

    async def local_employee_execute(
        self,
        request: Request,
        employee_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """绑定当前账号与稳定请求标识，经统一任务登记执行本机员工。"""
        from app.domain.app_pure.auth_permission_resolver import require_allowed

        principal = self._identity(request)
        if isinstance(principal, JSONResponse):
            return principal
        sid, user, meta = principal.session_id, principal.user, principal.metadata
        require_allowed(
            user=user,
            account_kind=str(meta.get("account_kind") or "admin"),
            session_meta=meta,
            route=f"/local/employees/{employee_id}/execute",
        )
        pid = str(employee_id or "").strip()
        if not pid:
            return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
        task = str(body.get("task") or "").strip()
        if not task:
            return JSONResponse({"success": False, "message": "task 必填"}, status_code=400)
        try:
            request_key = _request_key(body, request)
            if not request_key:
                raise HTTPException(status_code=400, detail="员工执行需要稳定请求标识")
        except HTTPException as exc:
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "task_identity_required",
                    "execution_state": "not_started",
                    "retryable": False,
                    "message": str(exc.detail),
                },
                status_code=400,
            )
        raw_input = body.get("input_data")
        if raw_input is not None and (not isinstance(raw_input, dict)):
            return JSONResponse(
                {"success": False, "message": "input_data 必须是对象"}, status_code=400
            )
        payload = dict(raw_input or {})
        for key in ("approved_write", "allow_write", "write_token", "approval_token"):
            if key in body and key not in payload:
                payload[key] = body[key]
        payload.setdefault("trigger", "admin_execute")
        try:
            user_id = int(getattr(user, "id", 0) or 0)
        except (TypeError, ValueError):
            user_id = 0
        tenant_id = trusted_tenant(meta)
        if tenant_id is None:
            return JSONResponse({"success": False, "message": "缺少可信租户"}, status_code=403)
        from app.infrastructure.workspace import workspace_root

        # The authenticated local-execution route uses the configured host workspace,
        # never an arbitrary filesystem root supplied in HTTP input.
        server_workspace = str(workspace_root())
        requested_workspace = str(body.get("workspace_root") or "").strip()
        if requested_workspace and requested_workspace != server_workspace:
            return JSONResponse(
                {"success": False, "message": "员工工作区必须使用服务器配置"}, status_code=403
            )
        payload["workspace_root"] = server_workspace
        for reserved in (
            "_runtime_context",
            "runtime_context",
            "_mod_authorization",
            "_actor_authorization",
            "mod_id",
            "active_mod_id",
            "actor_id",
            "local_user_id",
            "run_id",
            "agent_run_id",
            "task_id",
            "turn_id",
            "idempotency_key",
        ):
            payload.pop(reserved, None)
        payload.update(
            user_id=user_id, session_id=sid, tenant_id=tenant_id, employee_id=pid, task=task
        )
        work = EmployeeWork(
            employee_id=pid,
            task=task,
            payload=payload,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=sid,
            workspace_root=server_workspace,
            idempotency_key=request_key,
            runtime_context=_trusted_context(request, user_id, tenant_id),
        )
        from app.application.agent_orchestrator.unified_task import UnifiedTaskConflictError
        from app.infrastructure.tenant_scope import tenant_scope

        from .employee_run import execute_admitted_employee

        def execute():
            with tenant_scope(tenant_id):
                return execute_admitted_employee(work, self._run)

        try:
            return await run_in_threadpool(execute)
        except UnifiedTaskConflictError:
            return JSONResponse(
                {
                    "success": False,
                    "execution_state": "blocked",
                    "retryable": False,
                    "message": "原请求标识已绑定不同员工、输入或授权范围，未再次执行。",
                },
                status_code=409,
            )

    async def local_employee_runs(
        self, request: Request, employee_id: str, limit: int = 50, idempotency_key: str = ""
    ):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        principal = self._identity(request)
        if isinstance(principal, JSONResponse):
            return principal
        tenant_id = trusted_tenant(principal.metadata)
        if tenant_id is None:
            return JSONResponse({"success": False, "message": "缺少可信租户"}, status_code=403)
        pid = str(employee_id or "").strip()
        if not pid:
            return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
        if idempotency_key:
            from app.application.agent_orchestrator.unified_task import UnifiedTaskConflictError
            from app.domain.app_pure.auth_permission_resolver import require_allowed
            from app.infrastructure.tenant_scope import tenant_scope

            from .employee_run import read_employee_receipt

            require_allowed(
                user=principal.user,
                account_kind=str(principal.metadata.get("account_kind") or "admin"),
                session_meta=principal.metadata,
                route=f"/local/employees/{employee_id}/execute",
            )
            key = _request_key({"idempotency_key": idempotency_key}, request)
            context = _trusted_context(request, int(principal.user.id), tenant_id)
            try:
                with tenant_scope(tenant_id):
                    receipt = await run_in_threadpool(read_employee_receipt, pid, key, context)
            except UnifiedTaskConflictError:
                return JSONResponse(
                    {"success": False, "message": "原请求授权范围不匹配"}, status_code=409
                )
            if receipt is None:
                return JSONResponse(
                    {
                        "success": False,
                        "execution_state": "unknown",
                        "retryable": False,
                        "requires_reconciliation": True,
                        "idempotency_key": key,
                        "message": "尚未找到原请求回执，未创建或执行新任务。",
                    },
                    status_code=404,
                )
            return receipt
        from app.application.employee_runtime.run_ledger import expire_employee_approvals

        expire_employee_approvals(tenant_id=tenant_id, timeout_seconds=86400)
        return {
            "success": True,
            "data": list_employee_run_logs(pid, tenant_id=tenant_id, limit=limit),
        }

    async def local_employee_decision(
        self,
        request: Request,
        employee_id: str,
        run_id: int,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.employee_runtime.run_ledger import decide_employee_run_log
        from app.domain.app_pure.auth_permission_resolver import require_allowed

        principal = self._identity(request)
        if isinstance(principal, JSONResponse):
            return principal
        user, meta = principal.user, principal.metadata
        require_allowed(
            user=user,
            account_kind=str(meta.get("account_kind") or "admin"),
            session_meta=meta,
            route=f"/local/employees/{employee_id}/runs/{run_id}/decision",
        )
        tenant_id = trusted_tenant(meta)
        if tenant_id is None:
            return JSONResponse({"success": False, "message": "缺少可信租户"}, status_code=403)
        decision = str(body.get("decision") or "")
        try:
            actor = str(int(getattr(user, "id", 0) or 0))
            decide_employee_run_log(
                int(run_id), tenant_id=tenant_id, decision=decision, actor=actor
            )
        except ValueError:
            return JSONResponse(
                {"success": False, "message": "审批决定无效或任务状态已变化"}, status_code=409
            )
        return {"success": True, "run_id": int(run_id), "decision": decision}
