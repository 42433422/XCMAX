"""Approval workspace HTTP 薄层 — 委托 approval_workspace_app_service。"""

from __future__ import annotations

from fastapi import APIRouter

from app.application import approval_workspace_app_service as svc

# Approval bridge Mods predate this route module becoming a pure router and
# import these callables from here at request time. Keep that compatibility
# surface explicit so a mounted Mod cannot turn every facade request into 500.
list_requests = svc.list_requests
cleanup_requests = svc.cleanup_requests
get_request_detail = svc.get_request_detail
submit_request = svc.submit_request
approve_request = svc.approve_request
reject_request = svc.reject_request
withdraw_request = svc.withdraw_request
delete_request = svc.delete_request
get_approval_users = svc.get_approval_users
list_flows = svc.list_flows
get_flow_detail = svc.get_flow_detail
create_flow = svc.create_flow
update_flow = svc.update_flow
toggle_flow_active = svc.toggle_flow_active
delete_flow = svc.delete_flow

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
