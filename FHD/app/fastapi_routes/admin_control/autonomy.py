"""AutonomyAdmin control-plane operations with explicit callback dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, JsonObject

from .common import read_json_object


class AutonomyAdmin:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        gate: AdminGate,
        approver: Callable[[Request], str],
        duty_health: Callable[[Request], Awaitable[JsonObject]],
    ) -> None:
        self._errors = errors
        self._gate = gate
        self._approver = approver
        self._duty_health = duty_health
        from app.application.autonomy.maintenance_console import register

        register()

    async def autonomy_audit_log(
        self,
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000),
        risk_level: str | None = None,
        decision: str | None = None,
        veto_only: bool = False,
        since: str | None = None,
        days: int = Query(default=1, ge=1, le=3650),
    ):
        """Query the append-only autonomy decision and veto trail."""
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
        from app.domain.autonomy.operating_metrics import evaluate_autonomy_window

        items = list_autonomy_audit(
            limit=limit, risk_level=risk_level, decision=decision, veto_only=veto_only, since=since
        )
        summary = summarize_autonomy_audit(days=days)
        return {
            "success": True,
            "append_only": True,
            "items": items,
            "count": len(items),
            "summary": summary,
            "evaluation": evaluate_autonomy_window(days, summary=summary)
            if days in {30, 90}
            else None,
        }

    async def admin_pending_autonomy_actions(self, request: Request):
        """管理端审批中心：用管理员会话拉取待办（勿走 webhook token）。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.approval_center import approval_center_snapshot

        return {"ok": True, **approval_center_snapshot()}

    async def admin_resume_autonomy_action(self, action_id: str, request: Request):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.approval_center import admin_execution_contract
        from app.application.autonomy.approval_resume import (
            ApprovalStateError,
            get_action_state,
            resume_action,
        )

        body = await read_json_object(request, self._errors) or {}
        approver = self._approver(request)
        current = get_action_state(action_id)
        if current is None:
            return JSONResponse(
                {"ok": False, "code": "action_not_found", "message": "待审批动作不存在"},
                status_code=409,
            )
        contract = admin_execution_contract(current)
        if not contract["admin_execution_ready"]:
            return JSONResponse(
                {
                    "ok": False,
                    "code": str(contract["execution_mode"]),
                    "message": str(contract["execution_guidance"]),
                    "action": {**current, **contract},
                },
                status_code=409,
            )
        try:
            from starlette.concurrency import run_in_threadpool

            item = await run_in_threadpool(
                resume_action,
                action_id,
                approver=approver,
                approval_id=str(body.get("approval_id") or ""),
                defer_execution=False,
            )
        except ApprovalStateError as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
        if str(item.get("state") or "") != "executed":
            return JSONResponse(
                {
                    "ok": False,
                    "code": "execution_failed",
                    "message": "审批已记录，但动作执行失败；请查看执行结果后修复。",
                    "action": item,
                },
                status_code=502,
            )
        return {"ok": True, "execution_dispatched": True, "action": item}

    async def admin_reject_autonomy_action(self, action_id: str, request: Request):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.approval_resume import ApprovalStateError, reject_action

        body = await read_json_object(request, self._errors) or {}
        approver = self._approver(request)
        if not approver:
            return JSONResponse({"ok": False, "message": "approver is required"}, status_code=400)
        try:
            item = reject_action(
                action_id,
                approver=approver,
                reason=str(body.get("reason") or ""),
                approval_id=str(body.get("approval_id") or ""),
            )
        except ApprovalStateError as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
        return {"ok": True, "action": item}

    async def admin_autonomy_health(self, request: Request):
        """Admin-session health for autonomy approval service (avoids /api/ops vite→modstore proxy)."""
        gate = self._gate(request)
        if gate is not None:
            return gate
        return {"ok": True, "service": "ops-autonomy-approval", "via": "xcmax-admin"}

    async def admin_autonomy_overview(self, request: Request):
        """One-shot autonomy dashboard payload for the admin console."""
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import (
            closure_gap_count,
            extract_loop_run_summary,
            list_deploy_events,
            operating_metrics_windows,
        )
        from app.application.autonomy.approval_center import list_pending_actions
        from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
        from app.application.ops_closure_status import build_ops_closure_status
        from app.fastapi_routes.xcmax_admin import _self_maintenance_local_or_proxy

        audit_items = list_autonomy_audit(limit=20)
        audit_summary = summarize_autonomy_audit(days=30)
        metrics = operating_metrics_windows()
        deploy = list_deploy_events(limit=20)
        pending = list_pending_actions()
        runtime: dict[str, Any] = {}
        try:
            runtime = await _self_maintenance_local_or_proxy(
                request, "GET", "/api/ops/self-maintenance/status?limit=40"
            )
            if isinstance(runtime, JSONResponse):
                runtime = {
                    "ok": False,
                    "error": "维护监控服务不可用",
                    "status": runtime.status_code,
                }
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("autonomy overview runtime status failed: %s", exc)
            runtime = {"ok": False, "error": str(exc)}
        closure: dict[str, Any] = {}
        try:
            closure = {
                "success": True,
                "data": build_ops_closure_status(await self._duty_health(request)),
            }
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("autonomy overview closure status failed: %s", exc)
            closure = {"success": False, "error": str(exc)}
        return {
            "ok": True,
            "health": {"ok": True, "service": "ops-autonomy-approval"},
            "pending": {"count": len(pending), "items": pending[:20]},
            "audit": {"items": audit_items, "count": len(audit_items), "summary": audit_summary},
            "loop": extract_loop_run_summary(runtime if isinstance(runtime, dict) else {}),
            "runtime": runtime,
            "closure": {"gap_count": closure_gap_count(closure), "payload": closure},
            "deploy_events": deploy,
            "operating_metrics": metrics,
        }

    async def admin_autonomy_deploy_events(
        self,
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
        since_cursor: str | None = None,
    ):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import list_deploy_events

        data = list_deploy_events(limit=limit, since_cursor=since_cursor)
        return {"ok": True, **data}

    async def admin_autonomy_operating_metrics(self, request: Request):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import operating_metrics_windows

        return {"ok": True, **operating_metrics_windows()}

    async def admin_autonomy_github_items(
        self, request: Request, limit: int = Query(default=30, ge=1, le=100)
    ):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import list_github_human_items

        return {"ok": True, **list_github_human_items(limit=limit)}

    async def admin_autonomy_cross_tier_gate(self, request: Request):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import evaluate_cross_tier_gate_snapshot

        return {"ok": True, **evaluate_cross_tier_gate_snapshot(None)}

    async def admin_autonomy_audit_cross_tier(
        self,
        request: Request,
        tier: str = Query(default="server"),
        limit: int = Query(default=50, ge=1, le=300),
    ):
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.autonomy.admin_overview import read_cross_tier_audit

        return {"ok": True, **read_cross_tier_audit(tier=tier, limit=limit)}

    async def admin_force_self_maintenance_run(self, request: Request):
        """Admin break-glass through the same configured target as runtime status."""
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.fastapi_routes.xcmax_admin import _self_maintenance_local_or_proxy

        body = await read_json_object(request, self._errors) or {}
        reason = (
            str(body.get("reason") or "admin_console_force_run").strip()
            or "admin_console_force_run"
        )
        try:
            result = await _self_maintenance_local_or_proxy(
                request,
                "POST",
                "/api/ops/self-maintenance/run",
                json_body={"reason": reason},
            )
            if isinstance(result, JSONResponse):
                return result
            return {"ok": True, "result": result}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("admin force self-maintenance failed: %s", exc)
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)

    async def admin_maintenance_tasks(self, request: Request):
        return await self._maintenance_call(request, "snapshot")

    async def admin_maintenance_evidence(self, execution_id: int, request: Request):
        return await self._maintenance_call(request, "execution_evidence", execution_id)

    async def admin_maintenance_run(self, request: Request):
        body = await read_json_object(request, self._errors) or {}
        return await self._maintenance_call(
            request, "request_run", str(body.get("action", "")), str(body.get("request_id", ""))
        )

    async def admin_maintenance_cancel(self, execution_id: int, request: Request):
        return await self._maintenance_call(request, "cancel", execution_id)

    async def _maintenance_call(self, request: Request, operation: str, *args):
        denied = self._gate(request)
        if denied is not None:
            return denied
        from starlette.concurrency import run_in_threadpool

        from app.application.autonomy import maintenance_console as service

        actor = self._approver(request)
        try:
            if operation not in {"snapshot", "execution_evidence"}:
                args = (*args, actor)
            return {"ok": True, **await run_in_threadpool(getattr(service, operation), *args)}
        except (ValueError, KeyError, OSError):
            return JSONResponse(
                {"ok": False, "message": "维护服务未就绪或操作不适用，请刷新状态后检查任务配置。"},
                status_code=409,
            )
        except service.requests.RequestException:
            return JSONResponse(
                {"ok": False, "message": "维护服务暂时无法连接；没有自动重发任务。"},
                status_code=502,
            )
