"""审批中心 Mod（里程碑 E）— 全量门面路由，委托宿主 approval 实现。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Header, Query, Request

from app.application import approval_workspace_app_service as svc

logger = logging.getLogger(__name__)

HOST_PREFIXES = ["/api/approval"]


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"approval-bridge-{mod_id}"])

    @router.get("/status")
    def status():
        from app.mod_sdk.approval_compat import list_approval_facade_registry

        return {
            "success": True,
            "data": {**list_approval_facade_registry(), "mod_id": mod_id, "phase": "E"},
        }

    @router.get("/registry")
    def registry():
        from app.mod_sdk.approval_compat import list_approval_facade_registry

        return {"success": True, "data": list_approval_facade_registry()}

    # ── 审批请求 ────────────────────────────────────────────────────
    @router.get("/requests")
    def mod_list_requests(
        approver_id: int | None = Query(default=None),
        applicant_id: int | None = Query(default=None),
        status: str | None = Query(default=None),
        business_type: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
    ):
        return svc.list_requests(approver_id, applicant_id, status, business_type, page, page_size)

    @router.post("/requests/cleanup")
    def mod_cleanup_requests(
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.cleanup_requests(request, body or {}, x_user_id)

    @router.get("/requests/{request_id:int}")
    def mod_get_request(request_id: int):
        return svc.get_request_detail(request_id)

    @router.post("/requests")
    def mod_submit_request(
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.submit_request(request, body or {}, x_user_id)

    @router.post("/requests/{request_id:int}/approve")
    def mod_approve(
        request_id: int,
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.approve_request(request_id, request, body or {}, x_user_id)

    @router.post("/requests/{request_id:int}/reject")
    def mod_reject(
        request_id: int,
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.reject_request(request_id, request, body or {}, x_user_id)

    @router.post("/requests/{request_id:int}/withdraw")
    def mod_withdraw(
        request_id: int,
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.withdraw_request(request_id, request, body or {}, x_user_id)

    @router.delete("/requests/{request_id:int}")
    def mod_delete_request(
        request_id: int,
        request: Request,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.delete_request(request_id, request, x_user_id)

    # ── 审批流程 ────────────────────────────────────────────────────
    @router.get("/flows")
    def mod_list_flows(
        is_active: bool | None = Query(default=None),
        business_type: str | None = Query(default=None),
    ):
        return svc.list_flows(is_active, business_type)

    @router.get("/flows/{flow_id:int}")
    def mod_get_flow(flow_id: int):
        return svc.get_flow_detail(flow_id)

    @router.post("/flows")
    def mod_create_flow(
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.create_flow(request, body or {}, x_user_id)

    @router.put("/flows/{flow_id:int}")
    def mod_update_flow(
        flow_id: int,
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.update_flow(flow_id, request, body or {}, x_user_id)

    @router.patch("/flows/{flow_id:int}/active")
    def mod_toggle_flow(
        flow_id: int,
        request: Request,
        body: dict | None = Body(default=None),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.toggle_flow_active(flow_id, request, body or {}, x_user_id)

    @router.delete("/flows/{flow_id:int}")
    def mod_delete_flow(
        flow_id: int,
        request: Request,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ):
        return svc.delete_flow(flow_id, request, x_user_id)

    @router.get("/users")
    def mod_approval_users():
        return svc.get_approval_users()

    app.include_router(router)
    logger.info("xcagi-approval-bridge facade registered: %s", mod_id)


def mod_init():
    logger.info("xcagi-approval-bridge mod_init (approval facade E)")
