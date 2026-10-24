"""LocalEmployees control-plane operations with explicit callback dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from .ports import ErrorPolicy


class LocalEmployees:
    def __init__(self, *, errors: ErrorPolicy) -> None:
        self._errors = errors

    async def local_duty_graph_health(self, request: Request):
        """本机编制图 health（不代理远端 MODstore）。"""
        from app.application.local_duty_graph_health import build_local_duty_graph_health
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        return build_local_duty_graph_health()

    async def local_employee_cron_jobs(self, request: Request):
        """本机员工定时任务列表（管理端点火状态）。"""
        from app.application.employee_runtime.scheduler import get_employee_cron_jobs
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        return {"success": True, "source": "local", "jobs": get_employee_cron_jobs()}

    async def local_employee_cron_job_run(
        self,
        request: Request,
        job_id: str,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """手动触发本机员工定时任务，供管理端立即验证 daily 员工是否能跑。"""
        from app.application.employee_runtime.scheduler import run_employee_cron_job
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        if not sid:
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        payload = body.get("input_data") if isinstance(body.get("input_data"), dict) else {}
        task = str(body.get("task") or "").strip() or None
        try:
            user_id = int(body.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        result = run_employee_cron_job(
            job_id,
            task=task,
            input_data=payload,
            user_id=user_id,
            workspace_root=str(body.get("workspace_root") or "").strip() or None,
            session_id=str(body.get("session_id") or sid),
            source="manual",
        )
        if not result.get("success") and "unknown employee cron job" in str(
            result.get("error") or ""
        ):
            return JSONResponse(result, status_code=404)
        return result

    async def local_employee_status(self, request: Request, employee_id: str):
        """本机员工包部署态与执行统计（编制图 Phase2，不代理 MODstore）。"""
        from app.application.local_duty_graph_health import build_local_employee_status
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        pid = str(employee_id or "").strip()
        if not pid:
            return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
        return build_local_employee_status(pid)

    async def local_employee_manifest(self, request: Request, employee_id: str):
        """读本机 mods/_employees/<id>/manifest.json（编制图 LLM/依赖解析）。"""
        from app.application.local_duty_graph_health import read_local_employee_manifest
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        pid = str(employee_id or "").strip()
        if not pid:
            return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
        row = read_local_employee_manifest(pid)
        if not row:
            return JSONResponse(
                {"success": False, "message": f"员工包不存在: {pid}"}, status_code=404
            )
        return row
