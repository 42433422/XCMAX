"""Approval workspace HTTP 薄层 — 委托 approval_workspace_app_service。"""

from __future__ import annotations

from fastapi import APIRouter

from app.application import approval_workspace_app_service as svc

router = APIRouter(prefix="/api/approval", tags=["approval"])

router.add_api_route("/requests", svc.list_requests, methods=["GET"])
router.add_api_route("/requests/cleanup", svc.cleanup_requests, methods=["POST"])
router.add_api_route("/requests/{request_id}", svc.get_request_detail, methods=["GET"])
router.add_api_route("/requests", svc.submit_request, methods=["POST"])
router.add_api_route("/requests/{request_id}/approve", svc.approve_request, methods=["POST"])
router.add_api_route("/requests/{request_id}/reject", svc.reject_request, methods=["POST"])
router.add_api_route("/requests/{request_id}/withdraw", svc.withdraw_request, methods=["POST"])
router.add_api_route("/requests/{request_id}", svc.delete_request, methods=["DELETE"])
router.add_api_route("/users", svc.get_approval_users, methods=["GET"])
router.add_api_route("/users/{user_id}/orphan-check", svc.check_approver_orphan, methods=["GET"])
router.add_api_route("/process-timeouts", svc.process_approval_timeouts_endpoint, methods=["POST"])
router.add_api_route("/flows", svc.list_flows, methods=["GET"])
router.add_api_route("/flows/{flow_id}", svc.get_flow_detail, methods=["GET"])
router.add_api_route("/flows", svc.create_flow, methods=["POST"])
router.add_api_route("/flows/{flow_id}", svc.update_flow, methods=["PUT"])
router.add_api_route("/flows/{flow_id}/active", svc.toggle_flow_active, methods=["PATCH"])
router.add_api_route("/flows/{flow_id}", svc.delete_flow, methods=["DELETE"])
