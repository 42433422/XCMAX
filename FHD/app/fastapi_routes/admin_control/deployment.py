"""Deployment control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from .port_contracts import AdminGate, ErrorPolicy


class Deployment:
    def __init__(self, *, errors: ErrorPolicy, gate: AdminGate) -> None:
        self._errors = errors
        self._gate = gate

    async def admin_deploy_check(self, request: Request, channel: str = Query("stable")):
        """管理端检查本地版本、update 中转站版本、企业端待更新状态。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        normalized_channel = "staging" if str(channel).strip() == "staging" else "stable"
        from app.domain.app_pure.admin_deploy_push import check_deploy_updates

        data = await asyncio.to_thread(check_deploy_updates, normalized_channel)
        return {"success": True, "data": data}

    async def admin_deploy_push(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """管理端推送更新包到 update 中转站；企业端自行拉取。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        payload = dict(body or {})
        channel = "staging" if str(payload.get("channel") or "").strip() == "staging" else "stable"
        options = {
            "include_backend": bool(payload.get("include_backend", True)),
            "include_frontend": bool(payload.get("include_frontend", True)),
            "skip_pack": bool(payload.get("skip_pack", False)),
            "channel": channel,
        }
        ssh_key = str(payload.get("ssh_key") or "").strip()
        if ssh_key:
            options["ssh_key"] = ssh_key
        try:
            from app.domain.app_pure.admin_deploy_push import start_deploy_push

            job = await start_deploy_push(options)
            return {"success": True, "data": job.to_dict()}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("admin deploy push failed to start: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=409)

    async def admin_deploy_job(self, request: Request, job_id: str):
        """查询管理端更新包推送任务。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        normalized_job_id = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[
            :128
        ]
        if not normalized_job_id:
            return JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
        from app.domain.app_pure.admin_deploy_push import get_deploy_job

        job = get_deploy_job(normalized_job_id)
        if job is None:
            return JSONResponse({"success": False, "message": "推送任务不存在"}, status_code=404)
        return {"success": True, "data": job.to_dict()}
