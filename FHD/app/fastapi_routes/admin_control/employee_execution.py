"""Trusted tenant execution, one-attempt deadline, and run-ledger completion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from .employee_backend import EmployeePrincipal, trusted_tenant
from .employee_run import EmployeeWork
from .ports import ErrorPolicy, JsonObject


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
        """管理端本机员工执行入口：绕开远端代理，直接调用 FHD employee_runtime。"""
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
        for reserved in ("_runtime_context", "runtime_context", "_mod_authorization"):
            payload.pop(reserved, None)
        payload.update(
            user_id=user_id, session_id=sid, tenant_id=tenant_id, employee_id=pid, task=task
        )
        return self._run(
            EmployeeWork(
                employee_id=pid,
                task=task,
                payload=payload,
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=sid,
                workspace_root=str(body.get("workspace_root") or "").strip() or None,
            )
        )

    async def local_employee_runs(self, request: Request, employee_id: str, limit: int = 50):
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
        return {
            "success": True,
            "data": list_employee_run_logs(pid, tenant_id=tenant_id, limit=limit),
        }
